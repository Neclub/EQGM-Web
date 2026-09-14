"""Detect character class from equipped Chest / breastplate (raidloot / EQ Resource)."""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from inventory_parser.http_fetch import http_get_text
from inventory_parser.parser import InventoryData, InventoryItem
from inventory_parser.slot2_augs.paths import appdata_dir
from inventory_parser.slot2_augs.profiles import CLASS_TO_PROFILE, ProfileId, profile_for_class

USER_AGENT = "EQ-Augs/0.2 (Slot2 type 7/8 checker; local tool)"
CACHE_FILENAME = "item_class_cache.json"
RAIDLOOT_ITEM_URL = "https://www.raidloot.com/items?name={item_id}"
EQRESOURCE_ITEM_URL = "https://items.eqresource.com/items.php?id={item_id}"

# Full names and abbreviations → canonical EQ class abbr.
_CLASS_ALIASES: dict[str, str] = {
    "war": "WAR",
    "warrior": "WAR",
    "pal": "PAL",
    "paladin": "PAL",
    "shd": "SHD",
    "sk": "SHD",
    "shadowknight": "SHD",
    "shadow knight": "SHD",
    "mnk": "MNK",
    "monk": "MNK",
    "rng": "RNG",
    "ranger": "RNG",
    "rog": "ROG",
    "rogue": "ROG",
    "bst": "BST",
    "beastlord": "BST",
    "brd": "BRD",
    "bard": "BRD",
    "ber": "BER",
    "berserker": "BER",
    "enc": "ENC",
    "enchanter": "ENC",
    "wiz": "WIZ",
    "wizard": "WIZ",
    "mag": "MAG",
    "magician": "MAG",
    "nec": "NEC",
    "necromancer": "NEC",
    "shm": "SHM",
    "shaman": "SHM",
    "clr": "CLR",
    "cleric": "CLR",
    "dru": "DRU",
    "druid": "DRU",
}

_RAIDLOOT_CLASS_RE = re.compile(
    r"<label>\s*Class:\s*</label>\s*(.*?)(?=<label>|<br\s*/?>|$)",
    re.IGNORECASE | re.DOTALL,
)
_EQR_CLASS_RE = re.compile(r"Class:\s*([^<\n]+)", re.IGNORECASE)
_TOKEN_SPLIT_RE = re.compile(r"[,/]| and |\s+")


def cache_path() -> Path:
    return appdata_dir() / CACHE_FILENAME


def _http_get(url: str, timeout: float = 30.0) -> str:
    return http_get_text(url, timeout=timeout, user_agent=USER_AGENT)


def _load_cache() -> dict:
    path = cache_path()
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_cache(data: dict) -> None:
    cache_path().write_text(json.dumps(data, indent=2), encoding="utf-8")


def _html_to_text(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", " ", fragment)
    return re.sub(r"\s+", " ", text).strip()


def normalize_class_token(token: str) -> str | None:
    """Map a class name/abbr token to WAR/ROG/… or None if not a real class."""
    key = re.sub(r"\s+", " ", (token or "").strip()).casefold()
    if not key or key == "all":
        return None
    return _CLASS_ALIASES.get(key)


def parse_class_list(text: str) -> list[str]:
    """Parse 'ROG' / 'Rogue' / 'WAR PAL SHD' into unique canonical abbrs."""
    cleaned = _html_to_text(text)
    if not cleaned:
        return []
    # Prefer multi-word aliases before splitting hard.
    lower = cleaned.casefold()
    found: list[str] = []
    seen: set[str] = set()
    # Try longest alias phrases first.
    for alias, abbr in sorted(_CLASS_ALIASES.items(), key=lambda kv: -len(kv[0])):
        if " " in alias and alias in lower:
            if abbr not in seen:
                found.append(abbr)
                seen.add(abbr)
    for part in _TOKEN_SPLIT_RE.split(cleaned):
        abbr = normalize_class_token(part)
        if abbr and abbr not in seen:
            found.append(abbr)
            seen.add(abbr)
    return found


def parse_raidloot_item_classes(html: str) -> list[str]:
    m = _RAIDLOOT_CLASS_RE.search(html or "")
    if not m:
        # Plain-text fallback
        m2 = re.search(r"Class:\s*([A-Za-z][A-Za-z /,]*)", html or "", re.IGNORECASE)
        return parse_class_list(m2.group(1)) if m2 else []
    return parse_class_list(m.group(1))


def parse_eqresource_item_classes(html: str) -> list[str]:
    m = _EQR_CLASS_RE.search(html or "")
    if not m:
        return []
    return parse_class_list(m.group(1))


def parse_eqresource_item_class_set(html: str) -> frozenset[str] | None:
    """Class restriction from an EQ Resource item page.

    Returns None when Class: is missing or unparsed, an empty frozenset for
    Class: All, and the parsed abbreviations otherwise.
    """
    m = _EQR_CLASS_RE.search(html or "")
    if not m:
        return None
    cleaned = _html_to_text(m.group(1))
    if not cleaned:
        return None
    if cleaned.casefold() == "all":
        return frozenset()
    parsed = parse_class_list(cleaned)
    return frozenset(parsed) if parsed else None


def equipped_chest_item(data: InventoryData) -> InventoryItem | None:
    """Return the equipped Chest parent item, if any."""
    for item in data.items:
        if item.location != "Chest":
            continue
        if item.item_id <= 0:
            continue
        if item.name.casefold() == "empty":
            continue
        return item
    return None


def fetch_item_classes(
    item_id: int,
    *,
    force_refresh: bool = False,
    raidloot_html: str | None = None,
    eqr_html: str | None = None,
    skip_cache_write: bool = False,
) -> list[str]:
    """
    Resolve usable class list for an item id (Chest armor).

    Prefers raidloot abbreviations; falls back to EQ Resource names.
    """
    if item_id <= 0:
        return []

    if raidloot_html is not None or eqr_html is not None:
        classes = parse_raidloot_item_classes(raidloot_html or "")
        if not classes:
            classes = parse_eqresource_item_classes(eqr_html or "")
        return classes

    cache = _load_cache()
    key = str(item_id)
    if not force_refresh and key in cache and "classes" in cache[key]:
        raw = cache[key].get("classes") or []
        return [str(c).upper() for c in raw if str(c).upper() in CLASS_TO_PROFILE]

    classes: list[str] = []
    try:
        html = _http_get(RAIDLOOT_ITEM_URL.format(item_id=item_id))
        classes = parse_raidloot_item_classes(html)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        classes = []

    if not classes:
        try:
            eqr = _http_get(EQRESOURCE_ITEM_URL.format(item_id=item_id))
            classes = parse_eqresource_item_classes(eqr)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            classes = []

    if not skip_cache_write:
        cache[key] = {
            "classes": classes,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        _save_cache(cache)
    return classes


def canonical_class_abbr(value: str | None) -> str | None:
    """Return a known class abbr or None."""
    if not value:
        return None
    abbr = value.strip().upper()
    return abbr if abbr in CLASS_TO_PROFILE else None


def primary_class_from_list(classes: list[str]) -> str | None:
    """Pick a single class abbr when the item lists one (or more) classes."""
    return choose_class_abbr(classes)


def choose_class_abbr(
    chest_classes: list[str],
    fallback: str | None = None,
) -> str | None:
    """Prefer worn-chest class; use filename/roster class only as fallback.

    A single-class chest always wins. Multi-class chests keep ``fallback`` when
    it is one of the listed classes; otherwise the first listed class is used.
    """
    usable = [c for c in chest_classes if c in CLASS_TO_PROFILE]
    fallback_abbr = canonical_class_abbr(fallback)
    if len(usable) == 1:
        return usable[0]
    if len(usable) > 1:
        if fallback_abbr and fallback_abbr in usable:
            return fallback_abbr
        return usable[0]
    return fallback_abbr


def detect_class_from_chest(
    data: InventoryData,
    *,
    force_refresh: bool = False,
    overrides: dict[int, tuple[str | None, str | None]] | None = None,
    allow_network: bool = True,
) -> str | None:
    """
    Detect character class from equipped Chest armor.

    Returns a canonical abbr (e.g. ``ROG``) or None.
    """
    chest = equipped_chest_item(data)
    if chest is None:
        return None
    overrides = overrides or {}
    ov = overrides.get(chest.item_id)
    if ov is not None:
        classes = fetch_item_classes(
            chest.item_id,
            raidloot_html=ov[0],
            eqr_html=ov[1],
        )
    elif allow_network:
        classes = fetch_item_classes(chest.item_id, force_refresh=force_refresh)
    else:
        return None
    return primary_class_from_list(classes)


def resolve_character_class(
    data: InventoryData,
    *,
    explicit_class: str | None = None,
    force_refresh: bool = False,
    overrides: dict[int, tuple[str | None, str | None]] | None = None,
    allow_network: bool = True,
) -> str | None:
    """Prefer worn Chest (BP) class; fall back to filename/roster class."""
    fallback = canonical_class_abbr(explicit_class) or canonical_class_abbr(
        data.class_abbr
    )
    chest = equipped_chest_item(data)
    if chest is None:
        return fallback
    overrides = overrides or {}
    ov = overrides.get(chest.item_id)
    if ov is not None:
        classes = fetch_item_classes(
            chest.item_id,
            raidloot_html=ov[0],
            eqr_html=ov[1],
        )
    elif allow_network:
        classes = fetch_item_classes(chest.item_id, force_refresh=force_refresh)
    else:
        classes = []
    return choose_class_abbr(classes, fallback)


def profile_from_class(class_abbr: str | None, fallback: ProfileId = "dex") -> ProfileId:
    return profile_for_class(class_abbr) or fallback


def resolve_classes_for_inventories(
    inventories: Iterable[InventoryData],
    *,
    explicit_by_path: dict[str, str | None] | None = None,
    overrides: dict[int, tuple[str | None, str | None]] | None = None,
    allow_network: bool = True,
    polite_delay_s: float = 0.05,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict[str, str | None]:
    """
    Map inventory filepath → class abbr.

    Always looks up equipped Chest (BP) class. Filename/roster class is
    fallback when the chest is missing or the lookup has no usable class.

    Batches unique Chest item ids so each armor is fetched once.
    ``on_progress(done, total)`` is called after each chest fetch (1-based done).
    """
    explicit_by_path = {
        str(Path(k)): canonical_class_abbr(v)
        for k, v in (explicit_by_path or {}).items()
    }
    overrides = overrides or {}
    result: dict[str, str | None] = {}
    fallback_by_path: dict[str, str | None] = {}
    need_fetch: dict[int, list[str]] = {}

    for data in inventories:
        path = str(Path(data.filepath))
        fallback = explicit_by_path.get(path) or canonical_class_abbr(data.class_abbr)
        fallback_by_path[path] = fallback
        chest = equipped_chest_item(data)
        if chest is None:
            result[path] = fallback
            continue
        need_fetch.setdefault(chest.item_id, []).append(path)

    fetched_live = 0
    classes_by_item: dict[int, list[str]] = {}
    fetch_ids = sorted(need_fetch)
    total = len(fetch_ids)
    cache = _load_cache() if allow_network else {}
    if total == 0 and on_progress is not None:
        on_progress(0, 0)

    for i, item_id in enumerate(fetch_ids, start=1):
        ov = overrides.get(item_id)
        if ov is not None:
            classes = fetch_item_classes(
                item_id, raidloot_html=ov[0], eqr_html=ov[1]
            )
        elif allow_network:
            key = str(item_id)
            if key in cache and "classes" in cache[key]:
                raw = cache[key].get("classes") or []
                classes = [str(c).upper() for c in raw if str(c).upper() in CLASS_TO_PROFILE]
            else:
                if fetched_live > 0 and polite_delay_s > 0:
                    time.sleep(polite_delay_s)
                classes = fetch_item_classes(item_id)
                fetched_live += 1
        else:
            classes = []
        classes_by_item[item_id] = [c for c in classes if c in CLASS_TO_PROFILE]
        if on_progress is not None:
            on_progress(i, total)

    for item_id, paths in need_fetch.items():
        chest_classes = classes_by_item.get(item_id, [])
        for path in paths:
            result[path] = choose_class_abbr(chest_classes, fallback_by_path[path])

    return result


def apply_resolved_classes_to_team(
    team: object,
    *,
    overrides: dict[int, tuple[str | None, str | None]] | None = None,
    allow_network: bool = True,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict[str, str | None]:
    """Set each team/spell persona's class from worn Chest, then filenames."""
    characters = list(getattr(team, "characters", []) or [])
    spell_characters = list(getattr(team, "spell_characters", []) or [])
    inventories: list[InventoryData] = []
    seen_data: set[int] = set()
    explicit_by_path: dict[str, str | None] = {}
    all_chars = characters + spell_characters
    for ch in all_chars:
        data = getattr(ch, "inventory_data", None)
        if data is None:
            continue
        path = str(Path(data.filepath))
        if path not in explicit_by_path:
            explicit_by_path[path] = getattr(ch, "class_abbr", None) or data.class_abbr
        if id(data) not in seen_data:
            seen_data.add(id(data))
            inventories.append(data)

    class_by_path = resolve_classes_for_inventories(
        inventories,
        explicit_by_path=explicit_by_path,
        overrides=overrides,
        allow_network=allow_network,
        on_progress=on_progress,
    )
    for ch in all_chars:
        data = getattr(ch, "inventory_data", None)
        if data is None:
            continue
        path = str(Path(data.filepath))
        abbr = class_by_path.get(path) or data.class_abbr
        data.class_abbr = abbr
        ch.class_abbr = abbr
    return class_by_path
