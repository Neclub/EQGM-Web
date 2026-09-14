"""Parse EverQuest inventory dump text files."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from inventory_parser.slots import EQUIPMENT_SLOT_BASES

_INVENTORY_FILENAME_RE = re.compile(
    r"^(.+)_([^-]+)(?:-([A-Za-z]+))?-Inventory\.txt$",
    re.IGNORECASE,
)

_SLOT_N_RE = re.compile(r"^(.+)-Slot(\d+)$", re.IGNORECASE)

# Range bows list Slot1–4 in the dump and include "bow" in the item name.
_BOW_RANGE_SLOTS: frozenset[int] = frozenset({1, 2, 3, 4})
_BOW_NAME_RE = re.compile(r"(?i)(?:cross)?bow\b")

# Secondary shields: parent item name contains Shield or Aegis (weapons ignored).
_SHIELD_NAME_RE = re.compile(r"(?i)\b(?:Shield|Aegis)\b")


@dataclass(frozen=True)
class InventoryItem:
    location: str
    name: str
    item_id: int
    count: int
    augment_slots: int | None = None  # 5th column (max augment slots on item)


@dataclass
class InventoryData:
    character: str
    server: str
    filepath: str
    items: list[InventoryItem] = field(default_factory=list)
    class_abbr: str | None = None


@dataclass(frozen=True)
class Slot2Aug:
    """Equipped type 7/8 aug contents for one gear slot (usually dump Slot2)."""

    gear_slot: str
    name: str | None
    item_id: int | None
    dump_slot: int = 2  # which *-SlotN row this came from
    parent_name: str | None = None
    parent_id: int | None = None
    socket_map_hit: bool = False  # True when dump_slot came from item socket map


@dataclass(frozen=True)
class Type5Aug:
    """Equipped type 5 aug contents for one gear slot (socket-map dump SlotN)."""

    gear_slot: str
    name: str | None
    item_id: int | None
    dump_slot: int
    parent_name: str | None = None
    parent_id: int | None = None


def parse_inventory_filename(filepath: str | Path) -> tuple[str, str, str | None]:
    """Extract character, server, and optional class from an inventory filename.

    Supports ``{Char}_{Server}-Inventory.txt`` and
    ``{Char}_{Server}-{CLASS}-Inventory.txt``.
    """
    name = Path(filepath).name
    match = _INVENTORY_FILENAME_RE.match(name)
    if match:
        class_abbr = match.group(3)
        return match.group(1), match.group(2), class_abbr.upper() if class_abbr else None
    stem = Path(filepath).stem
    if stem.endswith("-Inventory"):
        stem = stem[: -len("-Inventory")]
    # Fallback: try trailing -CLASS before treating rest as Char_Server
    class_match = re.match(r"^(.+)_([^-]+)-([A-Za-z]+)$", stem)
    if class_match:
        return class_match.group(1), class_match.group(2), class_match.group(3).upper()
    parts = stem.rsplit("_", 1)
    if len(parts) == 2:
        return parts[0], parts[1], None
    return stem, "", None


def parse_character_from_filename(filepath: str | Path) -> tuple[str, str]:
    """Extract character and server from an inventory filename (class ignored)."""
    character, server, _class_abbr = parse_inventory_filename(filepath)
    return character, server


def parse_inventory_file(filepath: str | Path) -> InventoryData | None:
    """Parse a tab-separated inventory dump. Returns None if the file is missing."""
    path = Path(filepath)
    if not path.is_file():
        return None

    character, server, class_abbr = parse_inventory_filename(path)
    items: list[InventoryItem] = []

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    for i, raw in enumerate(text.splitlines()):
        line = raw.strip()
        if not line:
            continue

        parts = line.split("\t")
        if len(parts) < 3:
            continue

        if i == 0 and parts[0].lower() == "location" and parts[1].lower() == "name":
            continue

        location = parts[0].strip()
        name = parts[1].strip()
        try:
            item_id = int(parts[2].strip())
        except ValueError:
            continue

        if name == "Empty" and item_id == 0 and "-Slot" not in location:
            continue

        if len(parts) >= 4:
            try:
                count = int(parts[3].strip())
            except ValueError:
                count = 1
        else:
            count = 1

        augment_slots: int | None = None
        if len(parts) >= 5:
            try:
                augment_slots = int(parts[4].strip())
            except ValueError:
                augment_slots = None

        items.append(
            InventoryItem(
                location=location,
                name=name,
                item_id=item_id,
                count=count,
                augment_slots=augment_slots,
            )
        )

    return InventoryData(
        character=character,
        server=server,
        filepath=str(path.resolve()),
        items=items,
        class_abbr=class_abbr,
    )


def extract_equipped_items(
    data: InventoryData,
) -> tuple[dict[str, InventoryItem], set[str]]:
    """
    Map normalized team slots (e.g. ``Ear-1``) to the equipped item in that slot.

    Returns equipped items and team slot keys marked as Evolvers (dump has the
    final augment row for that slot, e.g. ``Ear-Slot6``, ``Primary-Slot5``).
    """
    from inventory_parser.evolver import (
        equipped_item_is_evolver,
        is_evolver_augment_row,
        parent_location_of_evolver_row,
    )

    equipped: dict[str, InventoryItem] = {}
    evolver_keys: set[str] = set()
    current_key_by_base: dict[str, str] = {}
    ear_n = 0
    finger_n = 0
    wrist_n = 0

    for item in data.items:
        loc = item.location

        if is_evolver_augment_row(loc):
            parent = parent_location_of_evolver_row(loc)
            if parent in current_key_by_base:
                key = current_key_by_base[parent]
                if equipped_item_is_evolver(equipped[key].name):
                    evolver_keys.add(key)
            continue

        if "-Slot" in loc:
            continue

        base = loc.split("-")[0].strip()
        if base not in EQUIPMENT_SLOT_BASES:
            continue

        if base == "Ear":
            ear_n += 1
            key = f"Ear-{ear_n}"
        elif base == "Fingers":
            finger_n += 1
            key = f"Fingers-{finger_n}"
        elif base == "Wrist":
            wrist_n += 1
            key = f"Wrist-{wrist_n}"
        else:
            key = base

        equipped[key] = item
        current_key_by_base[base] = key

    return equipped, evolver_keys


def equipped_item_from_inventory(
    item: InventoryItem, *, is_evolver: bool = False
) -> "EquippedItem":
    """Build export row data from a top-level inventory item."""
    from inventory_parser.items import EquippedItem

    return EquippedItem(
        name=item.name,
        item_id=item.item_id,
        is_evolver=is_evolver,
    )


def range_name_looks_like_bow(item_name: str | None) -> bool:
    """True when the Range item name contains bow/crossbow (e.g. Short Bow)."""
    if not item_name:
        return False
    return bool(_BOW_NAME_RE.search(item_name))


def parent_name_is_shield(item_name: str | None) -> bool:
    """True when Secondary parent name looks like a shield (Shield or Aegis)."""
    if not item_name:
        return False
    if item_name.strip().casefold() == "empty":
        return False
    return bool(_SHIELD_NAME_RE.search(item_name))


def range_has_bow_slots(slot_numbers: set[int] | frozenset[int]) -> bool:
    """True when Range lists Slot1–Slot4 (bow aug layout)."""
    return _BOW_RANGE_SLOTS.issubset(slot_numbers)


def is_range_bow(
    *,
    slot_numbers: set[int] | frozenset[int],
    item_name: str | None,
) -> bool:
    """True when Range is a bow: dump lists Slot1–4 and the item name contains bow."""
    return range_has_bow_slots(slot_numbers) and range_name_looks_like_bow(item_name)


def type78_dump_slot_for_parent(
    gear_base: str,
    parent_name: str | None = None,
    *,
    range_is_bow: bool = False,
) -> int:
    """Which ``*-SlotN`` row holds the type 7/8 aug for this parent item."""
    del parent_name
    if gear_base == "Range" and range_is_bow:
        return 4
    return 2


def _is_equipped_aug_location(location: str) -> tuple[str, int] | None:
    """Return (parent_location, slot_n) for equipped aug rows; else None."""
    if location.count("-Slot") != 1:
        return None
    match = _SLOT_N_RE.match(location)
    if not match:
        return None
    parent = match.group(1)
    slot_n = int(match.group(2))
    base = parent.split("-")[0].strip()
    if base not in EQUIPMENT_SLOT_BASES:
        return None
    if parent.lower().startswith(("general", "bank", "sharedbank", "shared bank")):
        return None
    return parent, slot_n


def _collect_range_aug_slot_numbers(data: InventoryData) -> set[int]:
    """Slot numbers present under equipped Range (e.g. {1,2,3,4,5})."""
    found: set[int] = set()
    for item in data.items:
        parsed = _is_equipped_aug_location(item.location)
        if parsed is None:
            continue
        parent, slot_n = parsed
        if parent.split("-")[0].strip() == "Range":
            found.add(slot_n)
    return found


def _range_parent_name(data: InventoryData) -> str | None:
    """Name of the equipped Range parent item, if present."""
    for item in data.items:
        if item.location == "Range" and "-Slot" not in item.location:
            return item.name
    return None


def collect_owned_item_ids(data: InventoryData) -> set[int]:
    """All non-empty item IDs anywhere in the dump (bags, bank, equipped, slots)."""
    owned: set[int] = set()
    for item in data.items:
        if item.item_id <= 0:
            continue
        if item.name.strip().casefold() == "empty":
            continue
        owned.add(item.item_id)
    return owned


def collect_owned_item_names(data: InventoryData) -> set[str]:
    """Casefolded names of non-empty items anywhere in the dump."""
    owned: set[str] = set()
    for item in data.items:
        name = item.name.strip()
        if not name or name.casefold() == "empty":
            continue
        if item.item_id <= 0:
            continue
        owned.add(name.casefold())
    return owned


def collect_equipped_aug_locations(
    data: InventoryData,
) -> tuple[dict[int, str], dict[str, str]]:
    """Map equipped aug item id / casefolded name → team gear slot.

    Only inventory rows under equipment (e.g. ``Chest-Slot3``, ``Ear-Slot1``).
    Paired slots become ``Ear-1`` / ``Ear-2``, ``Fingers-1`` / ``Fingers-2``,
    ``Wrist-1`` / ``Wrist-2``. Bags and bank are ignored. When the same aug
    appears in more than one equipped hole, locations are joined with ``, ``.
    """
    by_id: dict[int, list[str]] = {}
    by_name: dict[str, list[str]] = {}
    ear_n = 0
    finger_n = 0
    wrist_n = 0
    current_key_by_base: dict[str, str] = {}

    for item in data.items:
        loc = item.location
        if "-Slot" not in loc:
            base = loc.split("-")[0].strip()
            if base not in EQUIPMENT_SLOT_BASES:
                continue
            key, ear_n, finger_n, wrist_n = _gear_slot_key_for_base(
                base, ear_n=ear_n, finger_n=finger_n, wrist_n=wrist_n
            )
            current_key_by_base[base] = key
            continue

        parsed = _is_equipped_aug_location(loc)
        if parsed is None:
            continue
        parent, _slot_n = parsed
        base = parent.split("-")[0].strip()
        gear_slot = current_key_by_base.get(base)
        if gear_slot is None:
            gear_slot, ear_n, finger_n, wrist_n = _gear_slot_key_for_base(
                base, ear_n=ear_n, finger_n=finger_n, wrist_n=wrist_n
            )
            current_key_by_base[base] = gear_slot

        name = item.name.strip()
        if not name or name.casefold() == "empty" or item.item_id <= 0:
            continue

        if item.item_id > 0:
            slots = by_id.setdefault(item.item_id, [])
            if gear_slot not in slots:
                slots.append(gear_slot)
        key_name = name.casefold()
        name_slots = by_name.setdefault(key_name, [])
        if gear_slot not in name_slots:
            name_slots.append(gear_slot)

    return (
        {iid: ", ".join(slots) for iid, slots in by_id.items()},
        {name: ", ".join(slots) for name, slots in by_name.items()},
    )


def collect_equipped_parent_ids(data: InventoryData) -> list[int]:
    """Equipped parent item IDs that need type 7/8 socket lookup."""
    ids: list[int] = []
    seen: set[int] = set()
    for item in data.items:
        if "-Slot" in item.location:
            continue
        base = item.location.split("-")[0].strip()
        if base not in EQUIPMENT_SLOT_BASES:
            continue
        if base == "Primary":
            continue
        if base == "Secondary" and not parent_name_is_shield(item.name):
            continue
        if item.item_id <= 0 or item.name.strip().casefold() == "empty":
            continue
        if item.item_id in seen:
            continue
        seen.add(item.item_id)
        ids.append(item.item_id)
    return ids


def extract_slot2_augs(
    data: InventoryData,
    *,
    type78_slot_by_parent_id: dict[int, int] | None = None,
) -> list[Slot2Aug]:
    """
    Extract equipped type 7/8 augs.

    When ``type78_slot_by_parent_id`` maps a parent item ID to a dump SlotN,
    that hole is used. Otherwise fall back to Range-bow Slot4 / Slot2 heuristic.
    """
    slot_map = type78_slot_by_parent_id or {}
    range_is_bow = is_range_bow(
        slot_numbers=_collect_range_aug_slot_numbers(data),
        item_name=_range_parent_name(data),
    )

    ear_n = 0
    finger_n = 0
    wrist_n = 0
    current_key_by_base: dict[str, str] = {}
    parent_name_by_base: dict[str, str] = {}
    parent_id_by_base: dict[str, int] = {}
    results: list[Slot2Aug] = []
    seen_keys: set[str] = set()

    for item in data.items:
        loc = item.location

        if "-Slot" not in loc:
            base = loc.split("-")[0].strip()
            if base not in EQUIPMENT_SLOT_BASES:
                continue
            if base == "Ear":
                ear_n += 1
                key = f"Ear-{ear_n}"
            elif base == "Fingers":
                finger_n += 1
                key = f"Fingers-{finger_n}"
            elif base == "Wrist":
                wrist_n += 1
                key = f"Wrist-{wrist_n}"
            else:
                key = base
            current_key_by_base[base] = key
            parent_name_by_base[base] = item.name
            parent_id_by_base[base] = item.item_id
            continue

        parsed = _is_equipped_aug_location(loc)
        if parsed is None:
            continue
        parent, slot_n = parsed
        base = parent.split("-")[0].strip()
        parent_name = parent_name_by_base.get(base)
        parent_id = parent_id_by_base.get(base)
        mapped: int | None = None
        if parent_id is not None and parent_id > 0 and parent_id in slot_map:
            mapped = slot_map[parent_id]
        if mapped is not None:
            wanted = mapped
            socket_map_hit = True
        else:
            wanted = type78_dump_slot_for_parent(
                base, parent_name, range_is_bow=range_is_bow
            )
            socket_map_hit = False
        if slot_n != wanted:
            continue

        gear_slot = current_key_by_base.get(base)
        if gear_slot is None:
            if base == "Ear":
                ear_n += 1
                gear_slot = f"Ear-{ear_n}"
            elif base == "Fingers":
                finger_n += 1
                gear_slot = f"Fingers-{finger_n}"
            elif base == "Wrist":
                wrist_n += 1
                gear_slot = f"Wrist-{wrist_n}"
            else:
                gear_slot = base
            current_key_by_base[base] = gear_slot

        if gear_slot in seen_keys:
            continue
        seen_keys.add(gear_slot)

        if item.name == "Empty" or item.item_id == 0:
            results.append(
                Slot2Aug(
                    gear_slot=gear_slot,
                    name=None,
                    item_id=None,
                    dump_slot=wanted,
                    parent_name=parent_name,
                    parent_id=parent_id,
                    socket_map_hit=socket_map_hit,
                )
            )
        else:
            results.append(
                Slot2Aug(
                    gear_slot=gear_slot,
                    name=item.name,
                    item_id=item.item_id,
                    dump_slot=wanted,
                    parent_name=parent_name,
                    parent_id=parent_id,
                    socket_map_hit=socket_map_hit,
                )
            )

    return results


def _gear_slot_key_for_base(
    base: str,
    *,
    ear_n: int,
    finger_n: int,
    wrist_n: int,
) -> tuple[str, int, int, int]:
    """Assign Ear-N / Fingers-N / Wrist-N keys; return (key, ear_n, finger_n, wrist_n)."""
    if base == "Ear":
        ear_n += 1
        return f"Ear-{ear_n}", ear_n, finger_n, wrist_n
    if base == "Fingers":
        finger_n += 1
        return f"Fingers-{finger_n}", ear_n, finger_n, wrist_n
    if base == "Wrist":
        wrist_n += 1
        return f"Wrist-{wrist_n}", ear_n, finger_n, wrist_n
    return base, ear_n, finger_n, wrist_n


def extract_type5_augs(
    data: InventoryData,
    *,
    type5_slot_by_parent_id: dict[int, int],
) -> list[Type5Aug]:
    """
    Extract equipped type 5 augs using parent-item socket maps only.

    Only gear slots whose parent has a mapped type 5 dump SlotN are included.
    Missing or empty ``*-SlotN`` rows become Empty. No Slot2 heuristic fallback.
    """
    ear_n = 0
    finger_n = 0
    wrist_n = 0
    current_key_by_base: dict[str, str] = {}
    parent_name_by_base: dict[str, str] = {}
    parent_id_by_base: dict[str, int] = {}
    # gear_slot → Type5Aug from dump rows that matched the mapped SlotN
    found: dict[str, Type5Aug] = {}
    # Parents that have a type 5 hole (gear_slot → dump_slot, parent meta)
    expected: dict[str, tuple[int, str | None, int | None]] = {}

    for item in data.items:
        loc = item.location

        if "-Slot" not in loc:
            base = loc.split("-")[0].strip()
            if base not in EQUIPMENT_SLOT_BASES:
                continue
            if base == "Primary":
                continue
            if base == "Secondary" and not parent_name_is_shield(item.name):
                continue
            if item.item_id <= 0 or item.name.strip().casefold() == "empty":
                continue
            key, ear_n, finger_n, wrist_n = _gear_slot_key_for_base(
                base, ear_n=ear_n, finger_n=finger_n, wrist_n=wrist_n
            )
            current_key_by_base[base] = key
            parent_name_by_base[base] = item.name
            parent_id_by_base[base] = item.item_id
            mapped = type5_slot_by_parent_id.get(item.item_id)
            if mapped is not None:
                expected[key] = (mapped, item.name, item.item_id)
            continue

        parsed = _is_equipped_aug_location(loc)
        if parsed is None:
            continue
        parent, slot_n = parsed
        base = parent.split("-")[0].strip()
        parent_id = parent_id_by_base.get(base)
        if parent_id is None or parent_id <= 0:
            continue
        wanted = type5_slot_by_parent_id.get(parent_id)
        if wanted is None or slot_n != wanted:
            continue

        gear_slot = current_key_by_base.get(base)
        if gear_slot is None:
            gear_slot, ear_n, finger_n, wrist_n = _gear_slot_key_for_base(
                base, ear_n=ear_n, finger_n=finger_n, wrist_n=wrist_n
            )
            current_key_by_base[base] = gear_slot

        parent_name = parent_name_by_base.get(base)
        if gear_slot not in expected:
            expected[gear_slot] = (wanted, parent_name, parent_id)

        if item.name == "Empty" or item.item_id == 0:
            found[gear_slot] = Type5Aug(
                gear_slot=gear_slot,
                name=None,
                item_id=None,
                dump_slot=wanted,
                parent_name=parent_name,
                parent_id=parent_id,
            )
        else:
            found[gear_slot] = Type5Aug(
                gear_slot=gear_slot,
                name=item.name,
                item_id=item.item_id,
                dump_slot=wanted,
                parent_name=parent_name,
                parent_id=parent_id,
            )

    results: list[Type5Aug] = []
    for gear_slot, (dump_slot, parent_name, parent_id) in expected.items():
        if gear_slot in found:
            results.append(found[gear_slot])
        else:
            results.append(
                Type5Aug(
                    gear_slot=gear_slot,
                    name=None,
                    item_id=None,
                    dump_slot=dump_slot,
                    parent_name=parent_name,
                    parent_id=parent_id,
                )
            )
    return results
