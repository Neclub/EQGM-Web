"""Fetch and parse type 7/8 aug lists from raidloot.com."""

from __future__ import annotations

import json
import os
import re
import urllib.error
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable

from inventory_parser.slot2_augs.aug_stats import (
    ATTR_BASE,
    ATTR_HEROIC,
    LABEL_TO_STAT,
    artisans_prize_stats,
    clean_stats,
    legacy_from_stats,
    merge_stats,
)
from inventory_parser.slot2_augs.profiles import (
    ARTISANS_PRIZE_ID,
    ARTISANS_PRIZE_NAME,
    PROFILE_FOCUS_STAT,
    SHIELD_AUG_URL,
    ProfileId,
    profile_info,
)
from inventory_parser.http_fetch import http_get_text
from inventory_parser.slot2_augs.paths import appdata_dir
from inventory_parser.slots import EAR_REPORT_SLOTS

USER_AGENT = "EQ-Augs/0.2 (Slot2 type 7/8 checker; local tool)"
CACHE_FILENAME = "raidloot_cache.json"

# Map raidloot exclusion names → our gear-slot base names.
_EXCLUSION_ALIASES: dict[str, str] = {
    "charm": "Charm",
    "range": "Range",
    "primary": "Primary",
    "secondary": "Secondary",
    "ammo": "Ammo",
    "ear": "Ear",
    "head": "Head",
    "face": "Face",
    "neck": "Neck",
    "shoulders": "Shoulders",
    "arms": "Arms",
    "back": "Back",
    "wrist": "Wrist",
    "hands": "Hands",
    "fingers": "Fingers",
    "finger": "Fingers",
    "chest": "Chest",
    "legs": "Legs",
    "feet": "Feet",
    "waist": "Waist",
    "power source": "Power Source",
}

_SLOT_LINE_RE = re.compile(
    r"(?:Slot:|</label>\s*)(.+?)(?=(?:AC:|<label>|Required|Class:|Tools:|$))",
    re.IGNORECASE | re.DOTALL,
)
_ITEM_ID_RE = re.compile(
    r"Aug:\s*7\s*8(?:\s*P)?\s*(?:—|&mdash;|–|-)\s*(\d+)",
    re.IGNORECASE,
)
_ITEM_ID_ALT_RE = re.compile(r"(?:—|&mdash;|–)\s*(\d{4,})")
_DATA_ID_RE = re.compile(
    r'<div[^>]*\bdata-id="(\d+)"[^>]*class="[^"]*\bitem\b[^"]*\baugment\b[^"]*"[^>]*>'
    r'(.*?)</div>\s*</td>\s*</tr>',
    re.IGNORECASE | re.DOTALL,
)
_DATA_ID_RE_ALT = re.compile(
    r'<div[^>]*class="[^"]*\bitem\b[^"]*\baugment\b[^"]*"[^>]*\bdata-id="(\d+)"[^>]*>'
    r'(.*?)</div>\s*</td>\s*</tr>',
    re.IGNORECASE | re.DOTALL,
)
_NAME_RE = re.compile(
    r'class="itemname"[^>]*>([^<]+)</(?:span|a)>|'
    r'class="itemname[^"]*"[^>]*>.*?<a[^>]*>([^<]+)</a>',
    re.IGNORECASE | re.DOTALL,
)
_LABEL_VALUE_RE = re.compile(
    r"<label>\s*([^<:]+):\s*</label>\s*(?:<span[^>]*>)?\s*([^<\n]+)",
    re.IGNORECASE,
)
_HEROIC_LABEL_RE = {
    "hdex": re.compile(
        r"<label>\s*DEX:\s*</label>\s*\d+\s*<span[^>]*class=\"[^\"]*heroic[^\"]*\"[^>]*>\s*\+\s*(\d+)",
        re.IGNORECASE,
    ),
    "hint": re.compile(
        r"<label>\s*INT:\s*</label>\s*\d+\s*<span[^>]*class=\"[^\"]*heroic[^\"]*\"[^>]*>\s*\+\s*(\d+)",
        re.IGNORECASE,
    ),
    "hwis": re.compile(
        r"<label>\s*WIS:\s*</label>\s*\d+\s*<span[^>]*class=\"[^\"]*heroic[^\"]*\"[^>]*>\s*\+\s*(\d+)",
        re.IGNORECASE,
    ),
    "hsta": re.compile(
        r"<label>\s*STA:\s*</label>\s*\d+\s*<span[^>]*class=\"[^\"]*heroic[^\"]*\"[^>]*>\s*\+\s*(\d+)",
        re.IGNORECASE,
    ),
    "hstr": re.compile(
        r"<label>\s*STR:\s*</label>\s*\d+\s*<span[^>]*class=\"[^\"]*heroic[^\"]*\"[^>]*>\s*\+\s*(\d+)",
        re.IGNORECASE,
    ),
    "hagi": re.compile(
        r"<label>\s*AGI:\s*</label>\s*\d+\s*<span[^>]*class=\"[^\"]*heroic[^\"]*\"[^>]*>\s*\+\s*(\d+)",
        re.IGNORECASE,
    ),
}
_HEROIC_RE = {
    "hdex": re.compile(r"DEX:\s*\d+\s*\+\s*(\d+)", re.IGNORECASE),
    "hint": re.compile(r"INT:\s*\d+\s*\+\s*(\d+)", re.IGNORECASE),
    "hwis": re.compile(r"WIS:\s*\d+\s*\+\s*(\d+)", re.IGNORECASE),
    "hsta": re.compile(r"STA:\s*\d+\s*\+\s*(\d+)", re.IGNORECASE),
    "hstr": re.compile(r"STR:\s*\d+\s*\+\s*(\d+)", re.IGNORECASE),
    "hagi": re.compile(r"AGI:\s*\d+\s*\+\s*(\d+)", re.IGNORECASE),
}


# Type 7/8 holes only; type 5 (and others) must never be recommended there.
TYPE78_AUG_TYPES: frozenset[int] = frozenset({7, 8})

_AUG_SLOT_TYPES_RE = re.compile(
    r"fits in slot types?:\s*(.+?)(?:<br|</td>|\n\n|$)",
    re.IGNORECASE | re.DOTALL,
)


def parse_aug_slot_types(html_or_text: str) -> frozenset[int]:
    """Parse ``This augmentation fits in slot types: 7, 8`` (EQ Resource / raidloot)."""
    if not html_or_text:
        return frozenset()
    match = _AUG_SLOT_TYPES_RE.search(html_or_text)
    if not match:
        return frozenset()
    chunk = re.sub(r"<[^>]+>", " ", match.group(1))
    nums = {int(n) for n in re.findall(r"\b(\d+)\b", chunk)}
    return frozenset(n for n in nums if 1 <= n <= 23)


def is_type78_aug(aug: AugCandidate, *, require_known: bool = False) -> bool:
    """True when the aug is type 7 and/or 8, or types are unknown unless required."""
    if aug.item_id == ARTISANS_PRIZE_ID:
        return True
    types = aug.aug_types
    if not types:
        return not require_known
    return bool(types & TYPE78_AUG_TYPES)


@dataclass
class AugCandidate:
    item_id: int
    name: str
    profile: ProfileId
    focus_heroic: int
    ac: int = 0
    hp: int = 0
    atk: int = 0
    slot_text: str = ""
    excluded_bases: frozenset[str] = field(default_factory=frozenset)
    allowed_bases: frozenset[str] = field(default_factory=frozenset)
    ear_only: bool = False
    lore: bool = False
    lore_group: str | None = None
    shield_only: bool = False
    source: str = ""
    stats: dict[str, int] = field(default_factory=dict)
    aug_types: frozenset[int] = field(default_factory=frozenset)

    def lore_group_key(self) -> str:
        """Casefolded lore-group id/name, or empty when the aug is not grouped."""
        return (self.lore_group or "").strip().casefold()

    def fits_gear_slot(self, gear_slot: str) -> bool:
        base = _gear_slot_base(gear_slot)
        if self.ear_only:
            return base == "Ear"
        if self.shield_only:
            return base == "Secondary"
        if self.allowed_bases:
            return base in self.allowed_bases
        if self.excluded_bases:
            return base not in self.excluded_bases
        return True

    def effective_stats(self) -> dict[str, int]:
        """Stats map with legacy fields filled in when the dict is thin."""
        base = dict(self.stats) if self.stats else {}
        if self.ac and "ac" not in base:
            base["ac"] = self.ac
        if self.hp and "hp" not in base:
            base["hp"] = self.hp
        if self.atk and "atk" not in base:
            base["atk"] = self.atk
        focus_key = PROFILE_FOCUS_STAT.get(self.profile)
        if self.focus_heroic and focus_key and focus_key not in base:
            base[focus_key] = self.focus_heroic
        return base


def unique_by_lore_group(augs: list[AugCandidate]) -> list[AugCandidate]:
    """Keep the first aug of each lore group (caller should sort best-first).

    Ungrouped augs are kept unless their item id is the canonical id of a
    group already chosen.
    """
    seen_groups: set[str] = set()
    seen_ids: set[int] = set()
    out: list[AugCandidate] = []
    for aug in augs:
        if aug.item_id in seen_ids:
            continue
        key = aug.lore_group_key()
        if key and key in seen_groups:
            continue
        if str(aug.item_id) in seen_groups:
            continue
        out.append(aug)
        seen_ids.add(aug.item_id)
        seen_groups.add(str(aug.item_id))
        if key:
            seen_groups.add(key)
            if key.isdigit():
                seen_ids.add(int(key))
    return out


@dataclass
class CatalogResult:
    profile: ProfileId
    augs: list[AugCandidate]
    fetched_at: str
    from_cache: bool
    warning: str | None = None
    url: str = ""


def cache_path() -> Path:
    return appdata_dir() / CACHE_FILENAME


def _gear_slot_base(gear_slot: str) -> str:
    if gear_slot in EAR_REPORT_SLOTS or gear_slot.startswith("Ear"):
        return "Ear"
    if gear_slot.startswith("Wrist"):
        return "Wrist"
    if gear_slot.startswith("Fingers"):
        return "Fingers"
    return gear_slot


def parse_slot_restrictions(slot_text: str) -> tuple[frozenset[str], frozenset[str], bool]:
    """
    Parse raidloot slot restriction text.

    Returns (excluded_bases, allowed_bases, ear_only).
    """
    text = (slot_text or "").strip()
    if not text:
        return frozenset(), frozenset(), False

    lower = text.lower()
    # "Slot: Ear" / "Ear only" style
    if re.match(r"^ear\b", lower) and "except" not in lower and "all" not in lower:
        return frozenset(), frozenset({"Ear"}), True

    # "All except Charm, Range, Primary, Secondary, Ammo"
    except_match = re.search(r"all\s+except\s+(.+)", lower, re.IGNORECASE)
    if except_match:
        raw = except_match.group(1)
        # Stop at parenthetical extras like (CHRMAdvTradeskills)
        raw = re.split(r"[(\n]", raw)[0]
        parts = re.split(r"[,/]| and ", raw)
        excluded: set[str] = set()
        for part in parts:
            name = part.strip().strip(".")
            if not name:
                continue
            mapped = _EXCLUSION_ALIASES.get(name.lower())
            if mapped:
                excluded.add(mapped)
        return frozenset(excluded), frozenset(), False

    # Explicit allow list: "Charm, Range" without "All"
    if "all" not in lower:
        parts = re.split(r"[,/]| and ", lower)
        allowed: set[str] = set()
        for part in parts:
            name = part.strip()
            mapped = _EXCLUSION_ALIASES.get(name)
            if mapped:
                allowed.add(mapped)
        if allowed:
            ear_only = allowed == {"Ear"}
            return frozenset(), frozenset(allowed), ear_only

    return frozenset(), frozenset(), False


def _extract_stat_int(pattern: re.Pattern[str], text: str) -> int:
    m = pattern.search(text)
    return int(m.group(1)) if m else 0


def _first_int(text: str) -> int:
    m = re.search(r"(\d+)", text or "")
    return int(m.group(1)) if m else 0


def _parse_stats_from_detail(detail: str) -> dict[str, int]:
    """Extract canonical stats from a raidloot aug detail HTML/plain fragment."""
    stats: dict[str, int] = {}

    # Labeled values: <label>AC:</label> … or plain "AC: 115"
    for raw_label, canon in LABEL_TO_STAT.items():
        # Prefer HTML label blocks
        labeled = _label_after(detail, raw_label.upper() if raw_label in ("ac", "hp", "atk") else raw_label.title())
        if not labeled and raw_label in ("mana", "end", "endurance"):
            labeled = _label_after(detail, "MANA" if raw_label == "mana" else "END")
        if not labeled:
            # Title-case multi-word (Heal Amount, Spell Damage, …)
            words = raw_label.split()
            titled = " ".join(w.capitalize() for w in words)
            labeled = _label_after(detail, titled)
        if labeled:
            n = _first_int(labeled)
            if n:
                stats[canon] = n
            continue
        plain = _html_to_text(detail)
        # Match "AC: 115" / "Heal Amount: 108" style
        pat = re.compile(
            rf"(?:^|[\s>]){re.escape(raw_label)}\s*:\s*(\d+)",
            re.IGNORECASE,
        )
        m = pat.search(plain)
        if m:
            stats[canon] = int(m.group(1))

    # Also try standard short labels via _label_after for AC/HP/ATK/MANA/END
    for label, key in (
        ("AC", "ac"),
        ("HP", "hp"),
        ("ATK", "atk"),
        ("MANA", "mana"),
        ("END", "endurance"),
    ):
        if key in stats:
            continue
        text = _label_after(detail, label)
        n = _first_int(text)
        if n:
            stats[key] = n

    # Heroic / base attrs: DEX: 0 + 61 or <label>DEX:</label> 0 <span class="heroic">+ 61</span>
    for attr_key, base_key in ATTR_BASE.items():
        if len(attr_key) > 3 and attr_key not in ("strength", "stamina", "agility", "dexterity", "wisdom", "intelligence", "charisma"):
            continue
        # Prefer short labels (DEX, INT, …)
        short = attr_key.upper() if len(attr_key) <= 3 else None
        if not short:
            continue
        heroic_key = ATTR_HEROIC[attr_key]
        html_heroic = _HEROIC_LABEL_RE.get(heroic_key)
        if html_heroic:
            n = _extract_stat_int(html_heroic, detail)
            if n:
                stats[heroic_key] = n
        if heroic_key not in stats:
            plain_re = _HEROIC_RE.get(heroic_key)
            if plain_re:
                n = _extract_stat_int(plain_re, _html_to_text(detail))
                if n:
                    stats[heroic_key] = n
        # Base attr (non-heroic) when present as "DEX: 70 + 49"
        base_m = re.search(
            rf"<label>\s*{short}:\s*</label>\s*(\d+)",
            detail,
            re.IGNORECASE,
        ) or re.search(
            rf"(?:^|[\s>]){short}:\s*(\d+)",
            _html_to_text(detail),
            re.IGNORECASE,
        )
        if base_m:
            base_n = int(base_m.group(1))
            if base_n:
                stats[base_key] = base_n

    # Extra combat labels that may appear as plain text on item pages
    plain = _html_to_text(detail)
    for label, key in (
        ("Accuracy", "accuracy"),
        ("Combat Effects", "combat_effects"),
        ("Avoidance", "avoidance"),
        ("Shielding", "shielding"),
        ("Spell Shield", "spell_shield"),
        ("DoT Shield", "dot_shield"),
        ("Stun Resist", "stun_resist"),
        ("Strike Through", "strikethrough"),
        ("Heal Amount", "heal_amount"),
        ("Heal Amt", "heal_amount"),
        ("Spell Damage", "spell_damage"),
        ("Spell Dmg", "spell_damage"),
        ("SpellDmg", "spell_damage"),
        ("Nuke", "spell_damage"),
        ("Clairvoyance", "clairvoyance"),
        ("Attack", "atk"),
        ("ATK", "atk"),
    ):
        if key in stats:
            continue
        labeled = _label_after(detail, label)
        if labeled:
            n = _first_int(labeled)
            if n:
                stats[key] = n
                continue
        m = re.search(rf"{re.escape(label)}\s*:\s*(\d+)", plain, re.IGNORECASE)
        if m:
            stats[key] = int(m.group(1))

    return clean_stats(stats)


def _prize_aug(profile: ProfileId) -> AugCandidate:
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
        excluded_bases=frozenset(),
        allowed_bases=frozenset({"Ear"}),
        ear_only=True,
        lore=True,
        source="Quest: Artisan's Prize",
        stats=stats,
        aug_types=TYPE78_AUG_TYPES,
    )


def _clean_aug_name(name: str) -> str:
    name = re.sub(r"<[^>]+>", "", name)
    name = re.sub(r"^[^A-Za-z]+", "", name)
    name = re.sub(r"^(?:td>|tr>|Icon|Name)\s*", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\s+", " ", name).strip()
    name = re.sub(r"(</?\w+>.*)$", "", name).strip()
    return name


def _clean_source(source: str) -> str:
    source = re.sub(r"<[^>]+>", "", source)
    source = re.sub(r"\s+", " ", source).strip()
    source = re.split(r"\s*</", source)[0].strip()
    return source


def _html_to_text(fragment: str) -> str:
    text = fragment.replace("&mdash;", "—").replace("&ndash;", "–").replace("&amp;", "&")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</(?:label|span|a|div)>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _normalize_lore_group_value(raw: str) -> str | None:
    text = re.sub(r"\s+", " ", (raw or "").strip())
    if not text:
        return None
    m = re.match(r"^(\d+)\b", text)
    if m:
        return m.group(1)
    return text


def parse_raidloot_lore_group(detail: str) -> str | None:
    """Lore-group key from a raidloot detail block (usually a canonical item id)."""
    if not detail:
        return None
    for label in ("Lore Equipped Group", "Lore Group"):
        labeled = _label_after(detail, label)
        if labeled:
            return _normalize_lore_group_value(labeled)
    plain = _html_to_text(detail)
    m = re.search(
        r"Lore Equipped Group:\s*(.+?)(?=(?:Slot:|AC:|HP:|Restrictions:|Required|Class:|Tools:|$))",
        plain,
        re.IGNORECASE,
    )
    if not m:
        m = re.search(
            r"Lore Group:\s*(.+?)(?=(?:Slot:|AC:|HP:|Restrictions:|Required|Class:|Tools:|$))",
            plain,
            re.IGNORECASE,
        )
    if m:
        return _normalize_lore_group_value(m.group(1))
    return None


def _label_after(html_fragment: str, label: str) -> str:
    """Return text after ``<label>Label:</label>`` until the next label/break."""
    pat = re.compile(
        rf"<label>\s*{re.escape(label)}:\s*</label>\s*(.*?)(?=<label>|<br\s*/?>|$)",
        re.IGNORECASE | re.DOTALL,
    )
    m = pat.search(html_fragment)
    if not m:
        return ""
    return _html_to_text(m.group(1))


def _parse_aug_block(
    name: str,
    detail: str,
    profile: ProfileId,
    *,
    item_id: int | None = None,
) -> AugCandidate | None:
    if item_id is None:
        id_match = _ITEM_ID_RE.search(detail) or _ITEM_ID_ALT_RE.search(detail)
        if not id_match:
            return None
        item_id = int(id_match.group(1))
    name = _clean_aug_name(name)

    slot_text = _label_after(detail, "Slot")
    if not slot_text:
        plain = _html_to_text(detail)
        slot_match = re.search(
            r"Slot:\s*(.+?)(?=(?:AC:|HP:|MANA:|END:|ATK:|Required|Class:|Tools:|$))",
            plain,
            re.IGNORECASE,
        )
        slot_text = slot_match.group(1).strip() if slot_match else ""
    slot_text = re.sub(r"\s+", " ", slot_text).strip()

    excluded, allowed, ear_only = parse_slot_restrictions(slot_text)

    restrictions = _label_after(detail, "Restrictions")
    if not restrictions:
        plain = _html_to_text(detail)
        restr_m = re.search(
            r"Restrictions:\s*(.+?)(?=(?:AC:|HP:|Required|Class:|Tools:|$))",
            plain,
            re.IGNORECASE,
        )
        restrictions = restr_m.group(1).strip() if restr_m else ""
    shield_only = bool(re.search(r"shield\s*only", restrictions, re.IGNORECASE))
    if shield_only:
        allowed = frozenset({"Secondary"})
        excluded = frozenset()
        ear_only = False

    # Hard-code Artisan's Prize
    if item_id == ARTISANS_PRIZE_ID or name.casefold() == ARTISANS_PRIZE_NAME.casefold():
        ear_only = True
        allowed = frozenset({"Ear"})
        excluded = frozenset()
        shield_only = False
        name = ARTISANS_PRIZE_NAME

    stats = _parse_stats_from_detail(detail)
    if item_id == ARTISANS_PRIZE_ID:
        stats = merge_stats(artisans_prize_stats(), stats)

    focus_key = PROFILE_FOCUS_STAT[profile]
    focus_heroic = int(stats.get(focus_key, 0))
    if focus_heroic == 0:
        focus_heroic = _extract_stat_int(_HEROIC_LABEL_RE[focus_key], detail)
    if focus_heroic == 0:
        focus_heroic = _extract_stat_int(_HEROIC_RE[focus_key], _html_to_text(detail))
    if item_id == ARTISANS_PRIZE_ID and focus_heroic == 0:
        focus_heroic = 150
    if focus_heroic and focus_key not in stats:
        stats[focus_key] = focus_heroic

    ac = int(stats.get("ac", 0))
    hp = int(stats.get("hp", 0))
    atk = int(stats.get("atk", 0))
    if not ac:
        ac_text = _label_after(detail, "AC")
        ac_m = re.search(r"(\d+)", ac_text) or re.search(
            r"AC:\s*(\d+)", _html_to_text(detail), re.IGNORECASE
        )
        ac = int(ac_m.group(1)) if ac_m else 0
        if ac:
            stats["ac"] = ac
    if not hp:
        hp_text = _label_after(detail, "HP")
        hp_m = re.search(r"(\d+)", hp_text) or re.search(
            r"HP:\s*(\d+)", _html_to_text(detail), re.IGNORECASE
        )
        hp = int(hp_m.group(1)) if hp_m else 0
        if hp:
            stats["hp"] = hp
    if not atk:
        atk_text = _label_after(detail, "ATK")
        atk_m = re.search(r"(\d+)", atk_text) or re.search(
            r"ATK:\s*(\d+)", _html_to_text(detail), re.IGNORECASE
        )
        atk = int(atk_m.group(1)) if atk_m else 0
        if atk:
            stats["atk"] = atk

    source = ""
    for src_label in ("Mob", "Quest", "Vendor"):
        src = _label_after(detail, src_label)
        if src:
            source = f"{src_label}: {src}"
            break
    if not source:
        src_m = re.search(
            r"(?:Mob|Quest|Vendor):\s*(.+?)(?=Tools:|$)",
            _html_to_text(detail),
            re.IGNORECASE,
        )
        if src_m:
            source = _clean_source(src_m.group(0))

    lore = False
    if re.search(r'class="itemflag"', detail, re.IGNORECASE):
        lore = bool(re.search(r'class="itemflag"\s*>\s*LORE\s*<', detail, re.IGNORECASE))
    elif re.search(r"\bLORE\b", _html_to_text(detail), re.IGNORECASE):
        lore = True
    else:
        # Plain fixtures / incomplete rows: type 7/8 raid augs are almost always Lore.
        lore = True
    if item_id == ARTISANS_PRIZE_ID:
        lore = True

    return AugCandidate(
        item_id=item_id,
        name=name.strip(),
        profile=profile,
        focus_heroic=focus_heroic,
        ac=ac,
        hp=hp,
        atk=atk,
        slot_text=slot_text,
        excluded_bases=excluded,
        allowed_bases=allowed,
        ear_only=ear_only,
        lore=lore,
        lore_group=parse_raidloot_lore_group(detail),
        shield_only=shield_only,
        source=source,
        stats=clean_stats(stats),
        aug_types=parse_aug_slot_types(detail) or (
            TYPE78_AUG_TYPES if item_id == ARTISANS_PRIZE_ID else frozenset()
        ),
    )


def _iter_detail_blocks(html: str) -> list[tuple[int, str]]:
    """Return (item_id, inner_html) for raidloot augment detail divs."""
    blocks: list[tuple[int, str]] = []
    seen: set[int] = set()
    for pattern in (_DATA_ID_RE, _DATA_ID_RE_ALT):
        for m in pattern.finditer(html):
            item_id = int(m.group(1))
            if item_id in seen:
                continue
            seen.add(item_id)
            blocks.append((item_id, m.group(2)))
    if blocks:
        return blocks

    # Fallback: looser match on data-id divs that mention Aug: 7 8
    loose = re.compile(
        r'<div[^>]*\bdata-id="(\d+)"[^>]*>(.*?)</div>',
        re.IGNORECASE | re.DOTALL,
    )
    for m in loose.finditer(html):
        inner = m.group(2)
        if "Aug:" not in inner and "aug:" not in inner.lower():
            continue
        item_id = int(m.group(1))
        if item_id in seen:
            continue
        seen.add(item_id)
        blocks.append((item_id, inner))
    return blocks


class _RaidlootTableParser(HTMLParser):
    """Extract aug name + detail text from raidloot search result tables."""

    def __init__(self) -> None:
        super().__init__()
        self._in_td = False
        self._td_parts: list[str] = []
        self._cells: list[str] = []
        self.rows: list[tuple[str, str]] = []  # (name_guess, detail)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "td":
            self._in_td = True
            self._td_parts = []
        elif tag == "tr":
            self._cells = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self._in_td:
            self._in_td = False
            text = " ".join(self._td_parts).strip()
            text = re.sub(r"\s+", " ", text)
            if text:
                self._cells.append(text)
        elif tag == "tr":
            self._finish_row()

    def handle_data(self, data: str) -> None:
        if self._in_td:
            self._td_parts.append(data)

    def _finish_row(self) -> None:
        if len(self._cells) < 2:
            self._cells = []
            return
        detail = ""
        name = ""
        for cell in self._cells:
            if "Aug:" in cell and ("—" in cell or "mdash" in cell.lower()):
                detail = cell
                name = cell.split("Aug:")[0].strip()
                break
        if not detail:
            joined = " | ".join(self._cells)
            if "Aug:" in joined or re.search(r"\b7\s*8\b", joined):
                detail = joined
                name = self._cells[1] if len(self._cells) > 1 else self._cells[0]
        if detail and name:
            self.rows.append((name, detail))
        self._cells = []


def parse_raidloot_html(html: str, profile: ProfileId) -> list[AugCandidate]:
    """Parse raidloot aug search HTML into candidates."""
    candidates: list[AugCandidate] = []
    seen_ids: set[int] = set()

    # Primary: live site detail divs (class="item augment" data-id="...")
    for item_id, inner in _iter_detail_blocks(html):
        name_m = re.search(r'class="itemname"[^>]*>([^<]+)<', inner, re.IGNORECASE)
        name = name_m.group(1).strip() if name_m else f"Item {item_id}"
        aug = _parse_aug_block(name, inner, profile, item_id=item_id)
        if aug and aug.item_id not in seen_ids:
            seen_ids.add(aug.item_id)
            candidates.append(aug)

    # Secondary: plain-text / markdown-ish fixture format
    if len(candidates) < 5:
        parser = _RaidlootTableParser()
        try:
            parser.feed(html)
        except Exception:
            parser.rows = []
        for name, detail in parser.rows:
            aug = _parse_aug_block(name, detail, profile)
            if aug and aug.item_id not in seen_ids:
                seen_ids.add(aug.item_id)
                candidates.append(aug)

    if len(candidates) < 5:
        block_re = re.compile(
            r"([A-Za-z][^|<\n]{2,80}?)\s+Aug:\s*7\s*8(?:\s*P)?\s*(?:—|&mdash;)\s*(\d+)"
            r"(.{0,1200}?)(?=(?:[A-Za-z][^|<\n]{2,80}?\s+Aug:\s*7\s*8)|$)",
            re.DOTALL,
        )
        for m in block_re.finditer(html):
            name = re.sub(r"\s+", " ", m.group(1)).strip()
            name = re.sub(r"^(?:Icon|Name)\s+", "", name, flags=re.IGNORECASE)
            detail = f"Aug: 7 8 — {m.group(2)}{m.group(3)}"
            aug = _parse_aug_block(name, detail, profile)
            if aug and aug.item_id not in seen_ids:
                seen_ids.add(aug.item_id)
                candidates.append(aug)

    # Always ensure Artisan's Prize stub exists (Ear-only; used when the dump contains it).
    if ARTISANS_PRIZE_ID not in seen_ids:
        candidates.insert(0, _prize_aug(profile))

    candidates.sort(key=lambda a: (-a.focus_heroic, -a.hp, -a.ac, a.name.casefold()))
    return candidates


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
    path = cache_path()
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _candidate_from_dict(d: dict, profile: ProfileId) -> AugCandidate:
    stats = clean_stats(d.get("stats") or {})
    focus = int(d.get("focus_heroic", 0))
    ac = int(d.get("ac", 0))
    hp = int(d.get("hp", 0))
    atk = int(d.get("atk", 0))
    if not stats:
        # Legacy cache row — rebuild thin stats from legacy fields.
        focus_key = PROFILE_FOCUS_STAT[profile]
        if focus:
            stats[focus_key] = focus
        if ac:
            stats["ac"] = ac
        if hp:
            stats["hp"] = hp
        if atk:
            stats["atk"] = atk
    else:
        if not focus or not ac or not hp or not atk:
            f2, a2, h2, t2 = legacy_from_stats(stats, profile)
            focus = focus or f2
            ac = ac or a2
            hp = hp or h2
            atk = atk or t2
    return AugCandidate(
        item_id=int(d["item_id"]),
        name=d["name"],
        profile=profile,
        focus_heroic=focus,
        ac=ac,
        hp=hp,
        atk=atk,
        slot_text=d.get("slot_text", ""),
        excluded_bases=frozenset(d.get("excluded_bases", [])),
        allowed_bases=frozenset(d.get("allowed_bases", [])),
        ear_only=bool(d.get("ear_only", False)),
        lore=bool(d.get("lore", False)),
        lore_group=(str(d["lore_group"]).strip() if d.get("lore_group") else None) or None,
        shield_only=bool(d.get("shield_only", False)),
        source=d.get("source", ""),
        stats=stats,
        aug_types=frozenset(int(t) for t in (d.get("aug_types") or []) if str(t).isdigit()),
    )


def _candidate_to_dict(a: AugCandidate) -> dict:
    return {
        "item_id": a.item_id,
        "name": a.name,
        "focus_heroic": a.focus_heroic,
        "ac": a.ac,
        "hp": a.hp,
        "atk": a.atk,
        "slot_text": a.slot_text,
        "excluded_bases": sorted(a.excluded_bases),
        "allowed_bases": sorted(a.allowed_bases),
        "ear_only": a.ear_only,
        "lore": a.lore,
        "lore_group": a.lore_group,
        "shield_only": a.shield_only,
        "source": a.source,
        "stats": dict(a.stats or a.effective_stats()),
        "stats_v": 2,
        "aug_types": sorted(a.aug_types),
    }


def _retag_profile(augs: list[AugCandidate], profile: ProfileId) -> list[AugCandidate]:
    """Copy candidates onto ``profile`` (shield fetch is shared across profiles)."""
    out: list[AugCandidate] = []
    for a in augs:
        if a.profile == profile:
            out.append(a)
            continue
        stats = dict(a.stats or a.effective_stats())
        focus, ac, hp, atk = legacy_from_stats(stats, profile)
        out.append(
            replace(
                a,
                profile=profile,
                focus_heroic=focus or a.focus_heroic,
                ac=ac or a.ac,
                hp=hp or a.hp,
                atk=atk or a.atk,
                stats=stats,
            )
        )
    return out


def merge_shield_augs(
    catalog: list[AugCandidate],
    shield_augs: list[AugCandidate],
) -> list[AugCandidate]:
    """Append Shield Only augs not already present in the profile catalog."""
    seen = {a.item_id for a in catalog}
    merged = list(catalog)
    for aug in shield_augs:
        if not aug.shield_only:
            continue
        if aug.item_id in seen:
            # Ensure existing row is marked shield-only Secondary.
            for i, existing in enumerate(merged):
                if existing.item_id == aug.item_id and not existing.shield_only:
                    stats = merge_stats(existing.effective_stats(), aug.effective_stats())
                    focus, ac, hp, atk = legacy_from_stats(stats, existing.profile)
                    merged[i] = replace(
                        existing,
                        focus_heroic=focus or existing.focus_heroic,
                        ac=ac or existing.ac or aug.ac,
                        hp=hp or existing.hp or aug.hp,
                        atk=atk or existing.atk or aug.atk,
                        slot_text=aug.slot_text or existing.slot_text,
                        excluded_bases=frozenset(),
                        allowed_bases=frozenset({"Secondary"}),
                        ear_only=False,
                        lore=existing.lore or aug.lore,
                        lore_group=existing.lore_group or aug.lore_group,
                        shield_only=True,
                        source=existing.source or aug.source,
                        stats=stats,
                    )
            continue
        seen.add(aug.item_id)
        merged.append(aug)
    merged.sort(key=lambda a: (-a.focus_heroic, -a.hp, -a.ac, a.name.casefold()))
    return merged


def parse_shield_html(html: str, profile: ProfileId) -> list[AugCandidate]:
    """Parse Aug_Shield search HTML; keep only Restrictions: Shield Only rows."""
    return [a for a in parse_raidloot_html(html, profile) if a.shield_only]


def fetch_catalog(
    profile: ProfileId,
    *,
    force_refresh: bool = False,
    html_override: str | None = None,
    shield_html_override: str | None = None,
) -> CatalogResult:
    """
    Fetch the type 7/8 catalog: EQ Resource advanced search first, raidloot fallback.

    Also merges Shield Only Secondary augs from the raidloot Aug_Shield list.

    ``html_override`` / ``shield_html_override`` are for tests — skip network
    and parse raidloot HTML directly.
    """
    info = profile_info(profile)
    now = datetime.now(timezone.utc).isoformat()
    cache = _load_cache()

    if html_override is not None:
        augs = parse_raidloot_html(html_override, profile)
        if shield_html_override is not None:
            augs = merge_shield_augs(augs, parse_shield_html(shield_html_override, profile))
        return CatalogResult(
            profile=profile,
            augs=augs,
            fetched_at=now,
            from_cache=False,
            url=info.url,
        )

    warning: str | None = None
    augs: list[AugCandidate] = []
    from_cache = False
    fetched_at = now
    catalog_url = info.url

    eqr_ok = False
    try:
        from inventory_parser.slot2_augs.eqresource_search import fetch_eqresource_catalog

        eqr = fetch_eqresource_catalog(profile, force_refresh=force_refresh)
        usable = [a for a in eqr.augs if a.item_id != ARTISANS_PRIZE_ID]
        if len(usable) < 3:
            raise ValueError(
                f"EQ Resource catalog parsed only {len(usable)} usable augs"
            )
        augs = [a for a in eqr.augs if is_type78_aug(a)]
        eqr_ok = True
        catalog_url = eqr.url or catalog_url
        from_cache = eqr.from_cache
        fetched_at = eqr.fetched_at or now
        if eqr.warning:
            warning = eqr.warning
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        warning = f"EQ Resource catalog failed ({exc}); trying raidloot."

    if not eqr_ok:
        try:
            html = _http_get(info.url)
            augs = parse_raidloot_html(html, profile)
            usable = [a for a in augs if a.item_id != ARTISANS_PRIZE_ID]
            if len(usable) < 3:
                raise ValueError(
                    f"Parsed only {len(usable)} usable augs from raidloot HTML "
                    f"(need a working detail-block parse)"
                )
            cache[profile] = {
                "fetched_at": now,
                "url": info.url,
                "augs": [_candidate_to_dict(a) for a in augs],
            }
            _save_cache(cache)
            catalog_url = info.url
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            cached = cache.get(profile)
            if cached and cached.get("augs"):
                augs = [_candidate_from_dict(d, profile) for d in cached["augs"]]
                from_cache = True
                fetched_at = cached.get("fetched_at", "")
                raid_warn = f"Live raidloot fetch failed ({exc}); using cached catalog."
                warning = f"{warning} {raid_warn}" if warning else raid_warn
            else:
                augs = [_prize_aug(profile)]
                raid_warn = f"Live raidloot fetch failed ({exc}); no cache available."
                warning = f"{warning} {raid_warn}" if warning else raid_warn

    # Merge Shield Only Secondary augs (separate raidloot list).
    shield_augs: list[AugCandidate] = []
    try:
        shield_html = _http_get(SHIELD_AUG_URL)
        shield_augs = parse_shield_html(shield_html, profile)
        if shield_augs:
            cache["shield"] = {
                "fetched_at": now,
                "url": SHIELD_AUG_URL,
                "augs": [_candidate_to_dict(a) for a in shield_augs],
            }
            _save_cache(cache)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        cached_shield = cache.get("shield")
        if cached_shield and cached_shield.get("augs"):
            shield_augs = _retag_profile(
                [_candidate_from_dict(d, profile) for d in cached_shield["augs"]],
                profile,
            )
            from_cache = True
            shield_warn = f"Live shield-aug fetch failed ({exc}); using cached shield augs."
            warning = f"{warning} {shield_warn}" if warning else shield_warn
        else:
            shield_warn = f"Live shield-aug fetch failed ({exc}); no shield cache."
            warning = f"{warning} {shield_warn}" if warning else shield_warn

    if shield_augs:
        augs = merge_shield_augs(augs, shield_augs)

    return CatalogResult(
        profile=profile,
        augs=augs,
        fetched_at=fetched_at,
        from_cache=from_cache,
        warning=warning,
        url=catalog_url,
    )


def augs_for_slot(catalog: Iterable[AugCandidate], gear_slot: str) -> list[AugCandidate]:
    """Filter and sort catalog for augs that fit ``gear_slot``."""
    fitted = [a for a in catalog if a.fits_gear_slot(gear_slot)]
    fitted.sort(key=lambda a: (-a.focus_heroic, -a.hp, -a.ac, a.name.casefold()))
    return fitted
