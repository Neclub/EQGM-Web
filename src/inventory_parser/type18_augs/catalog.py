"""Fetch and hydrate the Type 18/19 aug catalog from EQ Resource."""

from __future__ import annotations

import json
import re
import time
import urllib.error
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from inventory_parser.http_fetch import http_get_text, http_post_text
from inventory_parser.slot2_augs.aug_stats import clean_stats
from inventory_parser.slot2_augs.eqresource_augs import (
    USER_AGENT,
    parse_eqresource_lore_group,
)
from inventory_parser.slot2_augs.eqresource_search import (
    EqrSearchRow,
    parse_eqresource_search_html,
)
from inventory_parser.slot2_augs.paths import appdata_dir
from inventory_parser.slot2_augs.profiles import EQRESOURCE_SEARCH_URL
from inventory_parser.slot2_augs.raidloot import parse_aug_slot_types
from inventory_parser.type18_augs.categories import (
    classify_aug_type,
    is_anniversary_aug,
    stats_rank_key,
    type_label,
)

CACHE_FILENAME = "eqresource_type18_catalog_cache.json"
ITEM_META_CACHE_FILENAME = "eqresource_type18_item_meta_cache.json"
# Live Type 19 search issues many POSTs; prefer disk cache on later runs.
_TYPE19_SEARCH_WORKERS = 6
_ITEM_META_WORKERS = 6

TYPE18_SEARCH_URL = (
    "https://items.eqresource.com/itemsearch.php?searchid=255223&page={page}"
)
TYPE18_CATALOG_URL = "https://items.eqresource.com/itemsearch.php?searchid=255223"
EQRESOURCE_ITEM_URL = "https://items.eqresource.com/items.php?id={item_id}"
# Fits Aug Slot is ``augtype`` on EQ Resource; ``augslot`` is a different field.
# Setting both to 19 returns zero rows.
TYPE19_CATALOG_URL = (
    "https://items.eqresource.com/itemsearch.php?s=advanced"
    "&type=augs&augtype=19&augmentation=1"
)

# Member search caps at 50 rows and POST page>1 repeats page 1, so always merge
# focused name queries (each stays under the cap).
_TYPE19_SUPPLEMENTAL_QUERIES: tuple[str, ...] = (
    # Anniversary event markers (substring match).
    "Jubilation",
    "Enduring Harmony",
    # Crafted Focus lines and older expansion families.
    "Selenelion",
    "Blazing Euphoria",
    "Whispering Midnight",
    "Weeping Heaven",
    "Secret Dawn",
    "Rallos Zek Devotee's",
    "Rallos Zek Acolyte's",
    # Devotee's alone exceeds 50 — split by category word.
    "Devotee's Assault",
    "Devotee's Attacker",
    "Devotee's Casting",
    "Devotee's Defense",
    "Devotee's Defending",
    "Devotee's Dorsal",
    "Devotee's Ventral",
    "Devotee's Enhancement",
    "Devotee's Fortification",
    "Devotee's Protecting",
    "Devotee's Soothing",
    "Devotee's Stealth",
    "Devotee's Strategy",
    "Devotee's Warding",
    # Silver Jubilation (avoid bare "Silver" — too many non-aug hits).
    "Silver Assaulting",
    "Silver Attacker",
    "Silver Casting",
    "Silver Defense",
    "Silver Defending",
    "Silver Dorsal",
    "Silver Ventral",
    "Silver Enhancement",
    "Silver Protecting",
    "Silver Soothing",
    "Silver Warding",
)

# Back-slot cloaks from anniversary name searches — not Type 18/19 augs.
_IGNORED_NON_AUG_NAMES: frozenset[str] = frozenset(
    {
        "mantle of enduring harmony",
        "cloak of enduring harmony",
        "cape of enduring harmony",
    }
)

_TOTAL_RESULTS_RE = re.compile(
    r"Total results:\s*([\d,]+)",
    re.IGNORECASE,
)
_ITEM_LORE_RE = re.compile(
    r"Item Lore:\s*(?:<[^>]+>\s*)*([^<\n]+)",
    re.IGNORECASE,
)

ProgressFn = Callable[[int, int], None]


@dataclass(frozen=True)
class Type18CatalogEntry:
    item_id: int
    name: str
    aug_type: int  # 18 or 19 (18 includes dual-slot 18+19)
    type_label: str  # "18/19", "19", or "18"
    category: str
    lore_group: str | None
    item_lore: str | None
    anniversary: bool
    stats: dict[str, int] = field(default_factory=dict)


@dataclass
class Type18CatalogResult:
    entries: list[Type18CatalogEntry] = field(default_factory=list)
    fetched_at: str = ""
    from_cache: bool = False
    warning: str | None = None
    type18_url: str = TYPE18_CATALOG_URL
    type19_url: str = TYPE19_CATALOG_URL


def catalog_cache_path() -> Path:
    return appdata_dir() / CACHE_FILENAME


def item_meta_cache_path() -> Path:
    return appdata_dir() / ITEM_META_CACHE_FILENAME


def parse_total_results(html: str) -> int | None:
    """Parse ``Total results: N`` from an EQ Resource search page."""
    if not html:
        return None
    m = _TOTAL_RESULTS_RE.search(html)
    if not m:
        return None
    try:
        return int(m.group(1).replace(",", ""))
    except ValueError:
        return None


def parse_item_lore(html: str) -> str | None:
    """Extract ``Item Lore: …`` from an EQ Resource item page."""
    if not html:
        return None
    m = _ITEM_LORE_RE.search(html)
    if not m:
        return None
    name = re.sub(r"\s+", " ", m.group(1)).strip()
    return name or None


def _http_get(url: str, timeout: float = 45.0) -> str:
    return http_get_text(url, timeout=timeout, user_agent=USER_AGENT)


def _http_post(url: str, payload: dict[str, str], timeout: float = 45.0) -> str:
    return http_post_text(url, payload, timeout=timeout, user_agent=USER_AGENT)


def _load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def type19_search_payload(*, name: str = "", page: int = 1) -> dict[str, str]:
    """Form fields for augs that fit Type 19 holes (Fits Aug Slot = augtype)."""
    payload: dict[str, str] = {
        "name": name,
        "class": "",
        "race": "",
        "slot": "",
        "level": "",
        "type": "augs",
        # Leave augslot empty — it is not "Fits Aug Slot"; both set to 19 → no results.
        "augslot": "",
        "augtype": "19",
        "searched": "true",
        "Submit": "Submit",
        "augmentation": "1",
        "page": str(max(1, page)),
        "attrib1": "hstr",
        "attrib1range": "",
        "attrib1amt": "",
        "attrib2": "hsta",
        "attrib2range": "",
        "attrib2amt": "",
        "attrib3": "hintel",
        "attrib3range": "",
        "attrib3amt": "",
        "attrib4": "hwis",
        "attrib4range": "",
        "attrib4amt": "",
        "attrib5": "hagi",
        "attrib5range": "",
        "attrib5amt": "",
        "attrib6": "hdex",
        "attrib6range": "",
        "attrib6amt": "",
        "attrib7": "hcha",
        "attrib7range": "",
        "attrib7amt": "",
    }
    return payload


def fetch_paginated_search_rows(
    *,
    fetch_page: Callable[[int], str],
    page_size: int = 50,
    max_pages: int = 20,
) -> list[EqrSearchRow]:
    """Fetch search pages until Total results is covered (or pages empty)."""
    by_id: dict[int, EqrSearchRow] = {}
    total: int | None = None
    for page in range(1, max_pages + 1):
        html = fetch_page(page)
        if total is None:
            total = parse_total_results(html)
        rows = parse_eqresource_search_html(html)
        if not rows:
            break
        for row in rows:
            by_id.setdefault(row.item_id, row)
        if total is not None and len(by_id) >= total:
            break
        if len(rows) < page_size and (total is None or len(by_id) >= total):
            break
        if page > 1 and len(rows) == 0:
            break
    return list(by_id.values())


def fetch_type18_search_rows(
    *,
    html_by_page: dict[int, str] | None = None,
    allow_network: bool = True,
) -> list[EqrSearchRow]:
    """Load Type 18 catalog from saved search ``searchid=255223``."""
    overrides = html_by_page or {}

    def fetch_page(page: int) -> str:
        if page in overrides:
            return overrides[page]
        if not allow_network:
            raise ValueError("Type 18 search HTML override missing for offline fetch")
        return _http_get(TYPE18_SEARCH_URL.format(page=page))

    return fetch_paginated_search_rows(fetch_page=fetch_page)


def _is_ignored_non_aug(name: str | None) -> bool:
    """True for known non-aug back items that share anniversary name tokens."""
    return (name or "").casefold().strip() in _IGNORED_NON_AUG_NAMES


def fetch_type19_search_rows(
    *,
    html_overrides: list[str] | None = None,
    allow_network: bool = True,
) -> list[EqrSearchRow]:
    """
    Load augs that fit Type 19 holes via advanced search (Fits Aug Slot / augtype=19).

    Always merges focused name queries (anniversary + craft/family markers). EQ Resource
    member search caps at 50 rows and ignores ``page`` on POST, so broad queries alone miss
    items such as anniversary Enduring Harmony / Jubilation augs.
    """
    by_id: dict[int, EqrSearchRow] = {}

    def keep(row: EqrSearchRow) -> bool:
        return not _is_ignored_non_aug(row.name)

    if html_overrides is not None:
        for html in html_overrides:
            for row in parse_eqresource_search_html(html):
                if keep(row):
                    by_id.setdefault(row.item_id, row)
        return list(by_id.values())

    if not allow_network:
        return []

    def collect_from_payload(name: str) -> list[EqrSearchRow]:
        # POST ``page`` does not advance results on EQ Resource; one request only.
        html = _http_post(
            EQRESOURCE_SEARCH_URL,
            type19_search_payload(name=name, page=1),
        )
        return [r for r in parse_eqresource_search_html(html) if keep(r)]

    queries = ("", *_TYPE19_SUPPLEMENTAL_QUERIES)
    workers = min(_TYPE19_SEARCH_WORKERS, len(queries))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(collect_from_payload, name) for name in queries]
        for fut in as_completed(futures):
            try:
                for row in fut.result():
                    by_id.setdefault(row.item_id, row)
            except (urllib.error.URLError, TimeoutError, OSError, ValueError):
                continue

    return list(by_id.values())


@dataclass(frozen=True)
class _ItemMeta:
    lore_group: str | None
    item_lore: str | None
    aug_types: frozenset[int]
    extra_stats: dict[str, int] = field(default_factory=dict)


def _extra_stats_from_item_html(html: str) -> dict[str, int]:
    """
    Pull Mana / Spell Damage / Heal Amount from an EQ Resource item page.

    Labels and values live in adjacent ``<td>`` cells (Heal Amount / Spell Damage /
    Clairvoyance), so use the shared combat-block parser — not a single-line regex.
    """
    if not html:
        return {}
    from inventory_parser.slot2_augs.eqresource_augs import (
        _parse_ac_hp_mana_end,
        _parse_combat_block,
    )

    out: dict[str, int] = {}
    _ac, _hp, mana, _end = _parse_ac_hp_mana_end(html)
    if mana:
        out["mana"] = int(mana)
    combat = _parse_combat_block(html)
    for key in ("spell_damage", "heal_amount", "clairvoyance", "atk"):
        val = int(combat.get(key, 0) or 0)
        if val:
            out[key] = val
    return out


def _parse_item_meta(html: str) -> _ItemMeta:
    return _ItemMeta(
        lore_group=parse_eqresource_lore_group(html),
        item_lore=parse_item_lore(html),
        aug_types=parse_aug_slot_types(html),
        extra_stats=_extra_stats_from_item_html(html),
    )


def _item_meta_cache_usable(entry: dict) -> bool:
    """True when cache row includes combat-block extra_stats (stats_v >= 2)."""
    if not entry.get("ok"):
        return False
    return int(entry.get("stats_v") or 0) >= 2


def resolve_item_meta(
    item_ids: Iterable[int],
    *,
    html_overrides: dict[int, str] | None = None,
    allow_network: bool = True,
    force_refresh: bool = False,
    polite_delay_s: float = 0.0,
    on_progress: ProgressFn | None = None,
) -> dict[int, _ItemMeta]:
    """Fetch (or cache) lore group, item lore, and aug slot types per item id."""
    result: dict[int, _ItemMeta] = {}
    unique = sorted({int(i) for i in item_ids if int(i) > 0})
    overrides = html_overrides or {}
    cache = _load_json(item_meta_cache_path())
    total = len(unique)
    dirty = False
    need_fetch: list[int] = []

    if total == 0 and on_progress is not None:
        on_progress(0, 0)

    def meta_from_cache_entry(entry: dict) -> _ItemMeta:
        types = frozenset(
            int(t) for t in (entry.get("aug_types") or []) if str(t).isdigit()
        )
        return _ItemMeta(
            lore_group=(
                str(entry["lore_group"]).strip() if entry.get("lore_group") else None
            )
            or None,
            item_lore=(
                str(entry["item_lore"]).strip() if entry.get("item_lore") else None
            )
            or None,
            aug_types=types,
            extra_stats=clean_stats(entry.get("extra_stats") or {}),
        )

    for i, item_id in enumerate(unique, start=1):
        if item_id in overrides:
            result[item_id] = _parse_item_meta(overrides[item_id])
            if on_progress is not None:
                on_progress(i, total)
            continue

        key = str(item_id)
        if (
            not force_refresh
            and key in cache
            and _item_meta_cache_usable(cache[key])
        ):
            result[item_id] = meta_from_cache_entry(cache[key])
            if on_progress is not None:
                on_progress(i, total)
            continue

        if not allow_network:
            if on_progress is not None:
                on_progress(i, total)
            continue

        need_fetch.append(item_id)

    done = total - len(need_fetch)
    if on_progress is not None and need_fetch:
        on_progress(done, total)

    def fetch_one(item_id: int) -> tuple[int, _ItemMeta | None, dict | None]:
        if polite_delay_s > 0:
            time.sleep(polite_delay_s)
        try:
            html = _http_get(EQRESOURCE_ITEM_URL.format(item_id=item_id))
            meta = _parse_item_meta(html)
            entry = {
                "ok": True,
                "stats_v": 2,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "lore_group": meta.lore_group,
                "item_lore": meta.item_lore,
                "aug_types": sorted(meta.aug_types),
                "extra_stats": dict(meta.extra_stats),
            }
            return item_id, meta, entry
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            entry = {
                "ok": False,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
            return item_id, None, entry

    if need_fetch:
        workers = min(_ITEM_META_WORKERS, len(need_fetch))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(fetch_one, item_id) for item_id in need_fetch]
            for fut in as_completed(futures):
                item_id, meta, entry = fut.result()
                if meta is not None:
                    result[item_id] = meta
                if entry is not None:
                    cache[str(item_id)] = entry
                    dirty = True
                done += 1
                if on_progress is not None:
                    on_progress(done, total)

    if dirty:
        _save_json(item_meta_cache_path(), cache)
    return result


def _row_dict(row: EqrSearchRow) -> dict:
    return {
        "item_id": row.item_id,
        "name": row.name,
        "stats": dict(row.stats),
    }


def _row_from_dict(d: dict) -> EqrSearchRow:
    return EqrSearchRow(
        item_id=int(d["item_id"]),
        name=str(d.get("name") or f"Item {d['item_id']}"),
        stats=clean_stats(d.get("stats") or {}),
    )


def fetch_type18_catalog(
    *,
    force_refresh: bool = False,
    allow_network: bool = True,
    type18_html_by_page: dict[int, str] | None = None,
    type19_html_overrides: list[str] | None = None,
    item_html_by_id: dict[int, str] | None = None,
    on_progress: ProgressFn | None = None,
) -> Type18CatalogResult:
    """
    Build the combined Type 18/19 catalog.

    Search rows supply stats; item pages supply slot types, lore group, and item lore.
    Classification uses slot types (18 present, including dual 18+19 → 18; 19-only → 19).

    When a disk catalog cache already has search rows, live EQ Resource searches are
    skipped unless ``force_refresh`` is set (Type 19 alone issues dozens of POSTs).
    """
    from inventory_parser.type18_augs.categories import category_from_name

    now = datetime.now(timezone.utc).isoformat()
    cache = _load_json(catalog_cache_path())
    warnings: list[str] = []
    from_cache = False
    rows_by_id: dict[int, EqrSearchRow] = {}

    use_overrides = (
        type18_html_by_page is not None
        or type19_html_overrides is not None
        or item_html_by_id is not None
    )

    cached_rows = cache.get("rows") if not force_refresh else None
    if (
        not use_overrides
        and cached_rows
        and isinstance(cached_rows, list)
        and len(cached_rows) > 0
    ):
        rows_by_id = {
            r.item_id: r for r in (_row_from_dict(d) for d in cached_rows)
        }
        from_cache = True
    else:
        try:
            if type18_html_by_page is not None or allow_network:
                for row in fetch_type18_search_rows(
                    html_by_page=type18_html_by_page,
                    allow_network=allow_network and type18_html_by_page is None,
                ):
                    rows_by_id.setdefault(row.item_id, row)
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            warnings.append(f"Type 18 search failed ({exc}).")

        try:
            if type19_html_overrides is not None or allow_network:
                for row in fetch_type19_search_rows(
                    html_overrides=type19_html_overrides,
                    allow_network=allow_network and type19_html_overrides is None,
                ):
                    rows_by_id.setdefault(row.item_id, row)
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            warnings.append(f"Type 19 search failed ({exc}).")

        if not rows_by_id:
            fallback_rows = cache.get("rows") if not force_refresh else None
            if fallback_rows:
                rows_by_id = {
                    r.item_id: r for r in (_row_from_dict(d) for d in fallback_rows)
                }
                from_cache = True
                warnings.append(
                    "Live Type 18/19 search returned no augs; using cached catalog."
                )
            else:
                detail = "; ".join(warnings) if warnings else "no results"
                raise ValueError(f"Type 18/19 search returned no augs ({detail})")
        elif allow_network and not use_overrides:
            cache["fetched_at"] = now
            cache["rows"] = [_row_dict(r) for r in rows_by_id.values()]
            cache["type18_url"] = TYPE18_CATALOG_URL
            cache["type19_url"] = TYPE19_CATALOG_URL
            _save_json(catalog_cache_path(), cache)

    meta_by_id = resolve_item_meta(
        rows_by_id.keys(),
        html_overrides=item_html_by_id,
        allow_network=allow_network and item_html_by_id is None,
        force_refresh=force_refresh,
        on_progress=on_progress,
    )

    entries: list[Type18CatalogEntry] = []
    for item_id, row in rows_by_id.items():
        if _is_ignored_non_aug(row.name):
            continue
        meta = meta_by_id.get(item_id)
        aug_types = meta.aug_types if meta else frozenset()
        aug_type = classify_aug_type(aug_types)
        label = type_label(aug_types)
        if aug_type is None:
            # Search context: type-18 saved search vs type-19 search — prefer name cues.
            name_cf = row.name.casefold()
            if (
                "devotee" in name_cf
                or "blazing euphoria" in name_cf
                or "jubilation" in name_cf
                or "enduring harmony" in name_cf
                or "selenelion" in name_cf
            ):
                aug_type = 19
                label = "19"
            elif "acolyte" in name_cf or "whispering midnight" in name_cf:
                aug_type = 18
                label = "18/19"
            else:
                # Keep unknown items out of the typed catalog.
                continue
        elif not label:
            label = "18/19" if aug_type == 18 else "19"
        stats = dict(row.stats)
        if meta and meta.extra_stats:
            for key, val in meta.extra_stats.items():
                if val and not stats.get(key):
                    stats[key] = int(val)
        entries.append(
            Type18CatalogEntry(
                item_id=item_id,
                name=row.name,
                aug_type=aug_type,
                type_label=label,
                category=category_from_name(row.name),
                lore_group=meta.lore_group if meta else None,
                item_lore=meta.item_lore if meta else None,
                anniversary=is_anniversary_aug(row.name),
                stats=stats,
            )
        )

    entries.sort(
        key=lambda e: (
            e.category.casefold(),
            (e.lore_group or e.item_lore or e.name).casefold(),
            *stats_rank_key(e.stats, e.name),
        )
    )

    warning = " ".join(warnings) if warnings else None
    return Type18CatalogResult(
        entries=entries,
        fetched_at=now if not from_cache else str(cache.get("fetched_at") or now),
        from_cache=from_cache,
        warning=warning,
        type18_url=str(cache.get("type18_url") or TYPE18_CATALOG_URL),
        type19_url=str(cache.get("type19_url") or TYPE19_CATALOG_URL),
    )
