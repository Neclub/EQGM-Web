"""Build achievement collection and summary reports for team exports."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from inventory_parser.achievement_files import collect_achievement_paths
from inventory_parser.achievement_parser import (
    AchievementParseResult,
    MissingCollectionItem,
    MissingRaidAchievement,
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


@dataclass
class AchievementReport:
    missing_collections: list[MissingCollectionRow] = field(default_factory=list)
    raid_achievements: list[RaidAchievementRow] = field(default_factory=list)
    quests: list[QuestRow] = field(default_factory=list)
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


def _rows_from_parse(
    display_name: str,
    parsed: AchievementParseResult,
    item_holders: dict[str, list[str]],
) -> tuple[
    list[MissingCollectionRow],
    list[RaidAchievementRow],
    list[QuestRow],
    list[AchievementSummaryRow],
    list[HeroicAARow],
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
    heroic = _heroic_aa_rows_from_parse(
        display_name,
        parsed.top_level,
        load_heroic_aa_catalog(),
    )
    return missing, raids, quests, summaries, heroic


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
        missing, raids, quests, summaries, heroic = _rows_from_parse(
            character.character,
            parsed,
            item_holders,
        )
        report.missing_collections.extend(missing)
        report.raid_achievements.extend(raids)
        report.quests.extend(quests)
        report.summaries.extend(summaries)
        report.heroic_aas.extend(heroic)

    report.raid_achievements = _sort_raid_achievement_rows(report.raid_achievements)
    report.quests = _sort_quest_rows(report.quests)
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
