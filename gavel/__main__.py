"""Allow `python -m gavel`."""

import sys

from gavel.cli import main

if __name__ == "__main__":
    sys.exit(main())
