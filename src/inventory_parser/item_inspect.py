"""Parse EQ Resource item pages into inspect-card payloads for HTML reports."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from html import unescape

from inventory_parser.raid_bis.icons import collect_icon_data_uris
from inventory_parser.slot2_augs.eqresource_augs import (
    USER_AGENT,
    _ATTR_BLOCK_RE,
    _ATTR_LABEL_RE,
    _ATTR_NAMES,
    _ATK_BLOCK_RE,
    _EXPAC_IMG_RE,
    _HEROIC_VAL_RE,
    _NAME_RE,
    _SLOT_RE,
)
from inventory_parser.slot2_augs.build import report_progress
from inventory_parser.team_report import TeamGearReport

ProgressFn = Callable[[dict], None]
StatusFn = Callable[[str, int, int], None]

_ICON_RE = re.compile(r"itemimages/(\d+)\.(?:png|gif|jpg|webp)", re.IGNORECASE)
_FOCUS_RE = re.compile(
    r"Focus:\s*(?:<[^>]+>\s*)*([^<\n]+)",
    re.IGNORECASE,
)

_FLAG_LINE_RE = re.compile(
    r"((?:Magic|Lore|No Trade|No Drop|Prestige|Artifact|Quest|Temporary|"
    r"Attuneable|Heirloom|Evolving|Placeable|Tradeskills)"
    r"(?:\s*,\s*(?:Magic|Lore|No Trade|No Drop|Prestige|Artifact|Quest|"
    r"Temporary|Attuneable|Heirloom|Evolving|Placeable|Tradeskills))*)"
    r"\s*<br>\s*Class:",
    re.IGNORECASE,
)
_CLASS_RE = re.compile(r"Class:\s*([^<\n]+)", re.IGNORECASE)
_RACE_RE = re.compile(r"Race:\s*([^<\n]+)", re.IGNORECASE)
_TIER_CAPTION_RE = re.compile(
    r"<center>\s*((?:Raid|Group)\s*[-–]\s*Tier\s*\d+)\s*</center>",
    re.IGNORECASE,
)
_AUG_TYPE_RE = re.compile(r"Type\s+(\d+)\s*\(([^)]+)\)", re.IGNORECASE)
_ITEM_LORE_RE = re.compile(
    r"<b>\s*Item Lore\s*</b>\s*:\s*([^<]+)",
    re.IGNORECASE,
)
_RECAST_DELAY_RE = re.compile(r"Recast Delay:\s*([^<\n]+)", re.IGNORECASE)
_RECAST_TYPE_RE = re.compile(r"Recast Type:\s*([^<\n]+)", re.IGNORECASE)
_META_LABELS = frozenset({"size", "weight", "tribute", "req lvl", "rec lvl", "recommended"})
_VITAL_LABELS = frozenset({"ac", "hp", "mana", "end", "purity"})
_ATTR_LABELS = frozenset(n.casefold() for n in _ATTR_NAMES)
_RESIST_LABELS = frozenset(
    {"magic", "fire", "cold", "disease", "poison", "corruption"}
)
_ORNAMENT_TYPES = frozenset({"21"})

EXPAC_IMAGE_URL = "https://items.eqresource.com/expacimages/{code}.jpg"


@dataclass
class StatBlock:
    labels: list[str] = field(default_factory=list)
    values: list[str] = field(default_factory=list)


@dataclass
class ItemInspect:
    item_id: int
    name: str
    icon_id: str | None = None
    flags: list[str] = field(default_factory=list)
    classes: str = ""
    races: str = ""
    slot: str = ""
    size: str = ""
    weight: str = ""
    tribute: str = ""
    req_level: str = ""
    rec_level: str = ""
    tier: str = ""
    expansion_code: str | None = None
    aug_slots_top: list[str] = field(default_factory=list)
    aug_slots_bottom: list[str] = field(default_factory=list)
    stat_blocks: list[StatBlock] = field(default_factory=list)
    effect: str = ""
    focus: str = ""
    lore: str = ""


@dataclass
class ItemInspectExport:
    cards: dict[str, dict] = field(default_factory=dict)
    icon_data_uris: dict[str, str] = field(default_factory=dict)
    expansion_data_uris: dict[str, str] = field(default_factory=dict)


def inspect_to_dict(item: ItemInspect) -> dict:
    payload = {
        "name": item.name,
        "iconId": item.icon_id or "",
        "flags": list(item.flags),
        "classes": item.classes,
        "races": item.races,
        "slot": item.slot,
        "size": item.size,
        "weight": item.weight,
        "tribute": item.tribute,
        "reqLevel": item.req_level,
        "recLevel": item.rec_level,
        "tier": item.tier,
        "expansionCode": item.expansion_code or "",
        "augSlotsTop": _aug_slots_without_power_source(item.aug_slots_top),
        "augSlotsBottom": _aug_slots_without_power_source(item.aug_slots_bottom),
        "statBlocks": [
            {"labels": list(block.labels), "values": list(block.values)}
            for block in item.stat_blocks
            if block.labels
        ],
        "effect": item.effect,
        "focus": item.focus,
        "lore": item.lore,
    }
    return payload


def inspect_from_dict(raw: dict, *, item_id: int = 0) -> ItemInspect | None:
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name") or "").strip()
    iid = int(raw.get("itemId") or raw.get("item_id") or item_id or 0)
    if iid <= 0 or not name:
        return None
    blocks: list[StatBlock] = []
    for block in raw.get("statBlocks") or []:
        if not isinstance(block, dict):
            continue
        labels = [str(x) for x in (block.get("labels") or []) if str(x).strip()]
        values = [str(x) for x in (block.get("values") or [])]
        if labels:
            blocks.append(StatBlock(labels=labels, values=values[: len(labels)]))
    return ItemInspect(
        item_id=iid,
        name=name,
        icon_id=str(raw.get("iconId") or raw.get("icon_id") or "") or None,
        flags=[str(x) for x in (raw.get("flags") or []) if str(x).strip()],
        classes=str(raw.get("classes") or ""),
        races=str(raw.get("races") or ""),
        slot=str(raw.get("slot") or ""),
        size=str(raw.get("size") or ""),
        weight=str(raw.get("weight") or ""),
        tribute=str(raw.get("tribute") or ""),
        req_level=str(raw.get("reqLevel") or raw.get("req_level") or ""),
        rec_level=str(raw.get("recLevel") or raw.get("rec_level") or ""),
        tier=str(raw.get("tier") or ""),
        expansion_code=str(raw.get("expansionCode") or raw.get("expansion_code") or "")
        or None,
        aug_slots_top=_aug_slots_without_power_source(
            [str(x) for x in (raw.get("augSlotsTop") or []) if str(x).strip()]
        ),
        aug_slots_bottom=_aug_slots_without_power_source(
            [str(x) for x in (raw.get("augSlotsBottom") or []) if str(x).strip()]
        ),
        stat_blocks=blocks,
        effect=str(raw.get("effect") or ""),
        focus=str(raw.get("focus") or ""),
        lore=str(raw.get("lore") or ""),
    )


def collect_equipped_item_ids(team: TeamGearReport) -> list[int]:
    seen: set[int] = set()
    out: list[int] = []
    for character in team.characters:
        for item in character.slots.values():
            iid = int(getattr(item, "item_id", 0) or 0)
            if iid <= 0 or iid in seen:
                continue
            seen.add(iid)
            out.append(iid)
    return out


def parse_item_inspect(
    html: str, item_id: int, *, name_hint: str = ""
) -> ItemInspect | None:
    """Parse an EQ Resource item page into inspect-card fields."""
    if not html or item_id <= 0:
        return None
    name_m = _NAME_RE.search(html)
    name = (name_m.group(1).strip() if name_m else "") or (name_hint or "")
    if not name:
        name = f"Item {item_id}"
    icon_m = _ICON_RE.search(html)
    expac_m = _EXPAC_IMG_RE.search(html)
    tier_m = _TIER_CAPTION_RE.search(html)
    slot_m = _SLOT_RE.search(html)
    class_m = _CLASS_RE.search(html)
    race_m = _RACE_RE.search(html)
    flags_m = _FLAG_LINE_RE.search(html)
    flags = []
    if flags_m:
        flags = [
            part.strip()
            for part in flags_m.group(1).split(",")
            if part.strip()
        ]
    meta, vitals, attributes, resists, combat = _parse_stat_tables(html)
    top_augs, bottom_augs = _parse_aug_slots(html)
    effect, focus = _parse_effect_focus(html)
    lore_m = _ITEM_LORE_RE.search(html)
    return ItemInspect(
        item_id=item_id,
        name=name,
        icon_id=icon_m.group(1) if icon_m else None,
        flags=flags,
        classes=_clean_line(class_m.group(1) if class_m else ""),
        races=_clean_line(race_m.group(1) if race_m else ""),
        slot=_clean_line(slot_m.group(1) if slot_m else ""),
        size=meta.get("size", ""),
        weight=meta.get("weight", ""),
        tribute=meta.get("tribute", ""),
        req_level=meta.get("req lvl", "") or meta.get("rec lvl", ""),
        rec_level=meta.get("recommended", "")
        or (meta.get("rec lvl", "") if "req lvl" in meta else ""),
        tier=_clean_line(tier_m.group(1) if tier_m else ""),
        expansion_code=(expac_m.group(1).strip().lower() if expac_m else None) or None,
        aug_slots_top=_aug_slots_without_power_source(top_augs),
        aug_slots_bottom=_aug_slots_without_power_source(bottom_augs),
        stat_blocks=_ordered_blocks(vitals, attributes, resists, combat),
        effect=effect,
        focus=focus,
        lore=_clean_line(lore_m.group(1) if lore_m else ""),
    )


def _clean_line(raw: str) -> str:
    text = unescape(re.sub(r"\s+", " ", raw or "")).strip()
    return text.strip(" -")


def _value_display(part: str) -> str:
    part = (part or "").strip()
    if not part:
        return ""
    hm = _HEROIC_VAL_RE.search(part)
    if hm:
        return f"{hm.group(1)} + {hm.group(2)}"
    text = re.sub(r"<[^>]+>", "", part)
    return unescape(re.sub(r"\s+", " ", text)).strip()


def _split_br_parts(html: str) -> list[str]:
    return [
        p.strip()
        for p in re.split(r"<br\s*/?>", html or "", flags=re.IGNORECASE)
        if p.strip()
    ]


def _parse_label_value_pair(label_html: str, value_html: str) -> tuple[list[str], list[str]]:
    labels = [
        lab.strip().rstrip(":")
        for lab in re.findall(r"([A-Za-z][A-Za-z ]*):", label_html or "")
        if lab.strip()
    ]
    values = [_value_display(part) for part in _split_br_parts(value_html)]
    if len(values) > len(labels):
        values = values[: len(labels)]
    while len(values) < len(labels):
        values.append("")
    return labels, values


def _parse_stat_tables(
    html: str,
) -> tuple[dict[str, str], StatBlock | None, StatBlock | None, StatBlock | None, list[StatBlock]]:
    meta: dict[str, str] = {}
    vitals: StatBlock | None = None
    attributes: StatBlock | None = None
    resists: StatBlock | None = None
    combat: list[StatBlock] = []

    for match in _ATTR_BLOCK_RE.finditer(html):
        labels: list[str] = []
        for raw in _ATTR_LABEL_RE.findall(match.group(1)):
            canon = next((n for n in _ATTR_NAMES if n.lower() == raw.lower()), raw)
            labels.append(canon)
        values = [_value_display(part) for part in _split_br_parts(match.group(2))]
        values = values[: len(labels)]
        while len(values) < len(labels):
            values.append("")
        if labels:
            attributes = StatBlock(labels=labels, values=values)

    for match in _ATK_BLOCK_RE.finditer(html):
        labels, values = _parse_label_value_pair(match.group(1), match.group(2))
        if not labels:
            continue
        first = labels[0].casefold()
        if first in _META_LABELS or all(lab.casefold() in _META_LABELS for lab in labels):
            for lab, val in zip(labels, values):
                meta[lab.casefold()] = val
            continue
        if first in _ATTR_LABELS:
            continue
        if first in _VITAL_LABELS or all(lab.casefold() in _VITAL_LABELS for lab in labels):
            vitals = StatBlock(labels=labels, values=values)
            continue
        if first in _RESIST_LABELS:
            resists = StatBlock(labels=labels, values=values)
            continue
        combat.append(StatBlock(labels=labels, values=values))
    return meta, vitals, attributes, resists, combat


def _ordered_blocks(
    vitals: StatBlock | None,
    attributes: StatBlock | None,
    resists: StatBlock | None,
    combat: list[StatBlock],
) -> list[StatBlock]:
    out: list[StatBlock] = []
    for block in (vitals, attributes, resists, *combat):
        if block and block.labels:
            out.append(block)
    return out


def _aug_slots_without_power_source(slots: list[str]) -> list[str]:
    return [slot for slot in slots if "power source" not in slot.casefold()]


def _parse_aug_slots(html: str) -> tuple[list[str], list[str]]:
    top: list[str] = []
    bottom: list[str] = []
    seen: set[str] = set()
    for match in _AUG_TYPE_RE.finditer(html or ""):
        number = match.group(1)
        kind = re.sub(r"\s+", " ", match.group(2)).strip()
        label = f"Type {number} ({kind})"
        key = label.casefold()
        if key in seen:
            continue
        seen.add(key)
        if number in _ORNAMENT_TYPES or "ornament" in kind.casefold():
            top.append(label)
        else:
            bottom.append(label)
    return top, bottom


def _parse_effect_focus(html: str) -> tuple[str, str]:
    effects: list[str] = []
    focuses: list[str] = []
    seen_e: set[str] = set()
    seen_f: set[str] = set()
    for match in re.finditer(
        r"Effect:\s*(?:<[^>]+>\s*)*([^<\n]+)", html or "", flags=re.IGNORECASE
    ):
        line = _clean_line(match.group(1))
        if not line:
            continue
        key = line.casefold()
        if key in seen_e:
            continue
        seen_e.add(key)
        effects.append(line)
    for match in _FOCUS_RE.finditer(html or ""):
        line = _clean_line(match.group(1))
        if not line:
            continue
        key = line.casefold()
        if key in seen_f:
            continue
        seen_f.add(key)
        focuses.append(line)
    extra: list[str] = []
    delay = _RECAST_DELAY_RE.search(html or "")
    if delay:
        extra.append(f"Recast Delay: {_clean_line(delay.group(1))}")
    recast = _RECAST_TYPE_RE.search(html or "")
    if recast:
        extra.append(f"Recast Type: {_clean_line(recast.group(1))}")
    effect = "; ".join(effects)
    if extra and effect:
        effect = f"{effect} {' '.join(extra)}"
    return effect, "; ".join(focuses)


def cached_inspect_map() -> dict[int, ItemInspect]:
    from inventory_parser.raid_bis import catalog as raid_catalog

    out: dict[int, ItemInspect] = {}
    cache = raid_catalog._load_item_cache()
    for key, entry in cache.items():
        if not str(key).isdigit():
            continue
        if not isinstance(entry, dict) or not entry.get("ok"):
            continue
        inspect = inspect_from_dict(entry.get("inspect") or {}, item_id=int(key))
        if inspect is None:
            continue
        out[inspect.item_id] = inspect
    return out


def build_item_inspect_export(
    team: TeamGearReport,
    *,
    raid_bis_icons: dict[str, str] | None = None,
    item_html_by_id: dict[int, str] | None = None,
    allow_network: bool = True,
    on_progress: ProgressFn | None = None,
    embed_icons: bool = True,
) -> ItemInspectExport:
    """Hydrate unique equipped items and return inspect cards plus extra icons."""
    item_html_by_id = item_html_by_id or {}
    ids = collect_equipped_item_ids(team)
    if not ids:
        return ItemInspectExport()

    def _status(message: str, done: int = 0, total: int = 1) -> None:
        report_progress(on_progress, message, 0.88, 0.95, done, max(total, 1))

    cached = cached_inspect_map()
    overrides: dict[int, ItemInspect] = {}
    for iid, html in item_html_by_id.items():
        parsed = parse_item_inspect(html, iid)
        if parsed is not None:
            overrides[iid] = parsed
            cached[iid] = parsed
    still_missing = [iid for iid in ids if iid not in cached]
    if still_missing:
        from inventory_parser.raid_bis.catalog import hydrate_item_ids

        hydrate_item_ids(
            still_missing,
            item_html_by_id=item_html_by_id,
            allow_network=allow_network,
            on_status=_status if on_progress else None,
        )
        cached.update(cached_inspect_map())
        cached.update(overrides)

    cards: dict[str, dict] = {}
    icon_ids: set[str] = set()
    expansion_codes: set[str] = set()
    for iid in ids:
        inspect = cached.get(iid)
        if inspect is None:
            html = item_html_by_id.get(iid)
            if html:
                inspect = parse_item_inspect(html, iid)
        if inspect is None:
            continue
        cards[str(iid)] = inspect_to_dict(inspect)
        if inspect.icon_id:
            icon_ids.add(str(inspect.icon_id))
        if inspect.expansion_code:
            expansion_codes.add(inspect.expansion_code)

    raid_icons = raid_bis_icons or {}
    extra_icons = {i for i in icon_ids if i not in raid_icons}
    icon_uris: dict[str, str] = {}
    if embed_icons and extra_icons:
        icon_uris = collect_icon_data_uris(
            extra_icons,
            allow_network=allow_network,
            on_status=_status if on_progress else None,
        )
    expansion_uris: dict[str, str] = {}
    if embed_icons and expansion_codes:
        expansion_uris = collect_expansion_data_uris(
            expansion_codes,
            allow_network=allow_network,
            on_status=_status if on_progress else None,
        )
    if ids:
        _status("Using cached item details…", 1, 1)
    return ItemInspectExport(
        cards=cards,
        icon_data_uris=icon_uris,
        expansion_data_uris=expansion_uris,
    )


def collect_expansion_data_uris(
    codes: Iterable[str],
    *,
    allow_network: bool = True,
    on_status: StatusFn | None = None,
) -> dict[str, str]:
    """Return expansion-code → data URI for EQ Resource expac thumbs."""
    import base64
    from inventory_parser.raid_bis.icons import icon_cache_dir

    wanted = sorted(
        {
            str(code).strip().lower()
            for code in codes
            if str(code).strip() and re.fullmatch(r"[a-z0-9_-]+", str(code).strip().lower())
        }
    )
    if not wanted:
        return {}
    cache_dir = icon_cache_dir()
    out: dict[str, str] = {}
    missing = [
        code
        for code in wanted
        if not (cache_dir / f"expac-{code}.jpg").is_file()
        and not (cache_dir / f"expac-{code}.png").is_file()
    ]
    if missing and allow_network and on_status is not None:
        on_status("Fetching item icons from EQ Resource…", 0, len(missing))
    fetched = 0
    for code in wanted:
        data, mime = _load_expansion_image(code, allow_network=allow_network)
        if not data:
            if code in missing and allow_network:
                fetched += 1
                if on_status is not None:
                    on_status(
                        f"Fetching item icons from EQ Resource… ({fetched}/{len(missing)})",
                        fetched,
                        len(missing),
                    )
            continue
        b64 = base64.b64encode(data).decode("ascii")
        out[code] = f"data:{mime};base64,{b64}"
        if code in missing and allow_network:
            fetched += 1
            if on_status is not None:
                on_status(
                    f"Fetching item icons from EQ Resource… ({fetched}/{len(missing)})",
                    fetched,
                    len(missing),
                )
    return out


def _load_expansion_image(code: str, *, allow_network: bool) -> tuple[bytes | None, str]:
    from inventory_parser.http_fetch import MAX_ICON_BYTES, http_get_bytes, is_jpeg, is_png
    from inventory_parser.raid_bis.icons import icon_cache_dir
    import urllib.error

    cache_dir = icon_cache_dir()
    for name, mime in (("jpg", "image/jpeg"), ("png", "image/png")):
        path = cache_dir / f"expac-{code}.{name}"
        if not path.is_file():
            continue
        try:
            data = path.read_bytes()
        except OSError:
            data = b""
        if name == "jpg" and is_jpeg(data):
            return data, mime
        if name == "png" and is_png(data):
            return data, mime
    if not allow_network:
        return None, ""
    try:
        data = http_get_bytes(
            EXPAC_IMAGE_URL.format(code=code),
            timeout=20,
            user_agent=USER_AGENT,
            max_bytes=MAX_ICON_BYTES,
        )
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None, ""
    if is_jpeg(data):
        mime = "image/jpeg"
        ext = "jpg"
    elif is_png(data):
        mime = "image/png"
        ext = "png"
    else:
        return None, ""
    try:
        (cache_dir / f"expac-{code}.{ext}").write_bytes(data)
    except OSError:
        pass
    return data, mime
