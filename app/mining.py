"""Signature -> mineral lookup.

Ship mining:   scan signature = base signature x number of rocks in the cluster.
               The base signature identifies the dominant mineral.
Ground mining: signature only encodes deposit size (ROC 4000, FPS 3000),
               multiplied by the number of deposits. Each kind lists its own
               minerals (hand mining 3,000 / ROC 4,000).

Data: the scmdb.net cache (app.sigsource) when "signature_source" is "scmdb"
and a cache for "signature_channel" exists, else app/data/signatures.json.
Fields scmdb lacks (short, value, secondary, salvage) come from the bundled
file, merged by name.
Salvage:       exterior hull panels / wreck scrap read as multiples of 2000.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from . import sigsource

DATA_PATH = Path(__file__).with_name("data") / "signatures.json"

MAX_CLUSTER = 10
MAX_GROUND_CLUSTER = 8
# Debris is not a rock cluster: each hull panel contributes 2,000 to the
# signature, so a large wreck can read far beyond a 10-rock cluster. Capping
# this at MAX_CLUSTER made 22,000 (11 panels) fall through to a fuzzy
# Quantanium match instead of being recognised as salvage.
MAX_DEBRIS_CLUSTER = 50


@dataclass(frozen=True)
class Match:
    kind: str            # "ship" | "roc" | "fps"
    name: str
    count: int
    target: int
    delta: int
    rarity: int
    value: float | None
    secondary: str | None
    short: str = ""
    # Ground kinds: the minerals that can give this reading (roc / fps list).
    minerals: tuple[str, ...] = ()

    @property
    def exact(self) -> bool:
        return self.delta == 0

    @property
    def label(self) -> str:
        if self.kind == "ship":
            return self.name
        if self.kind == "debris":
            return "Debris"
        return "ROC deposit" if self.kind == "roc" else "FPS deposit"

    @property
    def is_ground(self) -> bool:
        return self.kind in ("roc", "fps")


class MiningData:
    def __init__(self, path: Path = DATA_PATH, source: str | None = None,
                 channel: str | None = None,
                 sig_source: sigsource.SignatureSource | None = None):
        """source/channel default to the config's "signature_source" /
        "signature_channel"; "bundled" never reads the scmdb cache."""
        self.path = path
        self._source_setting = source
        self._channel_setting = channel
        self.sig_source = sig_source or sigsource.SignatureSource()
        self.version = "?"
        self.data_version = "?"
        self.source = ""
        self.source_text = ""
        self.fallback_reason = ""
        self.ores: list[dict] = []
        self.max_cluster = MAX_CLUSTER
        self.ground_max_cluster = MAX_GROUND_CLUSTER
        self.roc_base = 4000
        self.fps_base = 3000
        self.fps_minerals: list[str] = []
        self.roc_minerals: list[str] = []
        self.ground_minerals: list[str] = []
        self.debris_base = 2000
        self.debris_max_cluster = MAX_CLUSTER
        self.debris_name = "Debris"
        self.debris_detail = "HULL PANELS / SCRAP METAL"
        self.reload()

    def _settings(self) -> tuple[str, str]:
        source, channel = self._source_setting, self._channel_setting
        if source is None or channel is None:
            try:
                from .config import Config
                cfg = Config.load()
                source = source or str(cfg.data.get("signature_source", "scmdb"))
                channel = channel or str(cfg.data.get("signature_channel", "live"))
            except Exception:
                source, channel = source or "scmdb", channel or "live"
        return source, channel

    def reload(self) -> None:
        with open(self.path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        source, channel = self._settings()
        scmdb = None
        self.fallback_reason = ""
        if source == "scmdb":
            try:
                scmdb = self.sig_source.cached(channel)
            except Exception as exc:
                self.fallback_reason = f"cache: {exc}"
            if scmdb is None and not self.fallback_reason:
                self.fallback_reason = (self.sig_source.last_error
                                        or f"no scmdb {channel} data cached yet")

        bundled_ground = raw.get("ground", {})
        if scmdb is not None:
            self.version = scmdb.get("version", "?")
            self.data_version = scmdb.get("data_version", self.version)
            self.source = "https://scmdb.net/"
            self.source_text = f"scmdb {self.version} {scmdb.get('channel') or channel}"
            self.ores = merge_ores(scmdb.get("ship_ores", []), raw.get("ship_ores", []))
            ground = scmdb.get("ground", {})
        else:
            self.version = raw.get("version", "?")
            self.data_version = raw.get("data_version", self.version)
            self.source = raw.get("source", "")
            self.source_text = f"bundled {self.version}"
            self.ores = sorted(raw.get("ship_ores", []), key=lambda o: o["base"])
            ground = bundled_ground
        self.max_cluster = int(raw.get("max_cluster", MAX_CLUSTER))
        self.ground_max_cluster = int(
            bundled_ground.get("max_cluster", MAX_GROUND_CLUSTER))
        self.roc_base = int(bundled_ground.get("roc_base", 4000))
        self.fps_base = int(bundled_ground.get("fps_base", 3000))
        self.fps_minerals = list(ground.get("fps_minerals", []))
        self.roc_minerals = list(ground.get("roc_minerals", []))
        self.ground_minerals = sorted(set(self.fps_minerals) | set(self.roc_minerals))
        debris = raw.get("debris", {})
        self.debris_base = int(debris.get("base", 2000))
        self.debris_max_cluster = int(debris.get("max_cluster", MAX_DEBRIS_CLUSTER))
        self.debris_name = debris.get("name", "Debris")
        self.debris_detail = debris.get("detail", "HULL PANELS / SCRAP METAL")

    def refresh_in_background(self, on_done=None, force: bool = False):
        """Refresh the scmdb cache off the GUI thread (at most once a day).

        on_done(changed: bool) runs on the worker thread; call reload() on the
        GUI thread afterwards when changed is True. No-op for "bundled".
        """
        source, channel = self._settings()
        if source != "scmdb":
            return None
        return self.sig_source.refresh_in_background(channel, on_done, force)

    # ------------------------------------------------------------------
    def lookup(self, value: int, tolerance: float = 0.08) -> list[Match]:
        """Return every plausible interpretation of a scan signature."""
        if value <= 0:
            return []

        matches: list[Match] = []
        for ore in self.ores:
            base = int(ore["base"])
            for count in range(1, self.max_cluster + 1):
                target = base * count
                delta = abs(value - target)
                if delta <= max(35, int(round(target * tolerance))):
                    matches.append(Match(
                        kind="ship",
                        name=ore["name"],
                        short=ore.get("short", ""),
                        count=count,
                        target=target,
                        delta=delta,
                        rarity=int(ore.get("rarity", 1)),
                        value=ore.get("value"),
                        secondary=ore.get("secondary"),
                    ))

        for kind, base, minerals in (("roc", self.roc_base, self.roc_minerals),
                                     ("fps", self.fps_base, self.fps_minerals)):
            count = round(value / base)
            if count < 1 or count > self.ground_max_cluster:
                continue
            target = base * count
            delta = abs(value - target)
            if delta <= max(35, int(round(target * tolerance))):
                matches.append(Match(
                    kind=kind,
                    name="Ground deposit",
                    count=count,
                    target=target,
                    delta=delta,
                    rarity=0,
                    value=None,
                    secondary=" / ".join(minerals) or None,
                    minerals=tuple(minerals),
                ))

        # Salvage: exterior hull panels and wreck scrap read as clean
        # multiples of 2,000. In space that is far more likely than a ground
        # deposit, so an exact multiple takes the headline and the ground
        # reading (when one exists) is kept as an alternative in the detail.
        if self.debris_base > 0 and value % self.debris_base == 0:
            count = value // self.debris_base
            if 1 <= count <= self.debris_max_cluster:
                detail = self.debris_detail
                alt = next((m for m in matches if m.is_ground and m.exact), None)
                if alt is not None:
                    detail = f"{detail}  ·  OR {alt.label.upper()} ×{alt.count}"
                matches.append(Match(
                    kind="debris",
                    name=self.debris_name,
                    count=count,
                    target=value,
                    delta=0,
                    rarity=1,
                    value=None,
                    secondary=detail,
                ))

        matches.sort(key=lambda m: (not m.exact, m.delta, m.is_ground, -m.rarity))
        # In-game signatures are exact multiples of the base value, so an
        # exact hit is authoritative. Only fall back to fuzzy matches when
        # nothing lands exactly (usually an OCR misread).
        exact = [m for m in matches if m.exact]
        if exact:
            return exact
        return matches

    def nearest(self, value: int, limit: int = 3) -> list[Match]:
        """Closest signatures when nothing matches exactly (OCR sanity check)."""
        pool: list[Match] = []
        for ore in self.ores:
            base = int(ore["base"])
            count = max(1, min(self.max_cluster, round(value / base)))
            target = base * count
            pool.append(Match(
                kind="ship", name=ore["name"], short=ore.get("short", ""),
                count=count, target=target, delta=abs(value - target),
                rarity=int(ore.get("rarity", 1)), value=ore.get("value"),
                secondary=ore.get("secondary"),
            ))
        pool.sort(key=lambda m: m.delta)
        return pool[:limit]

    # ------------------------------------------------------------------
    def ore_by_name(self, name: str) -> dict | None:
        for ore in self.ores:
            if ore["name"].lower() == name.lower():
                return ore
        return None


def merge_ores(scmdb_ores: list[dict], bundled_ores: list[dict]) -> list[dict]:
    """scmdb bases with our short/value/secondary/rarity, matched by name."""
    ours = {o["name"].lower(): o for o in bundled_ores}
    merged = []
    for ore in scmdb_ores:
        extra = ours.get(ore["name"].lower(), {})
        merged.append({
            "name": ore["name"],
            "short": extra.get("short") or ore["name"][:4].upper(),
            "base": int(ore["base"]),
            "value": extra.get("value"),
            "rarity": int(extra.get("rarity", ore.get("rarity", 1))),
            "secondary": extra.get("secondary"),
        })
    return sorted(merged, key=lambda o: o["base"])
