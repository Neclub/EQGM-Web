"""Count raid spell rune items held in character inventories."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from inventory_parser.package_data import read_data_text
from inventory_parser.parser import parse_inventory_file
from inventory_parser.team_report import CharacterGear, TeamGearReport

_CONFIG_NAME = "spell_rune_inventory.json"


@dataclass(frozen=True)
class RuneFamilyConfig:
    id: str
    label: str
    suffix: str
    prefix: str

    @property
    def item_pattern(self) -> str:
        if self.prefix.strip():
            return f"{self.prefix}{{Tier}} {self.suffix}"
        return f"{{Tier}} {self.suffix}"


@dataclass(frozen=True)
class RuneInventoryConfig:
    tiers: tuple[str, ...]
    families: tuple[RuneFamilyConfig, ...]


@dataclass(frozen=True)
class RuneFamilyInventory:
    id: str
    label: str
    item_pattern: str
    tiers: tuple[str, ...]
    counts: dict[str, dict[str, int]]


@dataclass(frozen=True)
class RuneInventoryReport:
    characters: tuple[CharacterGear, ...]
    families: tuple[RuneFamilyInventory, ...]

    def has_counts(self) -> bool:
        for family in self.families:
            for tier_counts in family.counts.values():
                if any(count > 0 for count in tier_counts.values()):
                    return True
        return False


def _parse_family(raw: dict[str, Any]) -> RuneFamilyConfig:
    return RuneFamilyConfig(
        id=str(raw["id"]),
        label=str(raw["label"]),
        suffix=str(raw["suffix"]),
        prefix=str(raw.get("prefix", "")),
    )


def _parse_config(data: dict[str, Any]) -> RuneInventoryConfig:
    return RuneInventoryConfig(
        tiers=tuple(str(tier) for tier in data["tiers"]),
        families=tuple(_parse_family(entry) for entry in data["families"]),
    )


@lru_cache(maxsize=1)
def load_rune_inventory_config() -> RuneInventoryConfig:
    text = read_data_text(_CONFIG_NAME)
    return _parse_config(json.loads(text))


def expected_item_name(tier: str, family: RuneFamilyConfig) -> str:
    return f"{family.prefix}{tier} {family.suffix}"


def is_rune_inventory_location(location: str) -> bool:
    """True for General, Bank, and Shared Bank inventory rows."""
    loc = location.strip()
    if loc.startswith("General"):
        return True
    if loc.startswith("SharedBank") or loc.startswith("Shared Bank"):
        return True
    if loc.startswith("Bank"):
        return True
    return False


def tier_from_item_name(
    item_name: str,
    family: RuneFamilyConfig,
    tiers: tuple[str, ...],
) -> str | None:
    normalized = item_name.strip()
    for tier in tiers:
        if normalized.casefold() == expected_item_name(tier, family).casefold():
            return tier
    return None


def _scan_character_inventory(
    character: CharacterGear,
    config: RuneInventoryConfig,
) -> dict[str, dict[str, int]]:
    by_family: dict[str, dict[str, int]] = {
        family.id: {tier: 0 for tier in config.tiers} for family in config.families
    }
    data = character.inventory_data or parse_inventory_file(character.filepath)
    if data is None:
        return by_family

    for item in data.items:
        if not item.name or item.name == "Empty":
            continue
        if not is_rune_inventory_location(item.location):
            continue
        for family in config.families:
            tier = tier_from_item_name(item.name, family, config.tiers)
            if tier is None:
                continue
            by_family[family.id][tier] += max(item.count, 1)
            break

    return by_family


def build_rune_inventory_report(team: TeamGearReport) -> RuneInventoryReport | None:
    """Build rune inventory counts from team inventory dumps."""
    if not team.characters:
        return None

    config = load_rune_inventory_config()
    characters = tuple(team.characters)
    family_counts: dict[str, dict[str, dict[str, int]]] = {
        family.id: {character.persona_key: {tier: 0 for tier in config.tiers} for character in characters}
        for family in config.families
    }

    for character in characters:
        scanned = _scan_character_inventory(character, config)
        for family in config.families:
            for tier, count in scanned[family.id].items():
                family_counts[family.id][character.persona_key][tier] += count

    families = tuple(
        RuneFamilyInventory(
            id=family.id,
            label=family.label,
            item_pattern=family.item_pattern,
            tiers=config.tiers,
            counts=family_counts[family.id],
        )
        for family in config.families
    )
    report = RuneInventoryReport(characters=characters, families=families)
    if not report.has_counts():
        return None
    return report
