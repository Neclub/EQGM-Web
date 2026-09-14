"""Evolver items — equipped gear whose inventory file includes the final augment row."""

from __future__ import annotations

EVOLVER_LABEL = "Evolver (final augment row in inventory file)"
EVOLVER_GAP_LABEL = "Evolver"

# Highest-numbered ``{slot}-SlotN`` row for an evolver in inventory files.
EVOLVER_AUGMENT_SLOT_BY_BASE: dict[str, int] = {
    "Primary": 5,
}
EVOLVER_AUGMENT_SLOT_DEFAULT = 6


def evolver_augment_slot_number(equipment_base: str) -> int:
    """Slot index in ``Ear-Slot6`` / ``Primary-Slot5`` style location names."""
    return EVOLVER_AUGMENT_SLOT_BY_BASE.get(equipment_base, EVOLVER_AUGMENT_SLOT_DEFAULT)


def is_evolver_augment_row(location: str) -> bool:
    """
    True when ``location`` is the final augment row for an evolver item.

    Jewelry/armor use ``Ear-Slot6``; primary weapons use ``Primary-Slot5``.
    Secondary weapons are never Evolvers. Nested rows like
    ``General 5-Slot6-Slot1`` are excluded.
    """
    if location.count("-Slot") != 1:
        return False
    parent, slot_part = location.rsplit("-Slot", 1)
    try:
        slot_num = int(slot_part)
    except ValueError:
        return False
    return slot_num == evolver_augment_slot_number(parent)


def parent_location_of_evolver_row(location: str) -> str:
    """``Ear-Slot6`` -> ``Ear``, ``Primary-Slot5`` -> ``Primary``."""
    return location.rsplit("-Slot", 1)[0]


def equipped_item_is_evolver(item_name: str) -> bool:
    """
    True when an equipped item should be treated as an Evolver.

    Fully augmented raid gear (e.g. Resonant Fracture with ``Ear-Slot6`` filled)
    also emits the final augment row, but recognized tier names take precedence.
    """
    from inventory_parser.gear_tiers import classify_gear_tier

    return classify_gear_tier(item_name) is None
