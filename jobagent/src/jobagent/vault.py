"""Encrypted store for ATS account credentials the agent creates.

Passwords are generated here (never chosen by a model) and encrypted at rest
with Fernet. The key lives in its own gitignored file next to the vault, so
neither can end up in a commit; anyone with disk access to profile/ can read
the vault, which matches the trust level of browser_profile/ (a logged-in
session) already stored there.
"""

from __future__ import annotations

import base64
import json
import secrets
import string
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

try:
    from cryptography.fernet import Fernet, InvalidToken
except ImportError as exc:  # pragma: no cover - dependency is declared
    raise ImportError(
        "the 'cryptography' package is required for the account vault — "
        "run: pip install -e ."
    ) from exc

# Mixed classes satisfy every ATS password policy seen in the wild; 20 chars
# clears their length ceilings while staying comfortably above any minimum.
_PASSWORD_LEN = 20
_SYMBOLS = "!@#$%^*-_+="


def generate_password() -> str:
    """A password satisfying upper/lower/digit/symbol policies, from the OS CSPRNG."""
    rng = secrets.SystemRandom()
    pools = (string.ascii_uppercase, string.ascii_lowercase, string.digits, _SYMBOLS)
    chars = [rng.choice(pool) for pool in pools]
    everything = "".join(pools)
    chars += [rng.choice(everything) for _ in range(_PASSWORD_LEN - len(chars))]
    rng.shuffle(chars)
    return "".join(chars)


@dataclass
class Credential:
    host: str            # e.g. nordic.wd1.myworkdayjobs.com
    email: str
    password: str
    created_at: str = ""
    note: str = ""       # e.g. "created by auto-apply for Security Engineer I"


class Vault:
    def __init__(self, path: Path):
        self.path = path
        self.key_path = path.with_name(".vault.key")

    # --- key handling ----------------------------------------------------
    def _fernet(self) -> Fernet:
        if self.key_path.exists():
            key = self.key_path.read_bytes().strip()
        else:
            key = Fernet.generate_key()
            self.key_path.parent.mkdir(parents=True, exist_ok=True)
            self.key_path.write_bytes(key)
            try:  # best effort on Windows, effective on POSIX
                self.key_path.chmod(0o600)
            except OSError:
                pass
        return Fernet(key)

    # --- storage ---------------------------------------------------------
    def _load(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        token = self.path.read_bytes()
        try:
            raw = self._fernet().decrypt(token)
        except InvalidToken:
            raise RuntimeError(
                f"could not decrypt {self.path} — the key file "
                f"{self.key_path.name} does not match. If the key was lost, "
                "delete the vault and let the agent re-create accounts "
                "(existing ATS passwords can be reset by email)."
            )
        return json.loads(raw.decode("utf-8"))

    def _save(self, data: dict[str, dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        token = self._fernet().encrypt(
            json.dumps(data, ensure_ascii=False).encode("utf-8"))
        self.path.write_bytes(token)
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    # --- API -------------------------------------------------------------
    def get(self, host: str) -> Credential | None:
        entry = self._load().get(host.lower())
        return Credential(**entry) if entry else None

    def create(self, host: str, email: str, note: str = "") -> Credential:
        """Generate and persist credentials for a host. Never overwrites —
        losing a working password would lock the agent out of that tenant."""
        host = host.lower()
        data = self._load()
        if host in data:
            return Credential(**data[host])
        cred = Credential(
            host=host, email=email, password=generate_password(),
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            note=note,
        )
        data[host] = asdict(cred)
        self._save(data)
        return cred

    def list(self) -> list[Credential]:
        return [Credential(**entry) for entry in self._load().values()]

    def delete(self, host: str) -> bool:
        data = self._load()
        if data.pop(host.lower(), None) is None:
            return False
        self._save(data)
        return True
