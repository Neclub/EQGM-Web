"""Build team equipped-gear reports from multiple inventory dumps."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from inventory_parser.items import EquippedItem
from inventory_parser.missing_spells import discover_persona_bindings, persona_key
from inventory_parser.parser import (
    InventoryData,
    equipped_item_from_inventory,
    extract_equipped_items,
    parse_inventory_file,
)


def format_character_display_name(character: str, class_abbr: str | None = None) -> str:
    """Format a column header like ``Deflub ( PAL )`` when class is known."""
    if class_abbr:
        return f"{character} ( {class_abbr} )"
    return character


@dataclass
class CharacterGear:
    character: str
    server: str
    filepath: str
    slots: dict[str, EquippedItem] = field(default_factory=dict)
    class_abbr: str | None = None
    inventory_data: InventoryData | None = None

    @property
    def persona_key(self) -> str:
        return persona_key(self.character, self.server, self.class_abbr)

    @property
    def display_name(self) -> str:
        return format_character_display_name(self.character, self.class_abbr)


@dataclass
class TeamGearReport:
    characters: list[CharacterGear] = field(default_factory=list)
    spell_characters: list[CharacterGear] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _sort_characters(rows: list[CharacterGear]) -> list[CharacterGear]:
    return sorted(rows, key=lambda r: (r.character.casefold(), (r.class_abbr or "").casefold()))


def _equipped_slots(data: InventoryData) -> dict[str, EquippedItem]:
    """Equipped items by slot (empty slots omitted).

    Includes Power Source and Ammo for the Raid BiS paperdoll; Excel/HTML
    gear matrices still iterate TEAM_GEAR_SLOTS and ignore those extras.
    """
    equipped, evolver_keys = extract_equipped_items(data)
    return {
        slot: equipped_item_from_inventory(
            item, is_evolver=slot in evolver_keys
        )
        for slot, item in equipped.items()
    }


def _persona_label(character: str, class_abbr: str | None) -> str:
    if class_abbr:
        return f"{character} ({class_abbr})"
    return character


def build_team_report(
    inventory_paths: list[Path],
    *,
    spell_paths: list[Path] | None = None,
) -> TeamGearReport:
    """Parse inventory files and collect equipped items per persona."""
    discovery = discover_persona_bindings(inventory_paths, spell_paths=spell_paths)
    gear_by_persona: dict[str, CharacterGear] = {}
    spell_by_persona: dict[str, CharacterGear] = {}
    inventory_by_path: dict[str, InventoryData] = {}
    warnings = list(discovery.warnings)

    for binding in discovery.bindings:
        pk = persona_key(binding.character, binding.server, binding.class_abbr)
        if pk in gear_by_persona or pk in spell_by_persona:
            prev_path = (gear_by_persona.get(pk) or spell_by_persona[pk]).filepath
            label = _persona_label(binding.character, binding.class_abbr)
            warnings.append(
                f"Duplicate persona '{label}': keeping {binding.inventory_path.name}, "
                f"skipping {Path(prev_path).name}"
            )
            continue

        resolved = str(binding.inventory_path.resolve())
        data = inventory_by_path.get(resolved)
        if data is None:
            data = parse_inventory_file(binding.inventory_path)
            if data is None:
                warnings.append(f"Could not read inventory file: {binding.inventory_path}")
                continue
            inventory_by_path[resolved] = data

        char_gear = CharacterGear(
            character=binding.character,
            server=binding.server,
            filepath=resolved,
            slots=_equipped_slots(data),
            class_abbr=binding.class_abbr,
            inventory_data=data,
        )
        if binding.spell_path is not None:
            spell_by_persona[pk] = char_gear
        if binding.include_gear:
            gear_by_persona[pk] = char_gear

    return TeamGearReport(
        characters=_sort_characters(list(gear_by_persona.values())),
        spell_characters=_sort_characters(list(spell_by_persona.values())),
        warnings=warnings,
    )


def discover_inventory_files(folder: Path) -> list[Path]:
    """Find ``*-Inventory.txt`` files in a folder (non-recursive)."""
    return sorted(folder.glob("*-Inventory.txt"), key=lambda p: p.name.casefold())


@dataclass(frozen=True)
class FolderCharacterChoice:
    """Inventory and spell files for one character discovered in a folder."""

    character: str
    server: str
    inventory_paths: tuple[Path, ...] = ()
    spell_paths: tuple[Path, ...] = ()
    achievement_paths: tuple[Path, ...] = ()

    @property
    def paths(self) -> list[Path]:
        combined = (
            list(self.inventory_paths)
            + list(self.spell_paths)
            + list(self.achievement_paths)
        )
        return sorted({p.resolve() for p in combined}, key=lambda p: p.name.casefold())

    @property
    def class_abbrs(self) -> tuple[str, ...]:
        from inventory_parser.missing_spells import parse_missing_spells_filename
        from inventory_parser.parser import parse_inventory_filename

        classes: list[str] = []
        seen: set[str] = set()
        for spell_path in self.spell_paths:
            parsed = parse_missing_spells_filename(spell_path)
            if parsed is None:
                continue
            abbr = parsed[2].upper()
            if abbr not in seen:
                seen.add(abbr)
                classes.append(abbr)
        for inv_path in self.inventory_paths:
            _character, _server, class_abbr = parse_inventory_filename(inv_path)
            if not class_abbr or class_abbr in seen:
                continue
            seen.add(class_abbr)
            classes.append(class_abbr)
        return tuple(classes)

    @property
    def display_name(self) -> str:
        if len(self.class_abbrs) == 1:
            return format_character_display_name(self.character, self.class_abbrs[0])
        if len(self.class_abbrs) > 1:
            joined = ", ".join(self.class_abbrs)
            return f"{self.character} ( {joined} )"
        return self.character

    @property
    def summary(self) -> str:
        parts: list[str] = [self.server]
        file_bits: list[str] = []
        if self.inventory_paths:
            file_bits.append(
                f"{len(self.inventory_paths)} inventory"
                if len(self.inventory_paths) != 1
                else "1 inventory"
            )
        if self.spell_paths:
            file_bits.append(
                f"{len(self.spell_paths)} MissingSpells"
                if len(self.spell_paths) != 1
                else "1 MissingSpells"
            )
        if self.achievement_paths:
            file_bits.append(
                f"{len(self.achievement_paths)} Achievements"
                if len(self.achievement_paths) != 1
                else "1 Achievements"
            )
        if file_bits:
            parts.append(" · ".join(file_bits))
        return " · ".join(parts)


def _folder_spell_search_dirs(folder: Path) -> list[Path]:
    dirs = [folder]
    spell_data = folder / "SpellData"
    if spell_data.is_dir():
        dirs.append(spell_data)
    return dirs


def discover_folder_character_choices(folder: Path) -> list[FolderCharacterChoice]:
    """Group inventory, spell, and achievement files in a folder by character for GUI selection."""
    from inventory_parser.achievement_files import (
        discover_achievements_files,
        parse_achievements_filename,
    )
    from inventory_parser.missing_spells import (
        discover_missing_spells_files,
        filter_inventories_for_bindings,
        parse_missing_spells_filename,
    )
    from inventory_parser.parser import parse_inventory_filename

    inventories = filter_inventories_for_bindings(discover_inventory_files(folder))
    spells: list[Path] = []
    for search_dir in _folder_spell_search_dirs(folder):
        spells.extend(discover_missing_spells_files(search_dir))
    achievements: list[Path] = list(discover_achievements_files(folder))
    achievement_data = folder / "AchievementData"
    if achievement_data.is_dir():
        achievements.extend(discover_achievements_files(achievement_data))

    by_key: dict[tuple[str, str], FolderCharacterChoice] = {}

    def ensure_choice(character: str, server: str) -> FolderCharacterChoice:
        key = (character.casefold(), server.casefold())
        existing = by_key.get(key)
        if existing is not None:
            return existing
        choice = FolderCharacterChoice(character=character, server=server)
        by_key[key] = choice
        return choice

    inventory_lists: dict[tuple[str, str], list[Path]] = {}
    spell_lists: dict[tuple[str, str], list[Path]] = {}
    achievement_lists: dict[tuple[str, str], list[Path]] = {}

    for inv_path in inventories:
        character, server, _class_abbr = parse_inventory_filename(inv_path)
        key = (character.casefold(), server.casefold())
        ensure_choice(character, server)
        inventory_lists.setdefault(key, []).append(inv_path.resolve())

    for spell_path in spells:
        parsed = parse_missing_spells_filename(spell_path)
        if parsed is None:
            continue
        character, server, _class_abbr = parsed
        key = (character.casefold(), server.casefold())
        ensure_choice(character, server)
        spell_lists.setdefault(key, []).append(spell_path.resolve())

    for achievement_path in achievements:
        parsed = parse_achievements_filename(achievement_path)
        if parsed is None:
            continue
        character, server = parsed
        key = (character.casefold(), server.casefold())
        ensure_choice(character, server)
        achievement_lists.setdefault(key, []).append(achievement_path.resolve())

    choices: list[FolderCharacterChoice] = []
    for key, choice in by_key.items():
        inv_paths = tuple(sorted(set(inventory_lists.get(key, [])), key=lambda p: p.name.casefold()))
        spell_paths = tuple(sorted(set(spell_lists.get(key, [])), key=lambda p: p.name.casefold()))
        achievement_paths = tuple(
            sorted(set(achievement_lists.get(key, [])), key=lambda p: p.name.casefold())
        )
        choices.append(
            FolderCharacterChoice(
                character=choice.character,
                server=choice.server,
                inventory_paths=inv_paths,
                spell_paths=spell_paths,
                achievement_paths=achievement_paths,
            )
        )
    return sorted(choices, key=lambda c: (c.character.casefold(), c.server.casefold()))


def discover_input_files(folder: Path) -> list[Path]:
    """Find inventory, MissingSpells, and achievement dumps in a folder (non-recursive)."""
    from inventory_parser.achievement_files import discover_achievements_files
    from inventory_parser.missing_spells import discover_missing_spells_files

    paths = (
        list(discover_inventory_files(folder))
        + discover_missing_spells_files(folder)
        + discover_achievements_files(folder)
    )
    achievement_data = folder / "AchievementData"
    if achievement_data.is_dir():
        paths.extend(discover_achievements_files(achievement_data))
    return sorted({p.resolve() for p in paths}, key=lambda p: p.name.casefold())
