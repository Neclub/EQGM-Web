"""Parse EverQuest /outputfile achievements dumps."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from pathlib import Path

EXPANSIONS_NEWEST_FIRST: tuple[tuple[str, int], ...] = (
    ("Shattering of Ro", 2025),
    ("The Outer Brood", 2024),
    ("Laurion's Song", 2023),
    ("Night of Shadows", 2022),
    ("Terror of Luclin", 2021),
    ("Claws of Veeshan", 2020),
    ("Torment of Velious", 2019),
    ("The Burning Lands", 2018),
    ("Ring of Scale", 2017),
    ("Empires of Kunark", 2016),
    ("The Broken Mirror", 2015),
    ("The Darkened Sea", 2014),
    ("Call of the Forsaken", 2013),
    ("Rain of Fear", 2012),
    ("Veil of Alaris", 2011),
    ("House of Thule", 2010),
    ("Underfoot", 2009),
    ("Seeds of Destruction", 2008),
    ("Secrets of Faydwer", 2007),
    ("The Buried Sea", 2007),
    ("The Serpent's Spine", 2006),
    ("Prophecy of Ro", 2006),
    ("Depths of Darkhollow", 2005),
    ("Dragons of Norrath", 2005),
    ("Omens of War", 2004),
    ("Gates of Discord", 2004),
    ("Lost Dungeons of Norrath", 2003),
    ("Legacy of Ykesha", 2003),
    ("Planes of Power", 2002),
    ("Shadows of Luclin", 2001),
    ("Scars of Velious", 2000),
    ("Ruins of Kunark", 2000),
)

_EXPANSION_ALIASES: dict[str, str] = {
    "the ruins of kunark": "Ruins of Kunark",
}

# Short codes used in dumps, vendor JSON, useful-spell lists, and rune families.
_EXPANSION_ABBREVS: dict[str, str] = {
    "classic": "EverQuest",
    "rok": "Ruins of Kunark",
    "kunark": "Ruins of Kunark",
    "sov": "Scars of Velious",
    "velious": "Scars of Velious",
    "sol": "Shadows of Luclin",
    "luclin": "Shadows of Luclin",
    "pop": "Planes of Power",
    "loy": "Legacy of Ykesha",
    "ldon": "Lost Dungeons of Norrath",
    "god": "Gates of Discord",
    "oow": "Omens of War",
    "don": "Dragons of Norrath",
    "dod": "Depths of Darkhollow",
    "por": "Prophecy of Ro",
    "tss": "The Serpent's Spine",
    "tbs": "The Buried Sea",
    "sof": "Secrets of Faydwer",
    "sod": "Seeds of Destruction",
    "uf": "Underfoot",
    "hot": "House of Thule",
    "voa": "Veil of Alaris",
    "rof": "Rain of Fear",
    "cotf": "Call of the Forsaken",
    "cof": "Call of the Forsaken",
    "tds": "The Darkened Sea",
    "tbm": "The Broken Mirror",
    "eok": "Empires of Kunark",
    "ros": "Ring of Scale",
    "tbl": "The Burning Lands",
    "tov": "Torment of Velious",
    "cov": "Claws of Veeshan",
    "tol": "Terror of Luclin",
    "nos": "Night of Shadows",
    "ls": "Laurion's Song",
    "tob": "The Outer Brood",
    "sor": "Shattering of Ro",
}

_YEAR_SUFFIX_RE = re.compile(r"\s+\(\d{4}\)\s*$")

_EXTRA_KNOWN_EXPANSIONS = (
    "Anashti Sul",
    "Veeshan's Peak",
)

KNOWN_EXPANSIONS = tuple(
    name for name, _year in EXPANSIONS_NEWEST_FIRST
) + _EXTRA_KNOWN_EXPANSIONS + ("The Ruins of Kunark",)

EVERQUEST_BASE_LABEL = "EverQuest Original Release (1999)"

GENERAL_CATEGORIES = (
    "General",
    "Tradeskill",
    "Slayer",
    "Events",
    "Overseer",
    "The Hero's Journey",
    "EverQuest",
)

_STATUS_LINE = re.compile(r"^([CIL])\t")
_ZONE_SUFFIX = re.compile(r"^(.*)\s+\(([^)]+)\)\s*$")
_PROGRESS_SUFFIX = re.compile(r"^(.*)\t(\d+)/(\d+)\s*$")
_QUEST_PARENT = re.compile(r"^(Mercenary|Partisan) of (.+)$", re.IGNORECASE)
_RAID_PARENT = re.compile(r"^(Conqueror|Vanquisher) of (.+)$", re.IGNORECASE)
_FROM_NPC_SUFFIX = re.compile(r"\s+-\s+from\s+.+$", re.IGNORECASE)


@dataclass(frozen=True)
class MissingCollectionItem:
    section: str
    zone: str
    collection: str
    item: str
    owned: int
    total: int

    @property
    def progress(self) -> str:
        return f"{self.owned}/{self.total}"


@dataclass(frozen=True)
class SectionSummary:
    section: str
    completed: int
    incomplete: int

    @property
    def total(self) -> int:
        return self.completed + self.incomplete

    @property
    def completion_pct(self) -> float:
        if self.total == 0:
            return 0.0
        return round(100.0 * self.completed / self.total, 1)


@dataclass(frozen=True)
class MissingRaidAchievement:
    section: str
    raid: str
    objective: str
    complete: bool = False
    event: str = ""


@dataclass(frozen=True)
class QuestAchievement:
    section: str
    quest_type: str
    zone: str
    quest: str
    complete: bool


@dataclass(frozen=True)
class TopLevelAchievement:
    section: str
    name: str
    complete: bool


@dataclass
class AchievementParseResult:
    missing_collections: list[MissingCollectionItem] = field(default_factory=list)
    missing_raid_achievements: list[MissingRaidAchievement] = field(default_factory=list)
    quest_achievements: list[QuestAchievement] = field(default_factory=list)
    section_summaries: list[SectionSummary] = field(default_factory=list)
    top_level: list[TopLevelAchievement] = field(default_factory=list)


def split_collection_name(name: str) -> tuple[str, str]:
    """``Eye Won! (Valley of King Xorbb)`` -> (collection, zone)."""
    match = _ZONE_SUFFIX.match(name.strip())
    if match is None:
        return name.strip(), ""
    return match.group(1).strip(), match.group(2).strip()


_SCAVENGER_SUFFIX = " scavenger"


def scavenger_zone_from_name(name: str) -> str | None:
    """``Scarred Grove Scavenger`` -> ``Scarred Grove``."""
    text = name.strip()
    folded = text.casefold()
    if not folded.endswith(_SCAVENGER_SUFFIX):
        return None
    zone = text[: -len(_SCAVENGER_SUFFIX)].strip()
    return zone or None


def _split_name_and_progress(text: str) -> tuple[str, int | None, int | None]:
    match = _PROGRESS_SUFFIX.match(text)
    if match is None:
        return text.strip(), None, None
    owned = int(match.group(2))
    total = int(match.group(3))
    return match.group(1).strip(), owned, total


def _parse_header_line(line: str) -> tuple[str, str, bool] | None:
    if _STATUS_LINE.match(line) or ":" not in line:
        return None
    name, subcategory = line.split(":", 1)
    section = name.strip()
    sub = subcategory.strip()
    if not section or not sub:
        return None
    if section in KNOWN_EXPANSIONS:
        return section, sub, True
    if section in GENERAL_CATEGORIES:
        return section, sub, False
    return section, sub, False


def _parse_status_line(line: str) -> tuple[str, str, int, int | None, int | None] | None:
    if not _STATUS_LINE.match(line):
        return None
    status = line[0]
    remaining = line[2:]
    indent = 0
    while remaining.startswith("\t"):
        indent += 1
        remaining = remaining[1:]
    name, owned, total = _split_name_and_progress(remaining)
    if not name:
        return None
    return status, name, indent, owned, total


def _is_collections_subcategory(subcategory: str) -> bool:
    return subcategory.casefold().endswith("collections")


# Collections omitted from Missing Collections (still counted in Achievement Summary).
IGNORED_MISSING_COLLECTIONS: frozenset[tuple[str, str]] = frozenset(
    {
        ("rain of fear", "stalking fear"),
    }
)


def is_ignored_missing_collection(section: str, collection: str) -> bool:
    """True when this expansion/collection should not appear on Missing Collections."""
    return (
        section.strip().casefold(),
        collection.strip().casefold(),
    ) in IGNORED_MISSING_COLLECTIONS


def _is_raids_subcategory(subcategory: str) -> bool:
    return subcategory.casefold() == "raids"


def _is_quests_subcategory(subcategory: str) -> bool:
    return subcategory.casefold() == "quests"


def parse_raid_parent(name: str) -> tuple[str, str] | None:
    """``Conqueror of Labyrinth of Spite: Echo of Hate`` -> (zone, event)."""
    match = _RAID_PARENT.match(name.strip())
    if match is None:
        return None
    rest = match.group(2).strip()
    zone, sep, event = rest.partition(": ")
    if not sep:
        return zone.strip(), ""
    return zone.strip(), event.strip()


def raid_header_name(zone: str, event: str) -> str:
    """Display header is always the Conqueror line for the zone/event."""
    if event:
        return f"Conqueror of {zone}: {event}"
    return f"Conqueror of {zone}"


def raid_event_label(zone: str, event: str) -> str:
    """Filter label: event name, or the zone when there is no named event."""
    return event or zone


def clean_raid_objective(name: str, event: str = "") -> str:
    """Drop NPC suffixes and the ``Event: `` prefix from a challenge name."""
    text = clean_quest_name(name)
    if event:
        prefix = f"{event}: "
        if text.casefold().startswith(prefix.casefold()):
            return text[len(prefix) :].strip()
    return text


def parse_quest_parent(name: str) -> tuple[str, str] | None:
    """``Mercenary of Arcstone, Shattered Isles`` -> (Mercenary, zone)."""
    match = _QUEST_PARENT.match(name.strip())
    if match is None:
        return None
    return match.group(1).title(), match.group(2).strip()


def clean_quest_name(name: str) -> str:
    """Drop NPC/zone suffixes from a quest child line."""
    text = name.strip()
    from_match = _FROM_NPC_SUFFIX.search(text)
    if from_match is not None:
        return text[: from_match.start()].strip()
    if " - " in text:
        return text.rsplit(" - ", 1)[-1].strip()
    return text


def _is_quest_meta_objective(name: str) -> bool:
    return name.casefold().startswith("complete either")


def _canonical_expansion_name(candidate: str) -> str | None:
    key = candidate.casefold()
    if key in _EXPANSION_ALIASES:
        return _EXPANSION_ALIASES[key]
    if key in _EXPANSION_ABBREVS:
        return _EXPANSION_ABBREVS[key]
    if key in {"everquest", "classic"}:
        return "EverQuest"
    for name, _year in EXPANSIONS_NEWEST_FIRST:
        if name.casefold() == key:
            return name
    if key.startswith("the "):
        rest = candidate[4:].strip()
        for name, _year in EXPANSIONS_NEWEST_FIRST:
            if name.casefold() == rest.casefold():
                return name
    return None


def _normalize_expansion_name(section: str) -> str:
    raw = (section or "").strip()
    if not raw:
        return raw
    matched = _canonical_expansion_name(raw)
    if matched is not None:
        return matched
    no_year = _YEAR_SUFFIX_RE.sub("", raw).strip()
    if no_year and no_year != raw:
        matched = _canonical_expansion_name(no_year)
        if matched is not None:
            return matched
    return raw


def _expansion_year(section: str) -> int | None:
    normalized = _normalize_expansion_name(section)
    for name, year in EXPANSIONS_NEWEST_FIRST:
        if name == normalized:
            return year
    return None


def format_expansion_label(section: str) -> str:
    """Display label for expansion filters: full name plus release year."""
    if not section:
        return ""
    normalized = _normalize_expansion_name(section)
    if normalized.casefold() == "everquest":
        return EVERQUEST_BASE_LABEL
    year = _expansion_year(normalized)
    if year is not None:
        return f"{normalized} ({year})"
    return section


def expansion_sort_key(section: str) -> tuple[int, str]:
    """Newest-to-oldest expansion order for Excel sorting and filters."""
    normalized = _normalize_expansion_name(section)
    for index, (name, _year) in enumerate(EXPANSIONS_NEWEST_FIRST):
        if name == normalized:
            return (index, section.casefold())
    if normalized.casefold() == "everquest":
        return (len(EXPANSIONS_NEWEST_FIRST), section.casefold())
    if section in GENERAL_CATEGORIES or normalized in GENERAL_CATEGORIES:
        return (len(EXPANSIONS_NEWEST_FIRST) + 1, section.casefold())
    return (len(EXPANSIONS_NEWEST_FIRST) + 2, section.casefold())


def parse_achievements_file(path: Path) -> AchievementParseResult:
    """Parse a ``Character_server-Achievements.txt`` dump."""
    current_section: str | None = None
    current_subcategory: str | None = None
    current_collection: str | None = None
    current_raid: str | None = None
    current_raid_event: str = ""
    current_raid_event_label: str = ""
    current_quest: tuple[str, str] | None = None
    in_collections = False
    in_raids = False
    in_quests = False
    current_scavenger_zone = ""
    scavenger_zones: dict[str, str] = {}

    section_completed: dict[str, int] = {}
    section_incomplete: dict[str, int] = {}
    missing_collections: list[MissingCollectionItem] = []
    missing_raid_achievements: list[MissingRaidAchievement] = []
    quest_achievements: list[QuestAchievement] = []
    top_level: list[TopLevelAchievement] = []

    with Path(path).open(encoding="utf-8", errors="ignore") as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\n\r")
            if not line.strip():
                continue

            header = _parse_header_line(line)
            if header is not None:
                current_section, current_subcategory, _is_expansion = header
                current_collection = None
                current_raid = None
                current_raid_event = ""
                current_raid_event_label = ""
                current_quest = None
                current_scavenger_zone = ""
                in_collections = _is_collections_subcategory(current_subcategory)
                in_raids = _is_raids_subcategory(current_subcategory)
                in_quests = _is_quests_subcategory(current_subcategory)
                continue

            parsed = _parse_status_line(line)
            if parsed is None or current_section is None:
                continue

            status, name, indent, owned, total = parsed

            if indent == 0:
                current_collection = name
                current_scavenger_zone = scavenger_zone_from_name(name) or ""
                raid_parent = parse_raid_parent(name) if in_raids else None
                if raid_parent is not None:
                    zone, event = raid_parent
                    current_raid = raid_header_name(zone, event)
                    current_raid_event = event
                    current_raid_event_label = raid_event_label(zone, event)
                else:
                    current_raid = None
                    current_raid_event = ""
                    current_raid_event_label = ""
                current_quest = parse_quest_parent(name) if in_quests else None
                section_completed.setdefault(current_section, 0)
                section_incomplete.setdefault(current_section, 0)
                if status == "C":
                    section_completed[current_section] += 1
                else:
                    section_incomplete[current_section] += 1
                top_level.append(
                    TopLevelAchievement(
                        section=current_section,
                        name=name,
                        complete=status == "C",
                    )
                )
                continue

            if (
                in_collections
                and indent == 1
                and owned is None
                and current_scavenger_zone
                and scavenger_zone_from_name(name) is None
            ):
                scavenger_zones.setdefault(name.casefold(), current_scavenger_zone)

            if in_raids and current_raid is not None and indent == 1:
                objective = clean_raid_objective(name, current_raid_event)
                if (
                    objective
                    and objective.casefold() != current_raid_event.casefold()
                ):
                    missing_raid_achievements.append(
                        MissingRaidAchievement(
                            section=current_section,
                            raid=current_raid,
                            objective=objective,
                            complete=status == "C",
                            event=current_raid_event_label,
                        )
                    )

            if (
                in_quests
                and current_quest is not None
                and indent == 1
                and not _is_quest_meta_objective(name)
            ):
                quest_name = clean_quest_name(name)
                if quest_name:
                    quest_type, zone = current_quest
                    quest_achievements.append(
                        QuestAchievement(
                            section=current_section,
                            quest_type=quest_type,
                            zone=zone,
                            quest=quest_name,
                            complete=status == "C",
                        )
                    )

            if not in_collections or current_collection is None:
                continue
            if status != "I" or owned is None or total is None or owned >= total:
                continue

            collection_name, zone = split_collection_name(current_collection)
            if is_ignored_missing_collection(current_section, collection_name):
                continue
            missing_collections.append(
                MissingCollectionItem(
                    section=current_section,
                    zone=zone,
                    collection=collection_name,
                    item=name,
                    owned=owned,
                    total=total,
                )
            )

    if scavenger_zones:
        missing_collections = [
            replace(item, zone=scavenger_zones[item.collection.casefold()])
            if not item.zone and item.collection.casefold() in scavenger_zones
            else item
            for item in missing_collections
        ]

    summaries = [
        SectionSummary(
            section=section,
            completed=section_completed.get(section, 0),
            incomplete=section_incomplete.get(section, 0),
        )
        for section in sorted(
            set(section_completed) | set(section_incomplete),
            key=str.casefold,
        )
    ]
    return AchievementParseResult(
        missing_collections=missing_collections,
        missing_raid_achievements=missing_raid_achievements,
        quest_achievements=quest_achievements,
        section_summaries=summaries,
        top_level=top_level,
    )
