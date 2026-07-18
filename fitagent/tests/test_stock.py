import httpx

from fitagent.integrations.stock import MockStockClient, PexelsClient, PixabayClient

PEXELS_PAYLOAD = {
    "videos": [{
        "id": 857802, "duration": 12, "url": "https://pexels.com/v/857802",
        "video_files": [
            {"link": "https://cdn/l.mp4", "width": 1920, "height": 1080},
            {"link": "https://cdn/xl.mp4", "width": 3840, "height": 2160},
            {"link": "https://cdn/s.mp4", "width": 960, "height": 540},
        ],
    }]
}

PIXABAY_PAYLOAD = {
    "hits": [{
        "id": 4321, "duration": 20, "pageURL": "https://pixabay.com/v/4321",
        "videos": {"large": {"url": "https://cdn/p.mp4",
                             "width": 1920, "height": 1080}},
    }]
}


def test_pexels_picks_smallest_hd_rendition():
    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, json=PEXELS_PAYLOAD))
    client = PexelsClient("key", transport=transport)
    clips = client.search("dark gym")
    assert len(clips) == 1
    assert clips[0].download_url == "https://cdn/l.mp4"  # 1080p, not 4k or 540p
    assert clips[0].clip_id == "857802"


def test_pixabay_filters_orientation():
    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, json=PIXABAY_PAYLOAD))
    client = PixabayClient("key", transport=transport)
    assert len(client.search("gym", orientation="landscape")) == 1
    assert client.search("gym", orientation="portrait") == []


def test_mock_stock_is_deterministic():
    a = MockStockClient().search("dark gym")
    b = MockStockClient().search("dark gym")
    assert [c.clip_id for c in a] == [c.clip_id for c in b]
    assert a[0].clip_id != MockStockClient().search("other query")[0].clip_id
    portrait = MockStockClient().search("dark gym", orientation="portrait")
    assert portrait[0].height > portrait[0].width
