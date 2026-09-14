"""Hero's Special AAs catalog and matching against achievement dumps."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from inventory_parser.package_data import read_data_text

_CATALOG_NAME = "heroic_aas.json"

FANRA_CREDIT_TEXT = "Hero's Special AAs — Fanra's EverQuest Wiki"
FANRA_CREDIT_URL = "https://everquest.fanra.info/wiki/Hero%27s_Special_AAs"
EQRESOURCE_ACHIEVEMENT_URL = (
    "https://achievements.eqresource.com/achievements.php?id={achievement_id}"
)

_APOSTROPHE_RE = re.compile(r"[\u2018\u2019\u2032`]")
_COLON_SPACE_RE = re.compile(r":(?=\S)")
_WS_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class HeroicAACatalogEntry:
    expansion: str
    name: str
    aliases: tuple[str, ...]
    fortitude: int
    resolution: int
    vitality: int
    eqresource_id: int | None = None

    def match_keys(self) -> set[str]:
        names = (self.name,) + self.aliases
        return {normalize_heroic_name(name) for name in names if name}

    @property
    def eqresource_url(self) -> str | None:
        if self.eqresource_id is None or self.eqresource_id <= 0:
            return None
        return EQRESOURCE_ACHIEVEMENT_URL.format(achievement_id=self.eqresource_id)


@dataclass(frozen=True)
class HeroicAAAbility:
    id: str
    label: str
    description: str


@dataclass(frozen=True)
class HeroicAACatalog:
    intro: str
    credit_text: str
    credit_url: str
    abilities: tuple[HeroicAAAbility, ...]
    max_fortitude: int
    max_resolution: int
    max_vitality: int
    achievements: tuple[HeroicAACatalogEntry, ...]


def normalize_heroic_name(name: str) -> str:
    """Casefold, straighten quotes, unify savior spelling, and fix ``:Name``."""
    text = _APOSTROPHE_RE.sub("'", (name or "").strip()).casefold()
    text = text.replace("saviour", "savior")
    text = _COLON_SPACE_RE.sub(": ", text)
    return _WS_RE.sub(" ", text).strip()


def _parse_ability(raw: object) -> HeroicAAAbility | None:
    if not isinstance(raw, dict):
        return None
    ident = str(raw.get("id", "") or "").strip()
    label = str(raw.get("label", "") or "").strip()
    description = str(raw.get("description", "") or "").strip()
    if not ident or not label:
        return None
    return HeroicAAAbility(id=ident, label=label, description=description)


def _parse_eqresource_id(raw: object) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _parse_entry(raw: object) -> HeroicAACatalogEntry | None:
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name", "") or "").strip()
    if not name:
        return None
    aliases_raw = raw.get("aliases") or []
    aliases = tuple(
        str(alias).strip()
        for alias in aliases_raw
        if isinstance(alias, str) and alias.strip()
    )
    return HeroicAACatalogEntry(
        expansion=str(raw.get("expansion", "") or "").strip(),
        name=name,
        aliases=aliases,
        fortitude=1 if raw.get("fortitude") else 0,
        resolution=1 if raw.get("resolution") else 0,
        vitality=1 if raw.get("vitality") else 0,
        eqresource_id=_parse_eqresource_id(raw.get("eqresource_id")),
    )


def _parse_catalog(data: dict[str, Any]) -> HeroicAACatalog:
    credit = data.get("credit") if isinstance(data.get("credit"), dict) else {}
    abilities = tuple(
        ability
        for ability in (_parse_ability(item) for item in data.get("abilities") or [])
        if ability is not None
    )
    achievements = tuple(
        entry
        for entry in (_parse_entry(item) for item in data.get("achievements") or [])
        if entry is not None
    )
    totals = data.get("totals") if isinstance(data.get("totals"), dict) else {}
    return HeroicAACatalog(
        intro=str(data.get("intro", "") or "").strip(),
        credit_text=str(credit.get("text") or FANRA_CREDIT_TEXT).strip(),
        credit_url=str(credit.get("url") or FANRA_CREDIT_URL).strip(),
        abilities=abilities,
        max_fortitude=int(totals.get("fortitude") or 0),
        max_resolution=int(totals.get("resolution") or 0),
        max_vitality=int(totals.get("vitality") or 0),
        achievements=achievements,
    )


@lru_cache(maxsize=1)
def load_heroic_aa_catalog() -> HeroicAACatalog:
    """Return the bundled Hero's Special AAs catalog."""
    return _parse_catalog(json.loads(read_data_text(_CATALOG_NAME)))


def lookup_heroic_aa_entry(name: str) -> HeroicAACatalogEntry | None:
    """Match a catalog entry by canonical name or alias."""
    key = normalize_heroic_name(name)
    if not key:
        return None
    for entry in load_heroic_aa_catalog().achievements:
        if key in entry.match_keys():
            return entry
    return None


def heroic_aa_eqresource_url(name: str) -> str | None:
    """EQ Resource URL for a Heroic AA achievement name, if known."""
    entry = lookup_heroic_aa_entry(name)
    if entry is None:
        return None
    return entry.eqresource_url
