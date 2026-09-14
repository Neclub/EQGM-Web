"""Raid vendor currency, ore/component costs, and best-purchase knapsack."""

from __future__ import annotations

import re
from dataclasses import dataclass

from inventory_parser.raid_bis.models import (
    RaidGearCandidate,
    RaidVendorCatalog,
    RaidVendorItem,
    slot_base,
)

# Current-expansion fallback when the vendor page does not parse a currency name.
_CURRENCY_BY_HOST = {
    "sor.eqresource.com": "Forgotten Ruined Coin",
}

_CURRENCY_RE = re.compile(
    r"Alternate Currency:.*?<a\s+href=[^>]*items\.php\?id=(\d+)[^>]*>([^<]+)</a>",
    re.IGNORECASE | re.DOTALL,
)
_CURRENCY_ICON_RE = re.compile(
    r"Alternate Currency:.*?itemimages/(\d+)\.(?:png|gif|jpg|webp)",
    re.IGNORECASE | re.DOTALL,
)
_ITEM_LINK_RE = re.compile(
    r"<a\s+href=(?:\"|')?(?:https?://items\.eqresource\.com/)?items\.php\?id=(\d+)(?:\"|')?>([^<]+)</a>",
    re.IGNORECASE,
)
_ORE_HINT_RE = re.compile(
    r"\bore\b|armor lining|polishing cloth|fastener|clasp|buckle|"
    r"enarmes|string serving|essence of|core of",
    re.IGNORECASE,
)
_FINISHED_ORE_NAME_RE = re.compile(r"tourmaline earring", re.IGNORECASE)
_SKIP_VENDOR_RE = re.compile(
    r"crate of|mirrorshard of relic|emblem of|riven arcana",
    re.IGNORECASE,
)
_DIMINISHED_RE = re.compile(r"\bdiminished\b", re.IGNORECASE)

_ORE_SLOT_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "Head": (re.compile(r"head armor lining", re.I), re.compile(r"\bhead\b.*\bore\b", re.I)),
    "Chest": (re.compile(r"chest armor lining", re.I), re.compile(r"\bchest\b.*\bore\b", re.I)),
    "Arms": (re.compile(r"arm(?:s)? armor lining", re.I), re.compile(r"\barms?\b.*\bore\b", re.I)),
    "Legs": (re.compile(r"leg(?:s)? armor lining", re.I), re.compile(r"\blegs?\b.*\bore\b", re.I)),
    "Hands": (re.compile(r"hand(?:s)? armor lining", re.I), re.compile(r"\bhands?\b.*\bore\b", re.I)),
    "Feet": (
        re.compile(r"(?:feet|foot) armor lining", re.I),
        re.compile(r"\bfeet\b.*\bore\b", re.I),
    ),
    "Wrist": (re.compile(r"wrist armor lining", re.I), re.compile(r"\bwrist\b.*\bore\b", re.I)),
    "Shoulders": (re.compile(r"amice fastener", re.I), re.compile(r"\bshoulder\b.*\bore\b", re.I)),
    "Back": (re.compile(r"cloak fastener", re.I), re.compile(r"\b(?:cloak|back)\b.*\bore\b", re.I)),
    "Waist": (re.compile(r"belt buckle", re.I), re.compile(r"\b(?:belt|waist)\b.*\bore\b", re.I)),
    "Face": (re.compile(r"mask fastener", re.I), re.compile(r"\b(?:mask|face)\b.*\bore\b", re.I)),
    "Neck": (re.compile(r"necklace clasp", re.I), re.compile(r"\b(?:neck|necklace)\b.*\bore\b", re.I)),
    "Ear": (re.compile(r"earring clasp", re.I), re.compile(r"\bear(?:ring)?\b.*\bore\b", re.I)),
    "Fingers": (
        re.compile(r"ring polishing cloth", re.I),
        re.compile(r"\bring\b.*\bore\b", re.I),
    ),
    "Charm": (
        re.compile(r"charm polishing cloth", re.I),
        re.compile(r"\bcharm\b.*\bore\b", re.I),
    ),
    "Range": (
        re.compile(r"idol polishing cloth", re.I),
        re.compile(r"\b(?:range|idol)\b.*\bore\b", re.I),
    ),
}

_DIMINISHED_SLOT_PATTERNS: dict[str, re.Pattern[str]] = {
    "Head": re.compile(r"\bhead armor\b", re.I),
    "Chest": re.compile(r"\bchest armor\b", re.I),
    "Arms": re.compile(r"\barms armor\b", re.I),
    "Legs": re.compile(r"\blegs armor\b", re.I),
    "Hands": re.compile(r"\bhands armor\b", re.I),
    "Feet": re.compile(r"\bfeet armor\b", re.I),
    "Wrist": re.compile(r"\bwrist armor\b", re.I),
}

_ARMOR_SLOTS = frozenset(_DIMINISHED_SLOT_PATTERNS)


@dataclass(frozen=True)
class PurchaseCandidate:
    gear_slot: str
    cost: int
    score_gain: float
    item_id: int = 0
    name: str = ""


def is_ore_name(name: str) -> bool:
    """True for vendor tradeskill components (ore, lining, clasp, etc.)."""
    text = name or ""
    if _FINISHED_ORE_NAME_RE.search(text):
        return False
    return bool(_ORE_HINT_RE.search(text))


def parse_currency(html: str, *, url: str = "") -> tuple[str, int | None, str | None]:
    """Return (currency name, item id, icon id) from a raid vendor page."""
    icon_id = None
    icon_m = _CURRENCY_ICON_RE.search(html or "")
    if icon_m:
        icon_id = icon_m.group(1)
    match = _CURRENCY_RE.search(html or "")
    if match:
        currency_id = int(match.group(1))
        name = re.sub(r"\s+", " ", match.group(2)).strip()
        if name:
            return name, currency_id, icon_id
    host = ""
    if url:
        host_m = re.search(r"https?://([^/]+)", url, re.I)
        host = (host_m.group(1).casefold() if host_m else "").removeprefix("www.")
    return _CURRENCY_BY_HOST.get(host, "Raid coins"), None, icon_id


def parse_raidvendor_html(html: str, *, url: str = "") -> RaidVendorCatalog:
    """Parse EQ Resource raid vendor rows: item name, id, and coin cost."""
    currency_name, currency_id, currency_icon_id = parse_currency(html, url=url)
    items: list[RaidVendorItem] = []
    seen: set[int] = set()
    if not html:
        return RaidVendorCatalog(
            currency_name=currency_name,
            currency_id=currency_id,
            currency_icon_id=currency_icon_id,
            url=url,
        )
    for row_m in re.finditer(r"<tr\b[^>]*>(.*?)</tr>", html, re.IGNORECASE | re.DOTALL):
        row = row_m.group(1)
        cells = re.findall(r"<td\b[^>]*>(.*?)</td>", row, re.IGNORECASE | re.DOTALL)
        if len(cells) < 3:
            continue
        link = _ITEM_LINK_RE.search(cells[1])
        if not link:
            continue
        item_id = int(link.group(1))
        if currency_id is not None and item_id == currency_id:
            continue
        name = re.sub(r"\s+", " ", link.group(2)).strip()
        if not name or item_id in seen or _SKIP_VENDOR_RE.search(name):
            continue
        cost_m = re.search(r"(\d+)", cells[2])
        if not cost_m:
            continue
        cost = int(cost_m.group(1))
        if cost <= 0:
            continue
        seen.add(item_id)
        items.append(
            RaidVendorItem(
                item_id=item_id,
                name=name,
                cost=cost,
                is_ore=is_ore_name(name),
            )
        )
    return RaidVendorCatalog(
        currency_name=currency_name,
        currency_id=currency_id,
        currency_icon_id=currency_icon_id,
        items=items,
        url=url,
    )


def _is_t2(item: RaidGearCandidate) -> bool:
    if (item.tier or "").strip().upper() == "T2":
        return True
    return "resonant fracture" in (item.name or "").casefold()


def _is_t1(item: RaidGearCandidate) -> bool:
    if (item.tier or "").strip().upper() == "T1":
        return True
    return "shattered dominion" in (item.name or "").casefold()


def _match_slot_item(
    items: list[RaidVendorItem],
    patterns: tuple[re.Pattern[str], ...] | re.Pattern[str],
    *,
    ore_only: bool | None = None,
    diminished: bool = False,
) -> RaidVendorItem | None:
    pats = patterns if isinstance(patterns, tuple) else (patterns,)
    for item in items:
        if ore_only is True and not item.is_ore:
            continue
        if ore_only is False and item.is_ore:
            continue
        if diminished and not _DIMINISHED_RE.search(item.name):
            continue
        if any(p.search(item.name) for p in pats):
            return item
    return None


def ore_for_slot(vendor: RaidVendorCatalog, gear_slot: str) -> RaidVendorItem | None:
    base = slot_base(gear_slot)
    patterns = _ORE_SLOT_PATTERNS.get(base)
    if not patterns:
        return None
    return _match_slot_item(vendor.items, patterns, ore_only=True)


def diminished_for_slot(vendor: RaidVendorCatalog, gear_slot: str) -> RaidVendorItem | None:
    base = slot_base(gear_slot)
    pattern = _DIMINISHED_SLOT_PATTERNS.get(base)
    if not pattern:
        return None
    return _match_slot_item(vendor.items, pattern, diminished=True)


def vendor_offer_for_item(
    item: RaidGearCandidate | None,
    gear_slot: str,
    vendor: RaidVendorCatalog | None,
) -> RaidVendorItem | None:
    """Map a BiS recommendation to the raid-vendor purchase (ore for T2)."""
    if item is None or vendor is None or not vendor.items:
        return None
    by_id = {v.item_id: v for v in vendor.items if v.item_id > 0}
    by_name = {v.name.casefold(): v for v in vendor.items}

    direct = None
    if item.item_id > 0:
        direct = by_id.get(item.item_id)
    if direct is None:
        direct = by_name.get((item.name or "").casefold())
    if direct is not None and direct.is_ore:
        direct = None

    # T2 BiS is crafted; buy the slot's vendor ore/lining, not the finished item.
    if _is_t2(item):
        ore = ore_for_slot(vendor, gear_slot)
        if ore is not None:
            return ore
        return direct

    if direct is not None:
        return direct

    if _is_t1(item) and slot_base(gear_slot) in _ARMOR_SLOTS:
        return diminished_for_slot(vendor, gear_slot)
    return None


def best_purchases(
    candidates: list[PurchaseCandidate],
    coins: int,
) -> list[PurchaseCandidate]:
    """0-1 knapsack: max score gain, then more items, then lower total cost.

    Keep in sync with ``raidBisBestPurchases`` in team_report.html.
    """
    try:
        budget = int(coins)
    except (TypeError, ValueError):
        return []
    if budget <= 0:
        return []
    affordable = [
        c
        for c in candidates
        if c.cost > 0 and c.score_gain > 0 and c.cost <= budget
    ]
    n = len(affordable)
    if n == 0:
        return []
    if n > 20:
        affordable = sorted(
            affordable, key=lambda c: (-c.score_gain / c.cost, -c.score_gain, c.cost)
        )[:20]
        n = len(affordable)
    best_gain = -1.0
    best_count = -1
    best_cost = 0
    best_mask = 0
    for mask in range(1, 1 << n):
        cost = 0
        gain = 0.0
        count = 0
        over = False
        for i in range(n):
            if not (mask & (1 << i)):
                continue
            cost += affordable[i].cost
            if cost > budget:
                over = True
                break
            gain += affordable[i].score_gain
            count += 1
        if over:
            continue
        better = gain > best_gain + 1e-9
        if not better and abs(gain - best_gain) <= 1e-9:
            if count > best_count:
                better = True
            elif count == best_count and cost < best_cost:
                better = True
        if better:
            best_gain = gain
            best_count = count
            best_cost = cost
            best_mask = mask
    return [affordable[i] for i in range(n) if best_mask & (1 << i)]


def vendor_catalog_to_dict(vendor: RaidVendorCatalog | None) -> dict | None:
    if vendor is None:
        return None
    return {
        "currencyName": vendor.currency_name,
        "currencyId": vendor.currency_id,
        "currencyIconId": vendor.currency_icon_id,
        "url": vendor.url,
        "warning": vendor.warning,
        "items": [
            {
                "itemId": i.item_id,
                "name": i.name,
                "cost": i.cost,
                "isOre": i.is_ore,
            }
            for i in vendor.items
        ],
    }


def vendor_catalog_from_dict(raw: dict | None) -> RaidVendorCatalog | None:
    if not raw or not isinstance(raw, dict):
        return None
    items = []
    for row in raw.get("items") or []:
        try:
            item_id = int(row.get("item_id") or row.get("itemId") or 0)
            cost = int(row.get("cost") or 0)
            name = str(row.get("name") or "").strip()
        except (TypeError, ValueError):
            continue
        if item_id <= 0 or cost <= 0 or not name:
            continue
        items.append(
            RaidVendorItem(
                item_id=item_id,
                name=name,
                cost=cost,
                is_ore=bool(row.get("is_ore", row.get("isOre", is_ore_name(name)))),
            )
        )
    currency_id = raw.get("currency_id", raw.get("currencyId"))
    try:
        currency_id_int = int(currency_id) if currency_id not in (None, "") else None
    except (TypeError, ValueError):
        currency_id_int = None
    icon_raw = raw.get("currency_icon_id", raw.get("currencyIconId"))
    icon_id = str(icon_raw).strip() if icon_raw not in (None, "") else None
    if icon_id and not icon_id.isdigit():
        icon_id = None
    return RaidVendorCatalog(
        currency_name=str(raw.get("currency_name") or raw.get("currencyName") or "").strip(),
        currency_id=currency_id_int,
        currency_icon_id=icon_id,
        items=items,
        fetched_at=str(raw.get("fetched_at") or raw.get("fetchedAt") or ""),
        warning=raw.get("warning"),
        url=str(raw.get("url") or ""),
    )
