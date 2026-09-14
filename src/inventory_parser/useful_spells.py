"""Curated useful spells intersected with MissingSpells dumps."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from inventory_parser.missing_spells import (
    MissingSpellLine,
    discover_missing_spells_for_inventories,
    is_missing_rank_iii,
    parse_missing_spells_file,
    spell_path_for_persona,
    strip_spell_rank,
)
from inventory_parser.package_data import read_data_text
from inventory_parser.spell_catalog import (
    eqresource_spell_url,
    load_spell_catalog,
    lookup_spell_id,
)
from inventory_parser.team_report import TeamGearReport

_CATALOG_NAME = "useful_spells.json"

RACCOO_USEFUL_SPELLS_CREDIT_TEXT = 'Based on "SOR - Raccoo\'s list of useful spells"'
RACCOO_USEFUL_SPELLS_URL = (
    "https://docs.google.com/spreadsheets/d/1ZqUFZ-WTZvfcBfwu5g6GGEQroEwNLSfK1LMOdMHVHcA/htmlview"
)

# Trailing roman / arabic rank token (Dichotemic Fury VI, Reciprocal Rage 6, etc.)
_TRAILING_RANK_TOKEN_RE = re.compile(
    r"\s+(?:X{0,3}(?:IX|IV|V?I{0,3})|\d+)\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class UsefulSpell:
    name: str
    level: int | None
    expansion: str = ""
    highest_rk: str = ""
    comments: str = ""


@dataclass(frozen=True)
class MissingUsefulSpell:
    persona_key: str
    display_name: str
    character: str
    level: int
    expansion: str
    spell_name: str
    highest_rk: str
    comments: str
    eqresource_url: str = ""


@dataclass
class MissingUsefulSpellsReport:
    persona_keys: list[str]
    entries: list[MissingUsefulSpell] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _spell_personas(team: TeamGearReport) -> list:
    if team.spell_characters:
        return team.spell_characters
    return team.characters


def _parse_catalog(data: dict[str, Any]) -> dict[str, list[UsefulSpell]]:
    raw = data.get("spells_by_class", {})
    by_class: dict[str, list[UsefulSpell]] = {}
    if not isinstance(raw, dict):
        return by_class
    for class_abbr, spells in raw.items():
        if not isinstance(spells, list):
            continue
        parsed: list[UsefulSpell] = []
        for entry in spells:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name", "")).strip()
            if not name:
                continue
            level_raw = entry.get("level")
            level: int | None
            try:
                level = int(level_raw) if level_raw is not None else None
            except (TypeError, ValueError):
                level = None
            parsed.append(
                UsefulSpell(
                    name=name,
                    level=level,
                    expansion=str(entry.get("expansion", "") or "").strip(),
                    highest_rk=str(entry.get("highest_rk", "") or "").strip(),
                    comments=str(entry.get("comments", "") or "").strip(),
                )
            )
        by_class[str(class_abbr).upper()] = parsed
    return by_class


@lru_cache(maxsize=1)
def load_useful_spells() -> dict[str, list[UsefulSpell]]:
    """Return useful spells keyed by class abbreviation (SHD, PAL, …)."""
    text = read_data_text(_CATALOG_NAME)
    return _parse_catalog(json.loads(text))


def _highest_rk_is_numeric(highest_rk: str) -> bool:
    return bool(re.fullmatch(r"\d+", highest_rk.strip()))


def useful_matches_missing(useful: UsefulSpell, missing_name: str) -> bool:
    """True when a MissingSpells line corresponds to a curated useful spell."""
    missing_base = strip_spell_rank(missing_name).casefold()
    useful_key = useful.name.casefold()
    if missing_base == useful_key:
        return True
    if _highest_rk_is_numeric(useful.highest_rk):
        stripped = _TRAILING_RANK_TOKEN_RE.sub("", missing_base).strip()
        if stripped == useful_key:
            return True
    return False


def _rank_preference(spell_name: str) -> int:
    """Higher is better when choosing among duplicate missing lines."""
    if is_missing_rank_iii(spell_name):
        return 3
    if re.search(r"Rk\.?\s*II\b", spell_name, re.IGNORECASE):
        return 2
    # Trailing roman / number after base name
    token = _TRAILING_RANK_TOKEN_RE.search(strip_spell_rank(spell_name))
    if token:
        raw = token.group(0).strip().upper()
        roman = {
            "I": 1,
            "II": 2,
            "III": 3,
            "IV": 4,
            "V": 5,
            "VI": 6,
            "VII": 7,
            "VIII": 8,
            "IX": 9,
            "X": 10,
            "XI": 11,
            "XII": 12,
        }
        if raw in roman:
            return roman[raw]
        if raw.isdigit():
            return int(raw)
    return 1


def _pick_best_missing(
    useful: UsefulSpell,
    candidates: list[MissingSpellLine],
) -> MissingSpellLine | None:
    matches = [line for line in candidates if useful_matches_missing(useful, line.name)]
    if not matches:
        return None
    if useful.level is not None:
        same_level = [line for line in matches if line.level == useful.level]
        if same_level:
            matches = same_level
    return max(matches, key=lambda line: (_rank_preference(line.name), line.level))


def build_missing_useful_spells_report(
    team: TeamGearReport,
    spell_paths: dict[str, Path] | None = None,
    *,
    inventory_paths: list[Path] | None = None,
    extra_spell_paths: list[Path] | None = None,
    discovery_warnings: list[str] | None = None,
    useful_by_class: dict[str, list[UsefulSpell]] | None = None,
) -> MissingUsefulSpellsReport | None:
    """
    Intersect each persona's MissingSpells dump with the curated useful list.

    Includes all levels (not limited to the 121–130 rune band).
    """
    personas = _spell_personas(team)
    warnings: list[str] = list(discovery_warnings or [])
    if spell_paths is None:
        inv_paths = inventory_paths or [Path(c.filepath) for c in personas]
        discovery = discover_missing_spells_for_inventories(
            inv_paths,
            extra_spell_paths=extra_spell_paths,
        )
        spell_paths = discovery.paths
        warnings.extend(discovery.warnings)

    if not spell_paths:
        return None

    catalog = useful_by_class if useful_by_class is not None else load_useful_spells()
    spell_catalog = load_spell_catalog()
    persona_order = [c.persona_key for c in personas]
    report = MissingUsefulSpellsReport(persona_keys=persona_order, warnings=warnings)

    for char_gear in personas:
        pk = char_gear.persona_key
        class_abbr = (char_gear.class_abbr or "").upper() or None
        spell_path = spell_path_for_persona(
            char_gear.character,
            char_gear.server,
            char_gear.class_abbr,
            spell_paths,
        )
        if spell_path is None:
            continue
        if not class_abbr:
            report.warnings.append(
                f"No class for {char_gear.display_name}; skipping useful-spell check"
            )
            continue
        useful_list = catalog.get(class_abbr)
        if not useful_list:
            report.warnings.append(
                f"No useful-spell list for class {class_abbr} ({char_gear.display_name})"
            )
            continue

        missing_lines = parse_missing_spells_file(spell_path)
        for useful in useful_list:
            best = _pick_best_missing(useful, missing_lines)
            if best is None:
                continue
            level = best.level if useful.level is None else useful.level
            spell_id = lookup_spell_id(
                class_abbr,
                level,
                best.name,
                catalog=spell_catalog,
            )
            report.entries.append(
                MissingUsefulSpell(
                    persona_key=pk,
                    display_name=char_gear.display_name,
                    character=char_gear.character,
                    level=level,
                    expansion=useful.expansion,
                    spell_name=best.name,
                    highest_rk=useful.highest_rk,
                    comments=useful.comments,
                    eqresource_url=eqresource_spell_url(
                        spell_id,
                        best.name,
                        class_abbr=class_abbr,
                        level=level,
                    ),
                )
            )

    report.entries.sort(
        key=lambda e: (
            e.persona_key.casefold(),
            -(e.level),
            e.spell_name.casefold(),
        )
    )
    return report
