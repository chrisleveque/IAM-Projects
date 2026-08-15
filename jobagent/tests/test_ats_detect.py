from jobagent.ats import adapter_for, detect_ats, is_supported


def test_detects_greenhouse_variants():
    for url in (
        "https://boards.greenhouse.io/acme/jobs/4123456",
        "https://job-boards.greenhouse.io/acme/jobs/4123456",
        "https://boards.eu.greenhouse.io/acme/jobs/4123456",
        "https://acme.greenhouse.io/jobs/1",
    ):
        assert detect_ats(url) == "greenhouse", url


def test_detects_lever_variants():
    assert detect_ats("https://jobs.lever.co/acme/uuid-1234") == "lever"
    assert detect_ats("https://jobs.eu.lever.co/acme/uuid-1234") == "lever"


def test_detects_unautomated_systems():
    cases = {
        "https://careers-acme.icims.com/jobs/1234/login": "icims",
        "https://acme.taleo.net/careersection/jobdetail.ftl": "taleo",
        "https://jobs.smartrecruiters.com/Acme/74400": "smartrecruiters",
        "https://jobs.ashbyhq.com/acme/uuid": "ashby",
        "https://apply.workable.com/acme/j/ABC/": "workable",
        "https://acme.bamboohr.com/careers/42": "bamboohr",
    }
    for url, expected in cases.items():
        assert detect_ats(url) == expected, url
        # detected, but deliberately not driven unattended
        assert not is_supported(url)
        assert adapter_for(url) is None


def test_workday_is_detected_and_automated():
    for url in (
        "https://acme.wd1.myworkdayjobs.com/en-US/careers/job/R-1",
        "https://nordic.wd5.myworkdayjobs.com/Nordic/job/US/Security-Engineer",
        "https://acme.wd1.myworkdaysite.com/recruiting/acme/careers",
    ):
        assert detect_ats(url) == "workday", url
        assert is_supported(url)
        assert adapter_for(url).name == "workday"


def test_unknown_hosts_return_empty():
    assert detect_ats("https://careers.acme.com/jobs/1") == ""
    assert detect_ats("https://www.linkedin.com/jobs/view/123") == ""
    assert detect_ats("") == ""
    assert detect_ats("not a url") == ""


def test_supported_urls_get_an_adapter():
    assert adapter_for("https://boards.greenhouse.io/a/jobs/1").name == "greenhouse"
    assert adapter_for("https://jobs.lever.co/a/uuid").name == "lever"
    assert is_supported("https://boards.greenhouse.io/a/jobs/1")


def test_host_matching_is_not_fooled_by_lookalikes():
    # a domain that merely contains an ATS name must not match
    assert detect_ats("https://greenhouse.io.evil.example/jobs/1") == ""
    assert detect_ats("https://notlever.co/x") == ""
