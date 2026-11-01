"""Offline checks for the release notes tooling.

    python tools/release_notes_selftest.py

Checks tools/release_body.py against a temporary notes folder and that both
workflows parse and wire it in. With RELEASE_CHECK=1 (the release workflow
sets it) it also fails when app/version.py's VERSION has no
release-notes/<version>.md. Prints PASS/FAIL per check; the exit code is the
number of failures.
"""
from __future__ import annotations

import contextlib
import io
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import version  # noqa: E402
from tools import release_body  # noqa: E402

WORKFLOWS = ROOT / ".github" / "workflows"
FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        FAILURES.append(name)


def run_main(args: list[str]) -> tuple[int, str]:
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        code = release_body.main(args)
    return code, err.getvalue()


def test_body(notes: Path) -> None:
    (notes / "9.8.7.md").write_text(
        "## What's new in 9.8.7\n\n### New\n- A thing.\n\n### Fixed\n- Another.\n",
        encoding="utf-8",
    )
    out = notes / "body.md"
    code, err = run_main(["v9.8.7", "--notes-dir", str(notes), "--out", str(out)])
    check("body: exit 0 for a good file", code == 0, err)
    body = out.read_text(encoding="utf-8") if out.exists() else ""
    check("body: starts with the notes heading", body.startswith("## What's new in 9.8.7\n"))
    check("body: keeps the notes", "- A thing." in body and "### Fixed" in body)
    check("body: has How to install", "\n## How to install\n" in body)
    setup = release_body.SETUP_ASSET.format(version="9.8.7")
    check("body: names both downloads", setup in body and release_body.ZIP_ASSET in body)
    check("body: download names come from app/version.py",
          release_body.SETUP_ASSET == version.SETUP_ASSET and release_body.ZIP_ASSET == version.ZIP_ASSET
          and "SCAssistant-9.8.7-Setup.exe" in body and "SCAssistant-windows-x64.zip" in body
          and "CitizenAssistant" not in body)
    check("body: SmartScreen hint", "More info" in body and "Run anyway" in body)
    check("body: notes come before How to install",
          body.index("- Another.") < body.index("## How to install"))


def test_errors(notes: Path) -> None:
    code, err = run_main(["1.2.3", "--notes-dir", str(notes), "--out", str(notes / "x.md")])
    check("missing file: exit 1", code == 1)
    check("missing file: clear message",
          "No release notes for 1.2.3" in err and "release-notes/1.2.3.md" in err, err)
    check("missing file: no output written", not (notes / "x.md").exists())

    (notes / "4.5.6.md").write_text("## What's new in 4.5.5\n\n### New\n- x\n", encoding="utf-8")
    code, err = run_main(["4.5.6", "--notes-dir", str(notes)])
    check("wrong heading: exit 1", code == 1)
    check("wrong heading: clear message",
          "must start with '## What's new in 4.5.6'" in err and "found '## What's new in 4.5.5'" in err,
          err)


def test_workflows() -> None:
    try:
        import yaml
    except ImportError:
        check("workflows: PyYAML available", False, "pip install pyyaml")
        return
    docs = {}
    for name in ("release.yml", "build-exe.yml"):
        try:
            docs[name] = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
            check(f"workflows: {name} parses", isinstance(docs[name], dict))
        except Exception as error:  # noqa: BLE001
            check(f"workflows: {name} parses", False, str(error))
    if not isinstance(docs.get("release.yml"), dict):
        return

    steps = docs["release.yml"]["jobs"]["release"]["steps"]
    names = [str(step.get("name", "")) for step in steps]
    runs = [str(step.get("run", "")) for step in steps]
    notes = [i for i, run in enumerate(runs) if "tools/release_body.py" in run]
    check("release.yml: a step calls tools/release_body.py", bool(notes))
    if notes:
        i = notes[0]
        check("release.yml: notes step writes release_notes.md",
              "--out release_notes.md" in runs[i])
        check("release.yml: notes step can't be skipped",
              "continue-on-error" not in steps[i] and "if" not in steps[i])
        build = [j for j, name in enumerate(names) if name == "Build"]
        check("release.yml: notes step runs before Build", bool(build) and i < build[0])
    check("release.yml: CHANGES.md step gone",
          not any("CHANGES.md" in run for run in runs))
    selftest = [s for s in steps if "release_notes_selftest" in str(s.get("run", ""))]
    check("release.yml: self-test runs with RELEASE_CHECK=1",
          any(str((s.get("env") or {}).get("RELEASE_CHECK")) == "1" for s in selftest))
    publish = [s for s in steps if "action-gh-release" in str(s.get("uses", ""))]
    check("release.yml: publish uses release_notes.md",
          bool(publish) and publish[0]["with"].get("body_path") == "release_notes.md")

    build_doc = docs.get("build-exe.yml")
    if isinstance(build_doc, dict):
        runs = [str(s.get("run", "")) for s in build_doc["jobs"]["build"]["steps"]]
        check("build-exe.yml: runs the release notes self-test",
              any("release_notes_selftest" in run for run in runs))

    for name, doc in docs.items():
        if isinstance(doc, dict):
            test_names(name, doc)


def test_names(name: str, doc: dict) -> None:
    """Build, zip, Setup and artifact names match app/version.py and exist."""
    text = (WORKFLOWS / name).read_text(encoding="utf-8")
    steps = next(iter(doc["jobs"].values()))["steps"]
    runs = {str(s.get("name", "")): str(s.get("run", "")) for s in steps}
    exe, zip_name = version.EXE_NAME, version.ZIP_ASSET
    setup_glob = "dist/" + version.SETUP_ASSET.format(version="*")
    check(f"{name}: no old Citizen Assistant names",
          not re.search(r"citizen.?assistant", text, re.I))
    build = runs.get("Build", "")
    spec = re.search(r"(\S+\.spec)", build)
    check(f"{name}: Build uses sc-assistant.spec and it exists",
          bool(spec) and spec.group(1) == "sc-assistant.spec" and (ROOT / spec.group(1)).is_file(), build)
    package = runs.get("Package standalone zip", "")
    check(f"{name}: zip packs dist/{exe} into {zip_name}",
          f"dist/{exe}/*" in package and package.rstrip().endswith(zip_name), package)
    installer = runs.get("Build installer", "")
    check(f"{name}: installer step's script exists",
          (ROOT / installer.strip().replace("\\", "/")).is_file(), installer)
    check(f"{name}: installer/sc_assistant.iss exists", (ROOT / "installer" / "sc_assistant.iss").is_file())
    script = ROOT / "installer" / "build_installer.ps1"
    body = script.read_text(encoding="utf-8-sig") if script.is_file() else ""
    check(f"{name}: build_installer.ps1 reads dist\\{exe} and builds sc_assistant.iss",
          f"dist\\{exe}\"" in body and "sc_assistant.iss" in body and "citizen_assistant.iss" not in body)
    iss = ROOT / "installer" / "sc_assistant.iss"
    iss_text = iss.read_text(encoding="utf-8-sig") if iss.is_file() else ""
    check(f"{name}: sc_assistant.iss names the Setup {version.SETUP_ASSET}",
          f'"{exe}-" + MyAppVersion + "-Setup"' in iss_text)
    uploads = [s for s in steps if "upload-artifact" in str(s.get("uses", ""))
               or "action-gh-release" in str(s.get("uses", ""))]
    files = str((uploads[0].get("with") or {}).get("path") or (uploads[0].get("with") or {}).get("files")
                ) if uploads else ""
    check(f"{name}: publishes {zip_name} and {setup_glob}",
          zip_name in files.split() and setup_glob in files.split(), files)
    tests = [s for s in steps if "selftest" in str(s.get("run", ""))]
    check(f"{name}: self-test steps set PYTHONIOENCODING=utf-8",
          bool(tests) and all((s.get("env") or {}).get("PYTHONIOENCODING") == "utf-8" for s in tests))


def test_version_has_notes() -> None:
    text = (ROOT / "app" / "version.py").read_text(encoding="utf-8")
    match = re.search(r'^VERSION\s*=\s*"([^"]+)"', text, re.M)
    if not match:
        check("version: VERSION found in app/version.py", False)
        return
    version = match.group(1)
    if os.environ.get("RELEASE_CHECK") != "1":
        print(f"SKIP  version {version} has a notes file (set RELEASE_CHECK=1)")
        return
    try:
        release_body.build_body(version)
        check(f"version: release-notes/{version}.md exists with its heading", True)
    except release_body.ReleaseNotesError as error:
        check(f"version: release-notes/{version}.md exists with its heading", False, str(error))


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        test_body(Path(tmp))
    with tempfile.TemporaryDirectory() as tmp:
        test_errors(Path(tmp))
    test_workflows()
    test_version_has_notes()
    print(f"\n{len(FAILURES)} failure(s)" + (": " + ", ".join(FAILURES) if FAILURES else ""))
    return len(FAILURES)


if __name__ == "__main__":
    sys.exit(main())
