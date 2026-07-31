"""Content agent + tiktok executor handlers, end to end through the gate.

The load-bearing property: the agent can write a script and propose a render,
but nothing is rendered or uploaded until a human approves. The agent has no
tool that touches the filesystem or TikTok.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from shopagent.agents.content import ContentAgent
from shopagent.executor import Executor
from shopagent.store import Approval
from shopagent.video.render import ffmpeg_available

needs_ffmpeg = pytest.mark.skipif(not ffmpeg_available(),
                                  reason="ffmpeg/ffprobe not installed")

SCRIPT = {"hook": "Your dog eats way too fast",
          "shots": ["Slows them right down", "Suction cups grip the tub",
                    "Rinse and reuse"],
          "cta": "Link in bio"}


@pytest.fixture
def listed_product(store, tmp_path):
    """A listed product with two real image files served over a stub transport."""
    images = []
    for index, color in enumerate(("red", "blue")):
        path = tmp_path / f"src_{index}.jpg"
        if ffmpeg_available():
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                            "-i", f"color=c={color}:s=400x600", "-frames:v", "1",
                            str(path)], check=True)
        else:
            path.write_bytes(b"\xff\xd8\xff")
        images.append(path)
    urls = [f"https://cdn.test/{p.name}" for p in images]
    product_id = store.upsert_product(
        "CJ-PET-001", "Silicone Lick Mat", niche="pet accessories",
        supplier_price=4.2, proposed_price=18.99,
        images_json=json.dumps(urls),
        listing_json=json.dumps({"title": "Silicone Lick Mat",
                                 "bullets": ["BPA-free silicone"]}))
    store.update_product(product_id, status="listed")
    return {"id": product_id, "urls": urls,
            "files": {url: path for url, path in zip(urls, images)}}


@pytest.fixture
def stub_images(monkeypatch, listed_product):
    """Serve the fixture image bytes for the CJ-style URLs the executor fetches."""
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        for url, path in listed_product["files"].items():
            if str(request.url) == url:
                return httpx.Response(200, content=path.read_bytes())
        return httpx.Response(404)

    real_client = httpx.Client
    monkeypatch.setattr(
        "httpx.Client",
        lambda *a, **kw: real_client(transport=httpx.MockTransport(handler)))
    return listed_product


# ------------------------------------------------------------------- agent

def test_agent_has_no_tool_that_renders_or_uploads(store, cfg, music, tiktok):
    """The gate is structural: no filesystem or TikTok tool is offered at all."""
    from tests.conftest import FakeAIClient

    agent = ContentAgent(FakeAIClient(), store, cfg, music=music, tiktok=tiktok)
    schemas, _ = agent.shared_tools()
    extra, _ = agent.extra_tools()
    names = {t["name"] for t in schemas} | {t["name"] for t in extra}
    assert names == {"propose_action", "query_products", "query_orders",
                     "get_video_candidates", "read_trend_notes", "search_music"}
    # propose_action is the only write path; everything else reads
    assert not any("render" in n or "upload" in n or "publish" in n for n in names)


def test_candidates_exclude_products_without_photos(store, cfg, music):
    from tests.conftest import FakeAIClient

    store.update_product(
        store.upsert_product("CJ-X", "No Photos", images_json="[]"), status="listed")
    agent = ContentAgent(FakeAIClient(), store, cfg, music=music)
    assert agent._candidates({}) == []


def test_candidates_exclude_products_that_already_have_a_video(
        store, cfg, music, listed_product):
    from tests.conftest import FakeAIClient

    agent = ContentAgent(FakeAIClient(), store, cfg, music=music)
    assert len(agent._candidates({})) == 1
    store.update_product(listed_product["id"], tiktok_status="rendered")
    assert agent._candidates({}) == []
    assert len(agent._candidates({"include_done": True})) == 1


def test_candidates_report_photo_count_as_the_shot_ceiling(
        store, cfg, music, listed_product):
    from tests.conftest import FakeAIClient

    agent = ContentAgent(FakeAIClient(), store, cfg, music=music)
    assert agent._candidates({})[0]["photo_count"] == 2


def test_search_music_without_a_provider_says_so(store, cfg, listed_product):
    from tests.conftest import FakeAIClient

    agent = ContentAgent(FakeAIClient(), store, cfg, music=None)
    assert "no music provider" in agent._search_music({"query": "x"})[0]["note"]


def test_agent_proposes_a_render(store, cfg, music, listed_product):
    from tests.conftest import FakeAIClient

    ai = FakeAIClient(script=[
        ("get_video_candidates", {}),
        ("search_music", {"query": "upbeat playful"}),
        ("propose_action", {
            "action_type": "tiktok.render_video",
            "title": "TikTok ad for Silicone Lick Mat",
            "payload": {"product_id": listed_product["id"], "script": SCRIPT,
                        "music_query": "upbeat playful"},
            "rationale": ("Problem-first hook. Swap in a Commercial Music Library "
                          "track before running as an ad."),
            "ref_table": "products", "ref_id": listed_product["id"]}),
    ])
    ContentAgent(ai, store, cfg, music=music).run("write an ad")
    pending = store.list_approvals("pending")
    assert len(pending) == 1
    assert pending[0].action_type == "tiktok.render_video"
    assert pending[0].payload["script"]["hook"] == SCRIPT["hook"]


def test_music_licensing_rule_is_in_the_prompt(store, cfg, music):
    from tests.conftest import FakeAIClient

    prompt = ContentAgent(FakeAIClient(), store, cfg, music=music).system_prompt()
    assert "Commercial Music Library" in prompt
    assert "copyright violation" in prompt


# ---------------------------------------------------------------- executor

def test_render_requires_photos(store, cfg, music, tmp_path, shopify, cj):
    product_id = store.upsert_product("CJ-NONE", "No Photos", images_json="[]")
    store.propose(Approval(action_type="tiktok.render_video", agent="content",
                           title="render", payload={"product_id": product_id,
                                                    "script": SCRIPT}))
    store.decide_approval(1, "approved")
    approval = Executor(store, cfg, shopify, cj, music=music).execute(1)
    assert approval.status == "failed"
    assert "no saved photos" in approval.error


def test_render_with_an_unknown_product_fails_clearly(store, cfg, music, shopify, cj):
    store.propose(Approval(action_type="tiktok.render_video", agent="content",
                           title="render", payload={"product_id": 999,
                                                    "script": SCRIPT}))
    store.decide_approval(1, "approved")
    approval = Executor(store, cfg, shopify, cj, music=music).execute(1)
    assert approval.status == "failed" and "no product with id 999" in approval.error


@needs_ffmpeg
def test_render_produces_a_video_and_writes_back(store, cfg, music, shopify, cj,
                                                 stub_images):
    cfg.video.width, cfg.video.height = 180, 320
    cfg.video.seconds_per_shot, cfg.video.fps = 0.6, 10
    cfg.video.font_size_hook, cfg.video.font_size_caption = 16, 12

    store.propose(Approval(
        action_type="tiktok.render_video", agent="content", title="render",
        payload={"product_id": stub_images["id"], "script": SCRIPT,
                 "music_query": "upbeat playful"},
        ref_table="products", ref_id=stub_images["id"]))
    store.decide_approval(1, "approved")
    approval = Executor(store, cfg, shopify, cj, music=music).execute(1)
    assert approval.status == "executed", approval.error

    result = json.loads(approval.result)
    from pathlib import Path
    assert Path(result["video_path"]).exists()
    assert result["shots"] == 2
    assert result["music"]["title"]
    assert "Commercial Music Library" in result["before_posting"]

    product = store.get_product(stub_images["id"])
    assert product["tiktok_status"] == "rendered"
    assert product["video_path"] == result["video_path"]

    from shopagent.video.render import probe
    assert probe(result["video_path"])["width"] == 180


@needs_ffmpeg
def test_render_without_a_music_query_still_works(store, cfg, music, shopify, cj,
                                                 stub_images):
    cfg.video.width, cfg.video.height = 180, 320
    cfg.video.seconds_per_shot, cfg.video.fps = 0.6, 10
    store.propose(Approval(action_type="tiktok.render_video", agent="content",
                           title="render",
                           payload={"product_id": stub_images["id"],
                                    "script": SCRIPT}))
    store.decide_approval(1, "approved")
    approval = Executor(store, cfg, shopify, cj, music=music).execute(1)
    assert approval.status == "executed", approval.error
    assert "music" not in json.loads(approval.result)


def test_upload_without_a_client_explains_the_fallback(store, cfg, shopify, cj,
                                                       tmp_path):
    video = tmp_path / "ad.mp4"
    video.write_bytes(b"x")
    store.propose(Approval(action_type="tiktok.upload_draft", agent="content",
                           title="upload",
                           payload={"video_path": str(video), "caption": "hi"}))
    store.decide_approval(1, "approved")
    approval = Executor(store, cfg, shopify, cj, tiktok=None).execute(1)
    assert approval.status == "failed"
    assert "output/video/" in approval.error


def test_upload_draft_marks_the_product(store, cfg, shopify, cj, tiktok, tmp_path,
                                        listed_product):
    video = tmp_path / "ad.mp4"
    video.write_bytes(b"x" * 100)
    store.propose(Approval(action_type="tiktok.upload_draft", agent="content",
                           title="upload",
                           payload={"video_path": str(video), "caption": "hi"},
                           ref_table="products", ref_id=listed_product["id"]))
    store.decide_approval(1, "approved")
    approval = Executor(store, cfg, shopify, cj, tiktok=tiktok).execute(1)
    assert approval.status == "executed", approval.error
    assert store.get_product(listed_product["id"])["tiktok_status"] == "uploaded"
    assert tiktok.uploads[0]["bytes_uploaded"] == 100


def test_upload_of_a_missing_file_fails(store, cfg, shopify, cj, tiktok, tmp_path):
    store.propose(Approval(action_type="tiktok.upload_draft", agent="content",
                           title="upload",
                           payload={"video_path": str(tmp_path / "nope.mp4"),
                                    "caption": ""}))
    store.decide_approval(1, "approved")
    approval = Executor(store, cfg, shopify, cj, tiktok=tiktok).execute(1)
    assert approval.status == "failed" and "video not found" in approval.error


# ------------------------------------------------------------------- store

def test_new_action_types_validate_their_payloads(store):
    with pytest.raises(ValueError, match="missing keys"):
        store.propose(Approval(action_type="tiktok.render_video", agent="content",
                               title="x", payload={"product_id": 1}))
    with pytest.raises(ValueError, match="missing keys"):
        store.propose(Approval(action_type="tiktok.upload_draft", agent="content",
                               title="x", payload={"video_path": "a.mp4"}))
