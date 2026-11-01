"""Scan limits, harvestables, reader limit, unmatched recorder and reset checks.

    python -m tools.nextdata_selftest            # offline (committed fixture)
    python -m tools.nextdata_selftest --live     # + the newest scmdb live data

The deposit limits in app/mining.py are compared with scmdb's
clusteringPresets (tools/fixtures/scmdb_clusters_4.10.2-live.json, or the
newest live mining_data with --live): a game update that makes clusters
larger than our limits fails here.

Exit code = number of failed checks. Runs with a temporary APPDATA; never
touches the real settings folder.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# app.config creates its folder on import: point it at a throwaway one first.
_TMP_HOME = tempfile.mkdtemp(prefix="nextdata-selftest-")
os.environ["APPDATA"] = _TMP_HOME
os.environ["XDG_CONFIG_HOME"] = _TMP_HOME

import numpy as np                                   # noqa: E402

from app import config, mining, sigsource            # noqa: E402
from app.ocr import SignatureOCR                     # noqa: E402

FIXTURE = ROOT / "tools" / "fixtures" / "scmdb_clusters_4.10.2-live.json"

failures = 0


def check(label: str, ok: bool, detail: str = "") -> bool:
    global failures
    failures += 0 if ok else 1
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail and not ok else ""))
    return ok


def kinds(matches) -> list[tuple[str, int, bool]]:
    return [(m.kind, m.count, m.exact) for m in matches]


# -- cluster presets ------------------------------------------------------
# (kind, name patterns): every scmdb preset with deposits must fall in one.
PRESET_KINDS = (
    ("roc", ("MiningCluster Med Lrg",)),
    ("fps", ("MiningCluster Sml Med",)),
    ("ship", ("*ShipMineable Cluster", "Mining Rare Cluster")),
    ("harvest", ("Harvestables Cluster *",)),
    ("debris", ("SalvageScrap*", "Salvage Cluster *")),
)


def limits() -> dict[str, int]:
    names = {"ship": "MAX_CLUSTER", "roc": "MAX_ROC_CLUSTER", "fps": "MAX_FPS_CLUSTER",
             "debris": "MAX_DEBRIS_CLUSTER", "harvest": "MAX_HARVEST_CLUSTER"}
    return {kind: getattr(mining, name, 0) for kind, name in names.items()}


def check_presets(presets: dict, label: str) -> None:
    lim = limits()
    biggest: dict[str, int] = {}
    unknown = []
    items = presets.values() if isinstance(presets, dict) else presets
    for preset in items:
        name = str(preset.get("name", ""))
        sizes = [int(p.get("maxSize", 0)) for p in preset.get("params") or []]
        if not sizes:
            continue                    # e.g. BushFieldLarge: no deposits
        kind = next((k for k, pats in PRESET_KINDS
                     if any(fnmatch.fnmatch(name, p) for p in pats)), None)
        if kind is None:
            unknown.append(name)
            continue
        biggest[kind] = max(biggest.get(kind, 0), max(sizes))
    check(f"{label}: every cluster preset with deposits has a kind",
          not unknown, f"new presets: {unknown}")
    for kind in lim:
        check(f"{label}: {kind} clusters up to {biggest.get(kind)} fit the limit {lim[kind]}",
              kind in biggest and biggest[kind] <= lim[kind], str(biggest))
    check(f"{label}: ROC 25 and hand mining 21 are the game's largest clusters",
          biggest.get("roc") == 25 and biggest.get("fps") == 21, str(biggest))


def live_presets() -> tuple[str, dict]:
    versions = json.loads(sigsource.http_get(sigsource.VERSIONS_URL))
    entry = sigsource.pick_version(versions, "live")
    if entry is None:
        raise ValueError("no live version on scmdb")
    raw = json.loads(sigsource.http_get(sigsource.data_url(entry)))
    return entry["version"], raw.get("clusteringPresets") or {}


# -- checks -----------------------------------------------------------------
def check_limits() -> None:
    check("limits: ship 10, ROC 25, hand mining 21, salvage 50, harvestables 10",
          limits() == {"ship": 10, "roc": 25, "fps": 21, "debris": 50, "harvest": 10},
          str(limits()))
    data = mining.MiningData(source="bundled", channel="live")
    got = {"ship": data.max_cluster, "roc": data.roc_max_cluster,
           "fps": data.fps_max_cluster, "debris": data.debris_max_cluster,
           "harvest": data.harvest_max_cluster}
    check("bundled signatures.json does not lower the limits", got == limits(), str(got))


def check_lookups(data: mining.MiningData, label: str) -> None:
    m = data.lookup(76000)
    check(f"{label}: 76,000 -> ROC x19 exact first, DEBRIS x38 exact second",
          len(m) >= 2 and kinds(m)[:2] == [("roc", 19, True), ("debris", 38, True)]
          and "Feynmaline" in m[0].minerals and m[0].target == 76000,
          str(kinds(m)))
    check(f"{label}: 76,000 has no harvestables (38 plants > 10)",
          not any(x.kind == "harvest" for x in m))

    exact_2k = [k for k in kinds(data.lookup(6000)) if k[2]]
    check(f"{label}: 6,000 (salvage range) -> DEBRIS x3, HARVESTABLES x3, then FPS x2",
          exact_2k == [("debris", 3, True), ("harvest", 3, True), ("fps", 2, True)],
          str(exact_2k))
    exact = [k for k in kinds(data.lookup(8000)) if k[2]]
    check(f"{label}: 8,000 in space stays DEBRIS x4 first, ROC x2 after",
          exact[0] == ("debris", 4, True) and ("roc", 2, True) in exact, str(exact))
    exact = [k for k in kinds(data.lookup(mining.SALVAGE_FIRST_MAX)) if k[2]]
    check(f"{label}: 30,000 (salvage limit) -> DEBRIS x15 first",
          exact[0] == ("debris", 15, True), str(exact))
    exact = [k for k in kinds(data.lookup(40000)) if k[2]]
    check(f"{label}: 40,000 (above it) -> ROC x10 first, DEBRIS x20 after",
          exact[:2] == [("roc", 10, True), ("debris", 20, True)], str(exact))
    m = data.lookup(2000)
    check(f"{label}: lower limit 1: 2,000 -> DEBRIS x1, HARVESTABLES x1",
          [k for k in kinds(m) if k[2]] == [("debris", 1, True), ("harvest", 1, True)]
          and m[1].label == "Harvestables" and not m[1].is_ground, str(kinds(m)))
    check(f"{label}: 20,000 -> harvestables x10 (upper limit)",
          ("harvest", 10, True) in kinds(data.lookup(20000)))
    check(f"{label}: 22,000 -> no harvestables x11, debris x11",
          not any(x.kind == "harvest" for x in data.lookup(22000))
          and data.lookup(22000)[0].kind == "debris")
    check(f"{label}: ROC x25 = 100,000 exact; x26 (104,000) is not",
          ("roc", 25, True) in kinds(data.lookup(100000))
          and not any(x.kind == "roc" for x in data.lookup(104000)))
    check(f"{label}: hand mining x21 = 63,000 exact; x22 (66,000) is not",
          ("fps", 21, True) in kinds(data.lookup(63000))
          and not any(x.kind == "fps" for x in data.lookup(66000)))
    check(f"{label}: ROC x9 (36,000) above the old ground limit 8",
          ("roc", 9, True) in kinds(data.lookup(36000)))
    check(f"{label}: ship rocks stop at 10 (Bexalite x11 = 39,600 not exact)",
          not any(x.kind == "ship" and x.exact for x in data.lookup(39600)))
    m = data.lookup(18000)
    check(f"{label}: 18,000: ship ore first (Bexalite x5), ground and salvage after",
          [k for k in kinds(m) if k[2]][:4]
          == [("ship", 5, True), ("debris", 9, True), ("harvest", 9, True), ("fps", 6, True)],
          str(kinds(m)))
    for value in (76000, 7200, 8000, 7201, 41000):
        m = data.lookup(value)
        flags = [x.exact for x in m]
        check(f"{label}: lookup({value:,}): exact matches before fuzzy ones",
              flags == sorted(flags, reverse=True), str(kinds(m)))
    m = data.lookup(7350)
    check(f"{label}: no exact hit -> fuzzy matches, closest first",
          m and not m[0].exact and [x.delta for x in m] == sorted(x.delta for x in m),
          str(kinds(m)))
    check(f"{label}: debris detail no longer repeats the ROC reading",
          all("OR ROC" not in (x.secondary or "") for x in data.lookup(8000)))


def check_reader() -> None:
    check("config DEFAULTS max_value is 100,000",
          config.DEFAULTS["max_value"] == 100000, str(config.DEFAULTS["max_value"]))
    ocr = SignatureOCR(threads=1)
    check("reader default max_value is 100,000", ocr.max_value == 100000)
    check("reader accepts 76,000 (the user's ROC x19)",
          [v for v, _ in ocr._numbers([("76,000", 0.99)])] == [76000])
    cfg_ocr = SignatureOCR(int(config.DEFAULTS["min_value"]),
                           int(config.DEFAULTS["max_value"]), 1)
    check("reader with the default settings accepts 76,000 and 100,000, not 100,001",
          [v for v, _ in cfg_ocr._numbers([("76000", 0.9), ("100,000", 0.9),
                                            ("100001", 0.9)])] == [76000, 100000])


def check_unmatched() -> None:
    try:
        from app.unmatched import MAX_ENTRIES, UnmatchedLog
    except ImportError as exc:
        check("app.unmatched imports", False, str(exc))
        return
    with tempfile.TemporaryDirectory() as tmp:
        default = UnmatchedLog()
        check("default folder is <settings>/unmatched",
              default.folder == config.config_dir() / "unmatched", str(default.folder))
        log = UnmatchedLog(Path(tmp) / "unmatched")
        crop = np.zeros((25, 57, 3), dtype=np.uint8)
        crop[5:20, 10:40] = 255
        t0 = 1_761_998_400.0
        ok = log.record(76000, "unknown", crop, when=t0)
        e = log.entries()
        check("record: saved with a PNG and an index entry",
              ok and len(e) == 1 and e[0]["value"] == 76000 and e[0]["kind"] == "unknown"
              and e[0]["time"] == t0 and e[0]["image"].endswith(".png")
              and (log.folder / e[0]["image"]).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n",
              str(e))
        check("record: index.json on disk",
              json.loads((log.folder / "index.json").read_text("utf-8"))[0]["value"] == 76000)
        check("record: same value within 60 s is skipped",
              log.record(76000, "unknown", crop, when=t0 + 59) is False and len(log.entries()) == 1)
        check("record: other value at once is kept; no crop -> no image",
              log.record(41000, "unknown", None, when=t0 + 1) is True
              and log.entries()[0]["image"] == "")
        check("record: same value after 60 s is kept again",
              log.record(76000, "unknown", crop, when=t0 + 61) is True)
        check("entries: newest first",
              [x["time"] for x in log.entries()] == [t0 + 61, t0 + 1, t0])
        first_image = log.folder / e[0]["image"]
        for i in range(MAX_ENTRIES):
            log.record(10_000 + i, "unknown", crop, when=t0 + 100 + i)
        e = log.entries()
        pngs = list(log.folder.glob("*.png"))
        check(f"keeps the newest {MAX_ENTRIES}; older pictures deleted",
              len(e) == MAX_ENTRIES and e[-1]["value"] == 10_000
              and not first_image.exists() and len(pngs) == MAX_ENTRIES,
              f"{len(e)} entries, {len(pngs)} pngs")
        log.clear()
        check("clear: no entries, no pictures", log.entries() == []
              and not list(log.folder.glob("*.png")))

        bad = UnmatchedLog(Path(tmp) / "bad")
        bad.folder.mkdir()
        (bad.folder / "index.json").write_text("{broken", "utf-8")
        check("damaged index.json: not saved over",
              bad.record(5000, "unknown", crop, when=t0) is False
              and (bad.folder / "index.json").read_text("utf-8") == "{broken")


def _make_settings(folder: Path) -> None:
    folder.mkdir(parents=True)
    files = {
        "config.json": "{}", "config.json.bak": "{}", "anchor.png": "png",
        "hauling_commodities.json": "{}", "hauling_top_routes.json": "{}",
        "hauling_top_routes.json.bak": "{}", "routes_cache.json": "{}",
        "where_to_mine.json": "{}", "signatures_scmdb.json": "{}",
        "notes.txt": "my notes", "notes.txt.bak": "old notes",
        "inventory.json": "[]", "inventory.json.bak": "[]",
        "unlocked_blueprints.json": "{}", "unlocked_blueprints.json.bak": "{}",
        "refinery_jobs.json": "{}", "active_run.json": "{}",
        "workflow_wallet.json": "{}", "error.log": "x", "something_else.dat": "?",
    }
    for name, text in files.items():
        (folder / name).write_text(text, "utf-8")
    (folder / "unmatched").mkdir()
    (folder / "unmatched" / "index.json").write_text("[]", "utf-8")


REMOVED = {"config.json", "config.json.bak", "anchor.png", "hauling_commodities.json",
           "hauling_top_routes.json", "hauling_top_routes.json.bak", "routes_cache.json",
           "where_to_mine.json", "signatures_scmdb.json", "unmatched"}


def check_reset() -> None:
    reset = getattr(config, "reset_to_defaults", None)
    if not check("config.reset_to_defaults exists", callable(reset)):
        return
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "SC Assistant"
        _make_settings(folder)
        before = {p.name for p in folder.iterdir()}
        backup = reset(folder)
        after = {p.name for p in folder.iterdir()}
        check("reset: backup is a dated sibling with everything in it",
              backup.parent == folder.parent
              and backup.name.startswith("SC Assistant backup ")
              and {p.name for p in backup.iterdir()} == before
              and (backup / "unmatched" / "index.json").exists()
              and (backup / "notes.txt").read_text("utf-8") == "my notes", str(backup))
        check("reset: settings, pin, caches and unmatched/ removed",
              not (after & REMOVED), str(sorted(after & REMOVED)))
        check("reset: notes, inventory, blueprints (+ .bak) and unknown files kept",
              after == before - REMOVED, str(sorted(before - REMOVED - after)))
        check("reset: RESET_REMOVE / RESET_KEEP lists",
              "config.json" in config.RESET_REMOVE and "unmatched" in config.RESET_REMOVE
              and {"notes.txt", "inventory.json", "unlocked_blueprints.json"}
              <= set(config.RESET_KEEP))
        second = reset(folder)
        check("reset: a second reset in the same second gets its own backup",
              second != backup and second.exists() and backup.exists())

        # A file that cannot be moved (held open on Windows): nothing removed.
        folder2 = Path(tmp) / "Other"
        _make_settings(folder2)
        before = {p.name for p in folder2.iterdir()}
        real_replace = config.os.replace
        calls = {"n": 0}

        def flaky(src, dst):
            calls["n"] += 1
            if calls["n"] == 4:
                raise PermissionError(13, "in use", str(src))
            return real_replace(src, dst)

        config.os.replace = flaky
        try:
            try:
                reset(folder2)
                raised = False
            except OSError:
                raised = True
        finally:
            config.os.replace = real_replace
        after = {p.name for p in folder2.iterdir()}
        check("reset: a failed removal raises and puts everything back",
              raised and after == before and calls["n"] > 4,
              f"raised={raised} missing={sorted(before - after)} extra={sorted(after - before)}")


def run(section, *args) -> None:
    """A section that crashes (old code without the new names) is one failure."""
    try:
        section(*args)
    except Exception as exc:
        check(f"{section.__name__} ran", False, f"{type(exc).__name__}: {exc}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true",
                    help="also compare with the newest scmdb live mining data")
    args = ap.parse_args()

    started = time.time()
    with open(FIXTURE, "r", encoding="utf-8") as fh:
        fixture = json.load(fh)
    run(check_presets, fixture["clusteringPresets"], f"scmdb {fixture['version']} (fixture)")
    if args.live:
        try:
            version, presets = live_presets()
            print(f"      scmdb live: {version}")
            check_presets(presets, f"scmdb {version} (live)")
        except Exception as exc:
            check("scmdb live fetch", False, f"{type(exc).__name__}: {exc}")

    run(check_limits)
    run(check_lookups, mining.MiningData(source="bundled", channel="live"), "bundled")
    with tempfile.TemporaryDirectory() as tmp:
        # The same answers with scmdb data in the cache (the app's default).
        cache = Path(tmp) / sigsource.CACHE_NAME
        bundled = mining.MiningData(source="bundled", channel="live")
        sigsource.write_cache(cache, "live", {
            "version": "4.10.2", "data_version": "4.10.2-live.12913470",
            "channel": "live", "source": "scmdb.net",
            "ship_ores": [{"name": o["name"], "base": o["base"], "rarity": o["rarity"]}
                          for o in bundled.ores],
            "ground": {"fps_minerals": bundled.fps_minerals,
                       "roc_minerals": bundled.roc_minerals}})
        src = sigsource.SignatureSource(cache, lambda url, timeout: b"")
        data = mining.MiningData(source="scmdb", channel="live", sig_source=src)
        if check("scmdb cache is used", data.source_text == "scmdb 4.10.2 live",
                 data.source_text):
            run(check_lookups, data, "scmdb cache")
    run(check_reader)
    run(check_unmatched)
    run(check_reset)
    print(f"\n{failures} failure(s) in {time.time() - started:.1f} s")
    return failures


if __name__ == "__main__":
    sys.exit(main())
