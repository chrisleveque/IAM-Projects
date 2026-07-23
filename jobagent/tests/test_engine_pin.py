from jobagent.browser import pin_engine, read_pinned_engine


def test_unpinned_profile_returns_none(tmp_path):
    assert read_pinned_engine(tmp_path) is None


def test_pin_roundtrip(tmp_path):
    pin_engine(tmp_path, "chrome")
    assert read_pinned_engine(tmp_path) == "chrome"
    pin_engine(tmp_path, "chromium")
    assert read_pinned_engine(tmp_path) == "chromium"


def test_garbage_marker_treated_as_unpinned(tmp_path):
    (tmp_path / ".engine").write_text("firefox??", encoding="utf-8")
    assert read_pinned_engine(tmp_path) is None
