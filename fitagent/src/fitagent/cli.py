"""fitagent CLI — init | doctor | status | run | queue | show | approve |
reject | upload | auth youtube."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .config import AppConfig, load_config
from .store import Approval, Store

app = typer.Typer(
    help="AI agent team for a fitness motivation YouTube channel. Agents write, "
         "voice, and edit videos into a review queue — YOU approve every upload.",
    no_args_is_help=True)
auth_app = typer.Typer(help="Authenticate external services.", no_args_is_help=True)
app.add_typer(auth_app, name="auth")

console = Console()


def _cfg() -> AppConfig:
    return load_config()


def _store(cfg: AppConfig) -> Store:
    return Store(cfg.db_path)


def _ai(cfg: AppConfig):
    from .ai.client import AIClient, MissingAPIKeyError
    try:
        return AIClient(cfg.ai.model, cfg.ai.max_tokens)
    except MissingAPIKeyError as exc:
        raise typer.Exit(code=_fail(str(exc)))


def _fail(msg: str) -> int:
    console.print(f"[red]{msg}[/red]")
    return 1


def _mode_banner(cfg: AppConfig) -> None:
    stock, yt = cfg.stock_mode(), cfg.youtube_mode()
    tts = cfg.tts_provider(cfg.preset())
    style = "yellow" if "mock" in (stock, yt) else "green"
    console.print(f"[{style}]mode: {cfg.mode} | stock: {stock} | tts: {tts} "
                  f"| youtube: {yt}[/{style}]")


def _executor(cfg: AppConfig, store: Store):
    from .executor import Executor
    from .integrations.youtube import make_youtube_client
    return Executor(store, cfg, make_youtube_client(cfg))


# ------------------------------------------------------------------ commands

@app.command()
def init() -> None:
    """Scaffold config.yaml/.env in the current directory and check setup."""
    root = Path.cwd()
    pkg_root = Path(__file__).resolve().parents[2].parent
    created = []
    for name in ("config.yaml", ".env.example"):
        src, dst = pkg_root / name, root / name
        if not dst.exists() and src.exists():
            dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
            created.append(name)
    env = root / ".env"
    if not env.exists() and (root / ".env.example").exists():
        env.write_text((root / ".env.example").read_text(encoding="utf-8"),
                       encoding="utf-8")
        created.append(".env  (fill in ANTHROPIC_API_KEY)")
    for sub in ("assets/music", "assets/fonts", "assets/public_domain", "output"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    console.print(Panel("\n".join(f"created {c}" for c in created)
                        or "everything already in place",
                        title="fitagent init"))
    doctor()


@app.command()
def doctor() -> None:
    """Check config, credentials, ffmpeg, and the asset folders."""
    cfg = _cfg()
    _mode_banner(cfg)
    table = Table(show_header=False, box=None)

    def row(ok: bool | None, label: str, note: str = "") -> None:
        icon = {True: "[green]ok[/green]", False: "[red]MISSING[/red]",
                None: "[yellow]optional[/yellow]"}[ok]
        table.add_row(icon, label, note)

    row(bool(os.environ.get("ANTHROPIC_API_KEY")), "ANTHROPIC_API_KEY",
        "required — agents can't reason without it")
    from .media.ffmpeg import ffmpeg_path
    row(bool(ffmpeg_path()), "ffmpeg",
        "required to render — sudo apt-get install -y ffmpeg")
    row(bool(os.environ.get("PEXELS_API_KEY")) or None, "PEXELS_API_KEY",
        "free key; without it stock footage is mocked")
    row(bool(os.environ.get("PIXABAY_API_KEY")) or None, "PIXABAY_API_KEY",
        "free key; without it stock footage is mocked")

    from .media.music import KNOWN_MOODS, library, track_mood
    tracks = library(cfg.music_dir)
    if tracks:
        thin = [m for m in KNOWN_MOODS
                if sum(1 for t in tracks if track_mood(t) == m) < 2]
        note = f"{len(tracks)} track(s)"
        if thin:
            note += f"; thin moods: {', '.join(thin)}"
        row(True, "assets/music", note)
    else:
        row(None, "assets/music",
            "empty — videos render voice-only; add YouTube Audio Library tracks")

    from .pd_library import load_sources
    row(bool(load_sources(cfg.public_domain_dir)), "assets/public_domain",
        f"{len(load_sources(cfg.public_domain_dir))} source(s)")

    secrets = cfg.youtube_client_secrets()
    row(secrets.exists() or None, "YouTube client secrets", str(secrets))
    token = cfg.youtube_token_path()
    row(token.exists() or None, "YouTube token",
        "run `fitagent auth youtube`" if not token.exists() else str(token))
    console.print(table)
    console.print(
        "[dim]YouTube caveats: unverified API projects upload PRIVATE-only "
        "until Google's audit passes; testing-mode OAuth tokens expire every "
        "7 days; quota allows ~6 uploads/day.[/dim]")


@app.command()
def status() -> None:
    """Overview: videos by status, recent runs, pending approvals."""
    cfg = _cfg()
    _mode_banner(cfg)
    store = _store(cfg)
    videos = store.list_videos()
    by_status: dict[str, int] = {}
    for v in videos:
        by_status[v["status"]] = by_status.get(v["status"], 0) + 1
    console.print(Panel(
        "  ".join(f"{k}: {v}" for k, v in sorted(by_status.items())) or "no videos yet",
        title="videos"))
    counts = store.source_type_counts()
    total = sum(counts.values())
    if total:
        console.print(f"content mix (last {total} long-form): "
                      f"original {counts['original']}, "
                      f"public domain {counts['public_domain']}")
    runs = store.list_runs_table(5)
    if runs:
        table = Table(title="recent runs")
        for col in ("id", "preset", "status", "source", "created"):
            table.add_column(col)
        for r in runs:
            table.add_row(str(r["id"]), r["preset"], r["status"],
                          r["source_type"], r["created_at"])
        console.print(table)
    pending = store.list_approvals("pending")
    if pending:
        console.print(f"[yellow]{len(pending)} pending approval(s) — "
                      f"see `fitagent queue`[/yellow]")


@app.command()
def run(preset: Optional[str] = typer.Option(None, help="Channel preset name"),
        source: Optional[str] = typer.Option(
            None, help="Force 'original' or 'public_domain'"),
        skip_shorts: bool = typer.Option(False, "--skip-shorts"),
        count: int = typer.Option(1, help="How many videos to produce")) -> None:
    """Run the full pipeline: concept -> script -> voice -> footage -> edit.
    Finished videos land in the review queue (`fitagent queue`)."""
    cfg = _cfg()
    _mode_banner(cfg)
    if source not in (None, "original", "public_domain"):
        raise typer.Exit(code=_fail("--source must be original or public_domain"))
    from .media.ffmpeg import FFmpegMissingError, require_ffmpeg
    try:
        require_ffmpeg()
    except FFmpegMissingError as exc:
        raise typer.Exit(code=_fail(str(exc)))
    store = _store(cfg)
    from .pipeline import Pipeline
    pipeline = Pipeline(_ai(cfg), store, cfg, preset,
                        on_event=lambda msg: console.print(f"[dim]{msg}[/dim]"))
    for _ in range(count):
        run_id = pipeline.run(source_override=source, skip_shorts=skip_shorts)
        console.print(f"[green]run #{run_id} complete[/green]")
        if cfg.publishing.auto_upload:
            _auto_publish(cfg, store, run_id)
    queue()


def _auto_publish(cfg: AppConfig, store: Store, run_id: int) -> None:
    """publishing.auto_upload: create+approve+execute upload approvals for the
    run's videos. The gate becomes a config flag; the ledger still records it."""
    executor = _executor(cfg, store)
    for video in store.list_videos(status="in_review"):
        if video["run_id"] != run_id:
            continue
        action = ("youtube.upload_short" if video["kind"] == "short"
                  else "youtube.upload_video")
        approval_id = store.propose(Approval(
            action_type=action, agent="auto_upload",
            title=f"upload {video['kind']} #{video['id']}: {video['title'][:60]}",
            payload={"video_row_id": video["id"]},
            rationale="publishing.auto_upload is enabled",
            ref_table="videos", ref_id=video["id"]))
        store.update_video(video["id"], status="approved",
                           privacy=cfg.publishing.default_privacy)
        store.decide_approval(approval_id, "approved", note="auto_upload")
        result = executor.execute(approval_id)
        console.print(f"auto-upload #{video['id']}: {result.status} {result.result}")


@app.command()
def queue(all: bool = typer.Option(False, "--all",
                                   help="Include uploaded/rejected videos")) -> None:
    """The review queue: what the agents produced, awaiting your approval."""
    cfg = _cfg()
    store = _store(cfg)
    videos = store.list_videos() if all else [
        v for v in store.list_videos()
        if v["status"] in ("in_review", "approved", "upload_failed")]
    if not videos:
        console.print("queue is empty — `fitagent run` to produce a video")
        return
    table = Table(title="review queue" if not all else "all videos")
    for col in ("id", "kind", "status", "len", "title", "file"):
        table.add_column(col)
    for v in videos:
        table.add_row(str(v["id"]), v["kind"], v["status"],
                      f"{v['duration_s']:.0f}s", (v["title"] or "")[:48],
                      v["file_path"])
    console.print(table)
    console.print("[dim]fitagent show <id> | approve <id> | reject <id> | upload[/dim]")


@app.command()
def show(video_id: int) -> None:
    """Full detail for one video: metadata, files, and provenance."""
    cfg = _cfg()
    store = _store(cfg)
    video = store.get_video(video_id)
    if video is None:
        raise typer.Exit(code=_fail(f"no video #{video_id}"))
    meta = json.loads(video["metadata_json"] or "{}")
    body = [f"{k}: {video[k]}" for k in
            ("kind", "status", "source_type", "duration_s", "width", "height",
             "file_path", "youtube_video_id", "privacy")]
    if meta:
        body.append("\n--- metadata ---")
        body.append(f"title: {meta.get('title', '')}")
        body.append(f"tags: {', '.join(meta.get('tags', []))}")
        body.append(f"thumbnail_text: {meta.get('thumbnail_text', '')}")
        body.append(f"\n{meta.get('description', '')}")
    run_row = store.get_run(video["run_id"])
    if run_row:
        body.append(f"\nrun #{run_row['id']} workdir: {run_row['workdir']}")
    console.print(Panel("\n".join(body), title=f"video #{video_id}: {video['title']}"))


@app.command()
def approve(video_id: int,
            privacy: Optional[str] = typer.Option(
                None, help="private | unlisted | public (default from config)"),
            now: bool = typer.Option(False, "--now",
                                     help="Upload immediately after approving")) -> None:
    """Approve a video for upload (creates the approval-queue row)."""
    cfg = _cfg()
    store = _store(cfg)
    video = store.get_video(video_id)
    if video is None:
        raise typer.Exit(code=_fail(f"no video #{video_id}"))
    if video["status"] not in ("in_review", "upload_failed"):
        raise typer.Exit(code=_fail(
            f"video #{video_id} is {video['status']}; only in_review or "
            "upload_failed videos can be approved"))
    if privacy not in (None, "private", "unlisted", "public"):
        raise typer.Exit(code=_fail("privacy must be private/unlisted/public"))
    effective_privacy = privacy or cfg.publishing.default_privacy
    action = ("youtube.upload_short" if video["kind"] == "short"
              else "youtube.upload_video")
    existing = store.find_approval_for_video(video_id)
    if existing is None:
        approval_id = store.propose(Approval(
            action_type=action, agent="cli",
            title=f"upload {video['kind']} #{video_id}: {video['title'][:60]}",
            payload={"video_row_id": video_id, "privacy": effective_privacy},
            rationale="approved via CLI", ref_table="videos", ref_id=video_id))
    else:
        approval_id = existing.id
    store.update_video(video_id, status="approved", privacy=effective_privacy)
    approval = store.get_approval(approval_id)
    if approval.status == "pending":
        store.decide_approval(approval_id, "approved")
    console.print(f"[green]video #{video_id} approved "
                  f"(privacy: {effective_privacy})[/green]")
    if now:
        upload()
    else:
        console.print("run [bold]fitagent upload[/bold] to push approved videos")


@app.command()
def reject(video_id: int,
           note: str = typer.Option("", help="Why it was rejected")) -> None:
    """Reject a video (it stays on disk; the row is marked rejected)."""
    cfg = _cfg()
    store = _store(cfg)
    video = store.get_video(video_id)
    if video is None:
        raise typer.Exit(code=_fail(f"no video #{video_id}"))
    existing = store.find_approval_for_video(video_id, statuses=("pending",))
    if existing is not None:
        store.decide_approval(existing.id, "rejected", note=note)
    store.update_video(video_id, status="rejected", notes=note)
    console.print(f"video #{video_id} rejected")


@app.command()
def upload(id: Optional[int] = typer.Option(None, help="One approval id")) -> None:
    """Execute approved-but-not-uploaded actions (the cron-safe half of the
    gate: `fitagent run && fitagent upload`)."""
    cfg = _cfg()
    _mode_banner(cfg)
    store = _store(cfg)
    executor = _executor(cfg, store)
    approvals = ([store.get_approval(id)] if id is not None
                 else store.list_approvals("approved"))
    approvals = [a for a in approvals if a is not None]
    if not approvals:
        console.print("nothing approved and waiting — `fitagent queue`")
        return
    for approval in approvals:
        result = executor.execute(approval.id)
        color = "green" if result.status == "executed" else "red"
        console.print(f"[{color}]approval #{approval.id}: {result.status}[/{color}] "
                      f"{result.result or result.error}")


@auth_app.command("youtube")
def auth_youtube(preset: Optional[str] = typer.Option(None)) -> None:
    """One-time OAuth flow for the YouTube upload scope."""
    cfg = _cfg()
    try:
        from .integrations.youtube import YouTubeClient
        client = YouTubeClient(cfg.youtube_client_secrets(),
                               cfg.youtube_token_path(preset))
        client.run_oauth()
    except ImportError:
        raise typer.Exit(code=_fail(
            'Google libraries missing — install with: pip install -e ".[youtube]"'))
    except RuntimeError as exc:
        raise typer.Exit(code=_fail(str(exc)))
    console.print("[green]YouTube token saved[/green]")


if __name__ == "__main__":
    app()
