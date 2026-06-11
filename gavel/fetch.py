"""Download the public Chinook SQLite database (MIT licensed).

Source: https://github.com/lerocha/chinook-database (release v1.4.5).
The download is SHA-256 verified before it is moved into place.
"""

from __future__ import annotations

import hashlib
import urllib.error
import urllib.request
from pathlib import Path

CHINOOK_URL = (
    "https://github.com/lerocha/chinook-database/releases/download/"
    "v1.4.5/Chinook_Sqlite.sqlite"
)
CHINOOK_SHA256 = "bdf635be69850bd3be09c9a2dbeef7ddfb80036bd3ef3381383cd03b61e4a61a"
DEFAULT_DEST = Path("data") / "Chinook_Sqlite.sqlite"


class FetchError(Exception):
    """Raised when the Chinook database cannot be fetched or verified."""


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_chinook(
    dest: str | Path = DEFAULT_DEST,
    *,
    url: str = CHINOOK_URL,
    sha256: str = CHINOOK_SHA256,
    force: bool = False,
) -> Path:
    """Download Chinook to ``dest``, verifying its SHA-256. Idempotent."""
    dest_path = Path(dest)
    if dest_path.exists() and not force:
        if sha256_of(dest_path) == sha256:
            return dest_path
        raise FetchError(
            f"{dest_path} exists but its SHA-256 does not match the pinned digest; "
            "re-run with --force to re-download"
        )
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_suffix(dest_path.suffix + ".part")
    try:
        with urllib.request.urlopen(url) as response, tmp_path.open("wb") as out:
            while chunk := response.read(1 << 16):
                out.write(chunk)
    except urllib.error.URLError as exc:
        tmp_path.unlink(missing_ok=True)
        raise FetchError(f"download failed: {exc}") from exc
    actual = sha256_of(tmp_path)
    if actual != sha256:
        tmp_path.unlink(missing_ok=True)
        raise FetchError(
            f"SHA-256 mismatch for downloaded file: expected {sha256}, got {actual}"
        )
    tmp_path.replace(dest_path)
    return dest_path
