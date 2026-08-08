"""Veo campaign runner + client tests — mock client and MockTransport only,
no network, no spend."""

from pathlib import Path

import httpx
import pytest
import yaml

from shopagent.integrations.veo_client import (
    COST_PER_SECOND_USD, MockVeoClient, VeoClient, VeoError,
    _extract_video_uri, make_veo_client)
from shopagent.video.veo_ads import (
    estimate_usd, full_prompt, load_campaign, run_ad)

REPO_BRIEFS = Path(__file__).resolve().parents[1] / "marketing" / "donut-bed-briefs.yaml"


# ------------------------------------------------------------------- briefs

def test_shipped_campaign_loads_ten_two_clip_ads():
    campaign = load_campaign(REPO_BRIEFS)
    assert len(campaign.ads) == 10
    assert sorted(campaign.photos) == ["brown", "dark-grey", "light-grey", "pink"]
    for ad in campaign.ads:
        assert len(ad.clips) == 2
        assert ad.seconds == 16  # 2 x 8s, inside the 15-25s target
        assert ad.color in campaign.photos
        # CTA lands in the closing clip, not the hook
        assert "link in bio" in ad.clips[-1].prompt.lower()


def test_shipped_campaign_stays_inside_product_truth():
    """No invented authorities or medical claims — the plan's hard rule."""
    text = REPO_BRIEFS.read_text(encoding="utf-8").lower()
    for banned in ("vet said", "veterinarian recommended", "clinically",
                   "% of dogs", "cures", "anxiety is gone"):
        assert banned not in text


def test_full_prompt_carries_style_creator_and_scene():
    campaign = load_campaign(REPO_BRIEFS)
    ad = campaign.ad(1)
    prompt = full_prompt(campaign, ad, ad.clips[0])
    assert campaign.style_prefix.strip()[:40] in prompt
    assert ad.creator.strip()[:40] in prompt
    assert ad.clips[0].prompt.strip()[:40] in prompt


def test_load_campaign_rejects_unknown_color(tmp_path):
    bad = dict(product="x", style_prefix="s",
               photos={"pink": "p.jpg"},
               ads=[dict(id=1, title="t", color="teal", creator="c",
                         clips=[dict(prompt="p")])])
    path = tmp_path / "briefs.yaml"
    path.write_text(yaml.safe_dump(bad), encoding="utf-8")
    with pytest.raises(VeoError, match="teal"):
        load_campaign(path)


def test_load_campaign_rejects_overlong_clip(tmp_path):
    bad = dict(product="x", style_prefix="s",
               photos={"pink": "p.jpg"},
               ads=[dict(id=1, title="t", color="pink", creator="c",
                         clips=[dict(prompt="p", seconds=12)])])
    path = tmp_path / "briefs.yaml"
    path.write_text(yaml.safe_dump(bad), encoding="utf-8")
    with pytest.raises(VeoError, match="caps a generation"):
        load_campaign(path)


# ----------------------------------------------------------------- estimate

def test_estimate_usd_uses_published_rates():
    campaign = load_campaign(REPO_BRIEFS)
    fast = estimate_usd(campaign.ads, "veo-3.1-fast-generate-preview")
    std = estimate_usd(campaign.ads, "veo-3.1-generate-preview")
    seconds = sum(ad.seconds for ad in campaign.ads)
    assert fast == pytest.approx(
        seconds * COST_PER_SECOND_USD["veo-3.1-fast-generate-preview"])
    assert std > fast


def test_estimate_usd_rejects_unknown_model():
    campaign = load_campaign(REPO_BRIEFS)
    with pytest.raises(VeoError, match="no published rate"):
        estimate_usd(campaign.ads, "veo-99")


# ------------------------------------------------------------------- runner

def _tiny_campaign(tmp_path, clips=1) -> tuple[Path, Path]:
    (tmp_path / "assets").mkdir()
    photo = tmp_path / "assets" / "pink.jpg"
    photo.write_bytes(b"\xff\xd8\xff\xe0-fake-jpeg")
    data = dict(product="bed", style_prefix="UGC iphone video.",
                photos={"pink": "assets/pink.jpg"},
                ads=[dict(id=1, title="t", color="pink", creator="a woman",
                          clips=[dict(prompt=f"scene {i}")
                                 for i in range(clips)])])
    briefs = tmp_path / "briefs.yaml"
    briefs.write_text(yaml.safe_dump(data), encoding="utf-8")
    return briefs, photo


def test_run_ad_generates_clip_with_reference_and_writes_final(tmp_path):
    briefs, _ = _tiny_campaign(tmp_path, clips=1)
    campaign = load_campaign(briefs)
    client = MockVeoClient()
    final = run_ad(client, campaign, campaign.ad(1), briefs_dir=tmp_path,
                   out_dir=tmp_path / "out", model="veo-3.1-fast-generate-preview")
    assert final == tmp_path / "out" / "ad01.mp4"
    assert final.read_bytes().startswith(b"\x00\x00\x00\x18ftyp")
    assert (tmp_path / "out" / "ad01_clip1.mp4").exists()
    [request] = client.requests
    assert request["has_reference"] and request["reference_mime"] == "image/jpeg"
    assert request["aspect_ratio"] == "9:16" and request["duration"] == 8


def test_run_ad_stitches_multi_clip_ads(tmp_path, monkeypatch):
    briefs, _ = _tiny_campaign(tmp_path, clips=2)
    campaign = load_campaign(briefs)
    calls = {}

    def fake_stitch(clips, out_path):
        calls["clips"] = list(clips)
        Path(out_path).write_bytes(b"stitched")

    monkeypatch.setattr("shopagent.video.veo_ads.stitch", fake_stitch)
    final = run_ad(MockVeoClient(), campaign, campaign.ad(1),
                   briefs_dir=tmp_path, out_dir=tmp_path / "out",
                   model="veo-3.1-fast-generate-preview")
    assert final.read_bytes() == b"stitched"
    assert len(calls["clips"]) == 2


def test_run_ad_fails_fast_on_missing_photo(tmp_path):
    briefs, photo = _tiny_campaign(tmp_path)
    photo.unlink()
    campaign = load_campaign(briefs)
    with pytest.raises(VeoError, match="product photo missing"):
        run_ad(MockVeoClient(), campaign, campaign.ad(1), briefs_dir=tmp_path,
               out_dir=tmp_path / "out", model="veo-3.1-fast-generate-preview")


# ------------------------------------------------------------------- client

def test_extract_video_uri_tolerates_both_documented_shapes():
    sample = {"video": {"uri": "https://x/video.mp4"}}
    assert _extract_video_uri(
        {"generateVideoResponse": {"generatedSamples": [sample]}}) \
        == "https://x/video.mp4"
    assert _extract_video_uri({"generatedVideos": [sample]}) \
        == "https://x/video.mp4"
    with pytest.raises(VeoError, match="no video uri"):
        _extract_video_uri({"generateVideoResponse": {}})


def test_veo_client_full_generation_roundtrip():
    """create -> poll (pending, then done) -> download, via MockTransport."""
    state = {"polls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(":predictLongRunning"):
            assert request.headers["x-goog-api-key"] == "test-key"
            return httpx.Response(200, json={"name": "operations/op-1"})
        if request.url.path.endswith("operations/op-1"):
            state["polls"] += 1
            if state["polls"] == 1:
                return httpx.Response(200, json={"done": False})
            return httpx.Response(200, json={
                "done": True,
                "response": {"generateVideoResponse": {"generatedSamples": [
                    {"video": {"uri": "https://dl.example/clip.mp4"}}]}}})
        if request.url.host == "dl.example":
            return httpx.Response(200, content=b"mp4-bytes")
        raise AssertionError(f"unexpected call: {request.url}")

    client = VeoClient("test-key", transport=httpx.MockTransport(handler),
                       poll_interval=0.0)
    video = client.generate_clip("a creator speaks",
                                 model="veo-3.1-fast-generate-preview",
                                 reference_image=b"jpeg-bytes")
    assert video == b"mp4-bytes"
    assert state["polls"] == 2


def test_veo_client_surfaces_operation_error():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(":predictLongRunning"):
            return httpx.Response(200, json={"name": "operations/op-2"})
        return httpx.Response(200, json={
            "done": True, "error": {"message": "prompt violates policy"}})

    client = VeoClient("k", transport=httpx.MockTransport(handler),
                       poll_interval=0.0)
    with pytest.raises(VeoError, match="prompt violates policy"):
        client.generate_clip("p", model="veo-3.1-fast-generate-preview")


def test_make_veo_client_is_mock_without_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert isinstance(make_veo_client(None), MockVeoClient)
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    assert isinstance(make_veo_client(None), VeoClient)
