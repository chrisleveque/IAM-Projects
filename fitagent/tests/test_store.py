import pytest

from fitagent.store import Approval


def test_run_and_video_lifecycle(store):
    run_id = store.create_run("forge", "original", "/tmp/wd")
    video_id = store.create_video(run_id, "long", "original",
                                  title="t", file_path="/tmp/v.mp4",
                                  status="in_review")
    store.update_video(video_id, status="approved")
    assert store.get_video(video_id)["status"] == "approved"
    with pytest.raises(ValueError):
        store.update_video(video_id, status="bogus")
    store.update_run(run_id, status="complete")
    assert store.get_run(run_id)["status"] == "complete"


def test_source_type_ledger(store):
    run_id = store.create_run("forge", "original", "wd")
    for source in ("original", "original", "public_domain", "original"):
        store.create_video(run_id, "long", source)
    counts = store.source_type_counts()
    assert counts == {"original": 3, "public_domain": 1}


def test_approval_gate(store):
    with pytest.raises(ValueError):
        store.propose(Approval("bogus.action", "t", "x", {}))
    with pytest.raises(ValueError):
        store.propose(Approval("youtube.upload_video", "t", "x", {}))
    approval_id = store.propose(Approval(
        "youtube.upload_video", "cli", "upload", {"video_row_id": 1}))
    assert store.get_approval(approval_id).status == "pending"
    store.decide_approval(approval_id, "approved")
    with pytest.raises(ValueError):
        store.decide_approval(approval_id, "rejected")  # already approved
    store.mark_failed(approval_id, "boom")
    store.decide_approval(approval_id, "approved")  # failed -> approved retry ok
    store.mark_executed(approval_id, '{"video_id": "x"}')
    assert store.get_approval(approval_id).status == "executed"


def test_find_approval_for_video(store):
    a = store.propose(Approval("youtube.upload_video", "cli", "u",
                               {"video_row_id": 7}))
    found = store.find_approval_for_video(7)
    assert found and found.id == a
    assert store.find_approval_for_video(8) is None


def test_recent_topics_reads_concepts(store):
    run_id = store.create_run("forge", "original", "wd")
    store.update_run(run_id, concept_json='{"concept": {"working_title": "T1", '
                                          '"theme": "discipline", "angle": "a"}}')
    topics = store.recent_topics()
    assert topics[0]["title"] == "T1"
