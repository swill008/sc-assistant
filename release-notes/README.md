# Release notes

Each version's notes live here as `<version>.md`, e.g. `1.0.0.md`. The file
starts with `## What's new in <version>`, then `### New`, `### Changed` and
`### Fixed` sections as needed. Write them in plain, user-facing words: what
changed for the person using the app, not how the code changed.

`CHANGES.md` stays the technical history (measurements, evidence, file
details); these files are what users read.

A release needs its file. The release workflow
(`.github/workflows/release.yml`) runs `tools/release_body.py <version>`
before building; it stops when the file for the version in `app/version.py`
is missing or doesn't start with that heading. The release text on GitHub is
the file followed by a "How to install" section, and the app's
Settings → Update shows the "What's new in <version>" section from it.

`tools/release_notes_selftest.py` checks all of this; with `RELEASE_CHECK=1`
set (the release workflow sets it) it also fails when `app/version.py` names
a version without a file here.
