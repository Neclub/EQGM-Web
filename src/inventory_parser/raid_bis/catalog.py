"""Fetch and parse current-expansion raid armor/jewelry from EQ Resource."""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

from inventory_parser.raid_bis.models import (
    ALL_CLASS_ABBRS,
    ARMOR_SLOT_HEADERS,
    JEWELRY_TYPE_SLOTS,
    RaidBisCatalog,
    RaidGearCandidate,
    RaidVendorCatalog,
)
from inventory_parser.raid_bis.vendor import (
    parse_raidvendor_html,
    vendor_catalog_from_dict,
    vendor_catalog_to_dict,
)
from inventory_parser.slot2_augs.aug_stats import clean_stats, merge_stats
from inventory_parser.slot2_augs.chest_class import parse_eqresource_item_class_set
from inventory_parser.slot2_augs.eqresource_augs import (
    EQRESOURCE_ITEM_URL,
    USER_AGENT,
    _NAME_RE,
    _SLOT_RE,
    _allowed_from_eqr_slot_text,
    _stats_from_eqr_html,
    parse_eqresource_lore_group,
)
from inventory_parser.http_fetch import http_get_text
from inventory_parser.slot2_augs.paths import appdata_dir

CACHE_FILENAME = "raid_bis_catalog.json"
ITEM_CACHE_FILENAME = "raid_bis_item_cache.json"
ITEM_CACHE_VERSION = 8
_CLASS_ALL_TOKEN = "ALL"
_CATALOG_FETCH_WORKERS = 6
RAIDARMOR_URL = "https://sor.eqresource.com/raidarmor.php"
RAIDGEAR_URL = "https://sor.eqresource.com/raidgear.php"
RAIDVENDOR_URL = "https://sor.eqresource.com/raidvendorgood.php"
RAIDLOOT_SEARCH_URL = "https://www.raidloot.com/items"

StatusFn = Callable[[str, int, int], None]


def _emit_status(
    on_status: StatusFn | None,
    message: str,
    done: int = 0,
    total: int = 1,
) -> None:
    if on_status is not None:
        on_status(message, done, total)


_ITEM_HREF_RE = re.compile(r"items\.php\?id=(\d+)", re.IGNORECASE)
_ICON_RE = re.compile(r"itemimages/(\d+)\.(?:png|gif|jpg|webp)", re.IGNORECASE)
_FOCUS_RE = re.compile(
    r"Focus:\s*(?:<[^>]+>\s*)*([^<\n]+)",
    re.IGNORECASE,
)
_EFFECT_RE = re.compile(
    r"Effect:\s*(?:<[^>]+>\s*)*([^<\n]+)",
    re.IGNORECASE,
)
_TIER_HEAD_RE = re.compile(
    r'<a\s+name="tier(\d+)"></a>.*?<font[^>]*>\s*Tier\s+\d+\s+-\s*([^<]+)',
    re.IGNORECASE | re.DOTALL,
)
_RAIDARMOR_STUB_NAME_RE = re.compile(r"^[A-Z]{3} \w+$")
# Catalog-only: do not recommend crates, linings, emblems, or vendor junk.
# Equipped items still hydrate (Power Source names include "Riven Arcana").
_SKIP_NAME_RE = re.compile(
    r"diminished|riven arcana|emblem of|crate of|armor lining|fractured armor",
    re.IGNORECASE,
)
_HEADER_TO_STAT = {
    "ac": "ac",
    "hp": "hp",
    "mana": "mana",
    "end": "endurance",
    "hstr": "hstr",
    "hsta": "hsta",
    "hint": "hint",
    "hwis": "hwis",
    "hagi": "hagi",
    "hdex": "hdex",
    "hcha": "hcha",
    "spell dmg": "spell_damage",
    "spell damage": "spell_damage",
}


def cache_path() -> Path:
    return appdata_dir() / CACHE_FILENAME


def item_cache_path() -> Path:
    return appdata_dir() / ITEM_CACHE_FILENAME


def _http_get(url: str, timeout: float = 45.0) -> str:
    return http_get_text(url, timeout=timeout, user_agent=USER_AGENT)


def _load_item_cache() -> dict:
    data = _load_json(item_cache_path())
    if int(data.get("_version") or 0) != ITEM_CACHE_VERSION:
        return {}
    return {k: v for k, v in data.items() if k != "_version"}


def _save_item_cache(cache: dict) -> None:
    payload = dict(cache)
    payload["_version"] = ITEM_CACHE_VERSION
    _save_json(item_cache_path(), payload)


def _load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def should_skip_name(name: str) -> bool:
    """True when a catalog row should not be recommended as Raid BiS.

    Not used when hydrating an item the character is already wearing.
    """
    return bool(_SKIP_NAME_RE.search(name or ""))


def _is_raidarmor_stub_name(name: str) -> bool:
    return bool(_RAIDARMOR_STUB_NAME_RE.fullmatch((name or "").strip()))


def _item_needs_page_hydrate(item: RaidGearCandidate) -> bool:
    """True when the catalog row is missing class, stats, icon, or a real name."""
    if item.classes is None:
        return True
    if _is_raidarmor_stub_name(item.name) or (item.name or "").startswith("Item "):
        return True
    if not item.icon_id:
        return True
    if not item.stats:
        return True
    return False


def parse_raidarmor_html(html: str) -> list[RaidGearCandidate]:
    """Parse class × slot matrices on sor.eqresource.com/raidarmor.php."""
    if not html:
        return []
    parts = re.split(r'<a\s+name="tier(\d+)"></a>', html, flags=re.IGNORECASE)
    items: list[RaidGearCandidate] = []
    seen: set[int] = set()
    # split keeps delimiters: [pre, '1', block1, '2', block2, ...]
    i = 1
    while i + 1 < len(parts):
        tier_n = parts[i].strip()
        block = parts[i + 1]
        i += 2
        tier = f"T{tier_n}" if tier_n.isdigit() else ""
        items.extend(_parse_raidarmor_block(block, tier, seen))
    if not items:
        items.extend(_parse_raidarmor_block(html, "T1", seen))
    return items


def _parse_raidarmor_block(
    html: str, tier: str, seen: set[int]
) -> list[RaidGearCandidate]:
    out: list[RaidGearCandidate] = []
    header_slots: list[str] = []
    for row_m in re.finditer(r"<tr\b[^>]*>(.*?)</tr>", html, re.IGNORECASE | re.DOTALL):
        row = row_m.group(1)
        cells = re.findall(r"<td\b[^>]*>(.*?)</td>", row, re.IGNORECASE | re.DOTALL)
        if not cells:
            continue
        texts = [_cell_text(c) for c in cells]
        if texts and texts[0].casefold() == "class":
            header_slots = []
            for label in texts[1:]:
                mapped = ARMOR_SLOT_HEADERS.get(label.strip().casefold())
                header_slots.append(mapped or "")
            continue
        if not header_slots or len(cells) < 2:
            continue
        class_abbr = ""
        for cell in cells[1:]:
            m = re.search(r">\s*([A-Z]{3})\s*<", cell)
            if m:
                class_abbr = m.group(1).upper()
                break
        if not class_abbr:
            continue
        for idx, cell in enumerate(cells[1:]):
            if idx >= len(header_slots) or not header_slots[idx]:
                continue
            href_m = _ITEM_HREF_RE.search(cell)
            if not href_m:
                continue
            item_id = int(href_m.group(1))
            if item_id in seen:
                continue
            seen.add(item_id)
            slot = header_slots[idx]
            out.append(
                RaidGearCandidate(
                    item_id=item_id,
                    name=f"{class_abbr} {slot}",
                    classes=frozenset({class_abbr}),
                    slots=frozenset({slot}),
                    tier=tier,
                    source="EQ Resource raidarmor",
                )
            )
    return out


def _cell_text(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text).strip()


class _GearTableParser(HTMLParser):
    """Parse raidgear.php result tables: icon, name/id, numeric stats."""

    def __init__(self) -> None:
        super().__init__()
        self._in_td = False
        self._td_parts: list[str] = []
        self._td_href = ""
        self._td_icon = ""
        self._row: list[tuple[str, str, str]] = []
        self.header: list[str] = []
        self.rows: list[tuple[int, str, str | None, list[str]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        ad = dict(attrs)
        if tag == "tr":
            self._row = []
        elif tag == "td":
            self._in_td = True
            self._td_parts = []
            self._td_href = ""
            self._td_icon = ""
        elif tag == "a" and self._in_td:
            href = ad.get("href") or ""
            if href:
                self._td_href = href
        elif tag == "img" and self._in_td:
            src = ad.get("src") or ""
            m = _ICON_RE.search(src)
            if m:
                self._td_icon = m.group(1)

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self._in_td:
            self._in_td = False
            text = re.sub(r"\s+", " ", " ".join(self._td_parts)).strip()
            self._row.append((self._td_href, text, self._td_icon))
        elif tag == "tr":
            self._finish_row()

    def handle_data(self, data: str) -> None:
        if self._in_td:
            self._td_parts.append(data)

    def _finish_row(self) -> None:
        cells = self._row
        self._row = []
        if not cells:
            return
        texts = [t for _h, t, _i in cells]
        joined = " ".join(texts).casefold()
        if "item name" in joined and "ac" in joined:
            self.header = [t.strip() for t in texts]
            return
        item_id = 0
        name = ""
        icon = None
        for href, text, icon_id in cells:
            m = _ITEM_HREF_RE.search(href) or _ITEM_HREF_RE.search(text)
            if m:
                item_id = int(m.group(1))
                name = text.strip() or name
            if icon_id and not icon:
                icon = icon_id
        if item_id <= 0:
            return
        self.rows.append((item_id, name, icon, texts))


def parse_raidgear_html(
    html: str, *, default_slot: str = "", default_tier: str = ""
) -> list[RaidGearCandidate]:
    """Parse jewelry/other-slot tables from raidgear.php."""
    if not html:
        return []
    slot = default_slot or _slot_from_caption(html)
    tier = default_tier or _tier_from_caption(html)
    parser = _GearTableParser()
    try:
        parser.feed(html)
    except Exception:
        return []
    header_keys: list[str | None] = []
    for label in parser.header:
        header_keys.append(_HEADER_TO_STAT.get(label.strip().casefold()))

    out: list[RaidGearCandidate] = []
    seen: set[int] = set()
    for item_id, name, icon, texts in parser.rows:
        if item_id in seen or should_skip_name(name):
            continue
        seen.add(item_id)
        stats: dict[str, int] = {}
        if header_keys and len(texts) == len(header_keys):
            for key, raw in zip(header_keys, texts):
                if not key:
                    continue
                n = _cell_int(raw)
                if n is not None:
                    stats[key] = n
        slots = frozenset({slot}) if slot else frozenset()
        out.append(
            RaidGearCandidate(
                item_id=item_id,
                name=name or f"Item {item_id}",
                stats=clean_stats(stats),
                classes=None,
                slots=slots,
                tier=tier,
                icon_id=icon,
                source="EQ Resource raidgear",
            )
        )
    return out


def _slot_from_caption(html: str) -> str:
    m = re.search(
        r"Search results for\s*<b><font[^>]*>([^<]+)</font></b>",
        html,
        re.IGNORECASE,
    )
    if not m:
        return ""
    label = m.group(1).strip().casefold()
    mapping = {
        "back": "Back",
        "charm": "Charm",
        "ear": "Ear",
        "face": "Face",
        "finger": "Fingers",
        "fingers": "Fingers",
        "neck": "Neck",
        "range": "Range",
        "shoulder": "Shoulders",
        "shoulders": "Shoulders",
        "waist": "Waist",
    }
    return mapping.get(label, "")


def _tier_from_caption(html: str) -> str:
    m = re.search(r"Raid Tier\s+(\d+)", html, re.IGNORECASE)
    if m:
        return f"T{m.group(1)}"
    if re.search(r"Raid Tier</font></b>\s*All", html, re.IGNORECASE):
        return ""
    return ""


def _cell_int(raw: str) -> int | None:
    text = (raw or "").strip()
    if not text or not re.fullmatch(r"-?\d+", text):
        return None
    return int(text)


def _labeled_spell_names(html: str, pattern: re.Pattern[str]) -> str:
    """Collect every Effect:/Focus: name on the page (items often have click + worn)."""
    names: list[str] = []
    seen: set[str] = set()
    for match in pattern.finditer(html or ""):
        raw = re.sub(r"\s+", " ", match.group(1)).strip()
        # Drop trailing UI suffixes like "- Casting Time: 0.5s" / "- Worn" for cleaner storage,
        # but keep the spell name itself for matching.
        name = re.split(r"\s*-\s*(?:Casting Time|Worn)\b", raw, maxsplit=1, flags=re.I)[0]
        name = name.strip(" -")
        if not name:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        names.append(name)
    return "; ".join(names)


def parse_item_page(html: str, item_id: int, *, name_hint: str = "") -> RaidGearCandidate | None:
    """Hydrate stats, class, slot, focus, effect, and icon from an EQ Resource item page."""
    if not html or item_id <= 0:
        return None
    name_m = _NAME_RE.search(html)
    name = (name_m.group(1).strip() if name_m else "") or (name_hint or f"Item {item_id}")
    stats = _stats_from_eqr_html(html)
    classes = parse_eqresource_item_class_set(html)
    slot_m = _SLOT_RE.search(html)
    slot_text = slot_m.group(1).strip() if slot_m else ""
    slots = _allowed_from_eqr_slot_text(re.sub(r"\s+", " ", slot_text))
    focus = _labeled_spell_names(html, _FOCUS_RE)
    effect = _labeled_spell_names(html, _EFFECT_RE)
    icon_m = _ICON_RE.search(html)
    tier = ""
    if re.search(r"Raid\s*[-–]\s*Tier\s*2", html, re.IGNORECASE):
        tier = "T2"
    elif re.search(r"Raid\s*[-–]\s*Tier\s*1", html, re.IGNORECASE):
        tier = "T1"
    return RaidGearCandidate(
        item_id=item_id,
        name=name,
        stats=clean_stats(stats),
        classes=classes,
        slots=slots,
        tier=tier,
        lore_group=parse_eqresource_lore_group(html),
        icon_id=icon_m.group(1) if icon_m else None,
        focus=focus,
        effect=effect,
        source="EQ Resource",
    )


def _better_name(base: RaidGearCandidate, extra: RaidGearCandidate) -> str:
    extra_name = (extra.name or "").strip()
    base_name = (base.name or "").strip()
    if _is_raidarmor_stub_name(base_name) and extra_name and extra_name != base_name:
        return extra_name
    return extra_name or base_name


def merge_hydrated(base: RaidGearCandidate, extra: RaidGearCandidate) -> RaidGearCandidate:
    # Prefer the longer effect/focus string (hydrated pages list click + worn).
    focus = extra.focus if len(extra.focus or "") >= len(base.focus or "") else base.focus
    effect = extra.effect if len(extra.effect or "") >= len(base.effect or "") else base.effect
    return RaidGearCandidate(
        item_id=base.item_id,
        name=_better_name(base, extra),
        stats=merge_stats(base.stats, extra.stats),
        classes=extra.classes if extra.classes is not None else base.classes,
        slots=extra.slots or base.slots,
        tier=extra.tier or base.tier,
        lore_group=extra.lore_group or base.lore_group,
        icon_id=extra.icon_id or base.icon_id,
        focus=focus or "",
        effect=effect or "",
        source=extra.source or base.source,
    )


def raidgear_url(slot_type: str, *, tier: str = "4") -> str:
    q = urllib.parse.urlencode(
        {"class": "", "type": slot_type, "stat": "ac", "tier": tier, "Submit": "Submit"}
    )
    return f"{RAIDGEAR_URL}?{q}"


def _classes_to_stored(classes: frozenset[str] | None) -> list[str] | None:
    if classes is None:
        return None
    if not classes:
        return sorted(ALL_CLASS_ABBRS)
    return sorted(classes)


def _classes_from_stored(raw: object) -> frozenset[str] | None:
    if raw is None:
        return None
    if not isinstance(raw, list):
        return None
    tokens = [str(c).strip().upper() for c in raw if str(c).strip()]
    if not tokens:
        # Legacy cache: [] was both unhydrated jewelry and Class: All.
        # Treat as unknown so restricted items are never assumed wearable.
        return None
    if tokens == [_CLASS_ALL_TOKEN] or set(tokens) >= ALL_CLASS_ABBRS:
        return frozenset()
    return frozenset(t for t in tokens if t != _CLASS_ALL_TOKEN and t in ALL_CLASS_ABBRS)


def _candidate_to_dict(item: RaidGearCandidate) -> dict:
    stored = _classes_to_stored(item.classes)
    return {
        "item_id": item.item_id,
        "name": item.name,
        "stats": dict(item.stats),
        "classes": stored,
        "class_all": bool(item.classes is not None and not item.classes),
        "slots": sorted(item.slots),
        "tier": item.tier,
        "lore_group": item.lore_group,
        "icon_id": item.icon_id,
        "focus": item.focus,
        "effect": item.effect,
        "source": item.source,
    }


def _candidate_from_dict(raw: dict) -> RaidGearCandidate:
    if raw.get("class_all"):
        classes: frozenset[str] | None = frozenset()
    else:
        classes = _classes_from_stored(raw.get("classes"))
    return RaidGearCandidate(
        item_id=int(raw["item_id"]),
        name=str(raw.get("name") or f"Item {raw['item_id']}"),
        stats=clean_stats(raw.get("stats") or {}),
        classes=classes,
        slots=frozenset(str(s) for s in (raw.get("slots") or [])),
        tier=str(raw.get("tier") or ""),
        lore_group=raw.get("lore_group"),
        icon_id=raw.get("icon_id"),
        focus=str(raw.get("focus") or ""),
        effect=str(raw.get("effect") or ""),
        source=str(raw.get("source") or "EQ Resource"),
    )


def _entry_has_inspect(entry: dict | None) -> bool:
    if not isinstance(entry, dict):
        return False
    raw = entry.get("inspect")
    return isinstance(raw, dict) and bool(str(raw.get("name") or "").strip())


def _item_cache_entry(
    item: RaidGearCandidate,
    *,
    inspect: object | None = None,
    inspect_raw: dict | None = None,
    fetched_at: str | None = None,
) -> dict:
    payload = _candidate_to_dict(item)
    entry = {
        "ok": True,
        "fetched_at": fetched_at or datetime.now(timezone.utc).isoformat(),
        "classes": payload["classes"],
        "class_all": payload["class_all"],
        "item": payload,
    }
    if inspect is not None:
        from inventory_parser.item_inspect import inspect_to_dict

        stored = inspect_to_dict(inspect)
        stored["itemId"] = item.item_id
        entry["inspect"] = stored
    elif isinstance(inspect_raw, dict) and inspect_raw.get("name"):
        entry["inspect"] = dict(inspect_raw)
    return entry


def _cached_item_from_entry(entry: dict) -> RaidGearCandidate | None:
    raw = entry.get("item")
    if not isinstance(raw, dict) or not raw.get("item_id"):
        return None
    if raw.get("classes") is None and entry.get("classes") is not None:
        raw = {
            **raw,
            "classes": entry.get("classes"),
            "class_all": entry.get("class_all"),
        }
    return _candidate_from_dict(raw)


def _item_cache_classes_stale(entry: dict | None, item: RaidGearCandidate) -> bool:
    if not entry or not entry.get("ok"):
        return True
    cached = _cached_item_from_entry(entry)
    if cached is None:
        return True
    return cached.classes != item.classes


def fetch_catalog(
    *,
    force_refresh: bool = False,
    allow_network: bool = True,
    html_overrides: dict[str, str] | None = None,
    item_html_by_id: dict[int, str] | None = None,
    polite_delay_s: float = 0.05,
    hydrate: bool = True,
    on_status: StatusFn | None = None,
) -> RaidBisCatalog:
    """Build the current-expansion raid armor + jewelry catalog."""
    now = datetime.now(timezone.utc).isoformat()
    html_overrides = html_overrides or {}
    item_html_by_id = item_html_by_id or {}
    cache = _load_json(cache_path())
    warning: str | None = None
    urls: list[str] = [RAIDARMOR_URL, RAIDVENDOR_URL]
    items: list[RaidGearCandidate] = []
    from_cache = False
    vendor: RaidVendorCatalog | None = None
    use_overrides = bool(html_overrides)
    cached = cache.get("catalog") if not force_refresh else None
    cached_items = cached.get("items") if isinstance(cached, dict) else None

    if (
        not use_overrides
        and isinstance(cached_items, list)
        and len(cached_items) > 0
    ):
        items = [_candidate_from_dict(d) for d in cached_items]
        from_cache = True
        urls = list(cached.get("urls") or urls)
        vendor = vendor_catalog_from_dict(cache.get("vendor"))
        _emit_status(on_status, "Using cached Raid BiS catalog…")
    else:
        try:
            _emit_status(on_status, "Fetching from EQ Resource…")
            armor_html = html_overrides.get("raidarmor")
            if armor_html is None:
                if not allow_network:
                    raise RuntimeError("network disabled")
                armor_html = _http_get(RAIDARMOR_URL)
            items.extend(parse_raidarmor_html(armor_html))

            def _jewelry_job(
                slot_type: str, slot_name: str
            ) -> tuple[str, list[RaidGearCandidate]]:
                key = f"raidgear:{slot_type}"
                url = raidgear_url(slot_type)
                gear_html = html_overrides.get(key)
                if gear_html is None:
                    if not allow_network:
                        return url, []
                    gear_html = _http_get(url)
                return url, parse_raidgear_html(gear_html, default_slot=slot_name)

            if use_overrides or _CATALOG_FETCH_WORKERS <= 1:
                for slot_type, slot_name in JEWELRY_TYPE_SLOTS:
                    url, parsed = _jewelry_job(slot_type, slot_name)
                    urls.append(url)
                    items.extend(parsed)
            else:
                with ThreadPoolExecutor(max_workers=_CATALOG_FETCH_WORKERS) as pool:
                    futures = [
                        pool.submit(_jewelry_job, slot_type, slot_name)
                        for slot_type, slot_name in JEWELRY_TYPE_SLOTS
                    ]
                    for fut in as_completed(futures):
                        url, parsed = fut.result()
                        urls.append(url)
                        items.extend(parsed)
            if not items:
                raise ValueError("EQ Resource raid catalog returned no items")
            vendor = _load_vendor(
                html_overrides=html_overrides,
                allow_network=allow_network,
                polite_delay_s=polite_delay_s,
                cache=cache,
                now=now,
                force_refresh=force_refresh,
            )
            if html_overrides or allow_network:
                cache["catalog"] = {
                    "fetched_at": now,
                    "urls": urls,
                    "items": [_candidate_to_dict(i) for i in items],
                }
                if vendor is not None:
                    cache["vendor"] = vendor_catalog_to_dict(vendor)
                    cache["vendor"]["fetched_at"] = now
                if not html_overrides:
                    _save_json(cache_path(), cache)
        except (
            urllib.error.URLError,
            TimeoutError,
            ValueError,
            OSError,
            RuntimeError,
        ) as exc:
            cached = cache.get("catalog") if not force_refresh else None
            if cached and cached.get("items"):
                items = [_candidate_from_dict(d) for d in cached["items"]]
                from_cache = True
                warning = (
                    f"Live EQ Resource raid catalog failed ({exc}); using cache."
                )
                vendor = vendor_catalog_from_dict(cache.get("vendor"))
                _emit_status(on_status, "Using cached Raid BiS catalog…")
            else:
                _emit_status(on_status, "Fetching from raidloot.com…")
                fallback = _raidloot_fallback(
                    allow_network=allow_network and not html_overrides,
                    html_overrides=html_overrides,
                )
                if fallback:
                    items = fallback
                    warning = (
                        f"EQ Resource raid catalog failed ({exc}); "
                        "using raidloot fallback."
                    )
                    vendor = _load_vendor(
                        html_overrides=html_overrides,
                        allow_network=allow_network,
                        polite_delay_s=polite_delay_s,
                        cache=cache,
                        now=now,
                        force_refresh=force_refresh,
                    )
                else:
                    return RaidBisCatalog(
                        items=[],
                        fetched_at=now,
                        from_cache=False,
                        warning=f"Raid BiS catalog failed ({exc}).",
                        urls=urls,
                        vendor=_load_vendor(
                            html_overrides=html_overrides,
                            allow_network=False,
                            polite_delay_s=0,
                            cache=cache,
                            now=now,
                            force_refresh=force_refresh,
                        ),
                    )

    by_id: dict[int, RaidGearCandidate] = {}
    for item in items:
        by_id.setdefault(item.item_id, item)

    if hydrate:
        hydrate_network = bool(allow_network) and not html_overrides
        hydrated = _hydrate_items(
            list(by_id.values()),
            item_html_by_id=item_html_by_id,
            allow_network=hydrate_network,
            skip_hydrated=from_cache,
            polite_delay_s=polite_delay_s,
            on_status=on_status,
        )
        for item_id, extra in hydrated.items():
            base = by_id.get(item_id)
            if base is None:
                by_id[item_id] = extra
            else:
                by_id[item_id] = merge_hydrated(base, extra)
        if not html_overrides and (allow_network or from_cache):
            cache["catalog"] = {
                "fetched_at": cache.get("catalog", {}).get("fetched_at") or now,
                "urls": urls,
                "items": [_candidate_to_dict(i) for i in by_id.values()],
            }
            if vendor is not None:
                cache["vendor"] = vendor_catalog_to_dict(vendor)
                cache["vendor"]["fetched_at"] = now
            _save_json(cache_path(), cache)
            if allow_network:
                _backfill_item_cache_classes(list(by_id.values()))

    ready = [i for i in by_id.values() if i.item_id > 0 and not should_skip_name(i.name)]
    if vendor is None:
        vendor = _load_vendor(
            html_overrides=html_overrides,
            allow_network=allow_network and not html_overrides and not from_cache,
            polite_delay_s=polite_delay_s,
            cache=cache,
            now=now,
            force_refresh=force_refresh,
        )
    return RaidBisCatalog(
        items=ready,
        fetched_at=now,
        from_cache=from_cache,
        warning=warning,
        urls=urls,
        vendor=vendor,
    )


def _load_vendor(
    *,
    html_overrides: dict[str, str],
    allow_network: bool,
    polite_delay_s: float,
    cache: dict,
    now: str,
    force_refresh: bool,
) -> RaidVendorCatalog | None:
    html = html_overrides.get("raidvendor")
    if html is None and allow_network:
        if polite_delay_s > 0:
            time.sleep(polite_delay_s)
        try:
            html = _http_get(RAIDVENDOR_URL)
        except (urllib.error.URLError, TimeoutError, OSError):
            html = None
    if html:
        vendor = parse_raidvendor_html(html, url=RAIDVENDOR_URL)
        vendor.fetched_at = now
        if vendor.items or vendor.currency_name:
            return vendor
    if html_overrides or force_refresh:
        return None
    return vendor_catalog_from_dict(cache.get("vendor"))


def _backfill_item_cache_classes(items: list[RaidGearCandidate]) -> None:
    """Persist usable class lists onto per-item cache entries."""
    item_cache = _load_item_cache()
    dirty = False
    for item in items:
        if item.item_id <= 0 or item.classes is None:
            continue
        if _item_needs_page_hydrate(item):
            continue
        key = str(item.item_id)
        if not _item_cache_classes_stale(item_cache.get(key), item):
            continue
        prior = item_cache.get(key) if isinstance(item_cache.get(key), dict) else {}
        prior_inspect = prior.get("inspect") if isinstance(prior.get("inspect"), dict) else None
        item_cache[key] = _item_cache_entry(
            item,
            inspect_raw=prior_inspect,
            fetched_at=str(prior.get("fetched_at") or "") or None,
        )
        dirty = True
    if dirty:
        _save_item_cache(item_cache)


def _hydrate_items(
    items: list[RaidGearCandidate],
    *,
    item_html_by_id: dict[int, str],
    allow_network: bool,
    polite_delay_s: float,
    skip_hydrated: bool = False,
    on_status: StatusFn | None = None,
) -> dict[int, RaidGearCandidate]:
    item_cache = _load_item_cache()
    out: dict[int, RaidGearCandidate] = {}
    fetched = 0
    cache_dirty = False
    network_ids: list[int] = []
    for item in items:
        if item.item_id <= 0:
            continue
        if item.item_id in item_html_by_id:
            continue
        key = str(item.item_id)
        entry = item_cache.get(key)
        if isinstance(entry, dict) and entry.get("ok"):
            cached_item = _cached_item_from_entry(entry)
            if cached_item is not None and (
                not _item_needs_page_hydrate(cached_item) or not allow_network
            ):
                if _entry_has_inspect(entry) or not allow_network:
                    continue
        if not allow_network:
            continue
        if skip_hydrated and not _item_needs_page_hydrate(item):
            continue
        network_ids.append(item.item_id)
    network_total = len(network_ids)
    if on_status is not None:
        if network_total:
            _emit_status(
                on_status,
                "Fetching item details from EQ Resource…",
                0,
                network_total,
            )
        elif items:
            _emit_status(on_status, "Using cached item details…", 1, 1)
    for item in items:
        key = str(item.item_id)
        html = item_html_by_id.get(item.item_id)
        parsed: RaidGearCandidate | None = None
        inspect = None
        if html is not None:
            from inventory_parser.item_inspect import parse_item_inspect

            parsed = parse_item_page(html, item.item_id, name_hint=item.name)
            inspect = parse_item_inspect(html, item.item_id, name_hint=item.name)
        if parsed is None and key in item_cache and item_cache[key].get("ok"):
            cached_item = _cached_item_from_entry(item_cache[key])
            if cached_item is not None and (
                not _item_needs_page_hydrate(cached_item) or not allow_network
            ):
                if _entry_has_inspect(item_cache[key]) or not allow_network:
                    parsed = cached_item
        if parsed is None and allow_network:
            if skip_hydrated and not _item_needs_page_hydrate(item):
                continue
            if fetched and polite_delay_s > 0:
                time.sleep(polite_delay_s)
            try:
                html = _http_get(EQRESOURCE_ITEM_URL.format(item_id=item.item_id))
                from inventory_parser.item_inspect import parse_item_inspect

                parsed = parse_item_page(html, item.item_id, name_hint=item.name)
                inspect = parse_item_inspect(html, item.item_id, name_hint=item.name)
            except (urllib.error.URLError, TimeoutError, OSError, ValueError):
                parsed = None
                inspect = None
            fetched += 1
            _emit_status(
                on_status,
                f"Fetching item details from EQ Resource… ({fetched}/{network_total})",
                fetched,
                max(network_total, 1),
            )
            item_cache[key] = (
                _item_cache_entry(parsed, inspect=inspect)
                if parsed is not None
                else {
                    "ok": False,
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "classes": None,
                    "class_all": False,
                    "item": None,
                }
            )
            cache_dirty = True
        elif parsed is not None and inspect is not None:
            prior = item_cache.get(key) if isinstance(item_cache.get(key), dict) else {}
            item_cache[key] = _item_cache_entry(
                parsed,
                inspect=inspect,
                fetched_at=str(prior.get("fetched_at") or "") or None,
            )
            cache_dirty = True
        if parsed is not None:
            out[item.item_id] = parsed
            if parsed.classes is not None and _item_cache_classes_stale(
                item_cache.get(key), parsed
            ):
                prior = item_cache.get(key) if isinstance(item_cache.get(key), dict) else {}
                item_cache[key] = _item_cache_entry(
                    parsed,
                    inspect=inspect,
                    inspect_raw=prior.get("inspect") if inspect is None else None,
                )
                cache_dirty = True
    if cache_dirty and allow_network:
        _save_item_cache(item_cache)
    return out


def hydrate_item_ids(
    item_ids: list[int],
    *,
    item_html_by_id: dict[int, str] | None = None,
    allow_network: bool = True,
    polite_delay_s: float = 0.05,
    on_status: StatusFn | None = None,
) -> dict[int, RaidGearCandidate]:
    """Fetch/cache EQ Resource pages for equipped items not already in the catalog."""
    stubs = [RaidGearCandidate(item_id=i, name=f"Item {i}") for i in item_ids if i > 0]
    return _hydrate_items(
        stubs,
        item_html_by_id=item_html_by_id or {},
        allow_network=allow_network,
        polite_delay_s=polite_delay_s,
        on_status=on_status,
    )


def _raidloot_fallback(
    *,
    allow_network: bool,
    html_overrides: dict[str, str],
) -> list[RaidGearCandidate]:
    html = html_overrides.get("raidloot")
    if html is None:
        if not allow_network:
            return []
        try:
            q = urllib.parse.urlencode(
                {"type": "Armor", "source": "Shattering of Ro", "order": "AC"}
            )
            html = _http_get(f"{RAIDLOOT_SEARCH_URL}?{q}")
        except (urllib.error.URLError, TimeoutError, OSError):
            return []
    return parse_raidloot_armor_html(html)


def parse_raidloot_armor_html(html: str) -> list[RaidGearCandidate]:
    """Minimal raidloot item-table parser used only as a catalog fallback."""
    if not html:
        return []
    out: list[RaidGearCandidate] = []
    seen: set[int] = set()
    for m in re.finditer(
        r'href="[^"]*[?&]id=(\d+)[^"]*"[^>]*>([^<]+)',
        html,
        re.IGNORECASE,
    ):
        item_id = int(m.group(1))
        name = re.sub(r"\s+", " ", m.group(2)).strip()
        if item_id in seen or not name or should_skip_name(name):
            continue
        seen.add(item_id)
        out.append(
            RaidGearCandidate(
                item_id=item_id,
                name=name,
                source="raidloot",
            )
        )
    if out:
        return out
    for m in re.finditer(
        r"items\.php\?id=(\d+)[^<]*>([^<]+)",
        html,
        re.IGNORECASE,
    ):
        item_id = int(m.group(1))
        name = re.sub(r"\s+", " ", m.group(2)).strip()
        if item_id in seen or should_skip_name(name):
            continue
        seen.add(item_id)
        out.append(
            RaidGearCandidate(item_id=item_id, name=name, source="raidloot")
        )
    return out
