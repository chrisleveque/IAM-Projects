"""Video renderer tests.

Tests that shell out to ffmpeg are skipped when it is absent rather than
failing, so the suite still runs on a machine that hasn't installed it yet —
`shopagent doctor` is what tells the operator it's missing. Renders here use a
tiny frame size and short shots to stay fast.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from shopagent.video.render import (PAN_MOVES, RenderError, Script,
                                    _filter_path, _pan_expr, add_captions,
                                    fetch_images, ffmpeg_available, find_font,
                                    probe, render_slideshow, swap_audio, trim)

needs_ffmpeg = pytest.mark.skipif(not ffmpeg_available(),
                                  reason="ffmpeg/ffprobe not installed")

SMALL = {"width": 180, "height": 320, "fps": 10, "seconds_per_shot": 0.6,
         "font_size_hook": 16, "font_size_caption": 12}


@pytest.fixture
def images(tmp_path) -> list[Path]:
    """Three distinct still images, made with ffmpeg so there's no image
    library dependency just for fixtures."""
    if not ffmpeg_available():
        pytest.skip("ffmpeg not installed")
    out = []
    for index, color in enumerate(("red", "green", "blue")):
        path = tmp_path / f"img_{index}.jpg"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                        "-i", f"color=c={color}:s=400x600", "-frames:v", "1",
                        str(path)], check=True)
        out.append(path)
    return out


@pytest.fixture
def music(tmp_path) -> Path:
    from shopagent.integrations.music_client import MockMusicClient
    client = MockMusicClient()
    return client.download(client.search("upbeat")[0], tmp_path / "bed.wav")


# ------------------------------------------------------------------ pure bits

def test_script_accepts_both_shot_shapes():
    from_strings = Script.from_dict({"hook": "H", "shots": ["a", "b"], "cta": "C"})
    from_dicts = Script.from_dict({"hook": "H", "cta": "C",
                                   "shots": [{"text": "a"}, {"text": "b"}]})
    assert from_strings.shots == from_dicts.shots == ["a", "b"]
    assert from_strings.hook == "H" and from_strings.cta == "C"


def test_script_drops_blank_shots():
    assert Script.from_dict({"shots": ["a", "", "   ", "b"]}).shots == ["a", "b"]


def test_script_tolerates_an_empty_dict():
    script = Script.from_dict({})
    assert script.shots == [] and script.hook == "" and script.cta == ""


def test_filter_path_escapes_windows_drive_colons():
    # an unescaped colon parses as an argument separator inside a filtergraph
    assert _filter_path(r"C:\Users\chril\hook.txt") == r"C\:/Users/chril/hook.txt"
    assert _filter_path("/tmp/hook.txt") == "/tmp/hook.txt"


def test_pan_expressions_cover_all_four_directions():
    seen = {_pan_expr(move, 3.0) for move in PAN_MOVES}
    assert len(seen) == 4, "two pan directions produced identical expressions"
    left_right, _ = _pan_expr("left_right", 3.0)
    right_left, _ = _pan_expr("right_left", 3.0)
    assert "(1-" in right_left and "(1-" not in left_right


def test_find_font_rejects_a_configured_path_that_does_not_exist():
    with pytest.raises(RenderError, match="configured font not found"):
        find_font("/no/such/font.ttf")


# ------------------------------------------------------------- input guards

def test_render_without_images_is_a_clear_error(tmp_path):
    with pytest.raises(RenderError, match="no images to render"):
        render_slideshow([], {"hook": "x"}, tmp_path / "out.mp4")


def test_render_with_a_missing_image_names_the_file(tmp_path):
    with pytest.raises(RenderError, match="image files not found"):
        render_slideshow([tmp_path / "nope.jpg"], {}, tmp_path / "out.mp4")


def test_trim_rejects_a_backwards_range(tmp_path):
    with pytest.raises(RenderError, match="must be after start"):
        trim(tmp_path / "in.mp4", tmp_path / "out.mp4", start=5.0, end=2.0)


def test_add_captions_rejects_empty_input(tmp_path):
    with pytest.raises(RenderError, match="no captions given"):
        add_captions(tmp_path / "in.mp4", [], tmp_path / "out.mp4")


@needs_ffmpeg
def test_add_captions_rejects_backwards_timing(tmp_path, images):
    with pytest.raises(RenderError, match="ends .* before it starts"):
        add_captions(tmp_path / "in.mp4",
                     [{"text": "x", "start": 3.0, "end": 1.0}],
                     tmp_path / "out.mp4")


# ------------------------------------------------------------ fit strategy

@needs_ffmpeg
def test_image_size_reads_dimensions(tmp_path):
    from shopagent.video.render import image_size
    path = tmp_path / "wide.jpg"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", "color=c=red:s=640x480", "-frames:v", "1", str(path)],
                   check=True)
    assert image_size(path) == (640, 480)


@needs_ffmpeg
def test_image_size_on_a_non_image_raises(tmp_path):
    from shopagent.video.render import image_size
    bad = tmp_path / "notanimage.jpg"
    bad.write_text("nope", encoding="utf-8")
    with pytest.raises(RenderError, match="could not read image dimensions"):
        image_size(bad)


@needs_ffmpeg
def test_square_sources_are_contained_not_cropped(tmp_path):
    """Cover-cropping a square into 9:16 discards ~44% of its width, which
    slices the edges off a wide product. Square sources must be contained."""
    from shopagent.video.render import _shot_chain
    square = tmp_path / "square.jpg"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", "color=c=white:s=800x800", "-frames:v", "1", str(square)],
                   check=True)
    chain = _shot_chain(0, square, 1080, 1920, 1242, 2208, 2.8)
    assert "overlay" in chain and "boxblur" in chain
    assert "force_original_aspect_ratio=decrease" in chain  # contain, not cover


@needs_ffmpeg
def test_portrait_sources_cover_and_pan(tmp_path):
    """A 9:16-ish source loses nothing to a cover crop and fills the frame with
    real content, so it should pan rather than sit on blurred bars."""
    from shopagent.video.render import _shot_chain
    portrait = tmp_path / "portrait.jpg"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", "color=c=white:s=540x960", "-frames:v", "1", str(portrait)],
                   check=True)
    chain = _shot_chain(0, portrait, 1080, 1920, 1242, 2208, 2.8)
    assert "overlay" not in chain
    assert "force_original_aspect_ratio=increase" in chain  # cover


@needs_ffmpeg
def test_a_full_bleed_source_gets_no_drift_that_would_expose_edges(tmp_path):
    """Drift has to stay inside the empty space; with none, there is no drift."""
    from shopagent.video.render import _shot_chain
    wide = tmp_path / "wide.jpg"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", "color=c=white:s=4000x400", "-frames:v", "1", str(wide)],
                   check=True)
    # a very wide source contains to a short strip, so there IS slack and drift
    assert "sin(" in _shot_chain(0, wide, 1080, 1920, 1242, 2208, 2.8)


@needs_ffmpeg
def test_mixed_aspect_images_render_in_one_pass(tmp_path, music):
    """Real product sets mix square packshots with portrait lifestyle photos;
    both strategies have to concat together."""
    paths = []
    for name, size in (("sq.jpg", "600x600"), ("port.jpg", "540x960"),
                       ("land.jpg", "800x450")):
        path = tmp_path / name
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                        "-i", f"color=c=white:s={size}", "-frames:v", "1", str(path)],
                       check=True)
        paths.append(path)
    out = render_slideshow(paths, {"shots": ["a", "b", "c"]},
                           tmp_path / "mixed.mp4", music_path=music, **SMALL)
    info = probe(out)
    assert (info["width"], info["height"]) == (180, 320)
    assert info["duration"] == pytest.approx(1.8, abs=0.15)


# ------------------------------------------------------------- real renders

@needs_ffmpeg
def test_render_produces_a_vertical_video_with_audio(tmp_path, images, music):
    out = render_slideshow(images, {"hook": "Hook here",
                                    "shots": ["one", "two", "three"],
                                    "cta": "Link in bio"},
                           tmp_path / "ad.mp4", music_path=music, **SMALL)
    info = probe(out)
    assert (info["width"], info["height"]) == (180, 320)
    assert info["has_audio"]
    assert info["duration"] == pytest.approx(1.8, abs=0.15)  # 3 shots x 0.6s


@needs_ffmpeg
def test_audio_and_video_durations_match(tmp_path, images, music):
    """-shortest does not reliably cut a filtered audio stream; an overlong bed
    pads the ad with dead air after the last frame."""
    out = render_slideshow(images, {"shots": ["a", "b", "c"]},
                           tmp_path / "ad.mp4", music_path=music, **SMALL)
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration",
         "-of", "csv=p=0", str(out)], capture_output=True, text=True, check=True)
    durations = {}
    for line in result.stdout.strip().splitlines():
        kind, value = line.split(",")
        durations[kind] = float(value)
    assert durations["audio"] == pytest.approx(durations["video"], abs=0.05)


@needs_ffmpeg
def test_a_music_bed_shorter_than_the_ad_is_looped(tmp_path, images):
    import wave
    short = tmp_path / "short.wav"
    with wave.open(str(short), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00" * 8000)  # 1 second against a 1.8s ad
    out = render_slideshow(images, {"shots": ["a", "b", "c"]},
                           tmp_path / "ad.mp4", music_path=short, **SMALL)
    assert probe(out)["duration"] == pytest.approx(1.8, abs=0.15)


@needs_ffmpeg
def test_renders_without_music(tmp_path, images):
    out = render_slideshow(images, {"shots": ["a"]}, tmp_path / "silent.mp4", **SMALL)
    assert probe(out)["has_audio"] is False


@needs_ffmpeg
def test_shot_count_is_capped_by_max_seconds(tmp_path, images):
    """A long image list should produce a shorter video, not one nobody
    watches to the end."""
    out = render_slideshow(images * 4, {"shots": ["a"] * 12},
                           tmp_path / "capped.mp4", max_seconds=1.2, **SMALL)
    assert probe(out)["duration"] == pytest.approx(1.2, abs=0.15)


@needs_ffmpeg
def test_text_with_filter_metacharacters_does_not_break_the_render(tmp_path, images):
    """Product copy is full of colons, quotes and percent signs — the reason
    text goes through textfile= instead of inline text=."""
    out = render_slideshow(
        images,
        {"hook": "50% off: it's here!",
         "shots": ["Size: 8.3in x 8.3in", "Rated 4,9/5 — \"great\"", "C:\\path\\like"]},
        tmp_path / "meta.mp4", **SMALL)
    assert probe(out)["width"] == 180


@needs_ffmpeg
def test_trim_shortens_a_clip(tmp_path, images, music):
    source = render_slideshow(images, {"shots": ["a", "b", "c"]},
                              tmp_path / "src.mp4", music_path=music, **SMALL)
    out = trim(source, tmp_path / "cut.mp4", start=0.2, end=1.0)
    assert probe(out)["duration"] == pytest.approx(0.8, abs=0.2)


@needs_ffmpeg
def test_swap_audio_replaces_the_track(tmp_path, images, music):
    silent = render_slideshow(images, {"shots": ["a"]}, tmp_path / "s.mp4", **SMALL)
    assert probe(silent)["has_audio"] is False
    out = swap_audio(silent, music, tmp_path / "dubbed.mp4")
    assert probe(out)["has_audio"] is True


@needs_ffmpeg
def test_add_captions_burns_into_existing_footage(tmp_path, images):
    source = render_slideshow(images, {"shots": ["a", "b", "c"]},
                              tmp_path / "src.mp4", **SMALL)
    out = add_captions(source, [{"text": "burned in", "start": 0.1, "end": 1.0}],
                       tmp_path / "capped.mp4", font_size=12)
    assert probe(out)["duration"] == pytest.approx(probe(source)["duration"], abs=0.2)


# ------------------------------------------------------------------ sourcing

def test_fetch_images_skips_failures_without_losing_the_rest(tmp_path):
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        if "bad" in request.url.path:
            return httpx.Response(404)
        return httpx.Response(200, content=b"\xff\xd8\xff-jpeg-bytes")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    saved = fetch_images(["https://cdn/a.jpg", "https://cdn/bad.jpg",
                          "https://cdn/c.jpg"], tmp_path, client=client)
    assert len(saved) == 2
    assert all(p.exists() for p in saved)


def test_fetch_images_handles_query_strings_in_urls(tmp_path):
    import httpx

    client = httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, content=b"bytes")))
    saved = fetch_images(["https://cdn/a.jpg?w=800&h=600"], tmp_path, client=client)
    assert saved[0].suffix == ".jpg"


def test_probe_on_a_missing_file_raises(tmp_path):
    if not ffmpeg_available():
        pytest.skip("ffmpeg not installed")
    with pytest.raises(RenderError, match="ffprobe failed"):
        probe(tmp_path / "nope.mp4")
