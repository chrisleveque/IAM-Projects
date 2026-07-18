import json

from fitagent.executor import Executor
from fitagent.integrations.youtube import MockYouTubeClient
from fitagent.store import Approval


def _rendered_video(store, tmp_path, status="approved"):
    run_id = store.create_run("forge", "original", str(tmp_path))
    video_file = tmp_path / "long.mp4"
    video_file.write_bytes(b"fake")
    meta = {"title": "T", "description": "D", "tags": ["a"], "category_id": "22"}
    return store.create_video(run_id, "long", "original", title="T",
                              file_path=str(video_file), status=status,
                              metadata_json=json.dumps(meta))


def test_executes_approved_upload(cfg, store, tmp_path):
    video_id = _rendered_video(store, tmp_path)
    approval_id = store.propose(Approval("youtube.upload_video", "cli", "u",
                                         {"video_row_id": video_id}))
    store.decide_approval(approval_id, "approved")
    result = Executor(store, cfg, MockYouTubeClient()).execute(approval_id)
    assert result.status == "executed"
    video = store.get_video(video_id)
    assert video["status"] == "uploaded"
    assert video["youtube_video_id"].startswith("mock-")
    assert (tmp_path / "long.upload.json").exists()


def test_refuses_pending_approval(cfg, store, tmp_path):
    video_id = _rendered_video(store, tmp_path)
    approval_id = store.propose(Approval("youtube.upload_video", "cli", "u",
                                         {"video_row_id": video_id}))
    try:
        Executor(store, cfg, MockYouTubeClient()).execute(approval_id)
        raise AssertionError("should have refused a pending approval")
    except ValueError:
        pass


def test_upload_failure_marks_video(cfg, store, tmp_path):
    video_id = _rendered_video(store, tmp_path, status="in_review")
    approval_id = store.propose(Approval("youtube.upload_video", "cli", "u",
                                         {"video_row_id": video_id}))
    store.decide_approval(approval_id, "approved")
    # video is in_review (not approved) -> handler raises -> marked failed
    result = Executor(store, cfg, MockYouTubeClient()).execute(approval_id)
    assert result.status == "failed"
    assert store.get_video(video_id)["status"] == "upload_failed"
