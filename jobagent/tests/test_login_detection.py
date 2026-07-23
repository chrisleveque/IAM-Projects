import pytest

from jobagent.scrapers.linkedin import _goto, _stuck_on_login


class FakePage:
    def __init__(self, failures: int):
        self.failures = failures
        self.goto_calls = 0
        self.waits: list[int] = []
        self.url = ""

    def goto(self, url, wait_until=None):
        self.goto_calls += 1
        if self.goto_calls <= self.failures:
            raise RuntimeError("Navigation is interrupted by another navigation")
        self.url = url

    def wait_for_timeout(self, ms):
        self.waits.append(ms)


class FakeSession:
    def pause(self):
        pass


def test_goto_retries_through_interrupted_navigation():
    page = FakePage(failures=2)
    _goto(FakeSession(), page, "https://www.linkedin.com/my-items/saved-jobs/")
    assert page.goto_calls == 3
    assert page.url.endswith("/saved-jobs/")
    assert len(page.waits) == 2  # backed off between failed attempts


def test_goto_raises_after_exhausting_attempts():
    page = FakePage(failures=99)
    with pytest.raises(RuntimeError):
        _goto(FakeSession(), page, "https://www.linkedin.com/feed/", attempts=3)
    assert page.goto_calls == 3


def test_login_and_authwall_urls_detected():
    for url in (
        "https://www.linkedin.com/login",
        "https://www.linkedin.com/uas/login?session_redirect=...",
        "https://www.linkedin.com/authwall?trk=...",
        "https://www.linkedin.com/checkpoint/lg/login-submit",
        "https://www.linkedin.com/signup/cold-join",
    ):
        assert _stuck_on_login(url), url


def test_normal_pages_not_detected():
    for url in (
        "https://www.linkedin.com/jobs/search/?keywords=iam",
        "https://www.linkedin.com/my-items/saved-jobs/",
        "https://www.linkedin.com/jobs/view/123456/",
        "https://www.linkedin.com/feed/",
    ):
        assert not _stuck_on_login(url), url
