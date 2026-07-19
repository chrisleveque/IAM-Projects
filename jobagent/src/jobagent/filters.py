"""Discovery filters: drop unwanted jobs at scan time, before they enter the
tracker.

Configured under `filters:` in config.yaml:

    filters:
      exclude_regions: [europe, middle_east]   # region keyword packs below
      exclude_location_keywords: []            # extra substrings to block
      exclude_title_special_chars: true        # drop emoji/symbol-laden titles

Region matching is keyword-based against the scraped location string (which
is freeform text like "London, England, United Kingdom" or "Remote - EMEA"),
so the packs list countries, major hub cities, and region shorthands.
"""

from __future__ import annotations

from .config import FiltersConfig
from .store import Job, Store

EUROPE_KEYWORDS = [
    "europe", "emea", "european union",
    # countries
    "albania", "austria", "belarus", "belgium", "bosnia", "bulgaria",
    "croatia", "cyprus", "czech", "denmark", "estonia", "finland", "france",
    "germany", "greece", "hungary", "iceland", "ireland", "italy", "kosovo",
    "latvia", "lithuania", "luxembourg", "malta", "moldova", "monaco",
    "montenegro", "netherlands", "north macedonia", "norway", "poland",
    "portugal", "romania", "serbia", "slovakia", "slovenia", "spain",
    "sweden", "switzerland", "ukraine", "united kingdom",
    # common location forms / hub cities
    "england", "scotland", "wales", "amsterdam", "barcelona", "berlin",
    "brussels", "bucharest", "budapest", "copenhagen", "dublin", "frankfurt",
    "geneva", "krakow", "lisbon", "london", "madrid", "milan", "munich",
    "oslo", "paris", "prague", "stockholm", "vienna", "warsaw", "zurich",
]

MIDDLE_EAST_KEYWORDS = [
    "middle east", "gulf region", "gcc",
    # countries
    "bahrain", "egypt", "iran", "iraq", "israel", "jordan", "kuwait",
    "lebanon", "oman", "qatar", "saudi arabia", "syria", "turkey", "türkiye",
    "united arab emirates", "yemen",
    # common location forms / hub cities
    "abu dhabi", "amman", "ankara", "beirut", "cairo", "doha", "dubai",
    "istanbul", "jeddah", "riyadh", "tel aviv",
]

REGION_PACKS: dict[str, list[str]] = {
    "europe": EUROPE_KEYWORDS,
    "middle_east": MIDDLE_EAST_KEYWORDS,
}

# Characters a legitimate job title uses. isalnum() covers accented letters;
# the punctuation set covers real titles like "Sr. IAM Engineer (Okta) - C#/.NET".
# Anything outside this — emoji, ★, ✅, |, !!, $$$ — marks a spammy listing.
TITLE_ALLOWED_PUNCTUATION = set("&/-,.()+#':;")


def title_has_special_chars(title: str) -> bool:
    return any(not (ch.isalnum() or ch.isspace() or ch in TITLE_ALLOWED_PUNCTUATION)
               for ch in title)


def _location_keywords(filters: FiltersConfig) -> list[str]:
    keywords: list[str] = []
    for region in filters.exclude_regions:
        pack = REGION_PACKS.get(region.strip().lower())
        if pack:
            keywords.extend(pack)
    keywords.extend(k.lower() for k in filters.exclude_location_keywords if k.strip())
    return keywords


def exclusion_reason(job: Job, filters: FiltersConfig) -> str | None:
    """Why this job should be dropped, or None to keep it."""
    location = (job.location or "").lower()
    for keyword in _location_keywords(filters):
        if keyword in location:
            return f"location matches excluded keyword '{keyword}'"
    if filters.exclude_title_special_chars and title_has_special_chars(job.title or ""):
        return "title contains special characters"
    return None


class FilteringStore:
    """Store wrapper handed to the scrapers during scan: drops excluded jobs
    at upsert time and counts what was blocked. Everything else proxies
    through to the real store."""

    def __init__(self, store: Store, filters: FiltersConfig, on_skip=None):
        self._store = store
        self._filters = filters
        self._on_skip = on_skip or (lambda job, reason: None)
        self.skipped = 0

    def upsert_job(self, job: Job) -> bool:
        reason = exclusion_reason(job, self._filters)
        if reason is not None:
            self.skipped += 1
            self._on_skip(job, reason)
            return False
        return self._store.upsert_job(job)

    def __getattr__(self, name):
        return getattr(self._store, name)


def skip_existing_matches(store: Store, filters: FiltersConfig) -> list[Job]:
    """Mark already-tracked jobs that match the filters as skipped (applied
    jobs are left untouched). Returns the jobs that were skipped."""
    skipped = []
    for job in store.list_jobs(status=("discovered", "scored", "queued", "tailored")):
        reason = exclusion_reason(job, filters)
        if reason is not None:
            store.update(job.url, status="skipped",
                         score_reasons=f"filtered: {reason}")
            skipped.append(job)
    return skipped
