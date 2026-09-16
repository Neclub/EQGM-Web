"""Missing raid-vendor ores derived from Raid BiS slot recommendations."""

from __future__ import annotations

from dataclasses import dataclass, field

from inventory_parser.raid_bis.build import RaidBisExport
from inventory_parser.raid_bis.compare import CharacterRaidBis, SlotComparison
from inventory_parser.raid_bis.models import RaidVendorCatalog, RaidVendorItem
from inventory_parser.raid_bis.vendor import is_ore_name, list_slot_ores, ore_for_slot


@dataclass
class OreNeedRow:
    name: str
    item_id: int
    counts: list[int] = field(default_factory=list)
    evolvers: list[bool] = field(default_factory=list)


@dataclass
class OreNeedsMatrix:
    characters: list[str]
    class_abbrs: list[str]
    rows: list[OreNeedRow] = field(default_factory=list)
    totals: list[int] = field(default_factory=list)


def _vendor_ore_for_slot(
    slot: SlotComparison,
    vendor: RaidVendorCatalog | None,
) -> RaidVendorItem | None:
    """Ore row for a BiS slot: attached vendor ore, else the slot's lining/clasp/etc."""
    if vendor is not None and slot.vendor_item_id and slot.vendor_item_name:
        if is_ore_name(slot.vendor_item_name):
            return RaidVendorItem(
                item_id=int(slot.vendor_item_id),
                name=slot.vendor_item_name,
                cost=int(slot.vendor_cost or 0),
                is_ore=True,
            )
    return ore_for_slot(vendor, slot.gear_slot) if vendor else None


def _slot_needs_ore_count(slot: SlotComparison) -> bool:
    if not slot.scored or slot.status in ("bis", "weapon", "unknown"):
        return False
    if slot.current_is_evolver:
        return False
    if slot.status not in ("upgrade", "empty"):
        return False
    return bool(slot.vendor_item_name and is_ore_name(slot.vendor_item_name))


def _accumulate_character(
    character: CharacterRaidBis,
    vendor: RaidVendorCatalog | None,
    ore_index: dict[int, int],
    counts: list[list[int]],
    evolvers: list[list[bool]],
    need_totals: list[int],
    char_idx: int,
) -> None:
    for slot in character.slots:
        if not slot.scored or slot.status == "weapon":
            continue
        ore = _vendor_ore_for_slot(slot, vendor)
        if ore is None or ore.item_id not in ore_index:
            continue
        row_idx = ore_index[ore.item_id]
        # Evolver slots are notation-only: purple crystal, never part of counts/Total.
        if slot.current_is_evolver:
            evolvers[row_idx][char_idx] = True
            continue
        if _slot_needs_ore_count(slot):
            counts[row_idx][char_idx] += 1
            need_totals[char_idx] += 1


def build_ore_needs_matrix(bundle: RaidBisExport) -> OreNeedsMatrix:
    """Character × ore matrix of vendor ores still needed from Raid BiS."""
    characters = [ch.display_name for ch in bundle.characters]
    class_abbrs = [(ch.class_abbr or "") for ch in bundle.characters]
    n = len(characters)
    vendor = bundle.catalog.vendor if bundle.catalog else None
    ores = list_slot_ores(vendor)
    if not ores:
        return OreNeedsMatrix(
            characters=characters,
            class_abbrs=class_abbrs,
            rows=[],
            totals=[0] * n,
        )

    ore_index = {ore.item_id: i for i, ore in enumerate(ores)}
    counts = [[0] * n for _ in ores]
    evolvers = [[False] * n for _ in ores]
    need_totals = [0] * n

    for char_idx, ch in enumerate(bundle.characters):
        _accumulate_character(
            ch, vendor, ore_index, counts, evolvers, need_totals, char_idx
        )

    rows = [
        OreNeedRow(
            name=ore.name,
            item_id=ore.item_id,
            counts=counts[i],
            evolvers=evolvers[i],
        )
        for i, ore in enumerate(ores)
    ]
    return OreNeedsMatrix(
        characters=characters,
        class_abbrs=class_abbrs,
        rows=rows,
        totals=need_totals,
    )


def serialize_ore_needs_section(bundle: RaidBisExport) -> dict:
    """JSON payload for the HTML Missing Ores tab (Missing Runes–style matrix)."""
    from inventory_parser.items import EQRESOURCE_ITEM_URL

    matrix = build_ore_needs_matrix(bundle)
    # One block so sortedColumnIndices / columnMissingTotal work unchanged.
    block_rows = [
        {
            "tier": row.name,
            "itemId": row.item_id,
            "counts": list(row.counts),
            "evolvers": list(row.evolvers),
        }
        for row in matrix.rows
    ]
    if matrix.rows:
        block_rows.append(
            {
                "tier": "Total",
                "itemId": 0,
                "counts": list(matrix.totals),
                "evolvers": [False] * len(matrix.characters),
                "isTotal": True,
            }
        )
    return {
        "characters": matrix.characters,
        "classAbbrs": matrix.class_abbrs,
        "eqResourceItemUrl": EQRESOURCE_ITEM_URL,
        "blocks": [
            {
                "label": "Raid vendor ores",
                "theme": (
                    "Ores still needed for Raid BiS upgrades · "
                    "Evolver slots show the purple crystal and are excluded from Total"
                ),
                "rows": block_rows,
            }
        ],
    }
