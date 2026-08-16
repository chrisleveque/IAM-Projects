import os
from pathlib import Path


def write_private(path: Path, text: str) -> None:
    """Write a secret-bearing file (token caches) readable only by the owner.

    Path.write_text honours the process umask, which typically leaves the
    file world-readable; live access tokens must not be.
    """
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
