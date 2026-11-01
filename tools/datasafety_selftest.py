"""Data-safety checks: user files are never lost to a failed read.

    python -m tools.datasafety_selftest          # check the working copy
    python -m tools.datasafety_selftest --old    # same checks on HEAD's files

Covers notes.txt, inventory.json, the blueprint registry and the ore-finder
cache: a locked file, a Windows-1252 file, broken JSON and a cache entry with
unknown fields must not crash, must not be overwritten (bytes compared), must
be reported, a normal save keeps a .bak, and a short lock is retried.  Also
checks the pin buttons on the NOTES and INVENTORY panels.

Everything runs in a temporary folder with a temporary APPDATA and Qt's
off-screen platform, so no window appears and no real user file is touched.
Prints PASS/FAIL lines; the exit code is the number of failures.

``--old`` copies app/ to a temporary folder, puts back HEAD's versions of the
data-safety files (``git show HEAD:<path>``, no checkout) and runs the same
checks there, to show which ones the old code fails.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

OWNED = ("app/notes.py", "app/ui/notes_panel.py", "app/inventory.py",
         "app/ui/inventory_panel.py", "app/blueprints.py", "app/orefinder.py")

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""),
          flush=True)
    return bool(ok)


def run_case(name: str, func) -> None:
    """Run one case; an exception is a FAIL with its type and message."""
    try:
        func()
    except Exception as exc:  # noqa: BLE001 - every crash is a finding
        tb = traceback.extract_tb(exc.__traceback__)[-1]
        check(name, False, f"crashed: {type(exc).__name__}: {exc} "
                           f"[{Path(tb.filename).name}:{tb.lineno}]")


# ---------------------------------------------------------------------------
# Windows file lock: open with no sharing, like an editor or scanner can.
class FileLock:
    GENERIC_READ = 0x80000000
    OPEN_EXISTING = 3
    INVALID = ctypes.c_void_p(-1).value

    def __init__(self, path: Path):
        self.path = path
        self.handle = None

    def __enter__(self) -> "FileLock":
        k32 = ctypes.windll.kernel32
        k32.CreateFileW.restype = ctypes.c_void_p
        k32.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
                                    ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                                    ctypes.c_void_p]
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = k32.CreateFileW(str(self.path), self.GENERIC_READ, 0, None,
                                 self.OPEN_EXISTING, 0, None)
        if handle in (None, self.INVALID):
            raise OSError(f"could not lock {self.path}")
        self.handle = handle
        return self

    def release(self) -> None:
        if self.handle is not None:
            ctypes.windll.kernel32.CloseHandle(self.handle)
            self.handle = None

    def __exit__(self, *exc) -> None:
        self.release()


def release_later(lock: FileLock, seconds: float) -> threading.Thread:
    thread = threading.Thread(target=lambda: (time.sleep(seconds), lock.release()),
                              daemon=True)
    thread.start()
    return thread


def head_neighbour(widget):
    """The widget just right of *widget* in its header layout (or None)."""
    from PySide6.QtWidgets import QLayout
    root = widget.window().layout()
    stack: list[QLayout] = [root]
    while stack:
        layout = stack.pop()
        index = layout.indexOf(widget)
        if index >= 0:
            item = layout.itemAt(index + 1)
            return item.widget() if item is not None else None
        for i in range(layout.count()):
            child = layout.itemAt(i).layout()
            if child is not None:
                stack.append(child)
    return None


NOTES_TEXT = "Hurston buyer: TDD Lorville.\nKeep 3 SCU Quantanium for later.\n"
INVENTORY = {"version": 1, "notes": [
    {"id": "a1", "location": "Area18", "item": "FS-9 LMG", "quantity": "1",
     "note": "locker", "updated": 200.0},
    {"id": "b2", "location": "Lorville", "item": "Medpens", "quantity": "6",
     "note": "", "updated": 100.0},
]}
REGISTRY = {"version": 1, "updated_at": "2026-10-01T00:00:00+00:00",
            "blueprints": {
                "coda_pistol": {"item_name": "Coda Pistol", "item_code": "Coda Pistol",
                                "first_seen": 1.0, "last_seen": 1.0, "seen_count": 1},
                "defiance_helmet": {"item_name": "Defiance Helmet",
                                    "item_code": "Defiance Helmet",
                                    "first_seen": 2.0, "last_seen": 2.0,
                                    "seen_count": 1}},
            "items": {}}


# ---------------------------------------------------------------------------
def main_checks(tmp: Path) -> None:
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])

    from app import blueprints as bp_mod
    from app.blueprint_log import KIND_BLUEPRINT, BlueprintLogEvent
    from app.inventory import InventoryStore
    from app.notes import NotesStore
    from app.orefinder import LiveData
    from app.ui.inventory_panel import InventoryPanel
    from app.ui.notes_panel import NotesPanel

    def bp_event(name: str, ts: float) -> BlueprintLogEvent:
        return BlueprintLogEvent(kind=KIND_BLUEPRINT, item_name=name,
                                 item_code=name, timestamp=ts,
                                 timestamp_iso="2026-11-01T00:00:00+00:00",
                                 quantity=0, container="")

    def fresh(name: str) -> Path:
        folder = tmp / name
        folder.mkdir()
        return folder

    # -- notes: locked at start-up, released before hide/quit --------------
    def notes_locked():
        path = fresh("notes_locked") / "notes.txt"
        path.write_text(NOTES_TEXT, encoding="utf-8")
        before = path.read_bytes()
        with FileLock(path):
            panel = NotesPanel(NotesStore(path))
        panel.flush()                       # the hide / aboutToQuit flush
        panel.editor.setPlainText("typed while not loaded")
        panel.flush()
        check("notes: locked at start-up, nothing written on flush",
              path.read_bytes() == before,
              f"file now {len(path.read_bytes())} bytes, was {len(before)}")
        check("notes: panel says NOT LOADED and is read-only",
              panel.status.text() == "NOT LOADED" and panel.editor.isReadOnly(),
              f"status={panel.status.text()!r} readOnly={panel.editor.isReadOnly()}")
        # Re-opening once the lock is gone loads the real text.
        panel.show()
        app.processEvents()
        check("notes: reopening after the lock is gone loads the text",
              panel.editor.toPlainText() == NOTES_TEXT
              and not panel.editor.isReadOnly())
        panel.hide()
        panel.deleteLater()
    run_case("notes: locked file", notes_locked)

    # -- notes: Windows-1252 file --------------------------------------------
    def notes_cp1252():
        path = fresh("notes_cp1252") / "notes.txt"
        raw = "Caf\xe9 at Lorville – cost 5€\n".encode("cp1252")
        path.write_bytes(raw)
        panel = NotesPanel(NotesStore(path))
        check("notes: Windows-1252 file opens without a crash",
              "Café" in panel.editor.toPlainText()
              and "€" in panel.editor.toPlainText())
        panel.flush()
        check("notes: unchanged text is not rewritten", path.read_bytes() == raw)
        panel.deleteLater()
    run_case("notes: Windows-1252 file", notes_cp1252)

    # -- notes: dirty flag + .bak --------------------------------------------
    def notes_bak():
        folder = fresh("notes_bak")
        path = folder / "notes.txt"
        path.write_text(NOTES_TEXT, encoding="utf-8")
        before = path.read_bytes()
        panel = NotesPanel(NotesStore(path))
        panel.flush()
        check("notes: flush without an edit does not write",
              not (folder / "notes.txt.bak").exists() and path.read_bytes() == before)
        panel.editor.setPlainText(NOTES_TEXT + "new line\n")
        panel.flush()
        bak = folder / "notes.txt.bak"
        check("notes: an edit is saved and the old file kept as .bak",
              path.read_text(encoding="utf-8").endswith("new line\n")
              and bak.exists() and bak.read_bytes() == before)
        panel.deleteLater()
    run_case("notes: .bak on save", notes_bak)

    # -- notes: a short lock during a save is retried ------------------------
    def notes_retry():
        path = fresh("notes_retry") / "notes.txt"
        path.write_text(NOTES_TEXT, encoding="utf-8")
        store = NotesStore(path)
        store.load()
        lock = FileLock(path).__enter__()
        release_later(lock, 0.25)
        try:
            store.save("after the lock")
        finally:
            lock.release()
        check("notes: a 0.25 s lock during a save is retried",
              path.read_text(encoding="utf-8") == "after the lock")
    run_case("notes: transient lock retried", notes_retry)

    # -- inventory: locked at start-up ---------------------------------------
    def inventory_locked():
        path = fresh("inv_locked") / "inventory.json"
        path.write_text(json.dumps(INVENTORY, indent=2), encoding="utf-8")
        before = path.read_bytes()
        with FileLock(path):
            panel = InventoryPanel(InventoryStore(path))
        store = panel.store
        store.add("New Babbage", "Pyro RYT", "1", "")
        store.delete("a1")
        check("inventory: locked at start-up, ADD/delete do not overwrite",
              path.read_bytes() == before,
              f"file now {len(path.read_bytes())} bytes, was {len(before)}")
        check("inventory: panel shows the error and disables ADD",
              bool(store.error) and not panel.submit_btn.isEnabled()
              and "NOT LOADED" in panel.status.text(),
              f"error={store.error!r} add_enabled={panel.submit_btn.isEnabled()} "
              f"status={panel.status.text()!r}")
        panel.show()
        app.processEvents()
        check("inventory: reopening after the lock is gone loads the notes",
              len(panel.store.notes) == 2 and panel.submit_btn.isEnabled())
        panel.hide()
        panel.deleteLater()
    run_case("inventory: locked file", inventory_locked)

    # -- inventory: Windows-1252 file ----------------------------------------
    def inventory_cp1252():
        path = fresh("inv_cp1252") / "inventory.json"
        data = json.loads(json.dumps(INVENTORY))
        data["notes"][0]["note"] = "café locker €"
        raw = json.dumps(data, ensure_ascii=False).encode("cp1252")
        path.write_bytes(raw)
        store = InventoryStore(path)
        check("inventory: Windows-1252 file opens with both notes",
              len(store.notes) == 2 and "é" in store.notes[0].note
              and not store.error, f"notes={len(store.notes)} error={store.error!r}")
    run_case("inventory: Windows-1252 file", inventory_cp1252)

    # -- inventory: broken JSON ----------------------------------------------
    def inventory_corrupt():
        folder = fresh("inv_corrupt")
        path = folder / "inventory.json"
        raw = b'{"version": 1, "notes": [{"id": "a1", "location": "Area18",'
        path.write_bytes(raw)
        panel = InventoryPanel(InventoryStore(path))
        panel.store.add("Area18", "Rifle", "", "")
        check("inventory: broken JSON is not overwritten by ADD",
              path.read_bytes() == raw)
        check("inventory: broken JSON reported and kept as .bad copy",
              bool(panel.store.error)
              and any(folder.glob("inventory.json.bad-*")),
              f"error={panel.store.error!r}")
        panel.deleteLater()
    run_case("inventory: broken JSON", inventory_corrupt)

    # -- inventory: .bak on a normal save ------------------------------------
    def inventory_bak():
        folder = fresh("inv_bak")
        path = folder / "inventory.json"
        path.write_text(json.dumps(INVENTORY, indent=2), encoding="utf-8")
        before = path.read_bytes()
        store = InventoryStore(path)
        store.add("Orison", "Ore bag", "2", "")
        saved = json.loads(path.read_text(encoding="utf-8"))
        bak = folder / "inventory.json.bak"
        check("inventory: normal ADD keeps every note and writes a .bak",
              len(saved["notes"]) == 3 and bak.exists() and bak.read_bytes() == before)
    run_case("inventory: .bak on save", inventory_bak)

    # -- blueprints: locked registry -----------------------------------------
    def blueprints_locked():
        path = fresh("bp_locked") / "unlocked_blueprints.json"
        path.write_text(json.dumps(REGISTRY, indent=2), encoding="utf-8")
        before = path.read_bytes()
        with FileLock(path):
            store = bp_mod.BlueprintStore(path)
        store.record(bp_event("Arrowhead Rifle", 50.0))
        saved = store.save()
        check("blueprints: registry locked at start-up is not overwritten",
              path.read_bytes() == before and not saved,
              f"save() returned {saved}")
        check("blueprints: the failed read is reported", bool(store.error))
    run_case("blueprints: locked registry", blueprints_locked)

    def blueprints_cp1252_and_corrupt():
        folder = fresh("bp_mixed")
        path = folder / "unlocked_blueprints.json"
        data = json.loads(json.dumps(REGISTRY))
        data["blueprints"]["coda_pistol"]["item_name"] = "Coda Pistol édition"
        path.write_bytes(json.dumps(data, ensure_ascii=False).encode("cp1252"))
        store = bp_mod.BlueprintStore(path)
        check("blueprints: Windows-1252 registry opens with both entries",
              len(store.blueprints) == 2, f"error={store.error!r}")
        bad = folder / "broken.json"
        raw = b'{"blueprints": {"x": '
        bad.write_bytes(raw)
        broken = bp_mod.BlueprintStore(bad)
        broken.record(bp_event("Arrowhead Rifle", 51.0))
        broken.save()
        check("blueprints: broken registry is not overwritten",
              bad.read_bytes() == raw and bool(broken.error))
    run_case("blueprints: Windows-1252 / broken registry",
             blueprints_cp1252_and_corrupt)

    # -- ore cache: unknown fields / bad entries -----------------------------
    def ore_cache():
        path = fresh("ore") / "where_to_mine.json"
        cache = {"patch": "4.3", "index_at": 1000.0, "ores": [
            {"slug": "gold", "name": "Gold", "category": "Ship", "price": 1,
             "top": {"rank": 1, "name": "Aaron Halo", "added_later": True},
             "best_refinery": {"name": "ARC-L1", "bonus": 5, "new_field": 1},
             "hotspots": [{"rank": 1, "name": "Aaron Halo", "new_field": 2}],
             "refineries": [{"name": "ARC-L1", "bonus": 5, "extra": "x"}],
             "brand_new_ore_field": 7},
            {"slug": "bad", "name": "Bad", "hotspots": [{"name": "no rank"}]},
            "not an object",
            {"slug": "agricium", "name": "Agricium", "price": 2},
        ]}
        path.write_text(json.dumps(cache), encoding="utf-8")
        data = LiveData(path)
        slugs = sorted(ore.slug for ore in data.ores)
        check("ore cache: unknown fields and bad entries skipped, no crash",
              slugs == ["agricium", "gold"], f"slugs={slugs}")
    run_case("ore cache: changed fields", ore_cache)

    # -- pins on both panels --------------------------------------------------
    def pins():
        folder = fresh("pins")
        for label, panel in (
                ("notes", NotesPanel(NotesStore(folder / "notes.txt"))),
                ("inventory", InventoryPanel(InventoryStore(folder / "inv.json")))):
            got: list[bool] = []
            panel.pin_toggled.connect(got.append)
            panel.set_pinned(True)
            quiet = panel.pinned is True and got == []
            panel.pin_button.click()
            clicked = panel.pinned is False and got == [False]
            neighbour = head_neighbour(panel.pin_button)
            left_of_close = neighbour is not None and neighbour.text() == "✕"
            check(f"pin: {label} panel set_pinned/pinned/pin_toggled, left of ✕",
                  quiet and clicked and left_of_close,
                  f"set_pinned quiet={quiet} click={clicked} "
                  f"left_of_close={left_of_close}")
            panel.deleteLater()
    run_case("pin: panels", pins)

    app.processEvents()


# ---------------------------------------------------------------------------
def build_old_tree(dest: Path) -> Path:
    """app/ as in the working copy, with HEAD's versions of the owned files."""
    shutil.copytree(ROOT / "app", dest / "app",
                    ignore=shutil.ignore_patterns("__pycache__"))
    for rel in OWNED:
        old = subprocess.run(["git", "-C", str(ROOT), "show", f"HEAD:{rel}"],
                             check=True, capture_output=True).stdout
        (dest / rel).write_bytes(old)
    (dest / "app" / "safe_store.py").unlink(missing_ok=True)
    return dest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--old", action="store_true",
                        help="run the checks against HEAD's files")
    parser.add_argument("--root", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.old:
        with tempfile.TemporaryDirectory(prefix="ca-datasafety-old-") as tmp:
            tree = build_old_tree(Path(tmp))
            print(f"Old code (HEAD) in {tree}", flush=True)
            return subprocess.run([sys.executable, str(Path(__file__).resolve()),
                                   "--root", str(tree)]).returncode

    root = Path(args.root) if args.root else ROOT
    sys.path.insert(0, str(root))
    with tempfile.TemporaryDirectory(prefix="ca-datasafety-") as tmp_name:
        tmp = Path(tmp_name)
        appdata = tmp / "appdata"
        appdata.mkdir()
        os.environ["APPDATA"] = str(appdata)      # never the real user folder
        os.environ["QT_QPA_PLATFORM"] = "offscreen"  # no window on any monitor
        work = tmp / "work"
        work.mkdir()
        import app  # noqa: F401
        print(f"Code under test: {Path(app.__file__).parent}", flush=True)
        main_checks(work)
    failures = sum(1 for _, ok, _ in RESULTS if not ok)
    print("-" * 70)
    print(f"{len(RESULTS) - failures} passed, {failures} failed")
    return failures


if __name__ == "__main__":
    sys.exit(main())
