"""Spell rune tiers by level and expansion block."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from inventory_parser.package_data import read_data_text

_CONFIG_NAME = "spell_rune_bands.json"


@dataclass(frozen=True)
class SpellLevelBlock:
    level_start: int
    level_end: int
    label: str
    expansions: tuple[str, ...]
    turn_in_theme: str
    count_runes: bool


@dataclass(frozen=True)
class SpellRuneConfig:
    band_size: int
    tiers: tuple[str, ...]
    blocks: tuple[SpellLevelBlock, ...]


@dataclass(frozen=True)
class MissingRuneExpansionGroup:
    key: str
    label: str
    turn_in_theme: str


MISSING_RUNE_EXPANSION_GROUPS: tuple[MissingRuneExpansionGroup, ...] = (
    MissingRuneExpansionGroup(
        "sor",
        "Shattering of Ro (2025)",
        "{Tier} Mirrorshard of Relic",
    ),
    MissingRuneExpansionGroup(
        "tob",
        "The Outer Brood (2024)",
        "Energized {Tier} Engram",
    ),
    MissingRuneExpansionGroup(
        "ls",
        "Laurion's Song (2023)",
        "{Tier} Emblem of the Forge",
    ),
)


def missing_rune_expansion_groups() -> tuple[MissingRuneExpansionGroup, ...]:
    return MISSING_RUNE_EXPANSION_GROUPS


def _parse_block(raw: dict[str, Any]) -> SpellLevelBlock:
    return SpellLevelBlock(
        level_start=int(raw["level_start"]),
        level_end=int(raw["level_end"]),
        label=str(raw["label"]),
        expansions=tuple(str(x) for x in raw["expansions"]),
        turn_in_theme=str(raw["turn_in_theme"]),
        count_runes=bool(raw.get("count_runes", True)),
    )


def _parse_config(data: dict[str, Any]) -> SpellRuneConfig:
    return SpellRuneConfig(
        band_size=int(data.get("band_size", 5)),
        tiers=tuple(str(t) for t in data["tiers"]),
        blocks=tuple(_parse_block(b) for b in data["blocks"]),
    )


@lru_cache(maxsize=1)
def load_rune_config() -> SpellRuneConfig:
    text = read_data_text(_CONFIG_NAME)
    return _parse_config(json.loads(text))


def block_for_level(level: int, config: SpellRuneConfig | None = None) -> SpellLevelBlock | None:
    cfg = config or load_rune_config()
    for block in cfg.blocks:
        if block.level_start <= level <= block.level_end:
            return block
    return None


def enabled_blocks(config: SpellRuneConfig | None = None) -> tuple[SpellLevelBlock, ...]:
    cfg = config or load_rune_config()
    return tuple(b for b in cfg.blocks if b.count_runes)


def rune_tier_for_level(level: int, config: SpellRuneConfig | None = None) -> str | None:
    cfg = config or load_rune_config()
    block = block_for_level(level, cfg)
    if block is None or not block.count_runes:
        return None
    offset = level - block.level_start
    if offset < 0 or offset >= len(cfg.tiers):
        return None
    return cfg.tiers[offset]
