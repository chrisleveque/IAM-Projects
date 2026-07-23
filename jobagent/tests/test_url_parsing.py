from jobagent.scrapers.indeed import jk_from_url, job_url_from_jk
from jobagent.scrapers.linkedin import canonical_job_url


def test_indeed_jk_from_common_url_shapes():
    assert jk_from_url("https://www.indeed.com/viewjob?jk=abc123def456") == "abc123def456"
    assert jk_from_url("https://www.indeed.com/rc/clk?jk=deadbeef01&from=serp") == "deadbeef01"
    assert jk_from_url("https://www.indeed.com/viewjob?from=x&jk=00ff00ff&tk=y") == "00ff00ff"
    assert jk_from_url("https://www.indeed.com/jobs?q=iam") is None
    assert job_url_from_jk("abc") == "https://www.indeed.com/viewjob?jk=abc"


def test_linkedin_canonical_strips_tracking():
    url = "https://www.linkedin.com/jobs/view/4439743037/?refId=x&trackingId=y"
    assert canonical_job_url(url) == "https://www.linkedin.com/jobs/view/4439743037/"
    # regional domains keep their host
    sa = "https://sa.linkedin.com/jobs/view/some-title-4439743037?trk=z"
    assert canonical_job_url(sa) == "https://sa.linkedin.com/jobs/view/some-title-4439743037/"
