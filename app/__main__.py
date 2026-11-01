"""Entry point for ``python -m app`` and the Windows launchers."""
from __future__ import annotations

import sys


def _run() -> int:
    # Answer --version before importing Qt.  A broken or half-updated install
    # can still report which build it is, which is the first question when an
    # old copy keeps winning over the new one.
    if "--version" in sys.argv[1:]:
        from .version import APP_NAME, label

        print(f"{APP_NAME} {label()}")
        return 0

    from .main import main

    return main()


raise SystemExit(_run())
