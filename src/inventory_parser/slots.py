"""Equipment slot layout for team gear spreadsheets."""

from __future__ import annotations

from typing import Literal

# Slots shown on the character model (armor view).
VISIBLE_SLOTS: tuple[str, ...] = (
    "Arms",
    "Chest",
    "Feet",
    "Hands",
    "Head",
    "Legs",
    "Wrist-1",
    "Wrist-2",
    "Primary",
    "Secondary",
)

# Equipped slots not on the visible model (jewelry, cloak, etc.).
NON_VISIBLE_SLOTS: tuple[str, ...] = (
    "Back",
    "Charm",
    "Ear-1",
    "Ear-2",
    "Face",
    "Fingers-1",
    "Fingers-2",
    "Neck",
    "Range",
    "Shoulders",
    "Waist",
)

# All team slots: visible first, then non-visible.
TEAM_GEAR_SLOTS: tuple[str, ...] = VISIBLE_SLOTS + NON_VISIBLE_SLOTS

VISIBILITY_VISIBLE = "Visible"
VISIBILITY_NON_VISIBLE = "Non-visible"

SlotFilter = Literal["all", "visible", "non_visible"]

SLOT_VISIBILITY: dict[str, str] = {
    **dict.fromkeys(VISIBLE_SLOTS, VISIBILITY_VISIBLE),
    **dict.fromkeys(NON_VISIBLE_SLOTS, VISIBILITY_NON_VISIBLE),
}

EQUIPMENT_SLOT_BASES: frozenset[str] = frozenset(
    {
        "Charm",
        "Ear",
        "Head",
        "Face",
        "Neck",
        "Shoulders",
        "Arms",
        "Back",
        "Wrist",
        "Range",
        "Hands",
        "Primary",
        "Secondary",
        "Fingers",
        "Chest",
        "Legs",
        "Feet",
        "Waist",
        "Power Source",
        "Ammo",
    }
)

# Canonical gear slots used when normalizing raidloot "All except …" strings.
ALL_GEAR_SLOTS: frozenset[str] = EQUIPMENT_SLOT_BASES

# Report keys that map to the Ear base for slot-restriction checks.
EAR_REPORT_SLOTS: frozenset[str] = frozenset({"Ear-1", "Ear-2", "Ear"})

# Range and Charm first — few augs fit those holes, so their BiS is claimed before
# general slots. Feet joins that priority set when the high-AC overlay applies.
PRIORITY_AUG_SLOTS: tuple[str, ...] = ("Range", "Charm")

AUG_ASSIGNMENT_ORDER: tuple[str, ...] = PRIORITY_AUG_SLOTS + tuple(
    s for s in TEAM_GEAR_SLOTS if s not in PRIORITY_AUG_SLOTS
)


def priority_aug_slots(class_abbr: str | None = None) -> tuple[str, ...]:
    """Slots that claim BiS first because fewer augs fit them."""
    if class_abbr:
        from inventory_parser.slot2_augs.weights import uses_feet_overlay

        if uses_feet_overlay(class_abbr):
            return ("Range", "Charm", "Feet")
    return PRIORITY_AUG_SLOTS


def aug_assignment_order(class_abbr: str | None = None) -> tuple[str, ...]:
    """Full slot claim order: priority holes first, then remaining report slots."""
    priority = priority_aug_slots(class_abbr)
    rest = tuple(s for s in TEAM_GEAR_SLOTS if s not in priority)
    return priority + rest


def slots_for_export(slot_filter: SlotFilter = "all") -> tuple[str, ...]:
    """Return slot row order for Excel export."""
    if slot_filter == "visible":
        return VISIBLE_SLOTS
    if slot_filter == "non_visible":
        return NON_VISIBLE_SLOTS
    return TEAM_GEAR_SLOTS


def slot_visibility(slot: str) -> str:
    return SLOT_VISIBILITY[slot]
