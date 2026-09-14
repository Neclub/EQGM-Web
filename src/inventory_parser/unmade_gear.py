"""Detect unmade craft mats and T1 containers in General bags."""

from __future__ import annotations

import re
from dataclasses import dataclass

from inventory_parser.team_report import CharacterGear, TeamGearReport, format_character_display_name
from inventory_parser.gear_tiers import (
    UNKNOWN_TIER_LABEL,
    _is_tradeskill_item,
    tier_rank,
)
from inventory_parser.parser import parse_inventory_file
from inventory_parser.sor_tier import equipped_tier_label

_FRACTURED_WEAPON_ESSENCES = frozenset(
    {
        "Fractured Essence of Finesse",
        "Fractured Essence of Power",
    }
)
_TOB_WEAPON_CORES = frozenset(
    {
        "Finesse Core of Rebellion",
        "Power Core of Rebellion",
    }
)

_OBSCURED_BOUND_CONTAINER = re.compile(
    r"^Obscured\s+(Arms|Chest|Feet|Hands|Head|Legs|Wrist)\s+Armor\s+of\s+the\s+Bound$",
    re.IGNORECASE,
)

_MATERIAL_SLOT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bHead\b", re.I), "Head"),
    (re.compile(r"\bChest\b", re.I), "Chest"),
    (re.compile(r"\bArms?\b", re.I), "Arms"),
    (re.compile(r"\bLegs?\b", re.I), "Legs"),
    (re.compile(r"\bFeet\b", re.I), "Feet"),
    (re.compile(r"\bHands?\b", re.I), "Hands"),
    (re.compile(r"\bWrist\b", re.I), "Wrist-1"),
    (re.compile(r"\bMask\b", re.I), "Face"),
    (re.compile(r"\bCloak\b", re.I), "Back"),
    (re.compile(r"\bAmice\b", re.I), "Shoulders"),
    (re.compile(r"\bShoulder\b", re.I), "Shoulders"),
    (re.compile(r"\bBelt\b", re.I), "Waist"),
    (re.compile(r"\bBuckle\b", re.I), "Waist"),
    (re.compile(r"\bNecklace\b", re.I), "Neck"),
    (re.compile(r"\bChoker\b", re.I), "Neck"),
    (re.compile(r"\bEarring\b", re.I), "Ear-1"),
    (re.compile(r"\bEar\b", re.I), "Ear-1"),
    (re.compile(r"\bRing\b", re.I), "Fingers-1"),
    (re.compile(r"\bIdol\b", re.I), "Range"),
    (re.compile(r"\bCharm\b", re.I), "Charm"),
    (re.compile(r"\bShield\b", re.I), "Secondary"),
    (re.compile(r"\bEnarmes\b", re.I), "Secondary"),
    (re.compile(r"\bString Serving\b", re.I), "Range"),
)

_BOUND_CONTAINER_SLOTS: dict[str, str] = {
    "Arms": "Arms",
    "Chest": "Chest",
    "Feet": "Feet",
    "Hands": "Hands",
    "Head": "Head",
    "Legs": "Legs",
    "Wrist": "Wrist-1",
}

# Ring / ear / wrist mats map to the first slot; Equipped Tier prefers a
# paired slot that is still below the material's target when one exists.
_PAIRED_SLOTS: dict[str, tuple[str, ...]] = {
    "Ear-1": ("Ear-1", "Ear-2"),
    "Wrist-1": ("Wrist-1", "Wrist-2"),
    "Fingers-1": ("Fingers-1", "Fingers-2"),
}


@dataclass(frozen=True)
class UnmadeMaterial:
    expansion: str
    material: str
    target_tier: str
    target_slot: str | None


@dataclass(frozen=True)
class UnmadeGearEntry:
    character: str
    display_name: str
    item_name: str
    item_id: int
    count: int
    bag_location: str
    expansion: str
    material: str
    target_slot: str | None
    equipped_tier: str
    notes: str = ""


def is_bag_location(location: str) -> bool:
    """True for General inventory rows (not Bank / Shared Bank)."""
    return location.startswith("General")


def _parse_material_slot(name: str) -> str | None:
    for pattern, slot in _MATERIAL_SLOT_PATTERNS:
        if pattern.search(name):
            return slot
    return None


def _is_ore_name(name: str) -> bool:
    return " Ore" in name or name.endswith(" Ore")


def parse_unmade_material(item_name: str) -> UnmadeMaterial | None:
    """Classify a bag item as an unmade mat/container, or return None."""
    name = " ".join(item_name.split()).strip()
    if not name or _is_ore_name(name):
        return None

    if name.startswith("Diminished Shattered"):
        slot = _parse_material_slot(name)
        return UnmadeMaterial("SoR", "T1", "SOR-R1", slot)

    bound_match = _OBSCURED_BOUND_CONTAINER.match(name)
    if bound_match is not None:
        slot = _BOUND_CONTAINER_SLOTS[bound_match.group(1)]
        return UnmadeMaterial("ToB", "T1", "TOB-R1", slot)

    if name.startswith("Fractured") and _is_tradeskill_item(name):
        slot = _parse_material_slot(name)
        if name in _FRACTURED_WEAPON_ESSENCES:
            slot = "Primary"
        return UnmadeMaterial("SoR", "T2", "SOR-R2", slot)

    if " of Rebellion" in name and _is_tradeskill_item(name):
        slot = _parse_material_slot(name)
        if name in _TOB_WEAPON_CORES:
            slot = "Primary"
        return UnmadeMaterial("ToB", "T2", "TOB-R2", slot)

    return None


def is_tier_below_target(
    equipped_label: str | None,
    target_tier: str,
    *,
    is_evolver: bool = False,
) -> bool:
    """True when equipped gear in a slot still needs the material's target tier."""
    if is_evolver:
        return False
    if not equipped_label:
        return True
    if equipped_label == UNKNOWN_TIER_LABEL:
        return True

    equipped_rank = tier_rank(equipped_label)
    target_rank_value = tier_rank(target_tier)
    if equipped_rank is None or target_rank_value is None:
        return True
    return equipped_rank < target_rank_value


def _equipped_tier_label(char: CharacterGear, slot: str | None) -> tuple[str | None, bool]:
    if not slot:
        return None, False
    item = char.slots.get(slot)
    if item is None:
        return None, False
    return equipped_tier_label(item), item.is_evolver


def _slots_to_check(target_slot: str) -> tuple[str, ...]:
    return _PAIRED_SLOTS.get(target_slot, (target_slot,))


def _display_slot_for_material(
    char: CharacterGear, target_slot: str | None, target_tier: str
) -> tuple[str | None, str]:
    """Slot and equipped-tier label for the Unmade Gear row (never used to hide)."""
    if not target_slot:
        return None, ""

    for slot in _slots_to_check(target_slot):
        equipped_label, is_evolver = _equipped_tier_label(char, slot)
        if is_tier_below_target(
            equipped_label,
            target_tier,
            is_evolver=is_evolver,
        ):
            return slot, equipped_label or ""

    equipped_label, _is_evolver = _equipped_tier_label(char, target_slot)
    return target_slot, equipped_label or ""


def build_unmade_gear_report(report: TeamGearReport) -> list[UnmadeGearEntry]:
    """Scan General bags and list every recognized unmade mat/container."""
    entries: list[UnmadeGearEntry] = []

    for char in report.characters:
        data = char.inventory_data or parse_inventory_file(char.filepath)
        if data is None:
            continue

        display_name = format_character_display_name(char.character, char.class_abbr)

        for item in data.items:
            if not is_bag_location(item.location):
                continue

            material = parse_unmade_material(item.name)
            if material is None:
                continue

            target_slot, equipped_label = _display_slot_for_material(
                char, material.target_slot, material.target_tier
            )

            entries.append(
                UnmadeGearEntry(
                    character=char.character,
                    display_name=display_name,
                    item_name=item.name,
                    item_id=item.item_id,
                    count=item.count,
                    bag_location=item.location,
                    expansion=material.expansion,
                    material=material.material,
                    target_slot=target_slot,
                    equipped_tier=equipped_label,
                    notes="",
                )
            )

    entries.sort(
        key=lambda row: (
            row.character.casefold(),
            row.expansion.casefold(),
            row.material.casefold(),
            row.item_name.casefold(),
            row.bag_location.casefold(),
        )
    )
    return entries
