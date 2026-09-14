"""Class-based Type 18/19 suggestions from the Zarax cheat sheet."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Iterable

from inventory_parser.package_data import read_data_text
from inventory_parser.type18_augs.catalog import Type18CatalogEntry
from inventory_parser.type18_augs.categories import (
    category_from_name,
    is_anniversary_aug,
    stats_rank_key,
)

_CHEAT_SHEET_NAME = "type18_cheat_sheet.json"

# Expansion / event series tokens used to keep Set A–D lanes distinct.
_SERIES_MARKERS: tuple[str, ...] = (
    "of the harbinger",
    "of legacies lost",
    "of enduring harmony",
    "of the selenelion",
    "of jubilation",
)

_CLASS_ORDER: tuple[str, ...] = (
    "BRD",
    "BST",
    "BER",
    "CLR",
    "DRU",
    "ENC",
    "MAG",
    "MNK",
    "NEC",
    "PAL",
    "RNG",
    "ROG",
    "SHD",
    "SHM",
    "WAR",
    "WIZ",
)

# Defense-family categories are demoted from Primary → Optional.
_DEFENSE_CATEGORIES: frozenset[str] = frozenset(
    {
        "Defense",
        "Dorsal Defense",
        "Ventral Defense",
        "Defender",
    }
)

# Casters show Mana + Spell Damage instead of AC + HP on suggestion tables.
_CASTER_ABBRS: frozenset[str] = frozenset(
    {"CLR", "DRU", "ENC", "MAG", "NEC", "SHM", "WIZ"}
)

# Melee/hybrid DPS show HDEX instead of AC on suggestion tables.
_DEX_STAT_ABBRS: frozenset[str] = frozenset(
    {"MNK", "ROG", "BER", "BRD", "BST", "RNG"}
)


@dataclass(frozen=True)
class ClassGuide:
    abbr: str
    name: str
    primary: tuple[str, ...]
    optional: tuple[str, ...]


@dataclass(frozen=True)
class SuggestionPick:
    item_id: int
    name: str
    aug_type: int
    type_label: str
    category: str
    lore_group: str | None
    anniversary: bool
    stats: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class SuggestionRow:
    class_abbr: str
    class_name: str
    priority: str  # primary | optional | filler
    rank: int
    guide_name: str
    suggested: SuggestionPick | None
    alternative: SuggestionPick | None
    upgraded: bool
    owned: bool = False


@dataclass
class ClassSuggestions:
    class_abbr: str
    class_name: str
    primary: list[SuggestionRow] = field(default_factory=list)
    optional: list[SuggestionRow] = field(default_factory=list)
    filler: list[SuggestionRow] = field(default_factory=list)
    caster_stats: bool = False
    dex_stats: bool = False


def is_defense_category(category: str | None) -> bool:
    return (category or "") in _DEFENSE_CATEGORIES


def is_caster_class(class_abbr: str | None) -> bool:
    return (class_abbr or "").strip().upper() in _CASTER_ABBRS


def is_dex_stat_class(class_abbr: str | None) -> bool:
    return (class_abbr or "").strip().upper() in _DEX_STAT_ABBRS


def _guide_category(guide_name: str) -> str:
    return category_from_name(guide_name)


def name_series(name: str | None) -> str | None:
    """Return the expansion/event series marker embedded in an aug name."""
    text = (name or "").casefold()
    if not text:
        return None
    for marker in _SERIES_MARKERS:
        if marker in text:
            return marker
    return None


def hint_aug_type(name: str | None) -> int | None:
    """
    Infer Type 18 vs 19 from naming families when catalog hydration is missing.

    Acolyte / Whispering Midnight / Secret Dawn / Weeping Heaven → 18.
    Devotee / Blazing Euphoria / Silver … → 19.
    """
    text = (name or "").casefold()
    if not text:
        return None
    if "devotee" in text or "blazing euphoria" in text or text.startswith("silver "):
        return 19
    if (
        "acolyte" in text
        or "whispering midnight" in text
        or "weeping heaven" in text
        or "secret dawn" in text
    ):
        return 18
    return None


@lru_cache(maxsize=1)
def load_cheat_sheet() -> dict[str, ClassGuide]:
    """Load packaged per-class primary/optional guide names."""
    raw = json.loads(read_data_text(_CHEAT_SHEET_NAME))
    classes = raw.get("classes") or {}
    out: dict[str, ClassGuide] = {}
    for abbr, entry in classes.items():
        key = str(abbr).strip().upper()
        if not key or not isinstance(entry, dict):
            continue
        primary = tuple(
            str(n).strip() for n in (entry.get("primary") or []) if str(n).strip()
        )
        optional = tuple(
            str(n).strip() for n in (entry.get("optional") or []) if str(n).strip()
        )
        out[key] = ClassGuide(
            abbr=key,
            name=str(entry.get("name") or key),
            primary=primary,
            optional=optional,
        )
    return out


def cheat_sheet_source_url() -> str:
    raw = json.loads(read_data_text(_CHEAT_SHEET_NAME))
    return str(raw.get("source") or "")


def _entry_to_pick(entry: Type18CatalogEntry) -> SuggestionPick:
    return SuggestionPick(
        item_id=entry.item_id,
        name=entry.name,
        aug_type=entry.aug_type,
        type_label=entry.type_label
        or ("18/19" if entry.aug_type == 18 else str(entry.aug_type)),
        category=entry.category,
        lore_group=entry.lore_group,
        anniversary=bool(entry.anniversary),
        stats=dict(entry.stats or {}),
    )


def _best(entries: Iterable[Type18CatalogEntry]) -> Type18CatalogEntry | None:
    pool = list(entries)
    if not pool:
        return None
    return min(pool, key=lambda e: stats_rank_key(e.stats, e.name))


def _resolve_suggested(
    guide_name: str,
    *,
    by_name: dict[str, Type18CatalogEntry],
    catalog: list[Type18CatalogEntry],
) -> tuple[Type18CatalogEntry | None, bool, str]:
    """
    Resolve a guide name to a catalog entry.

    Prefer an exact match; if a same category + type + series aug has better
    stats, use that (``upgraded``).
    """
    category = category_from_name(guide_name)
    type_hint = hint_aug_type(guide_name)
    series = name_series(guide_name)
    exact = by_name.get(guide_name.casefold())

    series_pool = [
        e
        for e in catalog
        if e.category == category
        and (type_hint is None or e.aug_type == type_hint)
        and (series is None or name_series(e.name) == series)
    ]

    if exact is not None:
        best = _best(series_pool) or exact
        if best.item_id != exact.item_id and stats_rank_key(
            best.stats, best.name
        ) < stats_rank_key(exact.stats, exact.name):
            return best, True, "Better stats in the same series"
        return exact, False, ""

    if series_pool:
        best = _best(series_pool)
        return best, False, "Guide name missing; best match in series"

    # Fall back: best in category + type (any series).
    type_pool = [
        e
        for e in catalog
        if e.category == category and (type_hint is None or e.aug_type == type_hint)
    ]
    best = _best(type_pool)
    if best is not None:
        return best, False, "Guide name missing; best match in category"
    return None, False, "Not found in catalog"


def _anniversary_alternative(
    suggested: Type18CatalogEntry | None,
    guide_name: str,
    *,
    catalog: list[Type18CatalogEntry],
    reserved_names: set[str],
) -> Type18CatalogEntry | None:
    """Next non-anniversary aug in the same category/type not already on the list."""
    if suggested is None and not is_anniversary_aug(guide_name):
        return None
    if suggested is not None and not suggested.anniversary:
        return None

    category = (
        suggested.category if suggested is not None else category_from_name(guide_name)
    )
    type_hint = (
        suggested.aug_type if suggested is not None else hint_aug_type(guide_name)
    )
    suggested_id = suggested.item_id if suggested is not None else None

    pool = [
        e
        for e in catalog
        if e.category == category
        and (type_hint is None or e.aug_type == type_hint)
        and not e.anniversary
        and e.name.casefold() not in reserved_names
        and e.item_id != suggested_id
    ]
    return _best(pool)


def _pick_owned(
    pick: SuggestionPick | None,
    *,
    owned_ids: set[int],
    owned_names: set[str],
) -> bool:
    if pick is None:
        return False
    if pick.item_id > 0 and pick.item_id in owned_ids:
        return True
    name = (pick.name or "").casefold()
    return bool(name) and name in owned_names


def _make_row(
    *,
    abbr: str,
    class_name: str,
    priority: str,
    rank: int,
    guide_name: str,
    suggested: Type18CatalogEntry | None,
    alternative: Type18CatalogEntry | None,
    upgraded: bool,
    owned_ids: set[int],
    owned_names: set[str],
) -> SuggestionRow:
    sug_pick = _entry_to_pick(suggested) if suggested else None
    return SuggestionRow(
        class_abbr=abbr,
        class_name=class_name,
        priority=priority,
        rank=rank,
        guide_name=guide_name,
        suggested=sug_pick,
        alternative=_entry_to_pick(alternative) if alternative else None,
        upgraded=upgraded,
        owned=_pick_owned(sug_pick, owned_ids=owned_ids, owned_names=owned_names),
    )


def build_class_suggestions(
    catalog: list[Type18CatalogEntry],
    *,
    class_abbrs: Iterable[str] | None = None,
    owned_ids_by_class: dict[str, set[int]] | None = None,
    owned_names_by_class: dict[str, set[str]] | None = None,
) -> list[ClassSuggestions]:
    """
    Build per-class suggestion rows from the cheat sheet + live catalog.

    Defense-family guide picks are moved from Primary to Optional. The top two
    unused Fortification catalog augs (greatest stats) are appended to Optional.
    Unused Enhancement catalog augs are listed under Filler, greatest first.

    When ``class_abbrs`` is set (team characters), those classes are listed first.
    ``owned_ids_by_class`` / ``owned_names_by_class`` mark suggestions owned in
    that class's inventories.
    """
    guides = load_cheat_sheet()
    by_name = {e.name.casefold(): e for e in catalog if e.name}
    owned_ids_map = owned_ids_by_class or {}
    owned_names_map = owned_names_by_class or {}

    requested = [str(a).strip().upper() for a in (class_abbrs or []) if str(a).strip()]
    ordered: list[str] = []
    for abbr in requested:
        if abbr in guides and abbr not in ordered:
            ordered.append(abbr)
    for abbr in _CLASS_ORDER:
        if abbr in guides and abbr not in ordered:
            ordered.append(abbr)
    for abbr in sorted(guides):
        if abbr not in ordered:
            ordered.append(abbr)

    results: list[ClassSuggestions] = []
    for abbr in ordered:
        guide = guides[abbr]
        reserved = {n.casefold() for n in (*guide.primary, *guide.optional)}
        owned_ids = set(owned_ids_map.get(abbr) or ())
        owned_names = set(owned_names_map.get(abbr) or ())
        block = ClassSuggestions(
            class_abbr=abbr,
            class_name=guide.name,
            caster_stats=is_caster_class(abbr),
            dex_stats=is_dex_stat_class(abbr),
        )

        primary_names: list[str] = []
        optional_names: list[str] = []
        for guide_name in guide.primary:
            if is_defense_category(_guide_category(guide_name)):
                optional_names.append(guide_name)
            else:
                primary_names.append(guide_name)
        optional_names.extend(guide.optional)

        for priority, names in (
            ("primary", primary_names),
            ("optional", optional_names),
        ):
            for rank, guide_name in enumerate(names, start=1):
                suggested, upgraded, _note = _resolve_suggested(
                    guide_name, by_name=by_name, catalog=catalog
                )
                alt = _anniversary_alternative(
                    suggested,
                    guide_name,
                    catalog=catalog,
                    reserved_names=reserved,
                )
                row = _make_row(
                    abbr=abbr,
                    class_name=guide.name,
                    priority=priority,
                    rank=rank,
                    guide_name=guide_name,
                    suggested=suggested,
                    alternative=alt,
                    upgraded=upgraded,
                    owned_ids=owned_ids,
                    owned_names=owned_names,
                )
                if priority == "primary":
                    block.primary.append(row)
                else:
                    block.optional.append(row)

        def _used() -> tuple[set[int], set[str]]:
            ids = {
                r.suggested.item_id
                for r in (*block.primary, *block.optional, *block.filler)
                if r.suggested is not None
            }
            names = {
                r.suggested.name.casefold()
                for r in (*block.primary, *block.optional, *block.filler)
                if r.suggested is not None and r.suggested.name
            }
            names.update(reserved)
            return ids, names

        used_ids, used_names = _used()
        fort_unused = [
            e
            for e in catalog
            if e.category == "Fortification"
            and e.item_id not in used_ids
            and e.name.casefold() not in used_names
        ]
        fort_unused.sort(key=lambda e: stats_rank_key(e.stats, e.name))
        optional_rank = len(block.optional)
        for entry in fort_unused[:2]:
            optional_rank += 1
            alt = _anniversary_alternative(
                entry,
                entry.name,
                catalog=catalog,
                reserved_names=used_names,
            )
            block.optional.append(
                _make_row(
                    abbr=abbr,
                    class_name=guide.name,
                    priority="optional",
                    rank=optional_rank,
                    guide_name=entry.name,
                    suggested=entry,
                    alternative=alt,
                    upgraded=False,
                    owned_ids=owned_ids,
                    owned_names=owned_names,
                )
            )
            used_names.add(entry.name.casefold())
            if entry.item_id > 0:
                used_ids.add(entry.item_id)

        used_ids, used_names = _used()
        enh_unused = [
            e
            for e in catalog
            if e.category == "Enhancement"
            and e.item_id not in used_ids
            and e.name.casefold() not in used_names
        ]
        enh_unused.sort(key=lambda e: stats_rank_key(e.stats, e.name))
        for rank, entry in enumerate(enh_unused, start=1):
            alt = _anniversary_alternative(
                entry,
                entry.name,
                catalog=catalog,
                reserved_names=used_names,
            )
            block.filler.append(
                _make_row(
                    abbr=abbr,
                    class_name=guide.name,
                    priority="filler",
                    rank=rank,
                    guide_name=entry.name,
                    suggested=entry,
                    alternative=alt,
                    upgraded=False,
                    owned_ids=owned_ids,
                    owned_names=owned_names,
                )
            )

        results.append(block)
    return results


__all__ = [
    "ClassGuide",
    "ClassSuggestions",
    "SuggestionPick",
    "SuggestionRow",
    "build_class_suggestions",
    "cheat_sheet_source_url",
    "hint_aug_type",
    "is_caster_class",
    "is_dex_stat_class",
    "is_defense_category",
    "load_cheat_sheet",
    "name_series",
]
