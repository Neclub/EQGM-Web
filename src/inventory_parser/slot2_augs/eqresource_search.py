"""EQ Resource advanced search as the type 7/8 aug catalog."""

from __future__ import annotations

import json
import os
import re
import urllib.error
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

from inventory_parser.http_fetch import http_post_text
from inventory_parser.slot2_augs.aug_stats import clean_stats, legacy_from_stats, merge_stats
from inventory_parser.slot2_augs.eqresource_augs import USER_AGENT, resolve_eqresource_augs
from inventory_parser.slot2_augs.profiles import (
    ARTISANS_PRIZE_ID,
    EQRESOURCE_SEARCH_COLUMNS,
    EQRESOURCE_SEARCH_PRIMARY,
    EQRESOURCE_SEARCH_URL,
    PROFILE_FOCUS_STAT,
    ProfileId,
)
from inventory_parser.slot2_augs.raidloot import AugCandidate, CatalogResult, is_type78_aug
from inventory_parser.slot2_augs.paths import appdata_dir

CACHE_FILENAME = "eqresource_search_cache.json"
_GENERAL_EXCL = frozenset({"Charm", "Range", "Primary", "Secondary", "Ammo"})

_HEADER_TO_STAT: dict[str, str] = {
    "ac": "ac",
    "hp": "hp",
    "mana": "mana",
    "end": "endurance",
    "spell dmg": "spell_damage",
    "spell damage": "spell_damage",
    "hint": "hint",
    "hdex": "hdex",
    "hwis": "hwis",
    "hstr": "hstr",
    "hsta": "hsta",
    "hagi": "hagi",
    "hcha": "hcha",
    "atk": "atk",
    "attack": "atk",
    "heal amount": "heal_amount",
    "clairvoyance": "clairvoyance",
}

_ITEM_HREF_RE = re.compile(r"items\.php\?id=(\d+)", re.IGNORECASE)


@dataclass(frozen=True)
class EqrSearchRow:
    item_id: int
    name: str
    stats: dict[str, int]


class _SearchTableParser(HTMLParser):
    """Collect result-table rows: icon, name/id, then numeric stat cells."""

    def __init__(self) -> None:
        super().__init__()
        self._in_td = False
        self._td_parts: list[str] = []
        self._td_href = ""
        self._row_cells: list[tuple[str, str]] = []
        self.header: list[str] = []
        self.rows: list[tuple[int, str, list[str]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row_cells = []
        elif tag == "td":
            self._in_td = True
            self._td_parts = []
            self._td_href = ""
        elif tag == "a" and self._in_td:
            href = dict(attrs).get("href") or ""
            if href:
                self._td_href = href

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self._in_td:
            self._in_td = False
            text = re.sub(r"\s+", " ", " ".join(self._td_parts)).strip()
            self._row_cells.append((self._td_href, text))
        elif tag == "tr":
            self._finish_row()

    def handle_data(self, data: str) -> None:
        if self._in_td:
            self._td_parts.append(data)

    def _finish_row(self) -> None:
        cells = self._row_cells
        self._row_cells = []
        if not cells:
            return
        texts = [t for _h, t in cells]
        joined = " ".join(texts).casefold()
        if "item name" in joined and "ac" in joined:
            self.header = [t.strip() for t in texts]
            return
        item_id = 0
        name = ""
        for href, text in cells:
            m = _ITEM_HREF_RE.search(href) or _ITEM_HREF_RE.search(text)
            if m:
                item_id = int(m.group(1))
                name = text.strip() or name
        if item_id <= 0:
            return
        self.rows.append((item_id, name, texts))


def parse_eqresource_search_html(html: str) -> list[EqrSearchRow]:
    """Parse an EQ Resource advanced-search result table into item rows."""
    if not html:
        return []
    parser = _SearchTableParser()
    try:
        parser.feed(html)
    except Exception:
        return []
    header_keys: list[str | None] = []
    for label in parser.header:
        key = _HEADER_TO_STAT.get(label.strip().casefold())
        header_keys.append(key)

    out: list[EqrSearchRow] = []
    seen: set[int] = set()
    for item_id, name, texts in parser.rows:
        if item_id in seen:
            continue
        seen.add(item_id)
        stats: dict[str, int] = {}
        # Align numeric cells to header labels when possible.
        if header_keys and len(texts) == len(header_keys):
            for key, raw in zip(header_keys, texts):
                if not key:
                    continue
                n = _cell_int(raw)
                if n is not None:
                    stats[key] = n
        else:
            # Fallback: AC/HP/Mana/End then remaining numeric cells ignored.
            nums = [_cell_int(t) for t in texts]
            nums = [n for n in nums if n is not None]
            for key, n in zip(("ac", "hp", "mana", "endurance"), nums[:4]):
                stats[key] = n
        out.append(
            EqrSearchRow(
                item_id=item_id,
                name=name or f"Item {item_id}",
                stats=clean_stats(stats),
            )
        )
    return out


def _cell_int(raw: str) -> int | None:
    text = (raw or "").strip()
    if not text or not re.fullmatch(r"-?\d+", text):
        return None
    return int(text)


def eqresource_search_payload(profile: ProfileId, *, augtype: str) -> dict[str, str]:
    """Form fields for type 7/8 augs filtered by the profile's primary stat."""
    primary, rng, amt = EQRESOURCE_SEARCH_PRIMARY[profile]
    extras = [c for c in EQRESOURCE_SEARCH_COLUMNS if c != primary]
    payload: dict[str, str] = {
        "name": "",
        "class": "",
        "race": "",
        "slot": "",
        "level": "",
        "type": "augs",
        # Fits Aug Slot is ``augtype``; ``augslot`` is "Item Has Aug Slot Type".
        # Setting both to 7/8 returns zero rows (same trap as Type 19).
        "augslot": "",
        "augtype": augtype,
        "searched": "true",
        "Submit": "Submit",
        "augmentation": "1",
        "attrib1": primary,
        "attrib1range": rng,
        "attrib1amt": amt,
    }
    for i, extra in enumerate(extras, start=2):
        payload[f"attrib{i}"] = extra
        payload[f"attrib{i}range"] = ""
        payload[f"attrib{i}amt"] = ""
    return payload


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


def _http_post(url: str, payload: dict[str, str], timeout: float = 45.0) -> str:
    return http_post_text(url, payload, timeout=timeout, user_agent=USER_AGENT)


def fetch_eqresource_search_html(
    profile: ProfileId,
    *,
    augtype: str = "7",
    html_override: str | None = None,
) -> str:
    if html_override is not None:
        return html_override
    return _http_post(EQRESOURCE_SEARCH_URL, eqresource_search_payload(profile, augtype=augtype))


def _row_to_candidate(row: EqrSearchRow, profile: ProfileId) -> AugCandidate:
    stats = dict(row.stats)
    focus, ac, hp, atk = legacy_from_stats(stats, profile)
    ear_only = row.item_id == ARTISANS_PRIZE_ID
    return AugCandidate(
        item_id=row.item_id,
        name=row.name,
        profile=profile,
        focus_heroic=focus,
        ac=ac or int(stats.get("ac", 0)),
        hp=hp or int(stats.get("hp", 0)),
        atk=atk,
        excluded_bases=frozenset() if ear_only else _GENERAL_EXCL,
        allowed_bases=frozenset({"Ear"}) if ear_only else frozenset(),
        ear_only=ear_only,
        lore=True,
        source="EQ Resource",
        stats=stats,
    )


def _rows_from_cached_profile(cached: dict | None) -> list[EqrSearchRow]:
    if not cached or not isinstance(cached.get("rows"), list):
        return []
    rows: list[EqrSearchRow] = []
    for d in cached["rows"]:
        if not isinstance(d, dict) or "item_id" not in d:
            continue
        rows.append(
            EqrSearchRow(
                item_id=int(d["item_id"]),
                name=str(d.get("name") or f"Item {d['item_id']}"),
                stats=clean_stats(d.get("stats") or {}),
            )
        )
    return rows


def fetch_eqresource_catalog(
    profile: ProfileId,
    *,
    force_refresh: bool = False,
    html_override: str | None = None,
    html_override_augtype8: str | None = None,
    item_html_by_id: dict[int, str] | None = None,
    allow_network: bool = True,
) -> CatalogResult:
    """Build a type 7/8 catalog from EQ Resource advanced search + item pages."""
    now = datetime.now(timezone.utc).isoformat()
    cache = _load_cache()
    rows: list[EqrSearchRow] = []
    from_cache = False
    warning: str | None = None
    url = EQRESOURCE_SEARCH_URL
    use_overrides = (
        html_override is not None
        or html_override_augtype8 is not None
        or item_html_by_id is not None
    )
    cached_rows = (
        _rows_from_cached_profile(cache.get(profile))
        if not force_refresh and not use_overrides
        else []
    )
    if cached_rows:
        rows = cached_rows
        from_cache = True
    else:
        try:
            html7 = fetch_eqresource_search_html(
                profile, augtype="7", html_override=html_override
            )
            rows.extend(parse_eqresource_search_html(html7))
            if html_override_augtype8 is not None or (
                allow_network and html_override is None
            ):
                html8 = fetch_eqresource_search_html(
                    profile, augtype="8", html_override=html_override_augtype8
                )
                rows.extend(parse_eqresource_search_html(html8))
            # Prefer first occurrence (search is already score-sorted).
            by_id: dict[int, EqrSearchRow] = {}
            for row in rows:
                by_id.setdefault(row.item_id, row)
            rows = list(by_id.values())
            if len([r for r in rows if r.item_id != ARTISANS_PRIZE_ID]) < 3:
                raise ValueError(
                    f"EQ Resource search returned {len(rows)} augs (need a working parse)"
                )
            if html_override is None:
                cache[profile] = {
                    "fetched_at": now,
                    "url": url,
                    "rows": [
                        {"item_id": r.item_id, "name": r.name, "stats": r.stats}
                        for r in rows
                    ],
                }
                _save_cache(cache)
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            cached = cache.get(profile) if not force_refresh else None
            fallback_rows = _rows_from_cached_profile(cached)
            if fallback_rows:
                rows = fallback_rows
                from_cache = True
                warning = f"Live EQ Resource search failed ({exc}); using cached search."
            else:
                raise

    name_hints = {r.item_id: r.name for r in rows}
    live_items = allow_network and html_override is None and not from_cache
    hydrated = resolve_eqresource_augs(
        [r.item_id for r in rows],
        profile,
        force_refresh=force_refresh,
        html_overrides=item_html_by_id,
        name_hints=name_hints,
        allow_network=live_items,
    )

    augs: list[AugCandidate] = []
    seen: set[int] = set()
    for row in rows:
        if row.item_id in seen:
            continue
        seen.add(row.item_id)
        aug = hydrated.get(row.item_id)
        if aug is not None and not is_type78_aug(aug):
            continue
        if aug is None:
            augs.append(_row_to_candidate(row, profile))
            continue
        stats = merge_stats(row.stats, aug.effective_stats())
        focus, ac, hp, atk = legacy_from_stats(stats, profile)
        augs.append(
            replace(
                aug,
                focus_heroic=focus or aug.focus_heroic,
                ac=ac or aug.ac,
                hp=hp or aug.hp,
                atk=atk or aug.atk,
                stats=stats,
                source=aug.source or "EQ Resource",
            )
        )

    augs.sort(key=lambda a: (-a.focus_heroic, -a.hp, -a.ac, a.name.casefold()))
    return CatalogResult(
        profile=profile,
        augs=augs,
        fetched_at=now,
        from_cache=from_cache,
        warning=warning,
        url=url,
    )
