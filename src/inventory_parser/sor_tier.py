"""Shattering of Ro (SOR) tier gap labels for the upgrade tracking sheet."""

from __future__ import annotations

from inventory_parser.evolver import EVOLVER_GAP_LABEL
from inventory_parser.gear_tiers import GEAR_TIER_BY_CODE, UNKNOWN_TIER_LABEL, classify_gear_tier
from inventory_parser.items import EquippedItem


def sor_gap_label(
    item_name: str | None,
    *,
    is_evolver: bool = False,
    resolved_tier: str | None = None,
) -> str | None:
    """
    Return a tier code for equipped gear on the Gear T-Level sheet.

    - ``None`` — empty slot
    - ``Evolver`` — equipped Evolver item
    - tier code — e.g. ``SOR-R2``, ``TOB-R2``, ``LS-G1``, ``SOR-R1``
    - ``???`` — equipped but unrecognized
    """
    if not item_name:
        return None

    tier = classify_gear_tier(item_name)
    if tier is not None:
        return tier.code
    if is_evolver:
        return EVOLVER_GAP_LABEL
    if resolved_tier and resolved_tier in GEAR_TIER_BY_CODE:
        return resolved_tier
    return UNKNOWN_TIER_LABEL


def equipped_tier_label(item: EquippedItem | None) -> str | None:
    """Tier label for an equipped item, including EQ Resource fallback."""
    if item is None:
        return None
    return sor_gap_label(
        item.name,
        is_evolver=item.is_evolver,
        resolved_tier=item.resolved_tier,
    )
