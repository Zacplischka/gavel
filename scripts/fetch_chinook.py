#!/usr/bin/env python3
"""Download the Chinook SQLite database into data/ (SHA-256 verified).

Thin wrapper over ``gavel.fetch`` so CI (and humans) can run it directly:

    python scripts/fetch_chinook.py [dest]

Equivalent to ``python -m gavel fetch``.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running from a source checkout without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gavel.fetch import DEFAULT_DEST, FetchError, fetch_chinook


def main(argv: list[str]) -> int:
    dest = Path(argv[1]) if len(argv) > 1 else DEFAULT_DEST
    try:
        path = fetch_chinook(dest)
    except FetchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"ok: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
