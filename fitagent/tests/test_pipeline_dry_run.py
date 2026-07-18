"""End-to-end dry run: FakeAI canned outputs + MockTTS + MockStock -> a real
playable mp4 and a short, rows landing in_review. Requires ffmpeg."""

from __future__ import annotations

import pytest

from fitagent.integrations.stock import MockStockClient
from fitagent.media.ffmpeg import ffmpeg_path
from fitagent.pipeline import Pipeline

from conftest import FakeAIClient

pytestmark = [
    pytest.mark.media,
    pytest.mark.skipif(not ffmpeg_path(), reason="ffmpeg not installed"),
]

CONCEPT = {
    "concept": {
        "working_title": "The Quiet Hours", "theme": "discipline",
        "angle": "discipline as self-respect", "source_type": "original",
        "pd_source": None, "hook": "Nobody is coming to save you.",
        "emotional_arc": ["low", "rise", "peak", "resolve"],
        "target_minutes": 1, "visual_world": "dark gym, rain, city night",
        "rationale": "test",
    }
}

SCRIPT = {
    "script": {
        "title_working": "The Quiet Hours", "estimated_minutes": 0.5,
        "segments": [
            {"id": "s01", "text": "Nobody is coming to save you and that is good news.",
             "role": "hook", "energy": 2, "visual_theme": "man alone dark gym",
             "pd_verbatim": False, "pause_after_ms": 600},
            {"id": "s02", "text": "The alarm rings and the choice is yours alone.",
             "role": "build", "energy": 3, "visual_theme": "alarm clock early morning",
             "pd_verbatim": False, "pause_after_ms": 500},
            {"id": "s03", "text": "Show up again tomorrow and the day after that.",
             "role": "resolve", "energy": 4, "visual_theme": "sunrise over city",
             "pd_verbatim": False, "pause_after_ms": 800},
        ],
        "pd_attribution": None,
        "shorts_candidates": [
            {"segment_ids": ["s01", "s02"], "hook_line": "Nobody is coming",
             "why": "standalone arc"},
        ],
    }
}


def _shot_plan():
    plan = []
    for i, (sid, query) in enumerate([("s01", "man dark gym"),
                                      ("s02", "alarm morning"),
                                      ("s03", "city sunrise")]):
        results = MockStockClient().search(query)
        plan.append({"segment_id": sid, "mood": "gritty",
                     "shots": [{"query": query, "provider": "mock",
                                "clip_id": results[i % len(results)].clip_id,
                                "fallback_queries": ["rain window"],
                                "target_seconds": 3.0}]})
    return {"shot_plan": plan, "reuse_notes": ""}


METADATA = {
    "long_form": {
        "title": "The Quiet Hours | Discipline Motivation",
        "description": "Hook.\n\nChapters:\n0:00 hook\n\n#motivation",
        "tags": ["motivation", "discipline"], "category_id": "22",
        "thumbnail_text": "THE QUIET HOURS",
    },
    "shorts": [{"for_segments": ["s01", "s02"],
                "title": "Nobody is coming #shorts",
                "description": "#shorts", "tags": ["motivation"]}],
}


def test_full_dry_run_renders_video_and_short(cfg, store):
    ai = FakeAIClient(
        json_responses=[CONCEPT, SCRIPT, METADATA],
        tool_script=[("submit_shot_plan", _shot_plan())])
    pipeline = Pipeline(ai, store, cfg, on_event=lambda m: None)
    run_id = pipeline.run()

    run = store.get_run(run_id)
    assert run["status"] == "complete"

    videos = store.list_videos()
    longs = [v for v in videos if v["kind"] == "long"]
    shorts = [v for v in videos if v["kind"] == "short"]
    assert len(longs) == 1 and len(shorts) == 1
    assert all(v["status"] == "in_review" for v in videos)

    from fitagent.media.ffmpeg import probe
    long_meta = probe(longs[0]["file_path"])
    assert long_meta["has_video"] and long_meta["has_audio"]
    assert (long_meta["width"], long_meta["height"]) == (1920, 1080)
    assert long_meta["duration_s"] > 5

    short_meta = probe(shorts[0]["file_path"])
    assert (short_meta["width"], short_meta["height"]) == (1080, 1920)
    assert short_meta["duration_s"] < 60

    # metadata applied
    assert longs[0]["title"].startswith("The Quiet Hours")
    assert "#shorts" in shorts[0]["title"]
    # provenance recorded
    kinds = {a["kind"] for a in store.list_assets(run_id)}
    assert {"voiceover", "clip"} <= kinds
