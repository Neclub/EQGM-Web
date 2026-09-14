"""Compare equipped type 7/8 augs against raidloot BiS as a whole loadout."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Literal

from inventory_parser.slot2_augs.aug_stats import STAT_DISPLAY
from inventory_parser.slot2_augs.craft_components import craft_component_for_aug, owns_craft_component
from inventory_parser.slot2_augs.eqresource_augs import resolve_eqresource_augs
from inventory_parser.parser import (
    InventoryData,
    Slot2Aug,
    collect_owned_item_ids,
    collect_owned_item_names,
    extract_slot2_augs,
    parent_name_is_shield,
)
from inventory_parser.slot2_augs.profiles import (
    ARTISANS_PRIZE_ID,
    ARTISANS_PRIZE_NAME,
    PROFILE_FOCUS_LABEL,
    PROFILE_FOCUS_STAT,
    VELIUM_FREEZING_GEM_ALLOWED_BASES,
    VELIUM_FREEZING_GEM_ID,
    VELIUM_FREEZING_GEM_NAME,
    ProfileId,
)
from inventory_parser.slot2_augs.raidloot import AugCandidate, CatalogResult, augs_for_slot, is_type78_aug
from inventory_parser.slots import (
    EAR_REPORT_SLOTS,
    TEAM_GEAR_SLOTS,
    aug_assignment_order,
    priority_aug_slots,
)
from inventory_parser.slot2_augs.weights import (
    rank_key,
    resolve_weights,
    score_aug,
    uses_feet_overlay,
)

SlotStatus = Literal["empty", "bis", "upgrade", "unknown", "no_fit"]

# Rows included in HTML/Excel reports. Ignored weapon slots (`no_fit`) are omitted.
REPORT_ROW_STATUSES: frozenset[str] = frozenset(
    {"upgrade", "empty", "unknown", "bis"}
)

# Statuses that show a non-blank Upgrade-to recommendation.
NEEDS_UPGRADE_STATUSES: frozenset[str] = frozenset({"upgrade", "empty", "unknown"})


def owns_artisans_prize(data: InventoryData) -> bool:
    """True when Artisan's Prize appears anywhere in the inventory dump."""
    if ARTISANS_PRIZE_ID in collect_owned_item_ids(data):
        return True
    return ARTISANS_PRIZE_NAME.casefold() in collect_owned_item_names(data)


def is_velium_freezing_gem(*, item_id: int | None = None, name: str | None = None) -> bool:
    if item_id is not None and item_id == VELIUM_FREEZING_GEM_ID:
        return True
    return (name or "").casefold() == VELIUM_FREEZING_GEM_NAME.casefold()

# Keys rolled into the "if all suggested augs equipped" summary.
SUMMARY_STAT_KEYS: tuple[str, ...] = (
    "focus",
    "ac",
    "hp",
    "atk",
    "heal_amount",
    "spell_damage",
    "clairvoyance",
)


@dataclass(frozen=True)
class Slot2Comparison:
    gear_slot: str
    current_name: str | None
    current_id: int | None
    recommended_name: str | None
    recommended_id: int | None
    recommended_focus: int | None
    status: SlotStatus
    note: str = ""
    recommended_owned: bool | None = None
    recommended_expansion: str | None = None
    move_from_slot: str | None = None
    stat_deltas: dict[str, int] | None = None
    # When Need to farm: known empower component (Focus / ore), if any.
    craft_component_name: str | None = None
    craft_component_id: int | None = None
    craft_component_owned: bool | None = None


@dataclass(frozen=True)
class FarmListEntry:
    character: str
    server: str
    persona_key: str
    gear_slot: str
    name: str
    item_id: int
    expansion: str | None = None
    craft_component_name: str | None = None
    craft_component_id: int | None = None
    craft_component_owned: bool | None = None


@dataclass
class CharacterSlot2Report:
    character: str
    server: str
    class_abbr: str | None
    profile: ProfileId
    filepath: str
    comparisons: list[Slot2Comparison]
    owned_item_ids: set[int] = field(default_factory=set)
    slots_changed: int = 0
    stat_summary: dict[str, int] = field(default_factory=dict)


def _is_ear_slot(gear_slot: str) -> bool:
    return gear_slot in EAR_REPORT_SLOTS or gear_slot.startswith("Ear")


def _is_feet_slot(gear_slot: str) -> bool:
    return gear_slot == "Feet"


def _is_secondary_shield(gear_slot: str, parent_name: str | None) -> bool:
    return gear_slot == "Secondary" and parent_name_is_shield(parent_name)


def _weapon_slot_skip_note(gear_slot: str, parent_name: str | None) -> str | None:
    """Primary always skipped; Secondary skipped unless parent is a shield."""
    if gear_slot == "Primary":
        return "Primary weapons ignored"
    if gear_slot == "Secondary" and not parent_name_is_shield(parent_name):
        return "Secondary weapons ignored (shield Secondary only)"
    return None


def _sort_key_for_slot(
    gear_slot: str,
    class_abbr: str | None,
    *,
    secondary_is_shield: bool = False,
    profile: ProfileId | None = None,
):
    def _key(a: AugCandidate):
        return rank_key(
            a,
            class_abbr,
            gear_slot,
            secondary_is_shield=secondary_is_shield,
            profile=profile or a.profile,
        )

    return _key


def _aug_rank_tuple(
    aug: AugCandidate,
    gear_slot: str,
    class_abbr: str | None,
    *,
    secondary_is_shield: bool = False,
    profile: ProfileId | None = None,
    peer: AugCandidate | None = None,
) -> tuple:
    """
    Sort key for one aug.

    When ``peer`` is set (upgrade vs current), drop Attack-adjacent combat weights
    that only one side has populated — raidloot list rows often omit Heal /
    Spell Damage / Clairvoyance while EQ Resource lookups include them.
    """
    from inventory_parser.slot2_augs.weights import resolve_weights, score_aug

    weights = resolve_weights(
        class_abbr,
        gear_slot,
        secondary_is_shield=secondary_is_shield,
        profile=profile or aug.profile,
    )
    if peer is not None:
        left = aug.effective_stats()
        right = peer.effective_stats()
        for key in ("heal_amount", "spell_damage", "clairvoyance"):
            if not left.get(key) or not right.get(key):
                weights.pop(key, None)
        score = score_aug(aug, weights)
        return (-score, -aug.hp, -aug.ac, aug.name.casefold())
    return rank_key(
        aug,
        class_abbr,
        gear_slot,
        secondary_is_shield=secondary_is_shield,
        profile=profile or aug.profile,
    )


def _uses_ac_primary(
    gear_slot: str,
    class_abbr: str | None,
    *,
    secondary_is_shield: bool = False,
) -> bool:
    if secondary_is_shield and gear_slot == "Secondary":
        return True
    if _is_feet_slot(gear_slot) and uses_feet_overlay(class_abbr):
        return True
    return False


def _signed_stat(delta: int) -> str:
    return f"+{delta}" if delta >= 0 else str(delta)


def slot_stat_deltas(
    current_aug: AugCandidate | None,
    recommended: AugCandidate,
    profile: ProfileId = "dex",
) -> dict[str, int]:
    """Raw (recommended − current) for summary stats. Empty current → zeros."""
    cur = current_aug.effective_stats() if current_aug is not None else {}
    rec = recommended.effective_stats()
    focus_key = PROFILE_FOCUS_STAT.get(profile, "hdex")

    def _int(stats: dict[str, int], key: str) -> int:
        if key == "focus":
            return int(stats.get(focus_key, 0))
        return int(stats.get(key, 0))

    return {key: _int(rec, key) - _int(cur, key) for key in SUMMARY_STAT_KEYS}


def summarize_stat_deltas(
    comparisons: list[Slot2Comparison],
) -> tuple[dict[str, int], int]:
    """Sum per-slot stat_deltas; return (totals, slots_changed)."""
    totals = {key: 0 for key in SUMMARY_STAT_KEYS}
    changed = 0
    for cmp_ in comparisons:
        if not cmp_.stat_deltas:
            continue
        changed += 1
        for key in SUMMARY_STAT_KEYS:
            totals[key] += int(cmp_.stat_deltas.get(key, 0))
    return totals, changed


def upgrade_stat_delta_note(
    current_aug: AugCandidate | None,
    recommended: AugCandidate,
    gear_slot: str,
    class_abbr: str | None,
    *,
    secondary_is_shield: bool = False,
    profile: ProfileId = "dex",
) -> str:
    """Format score plus Spell Damage / heroic / AC / HP gains."""
    weights = resolve_weights(
        class_abbr,
        gear_slot,
        secondary_is_shield=secondary_is_shield,
        profile=profile,
    )
    cur_score = score_aug(current_aug, weights) if current_aug else 0.0
    rec_score = score_aug(recommended, weights)
    d_score = rec_score - cur_score

    cur_stats = current_aug.effective_stats() if current_aug else {}
    rec_stats = recommended.effective_stats()
    d_sd = int(rec_stats.get("spell_damage", 0)) - int(cur_stats.get("spell_damage", 0))

    cur_focus = current_aug.focus_heroic if current_aug else 0
    cur_ac = current_aug.ac if current_aug else 0
    cur_hp = current_aug.hp if current_aug else 0
    d_focus = recommended.focus_heroic - cur_focus
    d_ac = recommended.ac - cur_ac
    d_hp = recommended.hp - cur_hp
    focus_label = PROFILE_FOCUS_LABEL.get(profile, "HDex")
    sd_label = STAT_DISPLAY.get("spell_damage", "Spell Damage")

    parts: list[str] = [f"{_signed_stat(int(round(d_score)))} score"]

    if _uses_ac_primary(
        gear_slot, class_abbr, secondary_is_shield=secondary_is_shield
    ):
        parts.append(f"{_signed_stat(d_ac)} AC")
        if d_hp:
            parts.append(f"{_signed_stat(d_hp)} HP")
        if d_focus:
            parts.append(f"{_signed_stat(d_focus)} {focus_label}")
        if d_sd:
            parts.append(f"{_signed_stat(d_sd)} {sd_label}")
    else:
        if d_sd:
            parts.append(f"{_signed_stat(d_sd)} {sd_label}")
        parts.append(f"{_signed_stat(d_focus)} {focus_label}")
        if d_hp:
            parts.append(f"{_signed_stat(d_hp)} HP")
        if d_ac:
            parts.append(f"{_signed_stat(d_ac)} AC")
    return ", ".join(parts)


def _normalize_freezing_gem(aug: AugCandidate) -> AugCandidate:
    return replace(
        aug,
        item_id=VELIUM_FREEZING_GEM_ID,
        name=aug.name or VELIUM_FREEZING_GEM_NAME,
        allowed_bases=VELIUM_FREEZING_GEM_ALLOWED_BASES,
        excluded_bases=frozenset(),
        ear_only=False,
        shield_only=False,
        aug_types=aug.aug_types or frozenset({7, 8}),
        slot_text=(
            "Arms, Back, Charm, Chest, Ear, Face, Feet, Finger, Hands, "
            "Head, Legs, Neck, Range, Shoulder, Waist, Wrist"
        ),
    )


def _freezing_gem_candidate(
    catalog: list[AugCandidate],
    *,
    profile: ProfileId | None = None,
) -> AugCandidate:
    found = next((a for a in catalog if is_velium_freezing_gem(item_id=a.item_id, name=a.name)), None)
    if found is not None:
        return _normalize_freezing_gem(found)
    used: ProfileId = profile or (catalog[0].profile if catalog else "dex")
    return _normalize_freezing_gem(
        AugCandidate(
            item_id=VELIUM_FREEZING_GEM_ID,
            name=VELIUM_FREEZING_GEM_NAME,
            profile=used,
            focus_heroic=0,
            lore=True,
            stats={},
            aug_types=frozenset({7, 8}),
        )
    )


def _equipped_freezing_gem_slot(
    current_by_slot: dict[str, Slot2Aug],
) -> str | None:
    for slot, cur in current_by_slot.items():
        if cur is None:
            continue
        if is_velium_freezing_gem(item_id=cur.item_id, name=cur.name):
            return slot
    return None


def _loadout_score(
    assigned: dict[str, AugCandidate | None],
    class_abbr: str | None,
    *,
    shield_secondary: bool = False,
) -> float:
    total = 0.0
    for slot, aug in assigned.items():
        if aug is None:
            continue
        skip = _weapon_slot_skip_note(slot, None)
        if skip is not None and not (slot == "Secondary" and shield_secondary):
            continue
        weights = resolve_weights(
            class_abbr,
            slot,
            secondary_is_shield=shield_secondary and slot == "Secondary",
            profile=aug.profile,
        )
        total += score_aug(aug, weights)
    return total


def _choose_freezing_gem_slot(
    gem: AugCandidate,
    gear_slots: list[str],
    catalog: list[AugCandidate],
    *,
    artisans_prize_owned: bool,
    class_abbr: str | None,
    shield_secondary: bool,
    current_slot: str | None,
) -> str | None:
    """Pick the legal hole that maximizes remaining loadout score with the gem pinned."""
    order = _slot_order(gear_slots, class_abbr)
    eligible = [
        slot
        for slot in order
        if gem.fits_gear_slot(slot)
        and not (
            _weapon_slot_skip_note(slot, None) is not None
            and not (slot == "Secondary" and shield_secondary)
        )
    ]
    if not eligible:
        return None
    if current_slot in eligible and len(eligible) == 1:
        return current_slot

    best_slot: str | None = None
    best_score: float | None = None
    for slot in eligible:
        pinned = build_ideal_loadout(
            gear_slots,
            catalog,
            artisans_prize_owned=artisans_prize_owned,
            class_abbr=class_abbr,
            shield_secondary=shield_secondary,
            pinned={slot: gem},
        )
        score = _loadout_score(
            pinned, class_abbr, shield_secondary=shield_secondary
        )
        if best_score is None or score > best_score + 1e-6:
            best_score = score
            best_slot = slot
        elif best_score is not None and abs(score - best_score) <= 1e-6:
            if slot == current_slot:
                best_slot = slot
    return best_slot


def _prize_candidate(catalog: list[AugCandidate]) -> AugCandidate:
    prize = next((a for a in catalog if a.item_id == ARTISANS_PRIZE_ID), None)
    if prize is not None:
        return prize
    from inventory_parser.slot2_augs.aug_stats import artisans_prize_stats, legacy_from_stats

    profile: ProfileId = catalog[0].profile if catalog else "dex"
    stats = artisans_prize_stats()
    focus, ac, hp, atk = legacy_from_stats(stats, profile)
    return AugCandidate(
        item_id=ARTISANS_PRIZE_ID,
        name=ARTISANS_PRIZE_NAME,
        profile=profile,
        focus_heroic=focus or 150,
        ac=ac,
        hp=hp,
        atk=atk,
        slot_text="Ear",
        allowed_bases=frozenset({"Ear"}),
        ear_only=True,
        lore=True,
        stats=stats,
    )


def _current_matches_aug(current: Slot2Aug, aug: AugCandidate) -> bool:
    if current.item_id is not None and current.item_id == aug.item_id:
        return True
    if current.name and current.name.casefold() == aug.name.casefold():
        return True
    return False


def _catalog_aug_for_id(
    catalog: list[AugCandidate], item_id: int | None
) -> AugCandidate | None:
    if item_id is None:
        return None
    return next((a for a in catalog if a.item_id == item_id), None)


def _expand_unavailable(
    catalog: list[AugCandidate],
    unavailable_ids: set[int] | None,
) -> set[int]:
    """Block claimed item ids and every catalog sibling in the same lore group."""
    blocked = set(unavailable_ids or ())
    if not blocked:
        return blocked
    groups: set[str] = set()
    by_id = {a.item_id: a for a in catalog}
    for iid in blocked:
        aug = by_id.get(iid)
        if aug is not None:
            key = aug.lore_group_key()
            if key:
                groups.add(key)
        groups.add(str(iid))
    extra: set[int] = set()
    for a in catalog:
        key = a.lore_group_key()
        if key and key in groups:
            extra.add(a.item_id)
            if key.isdigit():
                extra.add(int(key))
    for g in groups:
        if g.isdigit():
            extra.add(int(g))
    return blocked | extra


def _claim_item(
    claimed: set[int],
    item_id: int | None,
    catalog: list[AugCandidate],
) -> None:
    if not item_id:
        return
    claimed.add(item_id)
    claimed.update(_expand_unavailable(catalog, claimed))


def _lookup_current_aug(
    catalog: list[AugCandidate],
    item_id: int | None,
    *,
    external_augs: dict[int, AugCandidate] | None = None,
) -> AugCandidate | None:
    found = _catalog_aug_for_id(catalog, item_id)
    if found is not None:
        return found
    if item_id is None or not external_augs:
        return None
    return external_augs.get(item_id)


def pick_best_for_slot(
    gear_slot: str,
    catalog: list[AugCandidate],
    *,
    unavailable_ids: set[int],
    artisans_prize_owned: bool,
    class_abbr: str | None = None,
    secondary_is_shield: bool = False,
) -> AugCandidate | None:
    """Best aug for one slot, skipping unavailable item ids and lore-group siblings."""
    if gear_slot == "Primary":
        return None
    if gear_slot == "Secondary" and not secondary_is_shield:
        return None

    blocked = _expand_unavailable(catalog, unavailable_ids)

    if artisans_prize_owned and _is_ear_slot(gear_slot):
        prize = _prize_candidate(catalog)
        if prize.item_id not in blocked:
            return prize

    fitted = [
        a
        for a in augs_for_slot(catalog, gear_slot)
        if a.item_id != ARTISANS_PRIZE_ID
        and a.item_id not in blocked
        and is_type78_aug(a)
    ]
    if gear_slot == "Secondary" and secondary_is_shield:
        fitted = [a for a in fitted if a.shield_only]
    else:
        fitted = [a for a in fitted if not a.shield_only]

    if not fitted:
        return None
    fitted.sort(
        key=_sort_key_for_slot(
            gear_slot, class_abbr, secondary_is_shield=secondary_is_shield
        )
    )
    return fitted[0]


def recommend_for_slot(
    gear_slot: str,
    catalog: list[AugCandidate],
    *,
    artisans_prize_owned: bool,
    class_abbr: str | None = None,
    used_lore_ids: set[int] | None = None,
    unavailable_ids: set[int] | None = None,
    secondary_is_shield: bool = False,
) -> AugCandidate | None:
    """Pick the best type 7/8 aug for a gear slot (optional exclusions)."""
    blocked = set(unavailable_ids or ())
    if used_lore_ids:
        blocked |= set(used_lore_ids)
    return pick_best_for_slot(
        gear_slot,
        catalog,
        unavailable_ids=blocked,
        artisans_prize_owned=artisans_prize_owned,
        class_abbr=class_abbr,
        secondary_is_shield=secondary_is_shield,
    )


def _slot_order(gear_slots: list[str], class_abbr: str | None = None) -> list[str]:
    present = set(gear_slots)
    order = [s for s in aug_assignment_order(class_abbr) if s in present]
    for slot in gear_slots:
        if slot not in order:
            order.append(slot)
    return order


def build_ideal_loadout(
    gear_slots: list[str],
    catalog: list[AugCandidate],
    *,
    artisans_prize_owned: bool,
    class_abbr: str | None = None,
    shield_secondary: bool = False,
    pinned: dict[str, AugCandidate] | None = None,
) -> dict[str, AugCandidate | None]:
    """Absolute BiS unique assignment ignoring what is currently equipped."""
    order = _slot_order(gear_slots, class_abbr)
    unavailable: set[int] = set()
    ideal: dict[str, AugCandidate | None] = {}

    for slot, aug in (pinned or {}).items():
        if slot not in order:
            continue
        ideal[slot] = aug
        _claim_item(unavailable, aug.item_id, catalog)

    # Empty-first is irrelevant with no currents; use report order.
    # Prefer putting Artisan's Prize on an Ear when owned.
    if artisans_prize_owned:
        for slot in order:
            if slot in ideal:
                continue
            if not _is_ear_slot(slot):
                continue
            prize = _prize_candidate(catalog)
            if prize.item_id in unavailable:
                break
            ideal[slot] = prize
            _claim_item(unavailable, prize.item_id, catalog)
            break

    for slot in order:
        if slot in ideal:
            continue
        pick = pick_best_for_slot(
            slot,
            catalog,
            unavailable_ids=unavailable,
            artisans_prize_owned=False,  # prize already placed if owned
            class_abbr=class_abbr,
            secondary_is_shield=shield_secondary and slot == "Secondary",
        )
        ideal[slot] = pick
        if pick is not None:
            _claim_item(unavailable, pick.item_id, catalog)
    return ideal


def assign_slot_recommendations(
    gear_slots: list[str],
    catalog: list[AugCandidate],
    *,
    artisans_prize_owned: bool,
    class_abbr: str | None = None,
    shield_secondary: bool = False,
    current_by_slot: dict[str, Slot2Aug] | None = None,
) -> dict[str, AugCandidate | None]:
    """
    Recommend only ideal BiS augs the character is missing.

    1. Build the ideal unique loadout (Range/Charm/Feet-when-needed first).
       An equipped Velium Empowered Gem of Freezing is pinned first to the
       legal slot that maximizes remaining weighted loadout score.
    2. Priority slots pull their ideal aug even when it is currently equipped
       in another slot (suggest a move). Priority = the freezing-gem pin
       (when worn), then Range, Charm, and Feet when the high-AC overlay
       applies — few augs fit those holes.
    3. Other slots claim their ideal only when it sits on a priority slot that
       does not need it (displaced piece moves into the general pool).
    4. General slots keep any equipped ideal-loadout piece (no general↔general
       reshuffle); the best owned/farmable set matters more than exact homes.
    5. Remaining missing ideal augs fill empty holes first, then non-ideal
       currents — priority slots before general slots.
    6. Never recommend an aug worse than the slot's current (by slot rank key).
    """
    current_by_slot = current_by_slot or {}
    order = _slot_order(gear_slots, class_abbr)
    priority_slots = tuple(s for s in priority_aug_slots(class_abbr) if s in order)

    gem_slot = _equipped_freezing_gem_slot(current_by_slot)
    pinned: dict[str, AugCandidate] | None = None
    if gem_slot is not None:
        gem = _freezing_gem_candidate(catalog)
        pin = _choose_freezing_gem_slot(
            gem,
            gear_slots,
            catalog,
            artisans_prize_owned=artisans_prize_owned,
            class_abbr=class_abbr,
            shield_secondary=shield_secondary,
            current_slot=gem_slot,
        )
        if pin is not None:
            pinned = {pin: gem}
            if pin not in priority_slots:
                priority_slots = (pin,) + priority_slots
            elif pin != priority_slots[0]:
                priority_slots = (pin,) + tuple(s for s in priority_slots if s != pin)
    priority = set(priority_slots)

    ideal = build_ideal_loadout(
        gear_slots,
        catalog,
        artisans_prize_owned=artisans_prize_owned,
        class_abbr=class_abbr,
        shield_secondary=shield_secondary,
        pinned=pinned,
    )
    ideal_ids = {a.item_id for a in ideal.values() if a is not None}

    equipped_ids = {
        cur.item_id
        for cur in current_by_slot.values()
        if cur is not None and cur.item_id is not None and cur.item_id > 0
    }
    owned_ideal_ids = ideal_ids & equipped_ids
    missing_ideal = [
        aug
        for aug in ideal.values()
        if aug is not None and aug.item_id not in owned_ideal_ids
    ]
    missing_ideal.sort(
        key=lambda a: rank_key(a, class_abbr, "Head", profile=a.profile)
    )

    assigned: dict[str, AugCandidate | None] = {}
    claimed_ids: set[int] = set()

    def _equipped_slot_for(item_id: int) -> str | None:
        for other, cur in current_by_slot.items():
            if cur is not None and cur.item_id == item_id:
                return other
        return None

    # Priority slots claim their ideal BiS, including moves from other slots.
    for slot in priority_slots:
        ideal_aug = ideal.get(slot)
        if ideal_aug is None:
            continue
        cur = current_by_slot.get(slot)
        if cur is not None and cur.item_id == ideal_aug.item_id:
            assigned[slot] = ideal_aug
            _claim_item(claimed_ids, ideal_aug.item_id, catalog)
            continue
        source = _equipped_slot_for(ideal_aug.item_id)
        if source is not None:
            assigned[slot] = ideal_aug
            _claim_item(claimed_ids, ideal_aug.item_id, catalog)

    # Non-priority slots claim their ideal when it sits on a priority slot and
    # that priority slot does not need it as its own ideal (displaced piece
    # moves into the general pool).
    for slot in order:
        if slot in assigned or slot in priority:
            continue
        ideal_aug = ideal.get(slot)
        if ideal_aug is None or ideal_aug.item_id in claimed_ids:
            continue
        source = _equipped_slot_for(ideal_aug.item_id)
        if source is None or source == slot:
            continue
        if source not in priority:
            continue
        source_ideal = ideal.get(source)
        # Do not steal a piece that is the source slot's own ideal.
        if source_ideal is not None and source_ideal.item_id == ideal_aug.item_id:
            continue
        assigned[slot] = ideal_aug
        _claim_item(claimed_ids, ideal_aug.item_id, catalog)

    # Keep ideal-loadout pieces where they already sit on general slots —
    # except priority slots holding a non-ideal piece (those stay free for
    # their constrained BiS).
    for slot in order:
        if slot in assigned:
            continue
        cur = current_by_slot.get(slot)
        if cur is None or cur.item_id is None:
            continue
        if cur.item_id not in ideal_ids or cur.item_id in claimed_ids:
            continue
        slot_ideal = ideal.get(slot)
        if slot in priority and (
            slot_ideal is None or cur.item_id != slot_ideal.item_id
        ):
            continue
        keep = _catalog_aug_for_id(catalog, cur.item_id) or slot_ideal
        if keep is None:
            keep = next(
                (a for a in ideal.values() if a and a.item_id == cur.item_id),
                None,
            )
        assigned[slot] = keep
        if keep is not None:
            _claim_item(claimed_ids, keep.item_id, catalog)

    owned_ideal_ids |= claimed_ids

    # Place missing ideal augs into needy slots (priority → empty → rest).
    needy = [s for s in order if s not in assigned]
    needy.sort(
        key=lambda s: (
            0 if s in priority else 1,
            0
            if (current_by_slot.get(s) is None or current_by_slot[s].item_id is None)
            else 1,
            order.index(s),
        )
    )

    still_missing = [a for a in missing_ideal if a.item_id not in claimed_ids]
    used_missing: set[int] = set()

    for slot in needy:
        secondary = shield_secondary and slot == "Secondary"
        cur = current_by_slot.get(slot)
        placed: AugCandidate | None = None
        for aug in still_missing:
            if aug.item_id in used_missing or aug.item_id in claimed_ids:
                continue
            if not aug.fits_gear_slot(slot):
                continue
            if secondary and not aug.shield_only:
                continue
            if not secondary and aug.shield_only:
                continue
            if aug.item_id == ARTISANS_PRIZE_ID and not artisans_prize_owned:
                continue
            if not is_type78_aug(aug):
                continue
            if cur is not None and cur.item_id is not None:
                cur_aug = _catalog_aug_for_id(catalog, cur.item_id)
                if cur_aug is not None:
                    if _aug_rank_tuple(
                        aug,
                        slot,
                        class_abbr,
                        secondary_is_shield=secondary,
                        peer=cur_aug,
                    ) > _aug_rank_tuple(
                        cur_aug,
                        slot,
                        class_abbr,
                        secondary_is_shield=secondary,
                        peer=aug,
                    ):
                        continue
            placed = aug
            break

        if placed is not None:
            assigned[slot] = placed
            used_missing.add(placed.item_id)
            _claim_item(claimed_ids, placed.item_id, catalog)
        elif cur is not None and cur.item_id is not None:
            if cur.item_id in claimed_ids:
                # Current was moved elsewhere — recommend next best free pick.
                assigned[slot] = pick_best_for_slot(
                    slot,
                    catalog,
                    unavailable_ids=set(claimed_ids),
                    artisans_prize_owned=artisans_prize_owned,
                    class_abbr=class_abbr,
                    secondary_is_shield=secondary,
                )
                replacement = assigned[slot]
                if replacement is not None:
                    _claim_item(claimed_ids, replacement.item_id, catalog)
            else:
                keep_cur = _catalog_aug_for_id(catalog, cur.item_id)
                if keep_cur is not None and is_type78_aug(keep_cur):
                    assigned[slot] = keep_cur
                else:
                    assigned[slot] = pick_best_for_slot(
                        slot,
                        catalog,
                        unavailable_ids=set(claimed_ids),
                        artisans_prize_owned=artisans_prize_owned,
                        class_abbr=class_abbr,
                        secondary_is_shield=secondary,
                    )
                    replacement = assigned[slot]
                    if replacement is not None:
                        _claim_item(claimed_ids, replacement.item_id, catalog)
        else:
            assigned[slot] = None

    return assigned


def classify_status(
    current: Slot2Aug,
    recommended: AugCandidate | None,
) -> tuple[SlotStatus, str]:
    skip = _weapon_slot_skip_note(current.gear_slot, current.parent_name)
    if skip is not None:
        return "no_fit", skip

    if current.name is None or current.item_id is None:
        if recommended is None:
            return "no_fit", "Empty; no type 7/8 aug fits this slot"
        return "empty", "Empty Slot2"

    if recommended is None:
        return "no_fit", "Current aug present; no catalog aug fits this slot"

    if current.item_id == recommended.item_id or (
        current.name.casefold() == recommended.name.casefold()
    ):
        return "bis", "Matches recommended"

    if current.item_id == ARTISANS_PRIZE_ID and _is_ear_slot(current.gear_slot):
        return "bis", "Artisan's Prize (Ear BiS)"

    if is_velium_freezing_gem(item_id=current.item_id, name=current.name) and (
        recommended.item_id == VELIUM_FREEZING_GEM_ID
        or is_velium_freezing_gem(name=recommended.name)
    ):
        return "bis", "Must-have Velium Empowered Gem of Freezing"

    return "upgrade", f"Recommended: {recommended.name}"


def _finalize_comparison(
    current: Slot2Aug,
    recommended: AugCandidate | None,
    catalog: list[AugCandidate],
    class_abbr: str | None,
    *,
    profile: ProfileId = "dex",
    move_from_slot: str | None = None,
    moved_to_slot: str | None = None,
    external_augs: dict[int, AugCandidate] | None = None,
    owned_item_ids: set[int] | None = None,
    owned_item_names: set[str] | None = None,
) -> Slot2Comparison:
    status, note = classify_status(current, recommended)
    secondary = _is_secondary_shield(current.gear_slot, current.parent_name)
    cur_aug = _lookup_current_aug(
        catalog, current.item_id, external_augs=external_augs
    )

    if (
        status == "upgrade"
        and current.item_id is not None
        and cur_aug is None
        and (current.name or "").casefold() != ARTISANS_PRIZE_NAME.casefold()
    ):
        status = "unknown"
        note = "Current aug not in raidloot catalog (EQ Resource miss)"

    # Guard: never list an upgrade that ranks worse than current — unless the
    # current piece is leaving for another slot. Then the replacement (even a
    # weaker one) belongs in Upgrade to; marking BiS would blank that column
    # while the note still says to move the aug.
    # Must-have freezing gem may occupy a hole whose catalog BiS scores higher.
    if (
        status == "upgrade"
        and recommended is not None
        and recommended.item_id == VELIUM_FREEZING_GEM_ID
    ):
        pass
    elif (
        status == "upgrade"
        and recommended is not None
        and cur_aug is not None
        and is_type78_aug(cur_aug)
        and not moved_to_slot
    ):
        if _aug_rank_tuple(
            recommended,
            current.gear_slot,
            class_abbr,
            secondary_is_shield=secondary,
            peer=cur_aug,
        ) > _aug_rank_tuple(
            cur_aug,
            current.gear_slot,
            class_abbr,
            secondary_is_shield=secondary,
            peer=recommended,
        ):
            status = "bis"
            note = "Current is better than remaining missing BiS options"
            recommended = cur_aug
            move_from_slot = None
            moved_to_slot = None

    # Lead note with score / Spell Damage / heroic / AC / HP gain when recommended.
    if status in ("upgrade", "empty") and recommended is not None:
        delta_current = cur_aug if status == "upgrade" else None
        if (
            status == "upgrade"
            and delta_current is None
            and (current.name or "").casefold() == ARTISANS_PRIZE_NAME.casefold()
        ):
            delta_current = _prize_candidate(catalog)
        note = upgrade_stat_delta_note(
            delta_current,
            recommended,
            current.gear_slot,
            class_abbr,
            secondary_is_shield=secondary,
            profile=profile,
        )

    move_bits: list[str] = []
    if move_from_slot and status in ("upgrade", "empty", "unknown"):
        move_bits.append(f"Move from {move_from_slot}")
    if moved_to_slot and status in ("upgrade", "empty", "unknown"):
        label = current.name or "Current aug"
        move_bits.append(f"Move {label} to {moved_to_slot}")
    if move_bits:
        move_txt = "; ".join(move_bits)
        note = f"{move_txt}; {note}" if note else move_txt

    extras: list[str] = []
    if recommended is not None and recommended.shield_only:
        extras.append("Shield Only Secondary aug")
    if (
        recommended is not None
        and _is_feet_slot(current.gear_slot)
        and uses_feet_overlay(class_abbr)
    ):
        extras.append(
            f"Highest AC for Feet ({class_abbr.strip().upper()}): {recommended.ac} AC"
        )
    if extras and status != "bis":
        extra = "; ".join(extras)
        note = f"{note}; {extra}" if note else extra

    if current.dump_slot == 4 and current.gear_slot == "Range":
        bow_note = "Range Slot1–4 + name has bow → type 7/8 in Slot4"
        note = f"{note}; {bow_note}" if note else bow_note
    elif (
        not current.socket_map_hit
        and current.parent_id
        and current.parent_id > 0
        and current.gear_slot not in ("Primary",)
        and not (
            current.gear_slot == "Secondary"
            and not parent_name_is_shield(current.parent_name)
        )
    ):
        miss_note = (
            f"type 7/8 via Slot{current.dump_slot} heuristic (no socket map)"
        )
        note = f"{note}; {miss_note}" if note else miss_note

    focus_value: int | None = None
    if recommended is not None:
        if recommended.shield_only and current.gear_slot == "Secondary":
            focus_value = recommended.ac
        elif _is_feet_slot(current.gear_slot) and uses_feet_overlay(class_abbr):
            focus_value = recommended.ac
        else:
            focus_value = recommended.focus_heroic

    rec_owned: bool | None = None
    if recommended is not None and recommended.item_id > 0:
        owned = owned_item_ids or set()
        # Equipped-elsewhere moves are owned even if the ID check were missed.
        rec_owned = recommended.item_id in owned or move_from_slot is not None

    craft_name: str | None = None
    craft_id: int | None = None
    craft_owned: bool | None = None
    if (
        recommended is not None
        and rec_owned is False
        and status in ("upgrade", "empty", "unknown")
    ):
        component = craft_component_for_aug(recommended.name)
        if component is not None:
            craft_name = component.name
            craft_id = component.item_id
            craft_owned = owns_craft_component(
                component,
                owned_item_ids=owned_item_ids,
                owned_item_names=owned_item_names,
            )

    deltas: dict[str, int] | None = None
    if status in ("upgrade", "empty") and recommended is not None:
        delta_current = cur_aug if status == "upgrade" else None
        if (
            status == "upgrade"
            and delta_current is None
            and (current.name or "").casefold() == ARTISANS_PRIZE_NAME.casefold()
        ):
            delta_current = _prize_candidate(catalog)
        deltas = slot_stat_deltas(delta_current, recommended, profile)

    return Slot2Comparison(
        gear_slot=current.gear_slot,
        current_name=current.name,
        current_id=current.item_id,
        recommended_name=recommended.name if recommended else None,
        recommended_id=recommended.item_id if recommended else None,
        recommended_focus=focus_value,
        status=status,
        note=note,
        recommended_owned=rec_owned,
        move_from_slot=move_from_slot
        if status in ("upgrade", "empty", "unknown")
        else None,
        stat_deltas=deltas,
        craft_component_name=craft_name,
        craft_component_id=craft_id,
        craft_component_owned=craft_owned,
    )


def _move_maps(
    assigned: dict[str, AugCandidate | None],
    current_by_slot: dict[str, Slot2Aug],
) -> tuple[dict[str, str], dict[str, str]]:
    """Map dest→source and donor→dest when a recommendation is currently equipped elsewhere."""
    move_from: dict[str, str] = {}
    moved_to: dict[str, str] = {}
    for slot, rec in assigned.items():
        if rec is None:
            continue
        cur = current_by_slot.get(slot)
        if cur is not None and cur.item_id == rec.item_id:
            continue
        for other, other_cur in current_by_slot.items():
            if other == slot or other_cur is None or other_cur.item_id is None:
                continue
            if other_cur.item_id == rec.item_id:
                move_from[slot] = other
                moved_to[other] = slot
                break
    return move_from, moved_to


def compare_character(
    data: InventoryData,
    catalog_result: CatalogResult,
    *,
    artisans_prize_owned: bool | None = None,
    profile: ProfileId | None = None,
    class_abbr: str | None = None,
    type78_slot_by_parent_id: dict[int, int | None] | None = None,
    eqr_aug_html_by_id: dict[int, str] | None = None,
    fetch_eqr_augs: bool = True,
) -> CharacterSlot2Report:
    """Build per-slot comparisons for one character (missing-BiS loadout)."""
    used_profile = profile or catalog_result.profile
    used_class = class_abbr if class_abbr is not None else data.class_abbr
    slot_map: dict[int, int] | None = None
    if type78_slot_by_parent_id is not None:
        slot_map = {
            iid: slot
            for iid, slot in type78_slot_by_parent_id.items()
            if slot is not None
        }
    slot2 = extract_slot2_augs(data, type78_slot_by_parent_id=slot_map)
    by_slot = {s.gear_slot: s for s in slot2}
    catalog = catalog_result.augs
    catalog_ids = {a.item_id for a in catalog}
    owned_ids = collect_owned_item_ids(data)
    owned_names = collect_owned_item_names(data)
    if artisans_prize_owned is None:
        artisans_prize_owned = owns_artisans_prize(data)
    if artisans_prize_owned:
        owned_ids = set(owned_ids)
        owned_ids.add(ARTISANS_PRIZE_ID)

    missing_ids: list[int] = []
    name_hints: dict[int, str] = {}
    for s in slot2:
        if s.item_id is None or s.item_id <= 0:
            continue
        if s.item_id in catalog_ids:
            continue
        if (s.name or "").casefold() == ARTISANS_PRIZE_NAME.casefold():
            continue
        missing_ids.append(s.item_id)
        if s.name:
            name_hints[s.item_id] = s.name
    external_augs = resolve_eqresource_augs(
        missing_ids,
        used_profile,
        html_overrides=eqr_aug_html_by_id,
        name_hints=name_hints,
        allow_network=fetch_eqr_augs,
    )

    gear_slots = [s for s in TEAM_GEAR_SLOTS if s in by_slot]
    for slot in by_slot:
        if slot not in gear_slots:
            gear_slots.append(slot)

    secondary = by_slot.get("Secondary")
    shield_secondary = bool(
        secondary and _is_secondary_shield(secondary.gear_slot, secondary.parent_name)
    )

    working_catalog = list(catalog)
    seen_ids = {a.item_id for a in working_catalog}
    for aug in external_augs.values():
        if aug.item_id not in seen_ids and is_type78_aug(aug, require_known=True):
            working_catalog.append(aug)
            seen_ids.add(aug.item_id)
    if _equipped_freezing_gem_slot(by_slot) is not None and VELIUM_FREEZING_GEM_ID not in seen_ids:
        working_catalog.append(
            _freezing_gem_candidate(working_catalog, profile=used_profile)
        )

    assigned = assign_slot_recommendations(
        gear_slots,
        working_catalog,
        artisans_prize_owned=artisans_prize_owned,
        class_abbr=used_class,
        shield_secondary=shield_secondary,
        current_by_slot=by_slot,
    )
    move_from, moved_to = _move_maps(assigned, by_slot)

    comparisons = [
        _finalize_comparison(
            by_slot[slot],
            assigned.get(slot),
            working_catalog,
            used_class,
            profile=used_profile,
            move_from_slot=move_from.get(slot),
            moved_to_slot=moved_to.get(slot),
            external_augs=external_augs,
            owned_item_ids=owned_ids,
            owned_item_names=owned_names,
        )
        for slot in gear_slots
        if slot in by_slot
    ]

    order = {s: i for i, s in enumerate(TEAM_GEAR_SLOTS)}
    comparisons.sort(key=lambda c: (order.get(c.gear_slot, 1000), c.gear_slot))

    summary, slots_changed = summarize_stat_deltas(comparisons)

    return CharacterSlot2Report(
        character=data.character,
        server=data.server,
        class_abbr=used_class,
        profile=used_profile,
        filepath=data.filepath,
        comparisons=comparisons,
        owned_item_ids=owned_ids,
        slots_changed=slots_changed,
        stat_summary=summary,
    )
