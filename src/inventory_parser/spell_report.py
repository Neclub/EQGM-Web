"""Build missing Rank III spell / rune reports."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from inventory_parser.team_report import TeamGearReport
from inventory_parser.missing_spells import (
    MissingSpellLine,
    counts_as_missing_rk3,
    discover_missing_spells_for_inventories,
    lacks_rank_suffix,
    normalize_spell_rank_iii,
    parse_missing_spells_file,
    spell_path_for_persona,
    spell_rank_priority,
    strip_spell_rank,
)
from inventory_parser.spell_runes import (
    MissingRuneExpansionGroup,
    SpellLevelBlock,
    block_for_level,
    enabled_blocks,
    load_rune_config,
    missing_rune_expansion_groups,
    rune_tier_for_level,
)
from inventory_parser.spell_catalog import (
    eqresource_spell_url,
    load_spell_catalog,
    lookup_expansion,
    lookup_expansion_label,
    lookup_spell_id,
)


@dataclass(frozen=True)
class MissingRankIII:
    persona_key: str
    display_name: str
    character: str
    level: int
    spell_name: str
    block_label: str
    rune_tier: str
    turn_in_theme: str
    expansion: str = ""
    not_purchased: bool = False
    eqresource_url: str = ""


@dataclass
class SpellRuneReport:
    persona_keys: list[str]
    entries: list[MissingRankIII] = field(default_factory=list)
    counts_by_persona: dict[str, dict[str, dict[str, int]]] = field(default_factory=dict)
    blocks: tuple[SpellLevelBlock, ...] = ()
    expansion_groups: tuple[MissingRuneExpansionGroup, ...] = ()
    warnings: list[str] = field(default_factory=list)


def _spell_personas(team: TeamGearReport) -> list:
    if team.spell_characters:
        return team.spell_characters
    return team.characters


def build_spell_rune_report(
    team: TeamGearReport,
    spell_paths: dict[str, Path] | None = None,
    *,
    inventory_paths: list[Path] | None = None,
    extra_spell_paths: list[Path] | None = None,
    discovery_warnings: list[str] | None = None,
) -> SpellRuneReport | None:
    """
    Build spell rune data for team characters.

    If ``spell_paths`` is omitted, discovers files from ``inventory_paths``,
    ``extra_spell_paths``, or each character's inventory filepath.
    """
    config = load_rune_config()
    blocks = enabled_blocks(config)
    if not blocks:
        return None

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

    persona_order = [c.persona_key for c in personas]
    catalog = load_spell_catalog()
    report = SpellRuneReport(
        persona_keys=persona_order,
        blocks=blocks,
        expansion_groups=missing_rune_expansion_groups(),
        warnings=warnings,
    )
    counts: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(int))
    )

    for char_gear in personas:
        pk = char_gear.persona_key
        spell_path = spell_path_for_persona(
            char_gear.character,
            char_gear.server,
            char_gear.class_abbr,
            spell_paths,
        )
        if spell_path is None:
            suffix = f"-{char_gear.class_abbr}" if char_gear.class_abbr else ""
            report.warnings.append(
                f"No MissingSpells file for {char_gear.display_name} "
                f"(expected {char_gear.character}_{char_gear.server}{suffix}-*-MissingSpells.txt)"
            )
            continue

        candidates: dict[tuple[int, str], MissingSpellLine] = {}
        for line in parse_missing_spells_file(spell_path):
            tier = rune_tier_for_level(line.level, config)
            if tier is None:
                continue
            if not counts_as_missing_rk3(line.name):
                # Rank 1 is listed by name only (no "Rk. I"). Include when the
                # catalog has a Rk. III version so AAs / mastery lines stay out.
                if (
                    lookup_expansion(
                        char_gear.class_abbr,
                        line.level,
                        line.name,
                        catalog=catalog,
                    )
                    is None
                ):
                    continue
            dedupe_key = (line.level, strip_spell_rank(line.name).casefold())
            existing = candidates.get(dedupe_key)
            if existing is None or spell_rank_priority(line.name) > spell_rank_priority(
                existing.name
            ):
                candidates[dedupe_key] = line

        for line in candidates.values():
            tier = rune_tier_for_level(line.level, config)
            assert tier is not None
            block = block_for_level(line.level, config)
            assert block is not None
            display_name = normalize_spell_rank_iii(line.name)
            spell_id = lookup_spell_id(
                char_gear.class_abbr,
                line.level,
                display_name,
                catalog=catalog,
            )
            entry = MissingRankIII(
                persona_key=pk,
                display_name=char_gear.display_name,
                character=char_gear.character,
                level=line.level,
                spell_name=display_name,
                block_label=block.label,
                rune_tier=tier,
                turn_in_theme=block.turn_in_theme,
                expansion=lookup_expansion_label(
                    char_gear.class_abbr,
                    line.level,
                    display_name,
                    catalog=catalog,
                ),
                not_purchased=lacks_rank_suffix(line.name),
                eqresource_url=eqresource_spell_url(
                    spell_id,
                    display_name,
                    class_abbr=char_gear.class_abbr,
                    level=line.level,
                ),
            )
            report.entries.append(entry)
            if entry.expansion:
                counts[pk][entry.expansion][tier] += 1

    report.entries.sort(
        key=lambda e: (
            e.persona_key.casefold(),
            e.expansion.casefold(),
            e.level,
            e.spell_name.casefold(),
        )
    )
    report.counts_by_persona = {
        pk: {label: dict(tiers) for label, tiers in by_block.items()}
        for pk, by_block in counts.items()
    }
    for pk in persona_order:
        report.counts_by_persona.setdefault(pk, {})

    return report
