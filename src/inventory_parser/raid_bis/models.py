"""Raid BiS item candidates and slot constants."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from inventory_parser.slots import TEAM_GEAR_SLOTS

_ENHANCED_MINION_RE = re.compile(
    r"enhanced\s+minion\s+([ivxlcdm]+|\d+)\b",
    re.IGNORECASE,
)
_ROMAN_VALUES: dict[str, int] = {
    "I": 1,
    "V": 5,
    "X": 10,
    "L": 50,
    "C": 100,
    "D": 500,
    "M": 1000,
}


def roman_to_int(token: str) -> int:
    """Parse a roman numeral (subtractive) or arabic digits; 0 if invalid."""
    raw = (token or "").strip().upper()
    if not raw:
        return 0
    if raw.isdigit():
        return int(raw)
    if not all(ch in _ROMAN_VALUES for ch in raw):
        return 0
    total = 0
    i = 0
    while i < len(raw):
        value = _ROMAN_VALUES[raw[i]]
        if i + 1 < len(raw):
            nxt = _ROMAN_VALUES[raw[i + 1]]
            if nxt > value:
                total += nxt - value
                i += 2
                continue
        total += value
        i += 1
    return total


def parse_enhanced_minion_level(*texts: str) -> int:
    """Highest Enhanced Minion rank found in any of the given strings."""
    best = 0
    for text in texts:
        if not text:
            continue
        for match in _ENHANCED_MINION_RE.finditer(text):
            level = roman_to_int(match.group(1))
            if level > best:
                best = level
    return best

# In-game Inventory window order (4 columns, portrait in the center).
PAPERDOLL_SLOTS: tuple[str, ...] = (
    "Ear-1",
    "Head",
    "Face",
    "Ear-2",
    "Chest",
    "Neck",
    "Arms",
    "Back",
    "Waist",
    "Shoulders",
    "Wrist-1",
    "Wrist-2",
    "Legs",
    "Hands",
    "Charm",
    "Feet",
    "Fingers-1",
    "Fingers-2",
    "Power Source",
    "Primary",
    "Secondary",
    "Range",
    "Ammo",
)

UNSCORED_SLOTS: frozenset[str] = frozenset(
    {"Primary", "Secondary", "Ammo", "Power Source"}
)
WEAPON_SLOTS: tuple[str, ...] = ("Primary", "Secondary", "Ammo")
SCORED_SLOTS: tuple[str, ...] = tuple(
    s for s in TEAM_GEAR_SLOTS if s not in UNSCORED_SLOTS
)

PET_FOCUS_CLASSES: frozenset[str] = frozenset({"MAG", "BST", "NEC"})
ALL_CLASS_ABBRS: frozenset[str] = frozenset(
    {
        "WAR",
        "PAL",
        "SHD",
        "MNK",
        "RNG",
        "ROG",
        "BST",
        "BRD",
        "BER",
        "ENC",
        "WIZ",
        "MAG",
        "NEC",
        "SHM",
        "CLR",
        "DRU",
    }
)

# Wrist items are not Lore; both slots may wear the same bracer.
NON_LORE_SLOTS: frozenset[str] = frozenset({"Wrist-1", "Wrist-2"})

DUAL_SLOT_GROUPS: tuple[tuple[str, ...], ...] = (
    ("Ear-1", "Ear-2"),
    ("Wrist-1", "Wrist-2"),
    ("Fingers-1", "Fingers-2"),
)

ARMOR_SLOT_HEADERS: dict[str, str] = {
    "wrist": "Wrist",
    "hand": "Hands",
    "hands": "Hands",
    "feet": "Feet",
    "head": "Head",
    "arms": "Arms",
    "legs": "Legs",
    "chest": "Chest",
}

JEWELRY_TYPE_SLOTS: tuple[tuple[str, str], ...] = (
    ("back", "Back"),
    ("charm", "Charm"),
    ("ear", "Ear"),
    ("face", "Face"),
    ("finger", "Fingers"),
    ("neck", "Neck"),
    ("rangex", "Range"),
    ("shoulder", "Shoulders"),
    ("waist", "Waist"),
)


def slot_base(gear_slot: str) -> str:
    """Map report keys like Ear-1 to the item Slot: base name."""
    if gear_slot.startswith("Ear"):
        return "Ear"
    if gear_slot.startswith("Wrist"):
        return "Wrist"
    if gear_slot.startswith("Fingers"):
        return "Fingers"
    return gear_slot


@dataclass
class RaidGearCandidate:
    item_id: int
    name: str
    stats: dict[str, int] = field(default_factory=dict)
    # None = class list unknown (not wearable). Empty frozenset = Class: All.
    classes: frozenset[str] | None = None
    slots: frozenset[str] = field(default_factory=frozenset)
    tier: str = ""
    lore_group: str | None = None
    icon_id: str | None = None
    focus: str = ""
    effect: str = ""
    source: str = "EQ Resource"

    def lore_key(self) -> str:
        if self.lore_group:
            return self.lore_group.strip().casefold()
        return str(self.item_id)

    def fits_class(self, class_abbr: str | None) -> bool:
        if not class_abbr:
            return False
        if self.classes is None:
            return False
        # Empty class list means ALL (EQ Resource "Class: All").
        if not self.classes:
            return True
        return class_abbr.strip().upper() in self.classes

    def fits_slot(self, gear_slot: str) -> bool:
        return slot_base(gear_slot) in self.slots

    def is_pet_focus_ear(self) -> bool:
        """True for Summoner-named or Enhanced Minion ears restricted to MAG/BST/NEC."""
        if "Ear" not in self.slots:
            return False
        name_hit = "summoner" in (self.name or "").casefold()
        focus_hit = "enhanced minion" in (self.focus or "").casefold()
        if not (name_hit or focus_hit):
            return False
        if self.classes is None:
            return False
        if self.classes and not (self.classes & PET_FOCUS_CLASSES):
            return False
        return True

    def enhanced_minion_level(self) -> int:
        """Enhanced Minion rank from focus, effect, or name (0 if none)."""
        return parse_enhanced_minion_level(self.focus, self.effect, self.name)

    def pet_focus_rank_tuple(self) -> tuple:
        """Sort key for pet ears: highest EM first, then name. Stats ignored."""
        return (-self.enhanced_minion_level(), (self.name or "").casefold())


@dataclass
class RaidVendorItem:
    item_id: int
    name: str
    cost: int
    is_ore: bool = False


@dataclass
class RaidVendorCatalog:
    currency_name: str = ""
    currency_id: int | None = None
    currency_icon_id: str | None = None
    items: list[RaidVendorItem] = field(default_factory=list)
    fetched_at: str = ""
    warning: str | None = None
    url: str = ""


@dataclass
class RaidBisCatalog:
    items: list[RaidGearCandidate] = field(default_factory=list)
    fetched_at: str = ""
    from_cache: bool = False
    warning: str | None = None
    urls: list[str] = field(default_factory=list)
    vendor: RaidVendorCatalog | None = None
