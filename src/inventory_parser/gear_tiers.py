"""Expansion gear tier codes for SOR gap tracking."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from inventory_parser.evolver import EVOLVER_GAP_LABEL, EVOLVER_LABEL
from inventory_parser.package_data import data_dir

DATA_DIR = data_dir()

TRADESKILL_SUFFIXES = (
    " Lining",
    " Polishing Cloth",
    " Fastener",
    " Clasp",
    " Buckle",
    " Enarmes",
    " String Serving",
    " Core of",
    " Essence of",
)


def _is_tradeskill_item(item_name: str) -> bool:
    if item_name.startswith("Fractured") and any(suffix in item_name for suffix in TRADESKILL_SUFFIXES):
        return True
    if " of Rebellion" in item_name and any(suffix in item_name for suffix in TRADESKILL_SUFFIXES):
        return True
    if item_name.startswith("Valiant"):
        return True
    if item_name.startswith("Apparitional"):
        return True
    return False


VENDOR_JSON_FILES = (
    "sor_r1_vendor_items.json",
    "tob_r1_vendor_items.json",
    "ls_r1_vendor_items.json",
    "nos_r1_vendor_items.json",
    "tol_r1_vendor_items.json",
    "cov_r1_vendor_items.json",
    "tov_r1_vendor_items.json",
    "ani27_raid_items.json",
)

UNKNOWN_TIER_LABEL = "???"
SOR_CURRENT_TIER_CODE = "SOR-R2"


@dataclass(frozen=True)
class GearTier:
    code: str
    label: str
    patterns: tuple[re.Pattern[str], ...]
    is_sor_current: bool = False


def _p(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.I)


_GEAR_TIERS: tuple[GearTier, ...] = (
    GearTier(
        SOR_CURRENT_TIER_CODE,
        "Shattering of Ro — Raid Tier 2 (Resonant Fracture)",
        (_p(r"Resonant Fracture"), _p(r"(?<!\w)Fracture(?!d)\b")),
        is_sor_current=True,
    ),
    GearTier("SOR-R1", "Shattering of Ro — Raid Tier 1 (Shattered Dominion)", (_p(r"Shattered Dominion"),)),
    GearTier(
        "SOR-G3",
        "Shattering of Ro — Group Tier 3 (Unraveling Order)",
        (_p(r"Unraveling Order"),),
    ),
    GearTier("SOR-G2", "Shattering of Ro — Group Tier 2 (Divine Schism)", (_p(r"Divine Schism"),)),
    GearTier("SOR-G1", "Shattering of Ro — Group Tier 1 (Broken Accord)", (_p(r"Broken Accord"),)),
    GearTier("TOB-R2", "The Outer Brood — Raid Tier 2 (Rebellion)", (_p(r"Rebellion"),)),
    GearTier(
        "TOB-G3",
        "The Outer Brood — Group Tier 3 (Cosmic Scalewrought / Starborne)",
        (_p(r"Cosmic Scalewrought"), _p(r"Starborne(?! Lychee)")),
    ),
    GearTier("TOB-R1", "The Outer Brood — Raid Tier 1 (Bound)", (_p(r" of the Bound\b"),)),
    GearTier("TOB-G2", "The Outer Brood — Group Tier 2 (Shackled)", (_p(r"Shackled"), _p(r"of the Shackled"))),
    GearTier(
        "TOB-G1",
        "The Outer Brood — Group Tier 1 (Enthralled)",
        (_p(r"Enthralled"), _p(r"Obscured.*Enthralled")),
    ),
    GearTier("LS-R2", "Laurion's Song — Raid Tier 2 (Eternal Reverie)", (_p(r"Eternal Reverie"),)),
    GearTier(
        "LS-G3",
        "Laurion's Song — Group Tier 3 (Harmonious Resonance)",
        (_p(r"Harmonious Resonance"),),
    ),
    GearTier("LS-R1", "Laurion's Song — Raid Tier 1 (Heroic Reflections)", (_p(r"Heroic Reflections"),)),
    GearTier(
        "LS-G2",
        "Laurion's Song — Group Tier 2 (Reverberant Resonance)",
        (_p(r"Reverberant Resonance"),),
    ),
    GearTier("LS-G1", "Laurion's Song — Group Tier 1 (Gallant Resonance)", (_p(r"Gallant Resonance"),)),
    GearTier("NoS-R2", "Night of Shadows — Raid Tier 2 (Spectral Luclinite)", (_p(r"Spectral Luclinite"),)),
    GearTier("NoS-G3", "Night of Shadows — Group Tier 3 (Spiritualist)", (_p(r"Spiritualist"),)),
    GearTier(
        "NoS-R1",
        "Night of Shadows — Raid Tier 1 (Spectral Luminosity)",
        (_p(r"Spectral Luminosity"), _p(r"Aurora's Luminosity")),
    ),
    GearTier(
        "NoS-G2",
        "Night of Shadows — Group Tier 2 (Transcendental Spirit)",
        (_p(r"Transcendental Spirit"),),
    ),
    GearTier("NoS-G1", "Night of Shadows — Group Tier 1 (Ascending Spirit)", (_p(r"Ascending Spirit"),)),
    GearTier(
        "ToL-R2",
        "Terror of Luclin — Raid Tier 2 (Luclinite Coagulated)",
        (_p(r"Luclinite Coagulated"),),
    ),
    GearTier(
        "ToL-G3",
        "Terror of Luclin — Group Tier 3 (Luclinite Ensanguined)",
        (_p(r"Luclinite Ensanguined"),),
    ),
    GearTier(
        "ToL-R1",
        "Terror of Luclin — Raid Tier 1 (Waning Gibbous)",
        (_p(r"Waning Gibbous"),),
    ),
    GearTier(
        "ToL-G2",
        "Terror of Luclin — Group Tier 2 (Waning Crescent)",
        (_p(r"Waning Crescent"),),
    ),
    GearTier(
        "ToL-G1",
        "Terror of Luclin — Group Tier 1 (Waxing Crescent)",
        (_p(r"Waxing Crescent"),),
    ),
    GearTier(
        "CoV-R2",
        "Claws of Veeshan — Raid Tier 2 (Velium Endowed)",
        (_p(r"Velium Endowed"),),
    ),
    GearTier(
        "CoV-G3",
        "Claws of Veeshan — Group Tier 3 (Velium Threaded)",
        (_p(r"Velium Threaded"),),
    ),
    GearTier(
        "CoV-R1",
        "Claws of Veeshan — Raid Tier 1 (Hoarfrost)",
        (_p(r"Hoarfrost"),),
    ),
    GearTier(
        "CoV-G2",
        "Claws of Veeshan — Group Tier 2 (Blizzard)",
        # Require a gear-slot word so bare "Blizzard" (spells/mobs) does not match.
        (
            _p(
                r"Blizzard\b.*\b(?:"
                r"Arm(?:s|wraps)?|Boot|Bracer|Breast(?:plate)?|Cap|Chest|"
                r"Cloak|Coif|Cowl|Earring|Gauntlet|Glove|Greave|Hand|"
                r"Helm|Leg(?:ging)?s?|Mask|Necklace|Pant|Ring|Robe|"
                r"Sandal|Shield|Sleeve|Tunic|Vambrace|Wrist"
                r")\b"
            ),
        ),
    ),
    GearTier(
        "CoV-G1",
        "Claws of Veeshan — Group Tier 1 (Snowsquall)",
        (_p(r"Snowsquall"),),
    ),
    GearTier(
        "ToV-R2",
        "Torment of Velious — Raid Tier 2 (Velium Empowered)",
        (_p(r"Velium Empowered"),),
    ),
    GearTier(
        "ToV-G3",
        "Torment of Velious — Group Tier 3 (Velium Infused)",
        (_p(r"Velium Infused"),),
    ),
    GearTier(
        "ToV-R1",
        "Torment of Velious — Raid Tier 1 (Ice Woven)",
        (_p(r"Ice Woven"),),
    ),
    GearTier(
        "ToV-G2",
        "Torment of Velious — Group Tier 2 (Icebound)",
        (_p(r"Icebound"),),
    ),
    GearTier(
        "ToV-G1",
        "Torment of Velious — Group Tier 1 (Snowbound)",
        (_p(r"Snowbound"),),
    ),
    GearTier(
        "ANI27",
        "Anniversary 2027 — Tides of Time: Glaze of the Ice Dragon (Enduring Harmony)",
        (_p(r"Enduring Harmony"),),
    ),
)

GEAR_TIERS_NEWEST_FIRST: tuple[GearTier, ...] = _GEAR_TIERS

GEAR_TIER_BY_CODE: dict[str, GearTier] = {tier.code: tier for tier in _GEAR_TIERS}

# Legend rows: blank/current first, then non-current tiers oldest-to-newest within expansion groups.
SOR_GAP_LEGEND_ROWS: tuple[tuple[str | None, str], ...] = (
    (None, "Blank — empty slot"),
    (EVOLVER_GAP_LABEL, EVOLVER_LABEL),
    *((tier.code, tier.label) for tier in reversed(_GEAR_TIERS)),
    (UNKNOWN_TIER_LABEL, "Equipped gear with no recognized tier pattern"),
)


@lru_cache(maxsize=1)
def _vendor_name_to_code() -> dict[str, str]:
    lookup: dict[str, str] = {}
    for filename in VENDOR_JSON_FILES:
        path = DATA_DIR / filename
        if not path.is_file():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        tier_code = payload["tier_code"]
        for item in payload.get("items", []):
            lookup[item["name"]] = tier_code
    return lookup


def classify_gear_tier(item_name: str) -> GearTier | None:
    """Return the newest matching tier for an item name, or None if unmatched."""
    if _is_tradeskill_item(item_name):
        return None
    for tier in _GEAR_TIERS:
        for pattern in tier.patterns:
            if pattern.search(item_name):
                return tier
    vendor_code = _vendor_name_to_code().get(item_name)
    if vendor_code is not None:
        return GEAR_TIER_BY_CODE[vendor_code]
    return None


def tier_code_for_item(item_name: str) -> str | None:
    """Return a tier code for an item name, or None when unmatched."""
    tier = classify_gear_tier(item_name)
    return tier.code if tier is not None else None


def tier_rank(code: str) -> int | None:
    """
    Numeric rank for tier comparison (higher = newer / better gear).

    Uses order in ``_GEAR_TIERS`` (newest tier first in that tuple).
    """
    for index, tier in enumerate(_GEAR_TIERS):
        if tier.code == code:
            return len(_GEAR_TIERS) - index
    return None
