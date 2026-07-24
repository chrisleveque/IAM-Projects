from jobagent.scrapers.linkedin import parse_page_title


def test_logged_in_title_with_notification_count():
    title, company = parse_page_title("(2) Senior IAM Engineer | Globex | LinkedIn")
    assert title == "Senior IAM Engineer"
    assert company == "Globex"


def test_logged_in_title_without_company():
    title, company = parse_page_title("IAM Analyst | LinkedIn")
    assert title == "IAM Analyst"
    assert company == ""


def test_guest_hiring_format():
    title, company = parse_page_title(
        "Globex hiring Senior IAM Engineer in Austin, TX | LinkedIn")
    assert title == "Senior IAM Engineer"
    assert company == "Globex"


def test_empty_and_bare_linkedin():
    assert parse_page_title("") == ("", "")
    assert parse_page_title("LinkedIn") == ("LinkedIn", "")  # degenerate, non-crashing
