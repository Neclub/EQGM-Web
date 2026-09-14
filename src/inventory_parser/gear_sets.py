"""Classify equipped item names into expansion gear sets for Excel color coding."""

from __future__ import annotations

import re
from dataclasses import dataclass

from openpyxl.styles import PatternFill

from inventory_parser.excel_theme import gear_set_fill


@dataclass(frozen=True)
class GearSet:
    """A recognizable armor tier / set name from item text."""

    key: str
    label: str
    fill: PatternFill
    patterns: tuple[re.Pattern[str], ...]


# Newest first — first match wins.
_GEAR_SETS: tuple[GearSet, ...] = (
    GearSet(
        "fracture",
        "SOR — Raid Tier 2 (Fracture)",
        gear_set_fill("fracture"),
        (
            re.compile(r"Resonant Fracture", re.I),
            re.compile(r"\bFracture\b", re.I),
        ),
    ),
    GearSet(
        "shattered_dominion",
        "SOR — Raid Tier 1 (Shattered Dominion)",
        gear_set_fill("shattered_dominion"),
        (re.compile(r"Shattered Dominion", re.I),),
    ),
    GearSet(
        "rebellion",
        "TOB — Raid Tier 2 (Rebellion)",
        gear_set_fill("rebellion"),
        (re.compile(r"Rebellion", re.I),),
    ),
    GearSet(
        "bound",
        "TOB — Raid Tier 1 (Bound)",
        gear_set_fill("bound"),
        (re.compile(r" of the Bound\b", re.I),),
    ),
    GearSet(
        "eternal_reverie",
        "LS — Raid Tier 2 (Eternal Reverie)",
        gear_set_fill("eternal_reverie"),
        (re.compile(r"Eternal Reverie", re.I),),
    ),
    GearSet(
        "heroic_reflections",
        "LS — Raid Tier 1 (Heroic Reflections)",
        gear_set_fill("heroic_reflections"),
        (re.compile(r"Heroic Reflections", re.I),),
    ),
    GearSet(
        "spectral_luclinite",
        "NoS — Raid Tier 2 (Spectral Luclinite)",
        gear_set_fill("spectral_luclinite"),
        (re.compile(r"Spectral Luclinite", re.I),),
    ),
    GearSet(
        "spectral_luminosity",
        "NoS — Raid Tier 1 (Spectral Luminosity)",
        gear_set_fill("spectral_luminosity"),
        (
            re.compile(r"Spectral Luminosity", re.I),
            re.compile(r"Aurora's Luminosity", re.I),
        ),
    ),
    GearSet(
        "luclinite_coagulated",
        "ToL — Raid Tier 2 (Luclinite Coagulated)",
        gear_set_fill("luclinite_coagulated"),
        (re.compile(r"Luclinite Coagulated", re.I),),
    ),
)

GEAR_SETS_NEWEST_FIRST: tuple[GearSet, ...] = _GEAR_SETS


def classify_gear_set(item_name: str) -> GearSet | None:
    """Return the gear set for an item name, or None if unrecognized."""
    for gear_set in _GEAR_SETS:
        for pattern in gear_set.patterns:
            if pattern.search(item_name):
                return gear_set
    return None
