"""python -m transmitter"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running from repo root without installation
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> None:
    from transmitter.app import main as app_main

    raise SystemExit(app_main())


if __name__ == "__main__":
    main()
