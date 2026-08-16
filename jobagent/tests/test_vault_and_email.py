import re

from jobagent.email_verify import Verification, extract_verification
from jobagent.vault import Vault, generate_password


# --- password generation ---------------------------------------------------

def test_generated_passwords_satisfy_ats_policies():
    for _ in range(50):
        pw = generate_password()
        assert len(pw) == 20
        assert re.search(r"[A-Z]", pw) and re.search(r"[a-z]", pw)
        assert re.search(r"[0-9]", pw) and re.search(r"[!@#$%^*\-_+=]", pw)


def test_generated_passwords_are_unique():
    assert len({generate_password() for _ in range(50)}) == 50


# --- vault -----------------------------------------------------------------

def test_vault_roundtrip_and_encryption_at_rest(tmp_path):
    vault = Vault(tmp_path / "vault.enc")
    cred = vault.create("acme.wd1.myworkdayjobs.com", "c@example.com", note="test")

    loaded = Vault(tmp_path / "vault.enc").get("ACME.wd1.myworkdayjobs.com")
    assert loaded is not None
    assert loaded.password == cred.password
    assert loaded.email == "c@example.com"

    # ciphertext on disk must not contain the secrets
    raw = (tmp_path / "vault.enc").read_bytes()
    assert cred.password.encode() not in raw
    assert b"c@example.com" not in raw


def test_vault_never_overwrites_an_existing_credential(tmp_path):
    vault = Vault(tmp_path / "vault.enc")
    first = vault.create("host", "c@example.com")
    second = vault.create("host", "other@example.com")
    assert second.password == first.password
    assert second.email == "c@example.com"


def test_vault_with_wrong_key_fails_loudly(tmp_path):
    vault = Vault(tmp_path / "vault.enc")
    vault.create("host", "c@example.com")
    (tmp_path / ".vault.key").unlink()

    import pytest

    with pytest.raises(RuntimeError, match="does not match"):
        Vault(tmp_path / "vault.enc").get("host")


def test_vault_delete(tmp_path):
    vault = Vault(tmp_path / "vault.enc")
    vault.create("host", "c@example.com")
    assert vault.delete("HOST")
    assert vault.get("host") is None
    assert not vault.delete("host")


# --- verification email parsing --------------------------------------------

def test_extracts_workday_style_verification_link():
    html = ('<p>Welcome!</p><a href="https://acme.wd1.myworkdayjobs.com/'
            'activate?token=abc123&amp;src=mail">Verify your email</a>'
            '<a href="https://acme.wd1.myworkdayjobs.com/help">Help</a>')
    found = extract_verification("", html, "acme")
    assert found.link == \
        "https://acme.wd1.myworkdayjobs.com/activate?token=abc123&src=mail"


def test_extracts_one_time_code():
    found = extract_verification("Your verification code is: 482913", "")
    assert found.code == "482913"
    found = extract_verification("Enter this passcode 4821 to continue", "")
    assert found.code == "4821"


def test_no_verification_content_found():
    found = extract_verification("Thanks for your interest in Acme!",
                                 "<p>We received your application.</p>")
    assert not found.found
    assert isinstance(found, Verification)


def test_plain_marketing_links_are_not_mistaken_for_verification():
    html = ('<a href="https://acme.com/careers">Careers</a>'
            '<a href="https://twitter.com/acme">Follow us</a>')
    assert not extract_verification("", html).found


# --- git privacy tripwire --------------------------------------------------

def test_doctor_privacy_check_flags_tracked_secrets(tmp_path, monkeypatch):
    import subprocess
    from types import SimpleNamespace

    subprocess.run(["git", "init", "-q"], cwd=tmp_path)
    (tmp_path / "profile").mkdir()
    secret = tmp_path / "profile" / "answers.yaml"
    secret.write_text("email: real@example.com")
    subprocess.run(["git", "add", "profile/answers.yaml"], cwd=tmp_path)

    from jobagent.cli import _check_git_privacy

    flagged = {}

    def check(label, passed, hint=""):
        flagged[label] = (passed, hint)

    _check_git_privacy(SimpleNamespace(root=tmp_path), check)
    label = next(iter(flagged))
    passed, hint = flagged[label]
    assert passed is False
    assert "answers.yaml" in hint and "git rm --cached" in hint


def test_doctor_privacy_check_passes_when_untracked(tmp_path):
    import subprocess
    from types import SimpleNamespace

    subprocess.run(["git", "init", "-q"], cwd=tmp_path)
    (tmp_path / "profile").mkdir()
    (tmp_path / "profile" / "answers.yaml").write_text("email: x")  # untracked

    from jobagent.cli import _check_git_privacy

    result = {}
    _check_git_privacy(SimpleNamespace(root=tmp_path),
                       lambda label, passed, hint="": result.update(passed=passed))
    assert result["passed"] is True
