"""The deterministic per-video pipeline: agents plan, media renders, videos
land in the review queue.

Order of operations (each step checkpointed onto the runs row):
  1. decide original vs public-domain from the store ledger (80/20)
  2. ideation agent -> concept
  3. scriptwriter agent -> segmented script
  4. TTS -> voiceover + master timeline; captions
  5. visual director agent -> shot plan (tool loop over stock search)
  6. footage download -> timeline slots
  7. music pick, long-form render, shorts render
  8. metadata agent -> titles/descriptions/tags
  9. video rows created with status in_review

Publishing stays behind the approval gate: this module never uploads. With
publishing.auto_upload, the CLI's upload path runs immediately after approval
rows are auto-created — the gate is a config flag, the ledger still records
everything.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .agents.ideation import IdeationAgent
from .agents.metadata import MetadataAgent
from .agents.scriptwriter import ScriptwriterAgent
from .agents.visual_director import VisualDirectorAgent
from .config import AppConfig
from .integrations.stock import make_stock_clients
from .media.assemble import render_long_form, video_meta
from .media.captions import write_ass
from .media.footage import build_slots
from .media.music import pick_track
from .media.shorts import candidate_windows, render_short
from .media.tts import build_voiceover, make_tts
from .pd_library import get_source, load_sources
from .store import Store

WPM_NOMINAL = 140


class Pipeline:
    def __init__(self, ai, store: Store, cfg: AppConfig,
                 preset_name: str | None = None, on_event=None):
        self.ai = ai
        self.store = store
        self.cfg = cfg
        self.preset_name = preset_name or cfg.active_preset
        self.preset = cfg.preset(preset_name)
        self.on_event = on_event or (lambda msg: None)

    # ------------------------------------------------------------- decisions

    def decide_source_type(self, override: str | None = None) -> str:
        """Deterministic 80/20: go public-domain only when its recent share
        has fallen below the configured target."""
        if override:
            return override
        if not load_sources(self.cfg.public_domain_dir):
            return "original"
        counts = self.store.source_type_counts(last_n=10)
        total = sum(counts.values())
        if total == 0:
            return "original"
        pd_target = 1.0 - self.preset.original_ratio
        return "public_domain" if counts["public_domain"] / total < pd_target else "original"

    # ------------------------------------------------------------------ run

    def run(self, source_override: str | None = None,
            skip_shorts: bool = False) -> int:
        source_type = self.decide_source_type(source_override)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        workdir = self.cfg.output_dir / "runs" / f"{stamp}_{self.preset_name}"
        workdir.mkdir(parents=True, exist_ok=True)
        run_id = self.store.create_run(self.preset_name, source_type, str(workdir))
        log_path = workdir / "ffmpeg.log"
        try:
            self._run_steps(run_id, source_type, workdir, skip_shorts, log_path)
            self.store.update_run(run_id, status="complete")
        except Exception as exc:
            self.store.update_run(run_id, status="failed", error=str(exc)[:1000])
            raise
        return run_id

    def _run_steps(self, run_id: int, source_type: str, workdir: Path,
                   skip_shorts: bool, log_path: Path) -> None:
        cfg, preset = self.cfg, self.preset
        target_minutes = (cfg.video.long_form.min_minutes
                          + cfg.video.long_form.max_minutes) / 2

        # 1-2. concept
        self.on_event(f"ideation: choosing a {source_type} concept")
        pd_sources = [s.summary() for s in load_sources(cfg.public_domain_dir)]
        concept_out = IdeationAgent(self.ai, self.store, cfg, preset).run(
            source_type, self.store.recent_topics(), pd_sources, target_minutes)
        concept = concept_out.concept
        self.store.update_run(run_id, concept_json=concept_out.model_dump_json())
        self.on_event(f"concept: {concept.working_title}")

        # 3. script
        pd_text, pd_attribution_default = None, None
        if source_type == "public_domain":
            source = (get_source(cfg.public_domain_dir, concept.pd_source or "")
                      or load_sources(cfg.public_domain_dir)[0])
            pd_text = (f"[attribution note: {source.attribution}]\n\n{source.text}")
            pd_attribution_default = source.attribution
        script_out = ScriptwriterAgent(self.ai, self.store, cfg, preset).run(
            concept.model_dump(), pd_text)
        script = script_out.script
        words_total = sum(len(s.text.split()) for s in script.segments)
        self.on_event(f"script: {len(script.segments)} segments, ~{words_total} words")
        self.store.update_run(run_id, script_json=script_out.model_dump_json())

        # 4. voiceover + captions
        self.on_event("tts: rendering voiceover")
        provider = make_tts(cfg, preset)
        voiceover = build_voiceover([s.model_dump() for s in script.segments],
                                    provider, workdir, log_path)
        self.store.update_run(run_id, timeline_json=json.dumps(
            [{"segment_id": sp.segment_id, "start_s": sp.start_s, "end_s": sp.end_s}
             for sp in voiceover.spans]))
        self.store.add_asset(run_id, "voiceover", provider=type(provider).__name__,
                             file_path=str(voiceover.audio_path),
                             duration_s=voiceover.duration_s)
        ass_path = write_ass(voiceover.words, workdir / "captions.ass")
        self.on_event(f"voiceover: {voiceover.duration_s:.0f}s")

        # 5. shot plan
        self.on_event("visual director: planning shots")
        stock_clients = make_stock_clients(cfg)
        plan_out = VisualDirectorAgent(self.ai, self.store, cfg, preset,
                                       stock_clients).run(
            [s.model_dump() for s in script.segments])
        self.store.update_run(run_id, shot_plan_json=plan_out.model_dump_json())

        # 6. footage
        self.on_event("footage: downloading clips")
        slots = build_slots([e.model_dump() for e in plan_out.shot_plan],
                            voiceover, stock_clients, cfg.cache_dir, self.on_event)
        for slot in slots:
            self.store.add_asset(run_id, "clip", provider=slot.clip.provider,
                                 provider_id=slot.clip.clip_id,
                                 source_url=slot.clip.page_url,
                                 license_note=slot.clip.license_note,
                                 file_path=str(slot.clip_path),
                                 duration_s=slot.duration_s,
                                 segment_id=slot.segment_id)

        # 7. music + renders
        moods = [e.mood for e in plan_out.shot_plan]
        dominant = max(set(moods), key=moods.count) if moods else ""
        music = pick_track(cfg.music_dir, dominant, self.store.recent_music_tracks())
        if music is not None:
            self.store.add_asset(run_id, "music", file_path=str(music),
                                 license_note="user-supplied (YouTube Audio Library)")
            self.on_event(f"music: {music.name}")
        else:
            self.on_event("music: none found in assets/music — rendering voice-only")

        final_dir = workdir / "final"
        final_dir.mkdir(exist_ok=True)
        self.on_event("render: long-form video")
        long_path = render_long_form(slots, voiceover.audio_path, music, ass_path,
                                     workdir, final_dir / "long.mp4",
                                     cfg.video.long_form, cfg.audio, log_path)
        long_meta = video_meta(long_path)
        long_id = self.store.create_video(
            run_id, "long", source_type, title=script.title_working,
            file_path=str(long_path), status="in_review", **long_meta)
        self.on_event(f"rendered: {long_path} ({long_meta['duration_s']:.0f}s)")

        short_rows: list[tuple[int, list[str]]] = []
        if not skip_shorts:
            windows = candidate_windows(
                [c.model_dump() for c in script.shorts_candidates],
                voiceover, cfg.video.shorts.max_seconds)[: cfg.video.shorts.count]
            for i, window in enumerate(windows):
                self.on_event(f"render: short {i + 1}/{len(windows)}")
                short_path = render_short(window, slots, voiceover, music,
                                          workdir, final_dir / f"short_{i + 1}.mp4",
                                          cfg.video.shorts, cfg.audio, i, log_path)
                short_id = self.store.create_video(
                    run_id, "short", source_type, parent_video_id=long_id,
                    title=window.hook_line or f"{script.title_working} #{i + 1}",
                    file_path=str(short_path), status="in_review",
                    **video_meta(short_path))
                short_rows.append((short_id, window.segment_ids))

        # 8. metadata
        self.on_event("metadata: writing titles and descriptions")
        chapters = self._chapters(script, voiceover)
        meta_out = MetadataAgent(self.ai, self.store, cfg, preset).run(
            concept.model_dump(), script.model_dump(), chapters,
            [{"video_row_id": vid, "segment_ids": ids} for vid, ids in short_rows],
            script.pd_attribution or pd_attribution_default)
        self.store.update_run(run_id, metadata_json=meta_out.model_dump_json())
        self.store.update_video(long_id, title=meta_out.long_form.title,
                                metadata_json=meta_out.long_form.model_dump_json())
        by_segments = {tuple(s.for_segments): s for s in meta_out.shorts}
        for vid, ids in short_rows:
            short_meta = by_segments.get(tuple(ids)) or (meta_out.shorts[0]
                                                         if meta_out.shorts else None)
            if short_meta:
                self.store.update_video(vid, title=short_meta.title,
                                        metadata_json=short_meta.model_dump_json())

    @staticmethod
    def _chapters(script, voiceover) -> list[dict]:
        """Chapter markers where the script's role changes (hook/build/peak...)."""
        chapters, last_role = [], None
        for seg in script.segments:
            if seg.role != last_role:
                span = voiceover.span_for(seg.id)
                hint = seg.visual_theme or seg.role
                chapters.append({"start_s": span.start_s,
                                 "hint": f"{seg.role}: {hint}"})
                last_role = seg.role
        if chapters:
            chapters[0]["start_s"] = 0.0  # YouTube requires chapter one at 0:00
        return chapters
