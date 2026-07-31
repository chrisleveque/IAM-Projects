"""Parse trend notes dropped into inbox/trends/ into the trends table.

No public API exposes trending TikTok Shop products — the official Shop API
only reads shops you already own, and scraping TikTok is both against its terms
and heavily bot-protected. So trends arrive the honest way: the operator
exports or pastes what they see in TikTok Creative Center (or a paid analytics
tool) into a file, and this parses it.

Two formats, both chosen because they're what you actually end up with:

**Markdown** — `## Section` headings become the ``kind``, and each `- item`
becomes a row. A trailing `— 41.2B views` or `(rising)` is split off as the
metric, since that's how people naturally write these lists.

**CSV** — a `label` column is required; `kind`, `metric`, and `note` are used
if present. This is the shape a paid tool exports.

When a real API is subscribed to later, it writes rows through
``Store.upsert_trend`` and everything downstream is unchanged.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

from .store import Store

# "- #dogtok — 41.2B views" / "- #dogtok - 41.2B views" / "- #dogtok (rising)"
BULLET = re.compile(r"^\s*[-*]\s+(?P<label>.+?)\s*$")
METRIC_SPLIT = re.compile(r"\s+[—–-]\s+|\s+\((?=[^)]*\)$)")
HEADING = re.compile(r"^\s*#{1,6}\s+(?P<title>.+?)\s*$")
META = re.compile(r"^\s*(?P<key>source|captured|captured_at)\s*:\s*(?P<value>.+?)\s*$",
                  re.IGNORECASE)

# Section heading -> the kind stored, so "## Hashtags" and "## Trending hashtags"
# both land as 'hashtag' and the agent can filter on one word.
KIND_WORDS = {
    "hashtag": "hashtag",
    "format": "format",
    "product": "product",
    "sound": "sound",
    "song": "sound",
    "music": "sound",
    "note": "note",
    "creator": "creator",
    "niche": "niche",
}


def _kind_for(heading: str) -> str:
    lowered = heading.lower()
    for word, kind in KIND_WORDS.items():
        if word in lowered:
            return kind
    return "note"


def _split_metric(label: str) -> tuple[str, str]:
    """'#dogtok — 41.2B views' -> ('#dogtok', '41.2B views')."""
    label = label.strip()
    trailing = re.search(r"\((?P<inner>[^()]+)\)\s*$", label)
    if trailing:
        return label[:trailing.start()].strip(), trailing.group("inner").strip()
    parts = re.split(r"\s+[—–]\s+|\s+-\s+", label, maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return label, ""


def parse_markdown(text: str, default_source: str = "") -> tuple[list[dict], dict]:
    """Return (rows, meta). Rows are dicts ready for Store.upsert_trend."""
    rows: list[dict] = []
    meta = {"source": default_source, "captured_at": ""}
    kind = "note"
    for line in text.splitlines():
        matched_meta = META.match(line)
        if matched_meta:
            key = matched_meta.group("key").lower()
            value = matched_meta.group("value")
            if key == "source":
                meta["source"] = value
            else:
                meta["captured_at"] = value
            continue
        heading = HEADING.match(line)
        if heading:
            title = heading.group("title")
            # the document title (single #) names the file, not a section
            if not line.startswith("# "):
                kind = _kind_for(title)
            continue
        bullet = BULLET.match(line)
        if bullet:
            label, metric = _split_metric(bullet.group("label"))
            if label:
                rows.append({"label": label, "kind": kind, "metric": metric})
    return rows, meta


def parse_csv(text: str, default_source: str = "") -> tuple[list[dict], dict]:
    reader = csv.DictReader(text.splitlines())
    if not reader.fieldnames:
        return [], {"source": default_source, "captured_at": ""}
    lowered = {name.lower().strip(): name for name in reader.fieldnames}
    if "label" not in lowered:
        raise ValueError(
            f"CSV needs a 'label' column; found {list(reader.fieldnames)}")
    rows = []
    for record in reader:
        label = (record.get(lowered["label"]) or "").strip()
        if not label:
            continue
        rows.append({
            "label": label,
            "kind": (record.get(lowered.get("kind", ""), "") or "note").strip(),
            "metric": (record.get(lowered.get("metric", ""), "") or "").strip(),
            "note": (record.get(lowered.get("note", ""), "") or "").strip(),
        })
    return rows, {"source": default_source, "captured_at": ""}


def import_file(store: Store, path: Path) -> int:
    """Parse one trend file into the store. Returns rows written."""
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".csv":
        rows, meta = parse_csv(text, default_source=path.stem)
    else:
        rows, meta = parse_markdown(text, default_source=path.stem)
    for row in rows:
        store.upsert_trend(
            label=row["label"], kind=row.get("kind") or "note",
            source=meta["source"] or path.stem, metric=row.get("metric", ""),
            note=row.get("note", ""), captured_at=meta["captured_at"])
    return len(rows)


def import_dir(store: Store, directory: Path) -> dict[str, int]:
    """Import every .md/.csv/.txt file in a directory. Returns {filename: rows}."""
    directory = Path(directory)
    if not directory.is_dir():
        return {}
    results: dict[str, int] = {}
    for path in sorted(directory.iterdir()):
        if path.suffix.lower() not in (".md", ".csv", ".txt"):
            continue
        results[path.name] = import_file(store, path)
    return results
