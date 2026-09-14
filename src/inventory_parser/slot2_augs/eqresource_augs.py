"""Fetch type 7/8 aug stats from items.eqresource.com for catalog misses."""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import unquote_plus

from inventory_parser.slot2_augs.aug_stats import (
    ATTR_BASE,
    ATTR_HEROIC,
    LABEL_TO_STAT,
    clean_stats,
    legacy_from_stats,
)
from inventory_parser.slot2_augs.profiles import ProfileId
from inventory_parser.slot2_augs.raidloot import (
    AugCandidate,
    parse_aug_slot_types,
    parse_slot_restrictions,
)
from inventory_parser.http_fetch import http_get_text
from inventory_parser.slot2_augs.paths import appdata_dir

USER_AGENT = "EQ-Augs/0.2 (Slot2 type 7/8 checker; local tool)"
CACHE_FILENAME = "eqresource_aug_cache.json"
EXPANSION_CACHE_FILENAME = "eqresource_expansion_cache.json"
CACHE_STATS_VERSION = 4
EQRESOURCE_ITEM_URL = "https://items.eqresource.com/items.php?id={item_id}"

_EXPAC_IMG_RE = re.compile(
    r'expacimages/([a-z0-9_-]+)\.(?:jpg|png|gif|webp)',
    re.IGNORECASE,
)

# EQ Resource expacimages/{code}.jpg → display name (recent + common codes).
EXPAC_CODE_TO_NAME: dict[str, str] = {
    "classic": "Classic",
    "rok": "Ruins of Kunark",
    "kunark": "Ruins of Kunark",
    "sov": "The Scars of Velious",
    "velious": "The Scars of Velious",
    "sol": "The Shadows of Luclin",
    "luclin": "The Shadows of Luclin",
    "pop": "The Planes of Power",
    "loy": "The Legacy of Ykesha",
    "ldon": "Lost Dungeons of Norrath",
    "god": "Gates of Discord",
    "oow": "Omens of War",
    "don": "Dragons of Norrath",
    "dod": "Depths of Darkhollow",
    "por": "Prophecy of Ro",
    "tss": "The Serpent's Spine",
    "tbs": "The Buried Sea",
    "sof": "Secrets of Faydwer",
    "sod": "Seeds of Destruction",
    "uf": "Underfoot",
    "hot": "House of Thule",
    "voa": "Veil of Alaris",
    "rof": "Rain of Fear",
    "cotf": "Call of the Forsaken",
    "cof": "Call of the Forsaken",
    "tds": "The Darkened Sea",
    "tbm": "The Broken Mirror",
    "eok": "Empires of Kunark",
    "ros": "Ring of Scale",
    "tbl": "The Burning Lands",
    "tov": "Torment of Velious",
    "cov": "Claws of Veeshan",
    "tol": "Terror of Luclin",
    "nos": "Night of Shadows",
    "ls": "Laurion's Song",
    "tob": "The Outer Brood",
    "sor": "Shattering of Ro",
}

_ATTR_NAMES = (
    "Strength",
    "Stamina",
    "Intelligence",
    "Wisdom",
    "Agility",
    "Dexterity",
    "Charisma",
)
_ATTR_LABEL_RE = re.compile(
    r"(" + "|".join(_ATTR_NAMES) + r"):",
    re.IGNORECASE,
)
_ATTR_BLOCK_RE = re.compile(
    r"<td[^>]*>\s*((?:(?:Strength|Stamina|Intelligence|Wisdom|Agility|Dexterity|Charisma):<br>\s*)+)</td>\s*"
    r"<td[^>]*>\s*(.*?)</td>",
    re.IGNORECASE | re.DOTALL,
)
_HEROIC_VAL_RE = re.compile(
    r"(\d+)\s*\+\s*<font[^>]*>\s*<b>\s*(\d+)\s*</b>",
    re.IGNORECASE,
)
_AC_HP_RE = re.compile(
    r"<td[^>]*>\s*AC:<br>\s*HP:<br>\s*Mana:<br>\s*End:<br>"
    r"(?:\s*[A-Za-z ]+:<br>)*\s*</td>\s*"
    r"<td[^>]*>\s*(\d+)<br>\s*(\d+)<br>\s*(\d+)<br>\s*(\d+)<br>",
    re.IGNORECASE | re.DOTALL,
)
_AC_HP_RE_LOOSE = re.compile(
    r"<td[^>]*>\s*AC:<br>\s*HP:<br>.*?Mana:<br>.*?End:<br>.*?</td>\s*"
    r"<td[^>]*>\s*(\d+)<br>\s*(\d+)<br>",
    re.IGNORECASE | re.DOTALL,
)
_ATK_BLOCK_RE = re.compile(
    r"<td[^>]*>\s*((?:[A-Za-z][A-Za-z ]*:<br>\s*)+)</td>\s*"
    r"<td[^>]*>\s*(.*?)</td>",
    re.IGNORECASE | re.DOTALL,
)
_NAME_RE = re.compile(
    r'<font size="\+1"><b><center>\s*([^<]+?)\s*<br>',
    re.IGNORECASE,
)
_SLOT_RE = re.compile(r"Slot:\s*([^<\n]+)", re.IGNORECASE)
_RESTRICTIONS_RE = re.compile(
    r"Restrictions?:\s*([^<\n]+)",
    re.IGNORECASE,
)

# EQ Resource allow-list names → our gear-slot bases.
_EQR_SLOT_ALIASES: dict[str, str] = {
    "finger": "Fingers",
    "fingers": "Fingers",
    "shoulder": "Shoulders",
    "shoulders": "Shoulders",
    "charm": "Charm",
    "range": "Range",
    "ear": "Ear",
    "head": "Head",
    "face": "Face",
    "neck": "Neck",
    "arms": "Arms",
    "back": "Back",
    "wrist": "Wrist",
    "hands": "Hands",
    "chest": "Chest",
    "legs": "Legs",
    "feet": "Feet",
    "waist": "Waist",
    "primary": "Primary",
    "secondary": "Secondary",
    "ammo": "Ammo",
    "power source": "Power Source",
}


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


def expansion_cache_path() -> Path:
    return appdata_dir() / EXPANSION_CACHE_FILENAME


def _load_expansion_cache() -> dict:
    path = expansion_cache_path()
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_expansion_cache(data: dict) -> None:
    expansion_cache_path().write_text(json.dumps(data, indent=2), encoding="utf-8")


def expansion_name_from_code(code: str | None) -> str | None:
    """Map EQ Resource expac image stem to a display name."""
    if not code:
        return None
    key = code.strip().lower()
    if not key:
        return None
    return EXPAC_CODE_TO_NAME.get(key) or key.upper()


def parse_expansion_from_eqr_html(html: str) -> str | None:
    """Extract expansion display name from an EQ Resource item page."""
    if not html:
        return None
    m = _EXPAC_IMG_RE.search(html)
    if not m:
        return None
    return expansion_name_from_code(m.group(1))


def fetch_item_expansion(
    item_id: int,
    *,
    force_refresh: bool = False,
    html_override: str | None = None,
    skip_cache_write: bool = False,
    allow_network: bool = True,
) -> str | None:
    """Fetch (or load cached) expansion name for one item id from EQ Resource."""
    if item_id <= 0:
        return None

    if html_override is not None:
        return parse_expansion_from_eqr_html(html_override)

    cache = _load_expansion_cache()
    key = str(item_id)
    if not force_refresh and key in cache:
        name = cache[key].get("expansion")
        return str(name) if name else None

    if not allow_network:
        return None

    expansion: str | None = None
    try:
        html = _http_get(EQRESOURCE_ITEM_URL.format(item_id=item_id))
        expansion = parse_expansion_from_eqr_html(html)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        expansion = None

    if not skip_cache_write:
        cache[key] = {
            "ok": expansion is not None,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "expansion": expansion,
        }
        _save_expansion_cache(cache)
    return expansion


def resolve_item_expansions(
    item_ids: Iterable[int],
    *,
    force_refresh: bool = False,
    html_overrides: dict[int, str] | None = None,
    polite_delay_s: float = 0.05,
    allow_network: bool = True,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict[int, str]:
    """Batch-resolve expansion names for item ids (recommended upgrades / farm list).

    ``on_progress(done, total)`` is called after each item (1-based done).
    """
    html_overrides = html_overrides or {}
    result: dict[int, str] = {}
    unique = sorted({int(i) for i in item_ids if int(i) > 0})
    cache = _load_expansion_cache() if not html_overrides else {}
    fetched_live = 0
    total = len(unique)
    dirty = False

    if total == 0 and on_progress is not None:
        on_progress(0, 0)

    for i, item_id in enumerate(unique, start=1):
        override = html_overrides.get(item_id)
        if override is not None:
            name = parse_expansion_from_eqr_html(override)
        elif not force_refresh and str(item_id) in cache:
            raw = cache[str(item_id)].get("expansion")
            name = str(raw) if raw else None
        elif allow_network:
            if fetched_live > 0 and polite_delay_s > 0:
                time.sleep(polite_delay_s)
            name = fetch_item_expansion(
                item_id,
                force_refresh=force_refresh,
                allow_network=True,
                skip_cache_write=True,
            )
            cache[str(item_id)] = {
                "ok": name is not None,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "expansion": name,
            }
            dirty = True
            fetched_live += 1
        else:
            name = None
        if name:
            result[item_id] = name
        if on_progress is not None:
            on_progress(i, total)
    if dirty:
        _save_expansion_cache(cache)
    return result


def _parse_attributes(html: str) -> dict[str, tuple[int, int]]:
    """Map attribute display name → (base, heroic)."""
    out: dict[str, tuple[int, int]] = {}
    for m in _ATTR_BLOCK_RE.finditer(html):
        labels: list[str] = []
        for raw in _ATTR_LABEL_RE.findall(m.group(1)):
            canon = next((n for n in _ATTR_NAMES if n.lower() == raw.lower()), raw)
            labels.append(canon)
        vals: list[tuple[int, int]] = []
        for part in re.split(r"<br\s*/?>", m.group(2), flags=re.IGNORECASE):
            part = part.strip()
            if not part:
                continue
            hm = _HEROIC_VAL_RE.search(part)
            if hm:
                vals.append((int(hm.group(1)), int(hm.group(2))))
                continue
            pm = re.search(r"(\d+)", part)
            if pm:
                vals.append((int(pm.group(1)), 0))
        for label, pair in zip(labels, vals):
            out[label] = pair
    return out


def _parse_ac_hp_mana_end(html: str) -> tuple[int, int, int, int]:
    m = _AC_HP_RE.search(html)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
    m2 = _AC_HP_RE_LOOSE.search(html)
    if not m2:
        return 0, 0, 0, 0
    return int(m2.group(1)), int(m2.group(2)), 0, 0


def _parse_combat_block(html: str) -> dict[str, int]:
    """Parse Attack / Heal Amount / Spell Damage / Clairvoyance style blocks."""
    out: dict[str, int] = {}
    for m in _ATK_BLOCK_RE.finditer(html):
        labels = re.findall(r"([A-Za-z ]+):", m.group(1))
        parts = [
            p.strip()
            for p in re.split(r"<br\s*/?>", m.group(2), flags=re.IGNORECASE)
            if p.strip()
        ]
        for label, val in zip(labels, parts):
            key = LABEL_TO_STAT.get(label.strip().casefold())
            if not key:
                continue
            nm = re.search(r"(\d+)", val)
            if nm:
                out[key] = int(nm.group(1))
    return out


def _parse_atk(html: str) -> int:
    return int(_parse_combat_block(html).get("atk", 0))


def _stats_from_eqr_html(html: str) -> dict[str, int]:
    stats: dict[str, int] = {}
    ac, hp, mana, end = _parse_ac_hp_mana_end(html)
    if ac:
        stats["ac"] = ac
    if hp:
        stats["hp"] = hp
    if mana:
        stats["mana"] = mana
    if end:
        stats["endurance"] = end
    stats.update(_parse_combat_block(html))

    attrs = _parse_attributes(html)
    for display_name, (base, heroic) in attrs.items():
        low = display_name.casefold()
        base_key = ATTR_BASE.get(low)
        heroic_key = ATTR_HEROIC.get(low)
        if base_key and base:
            stats[base_key] = base
        if heroic_key and heroic:
            stats[heroic_key] = heroic
    return clean_stats(stats)


def _allowed_from_eqr_slot_text(slot_text: str) -> frozenset[str]:
    text = (slot_text or "").strip()
    if not text:
        return frozenset()
    if re.search(r"\ball\s+except\b", text, re.IGNORECASE):
        _excluded, allowed, _ear = parse_slot_restrictions(text)
        return allowed if allowed else frozenset()
    allowed: set[str] = set()
    for part in re.split(r"[,/]| and ", text):
        name = part.strip().strip(".")
        if not name:
            continue
        mapped = _EQR_SLOT_ALIASES.get(name.casefold())
        if mapped:
            allowed.add(mapped)
    return frozenset(allowed)


def parse_eqresource_lore_group(html: str) -> str | None:
    """Lore-group name from an EQ Resource item page (``loregroup=`` / Lore Group:)."""
    if not html:
        return None
    m = re.search(
        r"itemsearch\.php\?loregroup=([^\"'<&]+)",
        html,
        re.IGNORECASE,
    )
    if m:
        name = unquote_plus(m.group(1).replace("+", " "))
        name = re.sub(r"\s+", " ", name).strip()
        if name:
            return name
    m = re.search(
        r"Lore Group:\s*(?:<a[^>]*>)?\s*([^<]+)",
        html,
        re.IGNORECASE,
    )
    if m:
        name = re.sub(r"\s+", " ", m.group(1)).strip()
        if name:
            return name
    return None


def parse_eqresource_aug_html(
    html: str,
    profile: ProfileId,
    *,
    item_id: int,
    name_hint: str | None = None,
) -> AugCandidate | None:
    """Parse stats / slots from an EQ Resource item page."""
    if not html or item_id <= 0:
        return None

    name_m = _NAME_RE.search(html)
    name = (name_m.group(1).strip() if name_m else "") or (
        name_hint or f"Item {item_id}"
    )

    stats = _stats_from_eqr_html(html)
    focus, ac, hp, atk = legacy_from_stats(stats, profile)

    slot_m = _SLOT_RE.search(html)
    slot_text = slot_m.group(1).strip() if slot_m else ""
    slot_text = re.sub(r"\s+", " ", slot_text)
    allowed = _allowed_from_eqr_slot_text(slot_text)
    excluded: frozenset[str] = frozenset()
    ear_only = allowed == frozenset({"Ear"})

    restr_m = _RESTRICTIONS_RE.search(html)
    restrictions = restr_m.group(1).strip() if restr_m else ""
    shield_only = bool(re.search(r"shield\s*only", restrictions, re.IGNORECASE))
    if shield_only:
        allowed = frozenset({"Secondary"})
        ear_only = False

    # Require at least one useful parsed stat so empty/error pages do not count.
    if not stats:
        return None

    return AugCandidate(
        item_id=item_id,
        name=name,
        profile=profile,
        focus_heroic=focus,
        ac=ac,
        hp=hp,
        atk=atk,
        slot_text=slot_text,
        excluded_bases=excluded,
        allowed_bases=allowed,
        ear_only=ear_only,
        lore=bool(re.search(r"\bLore\b", html)),
        lore_group=parse_eqresource_lore_group(html),
        shield_only=shield_only,
        source="EQ Resource",
        stats=stats,
        aug_types=parse_aug_slot_types(html),
    )


def _aug_from_cache_entry(
    entry: dict,
    profile: ProfileId,
    item_id: int,
    name_hint: str | None = None,
) -> AugCandidate | None:
    if not entry.get("ok"):
        return None
    if int(entry.get("stats_v", 0)) < CACHE_STATS_VERSION or not entry.get("stats"):
        return None
    stats = clean_stats(entry.get("stats") or {})
    focus, ac, hp, atk = legacy_from_stats(stats, profile)
    types = frozenset(
        int(t) for t in (entry.get("aug_types") or []) if str(t).isdigit()
    )
    return AugCandidate(
        item_id=item_id,
        name=str(entry.get("name") or name_hint or f"Item {item_id}"),
        profile=profile,
        focus_heroic=focus or int(entry.get("focus_heroic", 0)),
        ac=ac or int(entry.get("ac", 0)),
        hp=hp or int(entry.get("hp", 0)),
        atk=atk or int(entry.get("atk", 0)),
        slot_text=str(entry.get("slot_text", "")),
        excluded_bases=frozenset(entry.get("excluded_bases") or ()),
        allowed_bases=frozenset(entry.get("allowed_bases") or ()),
        ear_only=bool(entry.get("ear_only", False)),
        lore=bool(entry.get("lore", False)),
        lore_group=(
            str(entry["lore_group"]).strip() if entry.get("lore_group") else None
        )
        or None,
        shield_only=bool(entry.get("shield_only", False)),
        source="EQ Resource",
        stats=stats,
        aug_types=types,
    )


def fetch_eqresource_aug(
    item_id: int,
    profile: ProfileId,
    *,
    force_refresh: bool = False,
    html_override: str | None = None,
    name_hint: str | None = None,
    skip_cache_write: bool = False,
) -> AugCandidate | None:
    """Fetch (or load cached) aug stats from EQ Resource for one item id."""
    if item_id <= 0:
        return None

    if html_override is not None:
        return parse_eqresource_aug_html(
            html_override, profile, item_id=item_id, name_hint=name_hint
        )

    cache = _load_cache()
    key = f"{profile}:{item_id}"
    if not force_refresh and key in cache:
        cached = _aug_from_cache_entry(
            cache[key], profile, item_id, name_hint=name_hint
        )
        if cached is not None:
            return cached

    try:
        html = _http_get(EQRESOURCE_ITEM_URL.format(item_id=item_id))
        aug = parse_eqresource_aug_html(
            html, profile, item_id=item_id, name_hint=name_hint
        )
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        aug = None

    if not skip_cache_write:
        if aug is None:
            cache[key] = {
                "ok": False,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
        else:
            cache[key] = {
                "ok": True,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "name": aug.name,
                "focus_heroic": aug.focus_heroic,
                "ac": aug.ac,
                "hp": aug.hp,
                "atk": aug.atk,
                "slot_text": aug.slot_text,
                "excluded_bases": sorted(aug.excluded_bases),
                "allowed_bases": sorted(aug.allowed_bases),
                "ear_only": aug.ear_only,
                "lore": aug.lore,
                "lore_group": aug.lore_group,
                "shield_only": aug.shield_only,
                "stats": dict(aug.stats),
                "stats_v": CACHE_STATS_VERSION,
                "aug_types": sorted(aug.aug_types),
            }
        _save_cache(cache)
    return aug


def resolve_eqresource_augs(
    item_ids: Iterable[int],
    profile: ProfileId,
    *,
    force_refresh: bool = False,
    html_overrides: dict[int, str] | None = None,
    name_hints: dict[int, str] | None = None,
    polite_delay_s: float = 0.05,
    allow_network: bool = True,
) -> dict[int, AugCandidate]:
    """Batch-resolve EQ Resource stats for aug item ids not in the raidloot catalog."""
    html_overrides = html_overrides or {}
    name_hints = name_hints or {}
    result: dict[int, AugCandidate] = {}
    unique = sorted({int(i) for i in item_ids if int(i) > 0})
    cache = _load_cache()
    fetched_live = 0
    dirty = False

    for item_id in unique:
        override = html_overrides.get(item_id)
        if override is not None:
            aug = fetch_eqresource_aug(
                item_id,
                profile,
                html_override=override,
                name_hint=name_hints.get(item_id),
            )
        else:
            key = f"{profile}:{item_id}"
            aug = None
            if not force_refresh and key in cache:
                aug = _aug_from_cache_entry(
                    cache[key],
                    profile,
                    item_id,
                    name_hint=name_hints.get(item_id),
                )
            if aug is None and allow_network:
                if fetched_live > 0 and polite_delay_s > 0:
                    time.sleep(polite_delay_s)
                aug = fetch_eqresource_aug(
                    item_id,
                    profile,
                    force_refresh=True,
                    name_hint=name_hints.get(item_id),
                    skip_cache_write=True,
                )
                if aug is None:
                    cache[key] = {
                        "ok": False,
                        "fetched_at": datetime.now(timezone.utc).isoformat(),
                    }
                else:
                    cache[key] = {
                        "ok": True,
                        "fetched_at": datetime.now(timezone.utc).isoformat(),
                        "name": aug.name,
                        "focus_heroic": aug.focus_heroic,
                        "ac": aug.ac,
                        "hp": aug.hp,
                        "atk": aug.atk,
                        "slot_text": aug.slot_text,
                        "excluded_bases": sorted(aug.excluded_bases),
                        "allowed_bases": sorted(aug.allowed_bases),
                        "ear_only": aug.ear_only,
                        "lore": aug.lore,
                        "lore_group": aug.lore_group,
                        "shield_only": aug.shield_only,
                        "stats": dict(aug.stats),
                        "stats_v": CACHE_STATS_VERSION,
                        "aug_types": sorted(aug.aug_types),
                    }
                dirty = True
                fetched_live += 1
            elif aug is None:
                continue
        if aug is not None:
            result[item_id] = aug
    if dirty:
        _save_cache(cache)
    return result
