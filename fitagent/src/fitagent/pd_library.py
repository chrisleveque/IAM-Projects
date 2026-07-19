"""Public-domain source library: assets/public_domain/*.md files with a YAML
front-matter header (key, title, author, year, attribution, license) followed
by the source text. Roughly 20% of videos build on these instead of a fully
original script."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class PDSource:
    key: str
    title: str
    author: str
    year: str
    attribution: str
    license: str
    text: str

    def summary(self) -> dict:
        return {"key": self.key, "title": self.title, "author": self.author,
                "year": self.year}


def load_sources(pd_dir: Path) -> list[PDSource]:
    sources = []
    if not pd_dir.is_dir():
        return sources
    for path in sorted(pd_dir.glob("*.md")):
        raw = path.read_text(encoding="utf-8")
        if not raw.startswith("---"):
            continue
        try:
            _, header, body = raw.split("---", 2)
            meta = yaml.safe_load(header) or {}
            sources.append(PDSource(
                key=str(meta.get("key", path.stem)),
                title=str(meta.get("title", path.stem)),
                author=str(meta.get("author", "")),
                year=str(meta.get("year", "")),
                attribution=str(meta.get("attribution", "")),
                license=str(meta.get("license", "")),
                text=body.strip(),
            ))
        except (ValueError, yaml.YAMLError):
            continue
    return sources


def get_source(pd_dir: Path, key: str) -> PDSource | None:
    for source in load_sources(pd_dir):
        if source.key == key:
            return source
    return None
