from jobagent.config import FiltersConfig
from jobagent.filters import (FilteringStore, exclusion_reason,
                              skip_existing_matches, title_has_special_chars)
from jobagent.store import Job, Store


def _job(title="IAM Engineer", location="Remote, United States",
         url="https://example.com/j/1"):
    return Job(url=url, source="linkedin", title=title, location=location)


FILTERS = FiltersConfig(exclude_regions=["europe", "middle_east"],
                        exclude_title_special_chars=True)


def test_titles_with_special_chars_flagged():
    assert title_has_special_chars("🚀 URGENT!! IAM Engineer 🚀")
    assert title_has_special_chars("IAM Engineer | Remote | $150k")
    assert not title_has_special_chars("Sr. IAM Engineer (Okta) - C#/.NET")
    assert not title_has_special_chars("Identity & Access Management Lead, Zürich")


def test_european_and_middle_east_locations_excluded():
    assert exclusion_reason(_job(location="London, England, United Kingdom"),
                            FILTERS) is not None
    assert exclusion_reason(_job(location="Berlin, Germany"), FILTERS) is not None
    assert exclusion_reason(_job(location="Remote - EMEA"), FILTERS) is not None
    assert exclusion_reason(_job(location="Dubai, United Arab Emirates"),
                            FILTERS) is not None
    assert exclusion_reason(_job(location="Austin, TX"), FILTERS) is None
    assert exclusion_reason(_job(location="Remote, United States"), FILTERS) is None


def test_custom_location_keywords():
    filters = FiltersConfig(exclude_location_keywords=["ontario"])
    assert exclusion_reason(_job(location="Toronto, Ontario, Canada"),
                            filters) is not None
    assert exclusion_reason(_job(location="Boston, MA"), filters) is None


def test_filters_off_by_default():
    assert exclusion_reason(
        _job(title="🚀 IAM Hero", location="Paris, France"), FiltersConfig()) is None


def test_filtering_store_drops_and_counts(tmp_path):
    store = Store(tmp_path / "jobs.db")
    skips = []
    filtering = FilteringStore(store, FILTERS,
                               on_skip=lambda job, reason: skips.append(reason))
    assert filtering.upsert_job(_job(url="https://x/1")) is True
    assert filtering.upsert_job(
        _job(url="https://x/2", location="Madrid, Spain")) is False
    assert filtering.upsert_job(
        _job(url="https://x/3", title="⭐ IAM Engineer ⭐")) is False
    assert filtering.skipped == 2 and len(skips) == 2
    assert len(store.list_jobs()) == 1
    # proxying still works
    assert filtering.status_counts()["discovered"] == 1
    store.close()


def test_skip_existing_matches_hides_tracked_jobs(tmp_path):
    store = Store(tmp_path / "jobs.db")
    store.upsert_job(_job(url="https://x/keep"))
    store.upsert_job(_job(url="https://x/europe", location="Oslo, Norway"))
    store.upsert_job(_job(url="https://x/spam", title="IAM Engineer ✅✅"))
    applied = _job(url="https://x/applied", location="Rome, Italy")
    store.upsert_job(applied)
    store.update(applied.url, status="applied")

    skipped = skip_existing_matches(store, FILTERS)
    assert {j.url for j in skipped} == {"https://x/europe", "https://x/spam"}
    assert store.get_job("https://x/keep").status == "discovered"
    assert store.get_job("https://x/europe").status == "skipped"
    assert "filtered:" in store.get_job("https://x/spam").score_reasons
    assert store.get_job("https://x/applied").status == "applied"  # untouched
    store.close()
