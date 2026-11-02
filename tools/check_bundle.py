"""Fail when a built EXE is missing any app module.

    python tools/check_bundle.py dist/SCAssistant/SCAssistant.exe

Lists every module under app/ from the source files and checks each one is in
the EXE's PYZ archive. 1.0.4 shipped without the voice engines that are loaded
by name at run time (app.tts.windows, .piper, .kokoro, .edge, .addons); the
release workflow runs this right after the build so that cannot ship again.
Exit code 0 when complete, 1 with the missing modules listed.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def source_modules(root: Path = ROOT) -> set[str]:
    mods = set()
    for path in (root / "app").rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(root).with_suffix("")
        parts = list(rel.parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        mods.add(".".join(parts))
    return mods


def bundled_modules(exe: Path) -> set[str]:
    from PyInstaller.archive.readers import CArchiveReader

    archive = CArchiveReader(str(exe))
    names = [n for n in archive.toc if n.endswith(".pyz")]
    if not names:
        raise SystemExit(f"{exe}: no PYZ archive found")
    pyz = archive.open_embedded_archive(names[0])
    return set(pyz.toc)


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    exe = Path(argv[0])
    if not exe.is_file():
        print(f"FAIL  {exe} does not exist")
        return 1
    wanted = source_modules()
    have = bundled_modules(exe)
    missing = sorted(wanted - have)
    if missing:
        print(f"FAIL  {len(missing)} app module(s) missing from {exe.name}:")
        for mod in missing:
            print(f"        {mod}")
        return 1
    print(f"PASS  all {len(wanted)} app modules are in {exe.name}")
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    raise SystemExit(main(sys.argv[1:]))
