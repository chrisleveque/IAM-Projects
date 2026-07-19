from fitagent.media.captions import CaptionStyle, build_ass, group_words
from fitagent.media.tts import WordTiming, spread_words


def _words(*specs):
    return [WordTiming(w, s, e) for w, s, e in specs]


def test_group_words_caps_line_length():
    words = _words(*[(f"w{i}", i * 0.3, i * 0.3 + 0.25) for i in range(9)])
    lines = group_words(words)
    assert all(len(line) <= 4 for line in lines)
    assert sum(len(line) for line in lines) == 9


def test_group_words_breaks_on_pause():
    words = _words(("one", 0.0, 0.3), ("two", 0.35, 0.6),
                   ("three", 2.0, 2.3))  # 1.4s gap
    lines = group_words(words)
    assert len(lines) == 2
    assert [w.word for w in lines[1]] == ["three"]


def test_build_ass_structure():
    words = _words(("push", 0.0, 0.4), ("through", 0.45, 0.9))
    doc = build_ass(words)
    assert "PlayResX: 1920" in doc
    assert "Dialogue:" in doc
    assert "{\\k40}PUSH" in doc  # 0.4s -> 40 centiseconds, uppercased
    assert "{\\k45}THROUGH" in doc


def test_build_ass_offset_drops_prewindow_lines():
    words = _words(("early", 0.0, 0.5), ("late", 10.0, 10.5))
    doc = build_ass(words, offset_s=9.5)
    assert "EARLY" not in doc
    assert "LATE" in doc


def test_shorts_style_is_center():
    style = CaptionStyle.for_shorts()
    doc = build_ass(_words(("go", 0.0, 0.3)), style)
    assert "PlayResX: 1080" in doc and "PlayResY: 1920" in doc


def test_spread_words_covers_duration():
    words = spread_words("one two three", 3.0)
    assert len(words) == 3
    assert abs(words[-1].end_s - 3.0) < 1e-6
    assert words[0].start_s == 0.0
