from jobagent.scrapers.linkedin import _stuck_on_login


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
