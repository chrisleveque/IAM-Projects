"""Trend note parsing.

Trend data arrives as whatever the operator pasted or exported, so the parser
has to be forgiving about formatting while still landing rows the agent can
filter. These tests pin the shapes people actually write.
"""

from __future__ import annotations

import pytest

from shopagent.trends import import_dir, import_file, parse_csv, parse_markdown

SAMPLE = """# TikTok trend notes
source: Creative Center
captured: 2026-07-29

## Hashtags
- #dogtok — 41.2B views
- #slowfeeder (rising fast)
- #pettok

## Formats working in pet niche
- Before/after on a messy eater, 7-12s
- POV from the dog's angle

## Trending sounds
- Some Cleared Track - 1.2M uses
"""


def test_markdown_sections_become_kinds():
    rows, meta = parse_markdown(SAMPLE)
    kinds = {r["kind"] for r in rows}
    assert kinds == {"hashtag", "format", "sound"}
    assert meta["source"] == "Creative Center"
    assert meta["captured_at"] == "2026-07-29"


def test_metric_is_split_off_the_label():
    rows, _ = parse_markdown(SAMPLE)
    by_label = {r["label"]: r["metric"] for r in rows}
    assert by_label["#dogtok"] == "41.2B views"          # em-dash form
    assert by_label["#slowfeeder"] == "rising fast"      # parenthetical form
    assert by_label["#pettok"] == ""                     # no metric at all
    assert by_label["Some Cleared Track"] == "1.2M uses"  # hyphen form


def test_document_title_is_not_treated_as_a_section():
    """A single '# Title' names the file; only '##' and deeper are sections."""
    rows, _ = parse_markdown("# Everything\n- first item\n")
    assert rows[0]["kind"] == "note"


def test_commas_in_a_label_survive():
    rows, _ = parse_markdown("## Formats\n- Before/after, 7-12s, text hook\n")
    assert rows[0]["label"] == "Before/after, 7-12s, text hook"


def test_unknown_section_falls_back_to_note():
    rows, _ = parse_markdown("## Miscellaneous observations\n- something\n")
    assert rows[0]["kind"] == "note"


def test_empty_markdown_yields_nothing():
    rows, _ = parse_markdown("")
    assert rows == []


# ----------------------------------------------------------------------- csv

def test_csv_requires_a_label_column():
    with pytest.raises(ValueError, match="needs a 'label' column"):
        parse_csv("product,revenue\nLick Mat,1200\n")


def test_csv_uses_optional_columns_when_present():
    rows, _ = parse_csv("label,kind,metric,note\n"
                        "Donut Bed,product,$18k GMV,strong in US\n")
    assert rows[0] == {"label": "Donut Bed", "kind": "product",
                       "metric": "$18k GMV", "note": "strong in US"}


def test_csv_headers_are_matched_case_insensitively():
    rows, _ = parse_csv("Label,Kind\nThing,product\n")
    assert rows[0]["label"] == "Thing" and rows[0]["kind"] == "product"


def test_csv_skips_blank_labels():
    rows, _ = parse_csv("label,kind\n,product\nReal,product\n")
    assert [r["label"] for r in rows] == ["Real"]


# -------------------------------------------------------------------- import

def test_import_file_writes_rows(store, tmp_path):
    path = tmp_path / "notes.md"
    path.write_text(SAMPLE, encoding="utf-8")
    assert import_file(store, path) == 6
    assert len(store.list_trends()) == 6
    hashtags = store.list_trends(kind="hashtag")
    assert {t["label"] for t in hashtags} == {"#dogtok", "#slowfeeder", "#pettok"}


def test_reimporting_updates_rather_than_duplicating(store, tmp_path):
    path = tmp_path / "notes.md"
    path.write_text(SAMPLE, encoding="utf-8")
    import_file(store, path)
    path.write_text(SAMPLE.replace("41.2B views", "44.9B views"), encoding="utf-8")
    import_file(store, path)
    rows = store.list_trends(kind="hashtag")
    assert len(rows) == 3, "re-import duplicated rows"
    assert {t["metric"] for t in rows if t["label"] == "#dogtok"} == {"44.9B views"}


def test_import_dir_handles_mixed_formats_and_ignores_others(store, tmp_path):
    (tmp_path / "a.md").write_text("## Hashtags\n- #one\n", encoding="utf-8")
    (tmp_path / "b.csv").write_text("label,kind\nTwo,product\n", encoding="utf-8")
    (tmp_path / "c.xlsx").write_bytes(b"not parsed")
    (tmp_path / "notes.txt").write_text("## Formats\n- Three\n", encoding="utf-8")
    results = import_dir(store, tmp_path)
    assert set(results) == {"a.md", "b.csv", "notes.txt"}
    assert len(store.list_trends()) == 3


def test_import_dir_on_a_missing_directory_is_empty_not_an_error(store, tmp_path):
    assert import_dir(store, tmp_path / "nope") == {}


def test_source_defaults_to_the_filename_when_unstated(store, tmp_path):
    path = tmp_path / "kalodata-export.md"
    path.write_text("## Products\n- Donut Bed\n", encoding="utf-8")
    import_file(store, path)
    assert store.list_trends()[0]["source"] == "kalodata-export"
