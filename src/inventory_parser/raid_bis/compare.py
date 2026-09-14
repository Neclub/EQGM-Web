"""Score current-expansion raid gear against equipped items using aug weights."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping

from inventory_parser.items import EquippedItem
from inventory_parser.raid_bis.catalog import StatusFn, hydrate_item_ids
from inventory_parser.raid_bis.models import (
    NON_LORE_SLOTS,
    PAPERDOLL_SLOTS,
    PET_FOCUS_CLASSES,
    SCORED_SLOTS,
    UNSCORED_SLOTS,
    RaidGearCandidate,
    RaidVendorCatalog,
    slot_base,
)
from inventory_parser.raid_bis.vendor import vendor_offer_for_item
from inventory_parser.slot2_augs.aug_stats import STAT_DISPLAY, STAT_KEYS
from inventory_parser.slot2_augs.profiles import CLASS_TO_PROFILE, PROFILE_FOCUS_STAT
from inventory_parser.slot2_augs.weights import resolve_weights
from inventory_parser.team_report import CharacterGear

SlotStatus = Literal["empty", "bis", "upgrade", "unknown", "weapon"]

TANK_CLASSES: frozenset[str] = frozenset({"WAR", "PAL", "SHD"})
NO_MANA_CLASSES: frozenset[str] = frozenset({"WAR", "ROG", "MNK", "BER"})

# Best-statted belt per effect/focus; Waist is a personal choice among these.
WAIST_CHOICE_LABELS: tuple[str, ...] = (
    "Overdrive Punch",
    "Treaded Boon of Potential",
    "Crippling Slicer",
)

DELTA_STAT_ORDER: tuple[str, ...] = (
    "ac",
    "hp",
    "mana",
    "endurance",
    "hdex",
    "hint",
    "hwis",
    "hstr",
    "hsta",
    "hagi",
    "hcha",
    "atk",
    "spell_damage",
    "heal_amount",
    "clairvoyance",
)


def score_stats(stats: Mapping[str, int] | None, weights: Mapping[str, float]) -> float:
    data = stats or {}
    total = 0.0
    for key, weight in weights.items():
        total += float(data.get(key, 0)) * float(weight)
    return total


def rank_tuple(
    item: RaidGearCandidate,
    class_abbr: str | None,
    gear_slot: str,
) -> tuple:
    weights = resolve_weights(class_abbr, gear_slot)
    score = score_stats(item.stats, weights)
    hp = int(item.stats.get("hp", 0))
    ac = int(item.stats.get("ac", 0))
    return (-score, -hp, -ac, item.name.casefold())


def legal_for_slot(
    item: RaidGearCandidate,
    *,
    class_abbr: str | None,
    gear_slot: str,
) -> bool:
    return item.fits_class(class_abbr) and item.fits_slot(gear_slot)


def _block_keys(item: RaidGearCandidate) -> set[str]:
    keys = {item.lore_key()}
    if item.item_id > 0:
        keys.add(str(item.item_id))
    return keys


def _equipped_elsewhere_keys(
    slot: str,
    equipped: dict[str, EquippedItem],
    by_id: dict[int, RaidGearCandidate],
) -> set[str]:
    """Lore/item keys already worn in a different slot (wrists may duplicate)."""
    if slot in NON_LORE_SLOTS:
        return set()
    keys: set[str] = set()
    for other, worn in equipped.items():
        if other == slot or other in NON_LORE_SLOTS:
            continue
        if worn is None or worn.item_id <= 0:
            continue
        keys.add(str(worn.item_id))
        known = by_id.get(worn.item_id)
        if known is not None:
            keys.update(_block_keys(known))
    return keys


def _best(
    candidates: list[RaidGearCandidate],
    *,
    class_abbr: str | None,
    gear_slot: str,
    used: set[str],
) -> RaidGearCandidate | None:
    legal = [
        c
        for c in candidates
        if legal_for_slot(c, class_abbr=class_abbr, gear_slot=gear_slot)
        and not (_block_keys(c) & used)
    ]
    if not legal:
        return None
    legal.sort(key=lambda c: rank_tuple(c, class_abbr, gear_slot))
    return legal[0]


def matches_waist_label(item: RaidGearCandidate, label: str) -> bool:
    """True if effect or focus text contains the waist choice label."""
    needle = label.casefold()
    hay = f"{item.effect or ''} {item.focus or ''}".casefold()
    return needle in hay


def waist_choices_for_class(
    catalog: list[RaidGearCandidate],
    *,
    class_abbr: str | None,
    used: set[str] | None = None,
) -> list[tuple[str, RaidGearCandidate]]:
    """Best legal belt per WAIST_CHOICE_LABELS for this class."""
    used = used or set()
    out: list[tuple[str, RaidGearCandidate]] = []
    for label in WAIST_CHOICE_LABELS:
        matches = [c for c in catalog if matches_waist_label(c, label)]
        pick = _best(matches, class_abbr=class_abbr, gear_slot="Waist", used=used)
        if pick is not None:
            out.append((label, pick))
    return out


def _best_waist(
    catalog: list[RaidGearCandidate],
    *,
    class_abbr: str | None,
    used: set[str],
) -> RaidGearCandidate | None:
    """Default Waist BiS: best of the three effect belts, else best waist overall."""
    choices = waist_choices_for_class(catalog, class_abbr=class_abbr, used=used)
    if choices:
        picks = [item for _, item in choices]
        picks.sort(key=lambda c: rank_tuple(c, class_abbr, "Waist"))
        return picks[0]
    return _best(catalog, class_abbr=class_abbr, gear_slot="Waist", used=used)


def build_ideal_loadout(
    catalog: list[RaidGearCandidate],
    *,
    class_abbr: str | None,
    equipped: dict[str, EquippedItem] | None = None,
) -> dict[str, RaidGearCandidate]:
    """Best unique item per scored slot, with MAG/BST/NEC pet-focus ear pinned."""
    equipped = equipped or {}
    used: set[str] = set()
    loadout: dict[str, RaidGearCandidate] = {}
    class_key = (class_abbr or "").strip().upper() or None
    by_id = {c.item_id: c for c in catalog if c.item_id > 0}

    if class_key in PET_FOCUS_CLASSES:
        pin_slot, pin_item = _choose_pet_focus_ear(
            catalog, class_abbr=class_key, equipped=equipped
        )
        if pin_slot and pin_item:
            loadout[pin_slot] = pin_item
            used.update(_block_keys(pin_item))

    for slot in SCORED_SLOTS:
        if slot in loadout:
            continue
        slot_used = (
            set()
            if slot in NON_LORE_SLOTS
            else used | _equipped_elsewhere_keys(slot, equipped, by_id)
        )
        if slot == "Waist":
            pick = _best_waist(catalog, class_abbr=class_key, used=slot_used)
        else:
            pick = _best(catalog, class_abbr=class_key, gear_slot=slot, used=slot_used)
        if pick is None:
            continue
        loadout[slot] = pick
        if slot not in NON_LORE_SLOTS:
            used.update(_block_keys(pick))
    return loadout


def _choose_pet_focus_ear(
    catalog: list[RaidGearCandidate],
    *,
    class_abbr: str,
    equipped: dict[str, EquippedItem],
) -> tuple[str | None, RaidGearCandidate | None]:
    """Highest-EM pet ear; pin on a worn pet-focus ear if any, else Ear-1."""
    ears = [
        c
        for c in catalog
        if c.is_pet_focus_ear()
        and legal_for_slot(c, class_abbr=class_abbr, gear_slot="Ear-1")
    ]
    if not ears:
        return None, None
    ears.sort(key=lambda c: c.pet_focus_rank_tuple())
    best = ears[0]

    worn_slots = []
    for slot in ("Ear-1", "Ear-2"):
        cur = equipped.get(slot)
        if cur is None or cur.item_id <= 0:
            continue
        match = next((c for c in ears if c.item_id == cur.item_id), None)
        if match is None and (
            "summoner" in cur.name.casefold()
            or any(
                c.name.casefold() == cur.name.casefold() and c.is_pet_focus_ear()
                for c in catalog
            )
        ):
            match = next(
                (c for c in catalog if c.item_id == cur.item_id and c.is_pet_focus_ear()),
                None,
            )
        if match is not None or "summoner" in cur.name.casefold():
            worn_slots.append(slot)

    pin_slot = worn_slots[0] if worn_slots else "Ear-1"
    return pin_slot, best


def stat_deltas(
    current: Mapping[str, int] | None,
    recommended: Mapping[str, int] | None,
) -> dict[str, int]:
    left = current or {}
    right = recommended or {}
    keys = [k for k in DELTA_STAT_ORDER if k in STAT_KEYS]
    extra = [k for k in STAT_KEYS if k not in keys]
    out: dict[str, int] = {}
    for key in keys + extra:
        delta = int(right.get(key, 0)) - int(left.get(key, 0))
        if delta:
            out[key] = delta
    return out


def display_delta_keys(class_abbr: str | None) -> tuple[str, ...]:
    """HP, primary HStat; AC for tanks; Mana except WAR/ROG/MNK/BER; Spell Damage for casters."""
    class_key = (class_abbr or "").strip().upper()
    keys: list[str] = []
    if class_key in TANK_CLASSES:
        keys.append("ac")
    keys.append("hp")
    if class_key not in NO_MANA_CLASSES:
        keys.append("mana")
    profile = CLASS_TO_PROFILE.get(class_key)
    if profile:
        keys.append(PROFILE_FOCUS_STAT[profile])
    if profile in {"int", "wis"}:
        keys.append("spell_damage")
    return tuple(keys)


def format_stat_deltas(
    deltas: Mapping[str, int],
    class_abbr: str | None = None,
) -> str:
    parts: list[str] = []
    for key in display_delta_keys(class_abbr):
        if key not in deltas:
            continue
        value = int(deltas[key])
        label = STAT_DISPLAY.get(key, key)
        parts.append(f"{value:+d} {label}")
    return ", ".join(parts)


def sum_deltas(rows: list[dict[str, int]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for row in rows:
        for key, value in row.items():
            totals[key] = totals.get(key, 0) + int(value)
    return {k: v for k, v in totals.items() if v}


@dataclass
class WaistChoice:
    effect_label: str
    item_id: int
    name: str
    tier: str = ""
    icon_id: str | None = None
    deltas: dict[str, int] = field(default_factory=dict)
    status: SlotStatus = "upgrade"
    score_gain: float = 0.0
    vendor_cost: int | None = None
    vendor_item_name: str | None = None
    vendor_item_id: int | None = None


@dataclass
class SlotComparison:
    gear_slot: str
    status: SlotStatus
    current_name: str | None = None
    current_id: int | None = None
    recommended_name: str | None = None
    recommended_id: int | None = None
    recommended_tier: str = ""
    recommended_icon_id: str | None = None
    current_icon_id: str | None = None
    deltas: dict[str, int] = field(default_factory=dict)
    note: str = ""
    # MAG/BST/NEC pet-focus ear: ranked by Enhanced Minion level, not stats.
    pet_focus: bool = False
    scored: bool = True
    choices: list[WaistChoice] = field(default_factory=list)
    score_gain: float = 0.0
    vendor_cost: int | None = None
    vendor_item_name: str | None = None
    vendor_item_id: int | None = None
    current_is_evolver: bool = False


@dataclass
class CharacterRaidBis:
    character: str
    server: str
    class_abbr: str | None
    display_name: str
    persona_key: str
    slots: list[SlotComparison] = field(default_factory=list)
    total_deltas: dict[str, int] = field(default_factory=dict)
    slots_changed: int = 0


def _normalize_icon_id(raw: str | int | None) -> str | None:
    if raw is None:
        return None
    icon_id = str(raw).strip()
    return icon_id or None


def paperdoll_display_name(slot: SlotComparison) -> str | None:
    """Item name the paper doll shows for this slot (empty cells return None)."""
    name = (
        slot.current_name
        if slot.status in ("bis", "weapon")
        else (slot.recommended_name or slot.current_name)
    )
    name = (name or "").strip()
    return name or None


def paperdoll_icon_id(slot: SlotComparison) -> str | None:
    """Icon id the paper doll uses for this slot."""
    raw = (
        slot.current_icon_id
        if slot.status in ("bis", "weapon")
        else (slot.recommended_icon_id or slot.current_icon_id)
    )
    return _normalize_icon_id(raw)


def collect_paperdoll_icon_ids(characters: list[CharacterRaidBis]) -> set[str]:
    """Icon ids needed to render paper-doll cells, including waist choices."""
    ids: set[str] = set()
    for ch in characters:
        for slot in ch.slots:
            for raw in (slot.recommended_icon_id, slot.current_icon_id):
                icon_id = _normalize_icon_id(raw)
                if icon_id:
                    ids.add(icon_id)
            for choice in slot.choices:
                icon_id = _normalize_icon_id(choice.icon_id)
                if icon_id:
                    ids.add(icon_id)
    return ids


def missing_paperdoll_icons(
    characters: list[CharacterRaidBis],
    icon_data_uris: Mapping[str, str] | None = None,
    *,
    require_embedded: bool = True,
) -> list[str]:
    """Occupied paper-doll cells that would render without an icon image."""
    embedded = icon_data_uris or {}
    missing: list[str] = []
    for ch in characters:
        label = (ch.display_name or ch.character or "character").strip()
        by_slot = {s.gear_slot: s for s in ch.slots}
        for slot_name in PAPERDOLL_SLOTS:
            slot = by_slot.get(slot_name)
            if slot is None:
                continue
            name = paperdoll_display_name(slot)
            if not name:
                continue
            icon_id = paperdoll_icon_id(slot)
            if not icon_id:
                missing.append(f"{label} {slot_name}: {name} has no icon id")
            elif require_embedded and icon_id not in embedded:
                missing.append(
                    f"{label} {slot_name}: icon {icon_id} not embedded"
                )
    return missing


def _score_gain(
    current_stats: Mapping[str, int] | None,
    recommended_stats: Mapping[str, int] | None,
    *,
    class_abbr: str | None,
    gear_slot: str,
    status: SlotStatus,
) -> float:
    if status == "bis" or not recommended_stats:
        return 0.0
    weights = resolve_weights(class_abbr, gear_slot)
    return score_stats(recommended_stats, weights) - score_stats(current_stats, weights)


def _pet_focus_score_gain(
    current: RaidGearCandidate | None,
    recommended: RaidGearCandidate,
    *,
    status: SlotStatus,
) -> float:
    """EM level delta for the pinned pet ear (stats are ignored for ranking)."""
    if status == "bis":
        return 0.0
    rec_em = recommended.enhanced_minion_level()
    cur_em = current.enhanced_minion_level() if current is not None else 0
    return float(rec_em - cur_em)


def _vendor_fields(
    item: RaidGearCandidate | None,
    gear_slot: str,
    vendor: RaidVendorCatalog | None,
) -> tuple[int | None, str | None, int | None]:
    offer = vendor_offer_for_item(item, gear_slot, vendor)
    if offer is None:
        return None, None, None
    return offer.cost, offer.name, offer.item_id


def _waist_choice_rows(
    catalog: list[RaidGearCandidate],
    *,
    class_abbr: str | None,
    current_stats: Mapping[str, int],
    current_id: int | None,
    current_empty: bool,
    used: set[str],
    vendor: RaidVendorCatalog | None = None,
) -> list[WaistChoice]:
    rows: list[WaistChoice] = []
    for label, item in waist_choices_for_class(
        catalog, class_abbr=class_abbr, used=used
    ):
        if current_empty:
            status: SlotStatus = "empty"
            deltas = stat_deltas(current_stats, item.stats)
        elif current_id is not None and current_id == item.item_id:
            status = "bis"
            deltas = {}
        else:
            status = "upgrade"
            deltas = stat_deltas(current_stats, item.stats)
        cost, vendor_name, vendor_id = _vendor_fields(item, "Waist", vendor)
        rows.append(
            WaistChoice(
                effect_label=label,
                item_id=item.item_id,
                name=item.name,
                tier=item.tier,
                icon_id=item.icon_id,
                deltas=deltas,
                status=status,
                score_gain=_score_gain(
                    current_stats,
                    item.stats,
                    class_abbr=class_abbr,
                    gear_slot="Waist",
                    status=status,
                ),
                vendor_cost=cost,
                vendor_item_name=vendor_name,
                vendor_item_id=vendor_id,
            )
        )
    return rows


def compare_character(
    character: CharacterGear,
    catalog: list[RaidGearCandidate],
    *,
    equipped_stats: dict[int, RaidGearCandidate] | None = None,
    vendor: RaidVendorCatalog | None = None,
) -> CharacterRaidBis:
    equipped_stats = equipped_stats or {}
    class_abbr = (character.class_abbr or "").strip().upper() or None
    loadout = build_ideal_loadout(
        catalog, class_abbr=class_abbr, equipped=character.slots
    )
    by_id = {c.item_id: c for c in catalog if c.item_id > 0}
    rows: list[SlotComparison] = []
    delta_rows: list[dict[str, int]] = []
    changed = 0

    for slot in PAPERDOLL_SLOTS:
        current = character.slots.get(slot)
        if slot in UNSCORED_SLOTS:
            note = (
                "Power Source is not scored."
                if slot == "Power Source"
                else "Weapons are not scored yet."
            )
            current_icon = None
            if current and current.item_id > 0:
                known = by_id.get(current.item_id) or equipped_stats.get(current.item_id)
                if known:
                    current_icon = known.icon_id
            rows.append(
                SlotComparison(
                    gear_slot=slot,
                    status="weapon",
                    current_name=current.name if current else None,
                    current_id=current.item_id if current else None,
                    current_icon_id=current_icon,
                    note=note,
                    scored=False,
                    current_is_evolver=bool(current and current.is_evolver),
                )
            )
            continue

        recommended = loadout.get(slot)
        current_stats: dict[str, int] = {}
        current_icon = None
        current_known: RaidGearCandidate | None = None
        if current and current.item_id > 0:
            known = by_id.get(current.item_id) or equipped_stats.get(current.item_id)
            if known:
                current_known = known
                current_stats = dict(known.stats)
                current_icon = known.icon_id

        rec_stats = dict(recommended.stats) if recommended else {}
        deltas = stat_deltas(current_stats, rec_stats) if recommended else {}
        pet_focus = bool(
            class_abbr in PET_FOCUS_CLASSES
            and recommended
            and recommended.is_pet_focus_ear()
            and slot_base(slot) == "Ear"
        )

        waist_rows: list[WaistChoice] = []
        if slot == "Waist":
            waist_used = _equipped_elsewhere_keys(slot, character.slots, by_id)
            waist_rows = _waist_choice_rows(
                catalog,
                class_abbr=class_abbr,
                current_stats=current_stats,
                current_id=current.item_id if current and current.item_id > 0 else None,
                current_empty=current is None or current.item_id <= 0,
                used=waist_used,
                vendor=vendor,
            )

        if recommended is None:
            status: SlotStatus = "unknown"
            note = "No current-expansion raid item found for this slot/class."
        elif current is None or current.item_id <= 0:
            status = "empty"
            note = "No item equipped."
            changed += 1
            delta_rows.append(deltas)
        elif current.item_id == recommended.item_id:
            status = "bis"
            note = "Already best in slot."
            deltas = {}
        else:
            status = "upgrade"
            note = ""
            changed += 1
            delta_rows.append(deltas)

        if pet_focus:
            note = (note + " " if note else "") + "Required pet focus."
        if slot == "Waist" and waist_rows:
            note = (
                (note + " " if note else "")
                + "Waist is a personal choice among Overdrive Punch, "
                "Treaded Boon of Potential, and Crippling Slicer."
            ).strip()

        if pet_focus and recommended is not None:
            gain = _pet_focus_score_gain(
                current_known, recommended, status=status
            )
        else:
            gain = _score_gain(
                current_stats,
                rec_stats,
                class_abbr=class_abbr,
                gear_slot=slot,
                status=status,
            )

        cost, vendor_name, vendor_id = _vendor_fields(recommended, slot, vendor)
        rows.append(
            SlotComparison(
                gear_slot=slot,
                status=status,
                current_name=current.name if current else None,
                current_id=current.item_id if current else None,
                recommended_name=recommended.name if recommended else None,
                recommended_id=recommended.item_id if recommended else None,
                recommended_tier=recommended.tier if recommended else "",
                recommended_icon_id=recommended.icon_id if recommended else None,
                current_icon_id=current_icon,
                deltas=deltas,
                note=note.strip(),
                pet_focus=pet_focus,
                scored=True,
                choices=waist_rows,
                score_gain=gain,
                vendor_cost=cost,
                vendor_item_name=vendor_name,
                vendor_item_id=vendor_id,
                current_is_evolver=bool(current and current.is_evolver),
            )
        )

    return CharacterRaidBis(
        character=character.character,
        server=character.server,
        class_abbr=class_abbr,
        display_name=character.display_name,
        persona_key=character.persona_key,
        slots=rows,
        total_deltas=sum_deltas(delta_rows),
        slots_changed=changed,
    )


def resolve_equipped_stats(
    characters: list[CharacterGear],
    catalog: list[RaidGearCandidate],
    *,
    item_html_by_id: dict[int, str] | None = None,
    allow_network: bool = True,
    on_status: StatusFn | None = None,
) -> dict[int, RaidGearCandidate]:
    known = {c.item_id for c in catalog if c.item_id > 0}
    needed: list[int] = []
    for ch in characters:
        for item in ch.slots.values():
            if item.item_id > 0 and item.item_id not in known:
                needed.append(item.item_id)
    if not needed:
        return {}
    return hydrate_item_ids(
        needed,
        item_html_by_id=item_html_by_id,
        allow_network=allow_network,
        on_status=on_status,
    )
