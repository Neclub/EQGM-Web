"""Build achievement collection and summary reports for team exports."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from inventory_parser.achievement_files import collect_achievement_paths
from inventory_parser.achievement_parser import (
    AchievementParseResult,
    MissingCollectionItem,
    MissingHunterAchievement,
    MissingRaidAchievement,
    MissingSlayerAchievement,
    QuestAchievement,
    TopLevelAchievement,
    expansion_sort_key,
    parse_achievements_file,
)
from inventory_parser.heroic_aas import (
    HeroicAACatalog,
    load_heroic_aa_catalog,
    normalize_heroic_name,
)
from inventory_parser.team_report import TeamGearReport
from inventory_parser.parser import parse_inventory_file

# Dump achievement name is ``Skill (N)``; display may differ (e.g. Smithing -> Blacksmithing).
_TRADESKILL_LEVEL_RE = re.compile(r"^(.+?)\s+\((\d+)\)\s*$")

# (dump_skill_name, display_name, group) — group is "core" or "special".
_TRADESKILL_CATALOG: tuple[tuple[str, str, str], ...] = (
    ("Baking", "Baking", "core"),
    ("Smithing", "Blacksmithing", "core"),
    ("Brewing", "Brewing", "core"),
    ("Fishing", "Fishing", "core"),
    ("Fletching", "Fletching", "core"),
    ("Jewelcrafting", "Jewelcrafting", "core"),
    ("Pottery", "Pottery", "core"),
    ("Tailoring", "Tailoring", "core"),
    ("Research", "Research", "core"),
    ("Alchemy", "Alchemy", "special"),
    ("Tinkering", "Tinkering", "special"),
    ("Poisonmaking", "Poisonmaking", "special"),
)

_TRADESKILL_BY_DUMP: dict[str, tuple[str, str]] = {
    dump.casefold(): (display, group) for dump, display, group in _TRADESKILL_CATALOG
}

TRADESKILL_CORE_COLUMNS: tuple[str, ...] = tuple(
    display for _dump, display, group in _TRADESKILL_CATALOG if group == "core"
)
TRADESKILL_SPECIAL_COLUMNS: tuple[str, ...] = tuple(
    display for _dump, display, group in _TRADESKILL_CATALOG if group == "special"
)


@dataclass(frozen=True)
class MissingCollectionRow:
    character: str
    expansion: str
    zone: str
    collection: str
    missing_item: str
    progress: str
    char_has: str
    total: int


@dataclass(frozen=True)
class AchievementSummaryRow:
    character: str
    section: str
    completed: int
    incomplete: int
    total: int
    completion_pct: float


@dataclass(frozen=True)
class RaidAchievementRow:
    character: str
    expansion: str
    raid: str
    event: str
    objective: str
    status: str


@dataclass(frozen=True)
class QuestRow:
    character: str
    expansion: str
    zone: str
    quest_type: str
    quest: str
    status: str


@dataclass(frozen=True)
class HunterRow:
    character: str
    expansion: str
    hunter: str
    zone: str
    target: str
    status: str


@dataclass(frozen=True)
class SlayerRow:
    character: str
    achievement: str
    objective: str
    status: str


@dataclass(frozen=True)
class HeroicAARow:
    character: str
    expansion: str
    achievement: str
    fortitude: int
    resolution: int
    vitality: int
    status: str


@dataclass(frozen=True)
class HeroicAATotal:
    character: str
    fortitude: int
    resolution: int
    vitality: int
    completed: int
    total: int


@dataclass(frozen=True)
class TradeskillLevel:
    name: str
    level: int
    group: str  # "core" or "special"


@dataclass(frozen=True)
class TradeskillCard:
    character: str
    skills: tuple[TradeskillLevel, ...]


@dataclass
class AchievementReport:
    missing_collections: list[MissingCollectionRow] = field(default_factory=list)
    raid_achievements: list[RaidAchievementRow] = field(default_factory=list)
    quests: list[QuestRow] = field(default_factory=list)
    hunters: list[HunterRow] = field(default_factory=list)
    slayer: list[SlayerRow] = field(default_factory=list)
    tradeskills: list[TradeskillCard] = field(default_factory=list)
    summaries: list[AchievementSummaryRow] = field(default_factory=list)
    heroic_aas: list[HeroicAARow] = field(default_factory=list)
    heroic_aa_totals: list[HeroicAATotal] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def has_data(self) -> bool:
        return bool(
            self.missing_collections
            or self.raid_achievements
            or self.quests
            or self.hunters
            or self.slayer
            or self.tradeskills
            or self.summaries
            or self.heroic_aas
        )


def _character_key(character: str, server: str) -> str:
    return f"{character}_{server}".casefold()


def _build_item_holders_by_name(team: TeamGearReport) -> dict[str, list[str]]:
    """Map item name (casefold) to character names that have it in inventory.

    Personas of the same character share one inventory/collections, so holders are
    keyed by character+server (base name once), not per class column.
    """
    holders: dict[str, list[str]] = {}
    seen: dict[str, set[str]] = {}
    for character in team.characters:
        data = character.inventory_data or parse_inventory_file(character.filepath)
        if data is None:
            continue
        holder_name = character.character
        holder_key = _character_key(character.character, character.server)
        for item in data.items:
            if not item.name or item.name == "Empty":
                continue
            key = item.name.casefold()
            seen_holders = seen.setdefault(key, set())
            if holder_key in seen_holders:
                continue
            seen_holders.add(holder_key)
            holders.setdefault(key, []).append(holder_name)
    for names in holders.values():
        names.sort(key=str.casefold)
    return holders


def _char_has_item(item_name: str, holders: dict[str, list[str]]) -> str:
    names = holders.get(item_name.casefold(), [])
    return ", ".join(names)


def _raid_rows_from_parse(
    display_name: str,
    raids: list[MissingRaidAchievement],
) -> list[RaidAchievementRow]:
    grouped: dict[tuple[str, str, str], list[MissingRaidAchievement]] = defaultdict(list)
    for item in raids:
        grouped[(display_name, item.section, item.raid)].append(item)

    rows: list[RaidAchievementRow] = []
    for (character, expansion, raid), children in grouped.items():
        unique: dict[str, MissingRaidAchievement] = {}
        order: list[str] = []
        for child in children:
            key = child.objective.casefold()
            previous = unique.get(key)
            if previous is None:
                unique[key] = child
                order.append(key)
            elif previous.complete and not child.complete:
                unique[key] = child
        merged = [unique[key] for key in order]
        if all(child.complete for child in merged):
            continue
        for child in merged:
            rows.append(
                RaidAchievementRow(
                    character=character,
                    expansion=expansion,
                    raid=raid,
                    event=child.event,
                    objective=child.objective,
                    status="Done" if child.complete else "Missing",
                )
            )
    return rows


def _sort_missing_collection_rows(rows: list[MissingCollectionRow]) -> list[MissingCollectionRow]:
    return sorted(
        rows,
        key=lambda row: (
            expansion_sort_key(row.expansion),
            row.zone.casefold(),
            row.collection.casefold(),
            row.missing_item.casefold(),
            row.character.casefold(),
        ),
    )


def _sort_achievement_summary_rows(rows: list[AchievementSummaryRow]) -> list[AchievementSummaryRow]:
    return sorted(
        rows,
        key=lambda row: (
            expansion_sort_key(row.section),
            row.character.casefold(),
        ),
    )


def _sort_raid_achievement_rows(rows: list[RaidAchievementRow]) -> list[RaidAchievementRow]:
    return sorted(
        rows,
        key=lambda row: (
            expansion_sort_key(row.expansion),
            row.event.casefold(),
            row.raid.casefold(),
            row.objective.casefold(),
            row.character.casefold(),
        ),
    )


def _sort_quest_rows(rows: list[QuestRow]) -> list[QuestRow]:
    return sorted(
        rows,
        key=lambda row: (
            expansion_sort_key(row.expansion),
            row.zone.casefold(),
            row.quest_type.casefold(),
            row.character.casefold(),
            row.quest.casefold(),
        ),
    )


def _sort_hunter_rows(rows: list[HunterRow]) -> list[HunterRow]:
    return sorted(
        rows,
        key=lambda row: (
            expansion_sort_key(row.expansion),
            row.zone.casefold(),
            row.target.casefold(),
            row.character.casefold(),
        ),
    )


def _sort_heroic_aa_rows(rows: list[HeroicAARow]) -> list[HeroicAARow]:
    return sorted(
        rows,
        key=lambda row: (
            expansion_sort_key(row.expansion),
            row.achievement.casefold(),
            row.character.casefold(),
        ),
    )


def _dump_complete_by_name(entries: list[TopLevelAchievement]) -> dict[str, bool]:
    found: dict[str, bool] = {}
    for item in entries:
        key = normalize_heroic_name(item.name)
        if not key:
            continue
        found[key] = found.get(key, False) or item.complete
    return found


def _heroic_aa_rows_from_parse(
    display_name: str,
    top_level: list[TopLevelAchievement],
    catalog: HeroicAACatalog,
) -> list[HeroicAARow]:
    dump_status = _dump_complete_by_name(top_level)
    rows: list[HeroicAARow] = []
    for entry in catalog.achievements:
        complete = any(dump_status.get(key, False) for key in entry.match_keys())
        rows.append(
            HeroicAARow(
                character=display_name,
                expansion=entry.expansion,
                achievement=entry.name,
                fortitude=entry.fortitude,
                resolution=entry.resolution,
                vitality=entry.vitality,
                status="Completed" if complete else "Incomplete",
            )
        )
    return rows


def _heroic_aa_totals_from_rows(rows: list[HeroicAARow]) -> list[HeroicAATotal]:
    by_character: dict[str, list[HeroicAARow]] = defaultdict(list)
    for row in rows:
        by_character[row.character].append(row)
    totals: list[HeroicAATotal] = []
    for character, items in by_character.items():
        completed_items = [item for item in items if item.status == "Completed"]
        totals.append(
            HeroicAATotal(
                character=character,
                fortitude=sum(item.fortitude for item in completed_items),
                resolution=sum(item.resolution for item in completed_items),
                vitality=sum(item.vitality for item in completed_items),
                completed=len(completed_items),
                total=len(items),
            )
        )
    totals.sort(key=lambda row: row.character.casefold())
    return totals


def _quest_rows_from_parse(
    display_name: str,
    quests: list[QuestAchievement],
) -> list[QuestRow]:
    grouped: dict[tuple[str, str, str, str], list[QuestAchievement]] = defaultdict(list)
    for item in quests:
        grouped[(display_name, item.section, item.quest_type, item.zone)].append(item)

    rows: list[QuestRow] = []
    for (character, expansion, quest_type, zone), children in grouped.items():
        if all(child.complete for child in children):
            continue
        for child in children:
            rows.append(
                QuestRow(
                    character=character,
                    expansion=expansion,
                    zone=zone,
                    quest_type=quest_type,
                    quest=child.quest,
                    status="Done" if child.complete else "Missing",
                )
            )
    return rows


def _hunter_rows_from_parse(
    display_name: str,
    hunters: list[MissingHunterAchievement],
) -> list[HunterRow]:
    grouped: dict[tuple[str, str, str], list[MissingHunterAchievement]] = defaultdict(list)
    for item in hunters:
        grouped[(display_name, item.section, item.hunter)].append(item)

    rows: list[HunterRow] = []
    for (character, expansion, hunter), children in grouped.items():
        unique: dict[str, MissingHunterAchievement] = {}
        order: list[str] = []
        for child in children:
            key = child.target.casefold()
            previous = unique.get(key)
            if previous is None:
                unique[key] = child
                order.append(key)
            elif previous.complete and not child.complete:
                unique[key] = child
        merged = [unique[key] for key in order]
        if all(child.complete for child in merged):
            continue
        for child in merged:
            rows.append(
                HunterRow(
                    character=character,
                    expansion=expansion,
                    hunter=hunter,
                    zone=child.zone,
                    target=child.target,
                    status="Done" if child.complete else "Missing",
                )
            )
    return rows


def _slayer_rows_from_parse(
    display_name: str,
    slayers: list[MissingSlayerAchievement],
) -> list[SlayerRow]:
    """Build Megadeath rows; keep fully complete cards so finished chars still appear."""
    grouped: dict[tuple[str, str], list[MissingSlayerAchievement]] = defaultdict(list)
    for item in slayers:
        grouped[(display_name, item.slayer)].append(item)

    rows: list[SlayerRow] = []
    for (character, achievement), children in grouped.items():
        unique: dict[str, MissingSlayerAchievement] = {}
        order: list[str] = []
        for child in children:
            key = child.objective.casefold()
            previous = unique.get(key)
            if previous is None:
                unique[key] = child
                order.append(key)
            elif previous.complete and not child.complete:
                unique[key] = child
        for key in order:
            child = unique[key]
            rows.append(
                SlayerRow(
                    character=character,
                    achievement=achievement,
                    objective=child.objective,
                    status="Done" if child.complete else "Missing",
                )
            )
    return rows


def _sort_slayer_rows(rows: list[SlayerRow]) -> list[SlayerRow]:
    return sorted(
        rows,
        key=lambda row: (
            row.character.casefold(),
            row.achievement.casefold(),
            row.objective.casefold(),
        ),
    )


def _tradeskill_card_from_parse(
    display_name: str,
    top_level: list[TopLevelAchievement],
) -> TradeskillCard | None:
    """Highest completed ``Skill (N)`` under Tradeskill; core always, special if present."""
    present: set[str] = set()
    completed_levels: dict[str, int] = {}
    for item in top_level:
        if item.section.casefold() != "tradeskill":
            continue
        match = _TRADESKILL_LEVEL_RE.match(item.name.strip())
        if match is None:
            continue
        dump_skill = match.group(1).strip()
        level = int(match.group(2))
        meta = _TRADESKILL_BY_DUMP.get(dump_skill.casefold())
        if meta is None:
            continue
        display, _group = meta
        present.add(display)
        if item.complete:
            previous = completed_levels.get(display, 0)
            if level > previous:
                completed_levels[display] = level

    if not present:
        return None

    skills: list[TradeskillLevel] = []
    for _dump, display, group in _TRADESKILL_CATALOG:
        if group == "core":
            skills.append(
                TradeskillLevel(
                    name=display,
                    level=completed_levels.get(display, 0),
                    group=group,
                )
            )
        elif display in present:
            skills.append(
                TradeskillLevel(
                    name=display,
                    level=completed_levels.get(display, 0),
                    group=group,
                )
            )
    return TradeskillCard(character=display_name, skills=tuple(skills))


def _sort_tradeskill_cards(cards: list[TradeskillCard]) -> list[TradeskillCard]:
    return sorted(cards, key=lambda card: card.character.casefold())


def _rows_from_parse(
    display_name: str,
    parsed: AchievementParseResult,
    item_holders: dict[str, list[str]],
) -> tuple[
    list[MissingCollectionRow],
    list[RaidAchievementRow],
    list[QuestRow],
    list[HunterRow],
    list[SlayerRow],
    list[AchievementSummaryRow],
    list[HeroicAARow],
    TradeskillCard | None,
]:
    missing = [
        MissingCollectionRow(
            character=display_name,
            expansion=item.section,
            zone=item.zone,
            collection=item.collection,
            missing_item=item.item,
            progress=item.progress,
            char_has=_char_has_item(item.item, item_holders),
            total=item.total,
        )
        for item in parsed.missing_collections
    ]
    summaries = [
        AchievementSummaryRow(
            character=display_name,
            section=summary.section,
            completed=summary.completed,
            incomplete=summary.incomplete,
            total=summary.total,
            completion_pct=summary.completion_pct,
        )
        for summary in parsed.section_summaries
        if summary.total > 0
    ]
    raids = _raid_rows_from_parse(display_name, parsed.missing_raid_achievements)
    quests = _quest_rows_from_parse(display_name, parsed.quest_achievements)
    hunters = _hunter_rows_from_parse(display_name, parsed.missing_hunter_achievements)
    slayer = _slayer_rows_from_parse(display_name, parsed.missing_slayer_achievements)
    heroic = _heroic_aa_rows_from_parse(
        display_name,
        parsed.top_level,
        load_heroic_aa_catalog(),
    )
    tradeskills = _tradeskill_card_from_parse(display_name, parsed.top_level)
    return missing, raids, quests, hunters, slayer, summaries, heroic, tradeskills


def build_achievement_report(
    team: TeamGearReport,
    achievement_paths: dict[str, Path] | None = None,
    *,
    inventory_paths: list[Path] | None = None,
    extra_achievement_paths: list[Path] | None = None,
) -> AchievementReport | None:
    """Build achievement rows for characters with achievement dumps."""
    if achievement_paths is None:
        if not inventory_paths and not extra_achievement_paths:
            inventory_paths = [Path(c.filepath) for c in team.characters]
        achievement_paths = collect_achievement_paths(
            inventory_paths or [],
            extra_achievement_paths,
        )
    if not achievement_paths:
        return None

    report = AchievementReport()
    seen_characters: set[str] = set()
    item_holders = _build_item_holders_by_name(team)

    for character in team.characters:
        key = _character_key(character.character, character.server)
        path = achievement_paths.get(key)
        if path is None:
            continue
        # Achievements/collections are character-level; personas share one dump.
        if key in seen_characters:
            continue
        seen_characters.add(key)
        try:
            parsed = parse_achievements_file(path)
        except OSError as exc:
            report.warnings.append(
                f"Could not read achievements for {character.character}: {exc}"
            )
            continue
        missing, raids, quests, hunters, slayer, summaries, heroic, tradeskills = (
            _rows_from_parse(
                character.character,
                parsed,
                item_holders,
            )
        )
        report.missing_collections.extend(missing)
        report.raid_achievements.extend(raids)
        report.quests.extend(quests)
        report.hunters.extend(hunters)
        report.slayer.extend(slayer)
        report.summaries.extend(summaries)
        report.heroic_aas.extend(heroic)
        if tradeskills is not None:
            report.tradeskills.append(tradeskills)

    report.raid_achievements = _sort_raid_achievement_rows(report.raid_achievements)
    report.quests = _sort_quest_rows(report.quests)
    report.hunters = _sort_hunter_rows(report.hunters)
    report.slayer = _sort_slayer_rows(report.slayer)
    report.tradeskills = _sort_tradeskill_cards(report.tradeskills)
    report.missing_collections = _sort_missing_collection_rows(report.missing_collections)
    report.summaries = _sort_achievement_summary_rows(report.summaries)
    report.heroic_aas = _sort_heroic_aa_rows(report.heroic_aas)
    report.heroic_aa_totals = _heroic_aa_totals_from_rows(report.heroic_aas)

    for key, path in achievement_paths.items():
        if key in seen_characters:
            continue
        report.warnings.append(
            f"Achievement file has no matching inventory character: {path.name}"
        )

    if not report.has_data and not report.warnings:
        return None
    return report
