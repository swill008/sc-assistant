"""Builds a GitHub release's text from release-notes/<version>.md.

    python tools/release_body.py <version> [--out FILE] [--notes-dir DIR]

The text is the notes file followed by "## How to install". Exits 1 with a
message when the notes file is missing or doesn't start with
"## What's new in <version>". Used by .github/workflows/release.yml.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:          # run as a script by release.yml
    sys.path.insert(0, str(ROOT))

from app import version as _names  # noqa: E402

NOTES_DIR = ROOT / "release-notes"

# Release download names; the workflows and installer build these files.
# They come from app/version.py, the one place a rename touches.
SETUP_ASSET = _names.SETUP_ASSET
ZIP_ASSET = _names.ZIP_ASSET


class ReleaseNotesError(Exception):
    """The notes file for a version is missing or malformed."""


def install_text(version: str) -> str:
    setup = SETUP_ASSET.format(version=version)
    return (
        "## How to install\n"
        "\n"
        f"- Installer: run {setup}. It installs for your Windows user only"
        " (no administrator rights), and installed copies update from"
        " Settings → Update.\n"
        f"- Standalone: unzip {ZIP_ASSET} anywhere and run it. To update,"
        " download the new zip.\n"
        "- Unsigned build: Windows SmartScreen may warn on first run"
        " (More info → Run anyway).\n"
    )


def build_body(version: str, notes_dir: Path = NOTES_DIR) -> str:
    path = Path(notes_dir) / f"{version}.md"
    if not path.is_file():
        raise ReleaseNotesError(
            f"No release notes for {version}: add release-notes/{version}.md"
            f" (looked for {path})."
        )
    notes = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    heading = f"## What's new in {version}"
    first = notes.lstrip("\n").split("\n", 1)[0].rstrip()
    if first != heading:
        raise ReleaseNotesError(
            f"release-notes/{version}.md must start with '{heading}'"
            f" (found '{first}')."
        )
    return notes.strip() + "\n\n" + install_text(version)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("version", help="e.g. 1.0.0 (a leading v is dropped)")
    parser.add_argument("--out", type=Path, help="write here instead of stdout")
    parser.add_argument("--notes-dir", type=Path, default=NOTES_DIR)
    args = parser.parse_args(argv)
    version = args.version.removeprefix("v")
    try:
        body = build_body(version, args.notes_dir)
    except ReleaseNotesError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    if args.out:
        args.out.write_text(body, encoding="utf-8", newline="\n")
        print(f"Release notes for {version} written to {args.out}")
    else:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        sys.stdout.write(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
