"""Resolve gear T-codes for unknown items from EQ Resource item pages."""

from __future__ import annotations

import json
import re
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from inventory_parser.gear_tiers import GEAR_TIER_BY_CODE, classify_gear_tier
from inventory_parser.slot2_augs.eqresource_augs import (
    EQRESOURCE_ITEM_URL,
    _EXPAC_IMG_RE,
    _http_get,
)
from inventory_parser.slot2_augs.paths import appdata_dir

CACHE_FILENAME = "eqresource_gear_tier_cache.json"
_HTTP_WORKERS = 6

# EQ Resource expacimages stem → our T-code prefix.
EXPAC_CODE_TO_TIER_PREFIX: dict[str, str] = {
    "sor": "SOR",
    "tob": "TOB",
    "ls": "LS",
    "nos": "NoS",
}

_RAID_GROUP_TIER_RE = re.compile(
    r"(Raid|Group)\s*[-–]\s*Tier\s*(\d+)",
    re.IGNORECASE,
)


def cache_path() -> Path:
    return appdata_dir() / CACHE_FILENAME


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


def parse_gear_tier_from_eqr_html(html: str) -> str | None:
    """Map EQ Resource expansion icon + Raid/Group tier line to a known T-code."""
    if not html:
        return None
    expac = _EXPAC_IMG_RE.search(html)
    if not expac:
        return None
    prefix = EXPAC_CODE_TO_TIER_PREFIX.get(expac.group(1).strip().lower())
    if not prefix:
        return None
    rest = html[expac.end() :]
    tier_match = _RAID_GROUP_TIER_RE.search(rest) or _RAID_GROUP_TIER_RE.search(html)
    if not tier_match:
        return None
    kind = "R" if tier_match.group(1).casefold() == "raid" else "G"
    code = f"{prefix}-{kind}{tier_match.group(2)}"
    return code if code in GEAR_TIER_BY_CODE else None


def fetch_item_gear_tier(
    item_id: int,
    *,
    force_refresh: bool = False,
    html_override: str | None = None,
    skip_cache_write: bool = False,
    allow_network: bool = True,
) -> str | None:
    """Fetch (or load cached) gear T-code for one item id from EQ Resource."""
    if item_id <= 0:
        return None

    if html_override is not None:
        return parse_gear_tier_from_eqr_html(html_override)

    cache = _load_cache()
    key = str(item_id)
    # Honor negative cache (ok: false / no parseable T-code) so generate
    # does not re-hit EQ Resource for the same unknown items every run.
    if not force_refresh and key in cache:
        raw = cache[key].get("tier")
        code = str(raw) if raw else None
        return code if code in GEAR_TIER_BY_CODE else None

    if not allow_network:
        return None

    tier: str | None = None
    try:
        html = _http_get(EQRESOURCE_ITEM_URL.format(item_id=item_id))
        tier = parse_gear_tier_from_eqr_html(html)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        tier = None

    if not skip_cache_write:
        cache[key] = {
            "ok": tier is not None,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "tier": tier,
        }
        _save_cache(cache)
    return tier


def _tier_from_cache_entry(entry: dict) -> str | None:
    raw = entry.get("tier")
    code = str(raw) if raw else None
    return code if code in GEAR_TIER_BY_CODE else None


def _fetch_live_gear_tier(item_id: int) -> str | None:
    try:
        html = _http_get(EQRESOURCE_ITEM_URL.format(item_id=item_id))
        return parse_gear_tier_from_eqr_html(html)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None


def resolve_item_gear_tiers(
    item_ids: Iterable[int],
    *,
    force_refresh: bool = False,
    html_overrides: dict[int, str] | None = None,
    polite_delay_s: float = 0.05,
    allow_network: bool = True,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict[int, str]:
    """Batch-resolve T-codes for unknown equipped item ids."""
    html_overrides = html_overrides or {}
    result: dict[int, str] = {}
    unique = sorted({int(i) for i in item_ids if int(i) > 0})
    total = len(unique)
    cache = _load_cache()
    need_fetch: list[int] = []
    done = 0

    if total == 0 and on_progress is not None:
        on_progress(0, 0)

    for item_id in unique:
        override = html_overrides.get(item_id)
        if override is not None:
            code = parse_gear_tier_from_eqr_html(override)
            if code:
                result[item_id] = code
            done += 1
            if on_progress is not None:
                on_progress(done, total)
            continue
        key = str(item_id)
        if not force_refresh and key in cache:
            code = _tier_from_cache_entry(cache[key])
            if code:
                result[item_id] = code
            done += 1
            if on_progress is not None:
                on_progress(done, total)
            continue
        if allow_network:
            need_fetch.append(item_id)
        else:
            done += 1
            if on_progress is not None:
                on_progress(done, total)

    if need_fetch:
        dirty = False
        workers = min(_HTTP_WORKERS, len(need_fetch))
        if workers <= 1:
            fetched_live = 0
            for item_id in need_fetch:
                if fetched_live > 0 and polite_delay_s > 0:
                    time.sleep(polite_delay_s)
                code = _fetch_live_gear_tier(item_id)
                cache[str(item_id)] = {
                    "ok": code is not None,
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "tier": code,
                }
                dirty = True
                fetched_live += 1
                if code:
                    result[item_id] = code
                done += 1
                if on_progress is not None:
                    on_progress(done, total)
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {
                    pool.submit(_fetch_live_gear_tier, item_id): item_id
                    for item_id in need_fetch
                }
                for fut in as_completed(futures):
                    item_id = futures[fut]
                    code = fut.result()
                    cache[str(item_id)] = {
                        "ok": code is not None,
                        "fetched_at": datetime.now(timezone.utc).isoformat(),
                        "tier": code,
                    }
                    dirty = True
                    if code:
                        result[item_id] = code
                    done += 1
                    if on_progress is not None:
                        on_progress(done, total)
        if dirty:
            _save_cache(cache)
    return result


def _needs_eqr_tier(name: str, item_id: int, *, is_evolver: bool) -> bool:
    if item_id <= 0 or is_evolver:
        return False
    return classify_gear_tier(name) is None


def apply_resolved_gear_tiers_to_team(
    team: object,
    *,
    html_overrides: dict[int, str] | None = None,
    allow_network: bool = True,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict[int, str]:
    """Set ``resolved_tier`` on equipped items whose names have no T-code."""
    from dataclasses import replace

    characters = list(getattr(team, "characters", []) or [])
    unknown_ids: list[int] = []
    seen: set[int] = set()
    for ch in characters:
        for item in getattr(ch, "slots", {}).values():
            if item is None:
                continue
            item_id = int(getattr(item, "item_id", 0) or 0)
            if item_id in seen:
                continue
            if not _needs_eqr_tier(
                getattr(item, "name", ""),
                item_id,
                is_evolver=bool(getattr(item, "is_evolver", False)),
            ):
                continue
            seen.add(item_id)
            unknown_ids.append(item_id)

    by_id = resolve_item_gear_tiers(
        unknown_ids,
        html_overrides=html_overrides,
        allow_network=allow_network,
        on_progress=on_progress,
    )
    for ch in characters:
        slots = getattr(ch, "slots", None)
        if not slots:
            continue
        for slot, item in list(slots.items()):
            if item is None:
                continue
            code = by_id.get(int(item.item_id))
            if code:
                slots[slot] = replace(item, resolved_tier=code)
    return by_id
