"""Discover and classify EverQuest achievement dump files."""

from __future__ import annotations

import re
from pathlib import Path

_ACHIEVEMENTS_FILENAME = re.compile(r"^(.+)_([^-]+)-Achievements\.txt$", re.IGNORECASE)


def is_achievements_file(path: str | Path) -> bool:
    return _ACHIEVEMENTS_FILENAME.match(Path(path).name) is not None


def parse_achievements_filename(path: str | Path) -> tuple[str, str] | None:
    match = _ACHIEVEMENTS_FILENAME.match(Path(path).name)
    if match is None:
        return None
    return match.group(1), match.group(2)


def achievement_character_key(path: str | Path) -> str | None:
    parsed = parse_achievements_filename(path)
    if parsed is None:
        return None
    return f"{parsed[0]}_{parsed[1]}"


def discover_achievements_files(folder: Path) -> list[Path]:
    """Find ``*-Achievements.txt`` files in a folder (non-recursive)."""
    return sorted(
        (p for p in folder.glob("*-Achievements.txt") if p.is_file()),
        key=lambda p: p.name.casefold(),
    )


def _achievement_search_dirs(parent: Path) -> list[Path]:
    dirs = [parent]
    achievement_data = parent / "AchievementData"
    if achievement_data.is_dir():
        dirs.append(achievement_data)
    return dirs


def _find_achievement_for_inventory(inventory_path: Path, character: str, server: str) -> Path | None:
    pattern = f"{character}_{server}-Achievements.txt"
    for folder in _achievement_search_dirs(inventory_path.parent):
        candidate = folder / pattern
        if candidate.is_file():
            return candidate.resolve()
    return None


def collect_achievement_paths(
    inventory_paths: list[Path],
    extra_achievement_paths: list[Path] | None = None,
) -> dict[str, Path]:
    """Map ``Character_server`` keys to achievement dump paths."""
    from inventory_parser.parser import parse_inventory_filename

    achievements: dict[str, Path] = {}
    if extra_achievement_paths:
        for raw in extra_achievement_paths:
            path = Path(raw).resolve()
            if not is_achievements_file(path):
                continue
            key = achievement_character_key(path)
            if key is not None:
                achievements[key.casefold()] = path
        return achievements

    for inventory_path in inventory_paths:
        character, server, _class_abbr = parse_inventory_filename(inventory_path)
        key = f"{character}_{server}"
        if key.casefold() in achievements:
            continue
        found = _find_achievement_for_inventory(inventory_path, character, server)
        if found is not None:
            achievements[key.casefold()] = found
    return achievements
