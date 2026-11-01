"""Build identity for this copy of the overlay.

A downloaded ZIP has no ``.git`` directory, so the build cannot be read from
git and has to be committed instead.  Bump both values in the same commit as a
fix: Settings shows the string, and ``python -m app --version`` prints it.

That matters because Windows happily keeps an old shortcut alive: searching
for "SC Assistant" can launch a previous folder for months.  The stamp is
how you tell, at a glance, which copy is actually running.
"""
from __future__ import annotations

VERSION = "1.0.0"
BUILD_DATE = "2026-11-01"

# The program's names, in one place for the app, installer tests and tools.
APP_NAME = "SC Assistant"                 # windows, settings folder, Start menu
EXE_NAME = "SCAssistant"                  # SCAssistant.exe, dist\SCAssistant
REPO = "swill008/sc-assistant"
MUTEX_NAME = "SCAssistantOverlay"         # single instance and installer AppMutex
SETUP_ASSET = "SCAssistant-{version}-Setup.exe"
ZIP_ASSET = "SCAssistant-windows-x64.zip"
USER_AGENT = f"SC-Assistant/{VERSION} (+https://github.com/{REPO})"

# ONE-TIME (rename to SC Assistant): the names before 1.0.0, only for the
# first-start settings move and the installer's clean-up of the old install.
OLD_APP_NAME = "Citizen Assistant"
OLD_EXE_NAME = "CitizenAssistant"
OLD_MUTEX_NAME = "CitizenAssistantOverlay"


def label() -> str:
    """Short build string, e.g. ``v1.1.0 · 2026-10-30``."""
    return f"v{VERSION} · {BUILD_DATE}"
