"""Signature data checks: scmdb conversion, ground lists, cache and fallback.

    python -m tools.signature_selftest                 # offline (default)
    python -m tools.signature_selftest --scmdb-dir DIR # also convert saved
                                                       # mining_data-*.json files
    python -m tools.signature_selftest --live          # + a real read-only fetch

Exit code = number of failed checks. Uses a temporary cache file; never
writes to the real config folder.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import sigsource                    # noqa: E402
from app.mining import DATA_PATH, MiningData  # noqa: E402

# Excerpt of scmdb mining_data-4.10.2-live.12913470.json (2026-11-01):
# (name, scanSignature, groundScanSignature, fpsScanSignature, rarity).
EXCERPT_ROWS = [
    ('Agricium (Ore)', 3885, 4000, 0, 'uncommon'),
    ('Aluminium (Ore)', 4285, 4000, 0, 'common'),
    ('Aslarite (Raw)', 3840, 0, 0, 'uncommon'),
    ('Beryl (Raw)', 3540, 4000, 0, 'rare'),
    ('Bexalite (Raw)', 3600, 4000, 0, 'rare'),
    ('Borase (Ore)', 3570, 4000, 0, 'rare'),
    ('Copper (Ore)', 4240, 4000, 0, 'common'),
    ('Corundum (Raw)', 4225, 4000, 0, 'common'),
    ('Gold (Ore)', 3585, 4000, 0, 'rare'),
    ('Hephaestanite (Raw)', 4180, 0, 0, 'common'),
    ('Ice (Raw)', 4300, 4000, 0, 'common'),
    ('Iron (Ore)', 4270, 4000, 0, 'common'),
    ('Laranite (Raw)', 3825, 4000, 0, 'uncommon'),
    ('Lindinium (Ore)', 3400, 0, 0, 'epic'),
    ('Aphorite', 0, 0, 3000, ''),
    ('Carinite', 0, 4000, 3000, ''),
    ('Carinite (Pure)', 0, 0, 0, ''),
    ('Dolivine', 0, 0, 3000, ''),
    ('Hadanite', 0, 0, 3000, ''),
    ('Jaclium', 0, 0, 3000, ''),
    ('Janalite', 0, 0, 3000, ''),
    ('Sadaryx', 0, 0, 3000, ''),
    ('Saldynium', 0, 0, 3000, ''),
    ('Beradom', 0, 4000, 0, ''),
    ('Carinite', 0, 0, 0, ''),
    ('Feynmaline', 0, 4000, 0, ''),
    ('Glacosite', 0, 4000, 0, ''),
    ('Ouratite (Raw)', 3370, 0, 0, 'epic'),
    ('Quantainium (Raw)', 3170, 4000, 0, 'legendary'),
    ('Quartz (Raw)', 4210, 4000, 0, 'common'),
    ('Riccite (Ore)', 3385, 0, 0, 'epic'),
    ('Savrilium (Ore)', 3200, 0, 0, 'legendary'),
    ('Stileron (Ore)', 3185, 0, 0, 'legendary'),
    ('Silicon (Raw)', 4255, 4000, 0, 'common'),
    ('Taranite (Raw)', 3555, 4000, 0, 'rare'),
    ('Tin (Ore)', 4195, 4000, 0, 'common'),
    ('Titanium (Ore)', 3855, 4000, 0, 'uncommon'),
    ('Torite (Ore)', 3900, 0, 0, 'uncommon'),
    ('Tungsten (Ore)', 3870, 4000, 0, 'uncommon'),
]

FPS = ["Aphorite", "Carinite", "Dolivine", "Hadanite", "Jaclium", "Janalite",
       "Sadaryx", "Saldynium"]
ROC_ONLY = ["Beradom", "Carinite", "Feynmaline", "Glacosite"]
LIVE = "4.10.2-live.12913470"
PTU = "4.10.3-ptu.13055118"


def excerpt(version: str = LIVE) -> dict:
    elements = {}
    for i, (name, ship, ground, fps, rarity) in enumerate(EXCERPT_ROWS):
        el = {"name": name}
        if ship:
            el["scanSignature"] = ship
        if ground:
            el["groundScanSignature"] = ground
        if fps:
            el["fpsScanSignature"] = fps
        if rarity:
            el["rarity"] = rarity
        elements[f"id-{i}"] = el
    return {"version": version, "mineableElements": elements}


VERSIONS = [
    {"version": "4.10.1-live.12700000", "file": "mining_data-4.10.1-live.12700000.json"},
    {"version": LIVE, "file": f"mining_data-{LIVE}.json"},
    {"version": "4.10.2-live.12800000", "file": "mining_data-4.10.2-live.12800000.json"},
    {"version": PTU, "file": f"mining_data-{PTU}.json"},
    {"version": "4.9.9-ptu.99999999", "file": "x.json"},
]


class FakeNet:
    """Fetcher stand-in: serves versions.json and the excerpt, counts calls."""

    def __init__(self, fail: Exception | None = None, mining: dict | None = None):
        self.fail = fail
        self.mining = mining
        self.urls: list[str] = []
        self.threads: list[str] = []

    def __call__(self, url: str, timeout: float) -> bytes:
        self.urls.append(url)
        self.threads.append(threading.current_thread().name)
        if self.fail is not None:
            raise self.fail
        if url == sigsource.VERSIONS_URL:
            return json.dumps(VERSIONS).encode()
        version = url.rsplit("mining_data-", 1)[-1].removesuffix(".json")
        return json.dumps(self.mining or excerpt(version)).encode()


failures = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global failures
    failures += 0 if ok else 1
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail and not ok else ""))


def bundled() -> dict:
    with open(DATA_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def check_conversion(conv: dict, label: str) -> None:
    ours = {o["name"]: o["base"] for o in bundled()["ship_ores"]}
    got = {o["name"]: o["base"] for o in conv["ship_ores"]}
    diff = sorted(set(ours.items()) ^ set(got.items()))
    check(f"{label}: 26 ship ores equal the bundled bases",
          len(got) == 26 and got == ours, f"differences {diff}")
    check(f"{label}: 8 hand-mining (3,000) minerals",
          conv["ground"]["fps_minerals"] == FPS, str(conv["ground"]["fps_minerals"]))
    roc = conv["ground"]["roc_minerals"]
    expected_roc = sorted(set(ROC_ONLY) | {n for n in ours if n not in (
        "Aslarite", "Hephaestanite", "Lindinium", "Ouratite", "Riccite",
        "Savrilium", "Stileron", "Torite")})
    check(f"{label}: 22 ROC (4,000) minerals", len(roc) == 22 and roc == expected_roc,
          f"{len(roc)}: {roc}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="real read-only fetch from scmdb.net")
    ap.add_argument("--scmdb-dir", type=Path, help="folder with saved mining_data-*.json")
    args = ap.parse_args()

    # -- conversion -------------------------------------------------------
    conv = sigsource.convert(excerpt())
    check_conversion(conv, "excerpt 4.10.2 live")
    names = {o["name"] for o in conv["ship_ores"]}
    check("names cleaned (Quantanium, Aluminum, Ice; no (Ore)/(Raw))",
          {"Quantanium", "Aluminum", "Ice"} <= names
          and not any("(" in n for n in names))
    check("version fields", (conv["version"], conv["data_version"], conv["channel"])
          == ("4.10.2", LIVE, "live"), str(conv))
    if args.scmdb_dir:
        files = sorted(args.scmdb_dir.glob("mining_data-*.json"))
        check("saved scmdb files found", bool(files), str(args.scmdb_dir))
        for f in files:
            with open(f, "r", encoding="utf-8") as fh:
                check_conversion(sigsource.convert(json.load(fh)), f.name)

    # -- version pick / URL safety ---------------------------------------
    check("newest live picked", sigsource.pick_version(VERSIONS, "live")["version"] == LIVE)
    check("newest ptu picked", sigsource.pick_version(VERSIONS, "ptu")["version"] == PTU)
    check("versions.json wrapped in an object",
          sigsource.pick_version({"versions": VERSIONS}, "live")["version"] == LIVE)
    check("unknown file name falls back to mining_data-<v>.json",
          sigsource.data_url({"version": LIVE, "file": "../../evil.json"})
          == sigsource.BASE_URL + f"mining_data-{LIVE}.json"
          and sigsource.data_url({"version": LIVE, "file": "https://x.example/a.json"})
          == sigsource.BASE_URL + f"mining_data-{LIVE}.json")

    # -- bundled lookups --------------------------------------------------
    data = MiningData(source="bundled", channel="live")
    check("bundled source text", data.source_text == "bundled 4.10.2"
          and data.data_version == LIVE, f"{data.source_text!r} {data.data_version!r}")
    m3 = data.lookup(3000)
    fps = [m for m in m3 if m.kind == "fps"]
    check("lookup(3000): FPS x1 lists only hand-mining minerals",
          len(fps) == 1 and m3[0] is fps[0] and list(fps[0].minerals) == FPS
          and fps[0].secondary == " / ".join(FPS), str(m3))
    m4 = data.lookup(4000)
    roc = [m for m in m4 if m.kind == "roc"]
    check("lookup(4000): ROC x1 lists only ROC minerals",
          len(roc) == 1 and len(roc[0].minerals) == 22
          and "Aphorite" not in roc[0].minerals and "Beradom" in roc[0].minerals
          and "Quantanium" in roc[0].minerals, str(roc))
    check("lookup(4000): salvage stays the headline", m4[0].kind == "debris", str(m4[0]))
    m9 = data.lookup(9000)
    check("lookup(9000): FPS x3 with the FPS list",
          m9 and m9[0].kind == "fps" and m9[0].count == 3 and list(m9[0].minerals) == FPS)
    check("ship result fields kept", data.lookup(7200)[0].name == "Bexalite"
          and data.lookup(7200)[0].count == 2 and data.lookup(7200)[0].minerals == ())

    with tempfile.TemporaryDirectory() as tmp:
        cache = Path(tmp) / sigsource.CACHE_NAME

        # -- offline / failed fetch falls back to bundled -------------------
        net = FakeNet(fail=OSError("offline"))
        src = sigsource.SignatureSource(cache, net)
        check("failed fetch: refresh returns False", src.refresh("live") is False)
        check("failed fetch: reason kept", "offline" in src.last_error, src.last_error)
        check("failed fetch: no cache written", not cache.exists())
        data = MiningData(source="scmdb", channel="live", sig_source=src)
        check("no cache: falls back to bundled with a reason",
              data.source_text == "bundled 4.10.2" and "offline" in data.fallback_reason
              and len(data.ores) == 26, f"{data.source_text!r} {data.fallback_reason!r}")

        bad = sigsource.SignatureSource(cache, FakeNet(mining={"mineableElements": {}}))
        check("empty scmdb data rejected", bad.refresh("live") is False
              and not cache.exists() and bad.last_error, bad.last_error)

        # -- background refresh writes the cache ----------------------------
        net = FakeNet()
        src = sigsource.SignatureSource(cache, net)
        done: list[bool] = []
        t = src.refresh_in_background("live", done.append)
        if t is not None:
            t.join(10)
        check("background refresh: off the calling thread, cache written",
              done == [True] and cache.exists()
              and all(n == "signature-refresh" for n in net.threads)
              and net.urls[-1].endswith(f"mining_data-{LIVE}.json"),
              f"{done} {net.threads} {net.urls}")

        # -- cache refresh rule ---------------------------------------------
        cached = sigsource.read_cache(cache)
        now = float(cached["fetched_at"])
        check("cache refresh rule",
              not sigsource.needs_refresh(cached, "live", now + 3600)
              and sigsource.needs_refresh(cached, "live", now + 25 * 3600)
              and sigsource.needs_refresh(cached, "ptu", now + 60)
              and sigsource.needs_refresh(None, "live", now)
              and sigsource.needs_refresh(cached, "live", now - 3600))
        calls = len(net.urls)
        check("fresh cache: no download", src.refresh("live", now=now + 3600) is False
              and len(net.urls) == calls)
        src.fetcher = FakeNet(fail=TimeoutError("timed out"))
        check("stale cache + failed fetch keeps the cache",
              src.refresh("live", now=now + 25 * 3600) is False
              and sigsource.read_cache(cache) == cached and "timed out" in src.last_error)

        # -- scmdb data in MiningData, merged fields kept -------------------
        data = MiningData(source="scmdb", channel="live", sig_source=src)
        bex = data.ore_by_name("Bexalite")
        check("scmdb source text", data.source_text == "scmdb 4.10.2 live"
              and data.data_version == LIVE, data.source_text)
        check("merged fields kept (short, value, secondary, rarity)",
              bex == {"name": "Bexalite", "short": "BEXA", "base": 3600, "value": 75.89,
                      "rarity": 4, "secondary": "Gold / Borase 5-10%"}, str(bex))
        check("salvage kept with scmdb data",
              data.lookup(22000)[0].kind == "debris" and data.lookup(22000)[0].count == 11)
        check("scmdb ground lists used",
              list(data.lookup(3000)[0].minerals) == FPS
              and len(next(m for m in data.lookup(4000) if m.kind == "roc").minerals) == 22)
        check("ptu channel without ptu cache falls back",
              MiningData(source="scmdb", channel="ptu", sig_source=src).source_text
              == "bundled 4.10.2")

        # -- "bundled" never downloads --------------------------------------
        net = FakeNet()
        quiet = sigsource.SignatureSource(cache, net)
        data = MiningData(source="bundled", channel="live", sig_source=quiet)
        check("bundled: ignores the cache and never downloads",
              data.refresh_in_background() is None and not net.urls
              and data.source_text == "bundled 4.10.2")

    # -- optional real fetch ------------------------------------------------
    if args.live:
        for channel in sigsource.CHANNELS:
            try:
                conv = sigsource.fetch(channel)
                print(f"      scmdb {channel}: {conv['data_version']}")
                check_conversion(conv, f"scmdb {channel} {conv['data_version']}")
            except Exception as exc:
                check(f"scmdb {channel} fetch", False, f"{type(exc).__name__}: {exc}")

    print("ALL CHECKS PASSED" if failures == 0 else f"{failures} CHECK(S) FAILED")
    return failures


if __name__ == "__main__":
    raise SystemExit(main())
