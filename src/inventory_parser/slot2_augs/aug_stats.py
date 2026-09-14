"""Canonical aug stat keys shared by parsers, weights, and scoring."""

from __future__ import annotations

from typing import Mapping

from inventory_parser.slot2_augs.profiles import PROFILE_FOCUS_STAT, ProfileId

# Keys used in AugCandidate.stats and weight JSON files.
STAT_KEYS: tuple[str, ...] = (
    "ac",
    "hp",
    "mana",
    "endurance",
    "str",
    "sta",
    "agi",
    "dex",
    "wis",
    "int",
    "cha",
    "hstr",
    "hsta",
    "hagi",
    "hdex",
    "hwis",
    "hint",
    "hcha",
    "atk",
    "accuracy",
    "combat_effects",
    "avoidance",
    "shielding",
    "spell_shield",
    "dot_shield",
    "stun_resist",
    "strikethrough",
    "heal_amount",
    "spell_damage",
    "clairvoyance",
)

# Advanced GUI always surfaces these stats (zeros when unused).
# Accuracy / Combat Effects / Shielding / Stun Resist stay out of scoring UI.
ADVANCED_WEIGHT_EXCLUDE: frozenset[str] = frozenset(
    {
        "accuracy",
        "combat_effects",
        "shielding",
        "stun_resist",
    }
)
ADVANCED_WEIGHT_ALWAYS: tuple[str, ...] = (
    "ac",
    "hp",
    "mana",
    "hdex",
    "hint",
    "hwis",
    "spell_damage",
)

# Short labels for upgrade notes / UI.
STAT_DISPLAY: dict[str, str] = {
    "ac": "AC",
    "hp": "HP",
    "mana": "Mana",
    "endurance": "End",
    "str": "STR",
    "sta": "STA",
    "agi": "AGI",
    "dex": "DEX",
    "wis": "WIS",
    "int": "INT",
    "cha": "CHA",
    "hstr": "HStr",
    "hsta": "HSta",
    "hagi": "HAgi",
    "hdex": "HDex",
    "hwis": "HWis",
    "hint": "HInt",
    "hcha": "HCha",
    "atk": "ATK",
    "accuracy": "Accuracy",
    "combat_effects": "Combat Effects",
    "avoidance": "Avoidance",
    "shielding": "Shielding",
    "spell_shield": "Spell Shield",
    "dot_shield": "DoT Shield",
    "stun_resist": "Stun Resist",
    "strikethrough": "Strike Through",
    "heal_amount": "Heal Amount",
    "spell_damage": "Spell Damage",
    "clairvoyance": "Clairvoyance",
}

# Raidloot / plain-text label → canonical key (non-heroic value).
LABEL_TO_STAT: dict[str, str] = {
    "ac": "ac",
    "hp": "hp",
    "mana": "mana",
    "end": "endurance",
    "endurance": "endurance",
    "atk": "atk",
    "attack": "atk",
    "accuracy": "accuracy",
    "combat effects": "combat_effects",
    "combateffects": "combat_effects",
    "avoidance": "avoidance",
    "shielding": "shielding",
    "spell shield": "spell_shield",
    "spellshield": "spell_shield",
    "dot shield": "dot_shield",
    "dotshield": "dot_shield",
    "stun resist": "stun_resist",
    "stunresist": "stun_resist",
    "strike through": "strikethrough",
    "strikethrough": "strikethrough",
    "heal amount": "heal_amount",
    "heal amt": "heal_amount",
    "healamt": "heal_amount",
    "heal": "heal_amount",
    "spell damage": "spell_damage",
    "spell dmg": "spell_damage",
    "spelldmg": "spell_damage",
    "nuke": "spell_damage",
    "clairvoyance": "clairvoyance",
    "clrv": "clairvoyance",
}

# Attribute labels that carry base + heroic.
ATTR_BASE: dict[str, str] = {
    "str": "str",
    "strength": "str",
    "sta": "sta",
    "stamina": "sta",
    "agi": "agi",
    "agility": "agi",
    "dex": "dex",
    "dexterity": "dex",
    "wis": "wis",
    "wisdom": "wis",
    "int": "int",
    "intelligence": "int",
    "cha": "cha",
    "charisma": "cha",
}

ATTR_HEROIC: dict[str, str] = {
    "str": "hstr",
    "strength": "hstr",
    "sta": "hsta",
    "stamina": "hsta",
    "agi": "hagi",
    "agility": "hagi",
    "dex": "hdex",
    "dexterity": "hdex",
    "wis": "hwis",
    "wisdom": "hwis",
    "int": "hint",
    "intelligence": "hint",
    "cha": "hcha",
    "charisma": "hcha",
}


def clean_stats(raw: Mapping[str, int]) -> dict[str, int]:
    """Keep known keys with positive ints only."""
    out: dict[str, int] = {}
    for key, val in raw.items():
        if key not in STAT_KEYS:
            continue
        try:
            n = int(val)
        except (TypeError, ValueError):
            continue
        if n:
            out[key] = n
    return out


def focus_from_stats(stats: Mapping[str, int], profile: ProfileId) -> int:
    return int(stats.get(PROFILE_FOCUS_STAT[profile], 0))


def legacy_from_stats(
    stats: Mapping[str, int], profile: ProfileId
) -> tuple[int, int, int, int]:
    """Return (focus_heroic, ac, hp, atk) derived from stats."""
    return (
        focus_from_stats(stats, profile),
        int(stats.get("ac", 0)),
        int(stats.get("hp", 0)),
        int(stats.get("atk", 0)),
    )


def artisans_prize_stats() -> dict[str, int]:
    return {
        "ac": 300,
        "hp": 3000,
        "atk": 200,
        "hstr": 150,
        "hsta": 150,
        "hagi": 150,
        "hdex": 150,
        "hwis": 150,
        "hint": 150,
        "hcha": 150,
        "sta": 75,
        "str": 75,
        "wis": 75,
        "int": 75,
        "dex": 75,
        "agi": 75,
        "cha": 75,
    }


def merge_stats(*parts: Mapping[str, int] | None) -> dict[str, int]:
    out: dict[str, int] = {}
    for part in parts:
        if not part:
            continue
        for k, v in part.items():
            if k in STAT_KEYS and int(v):
                out[k] = int(v) if k not in out else max(out[k], int(v))
    return out
