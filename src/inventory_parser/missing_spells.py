"""Parse EverQuest *-MissingSpells.txt dumps."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, replace
from pathlib import Path

from inventory_parser.parser import parse_inventory_filename

_MISSING_SPELLS_SUFFIX = "-missingspells.txt"
_INVENTORY_SUFFIX = "-inventory.txt"
_FILENAME_RE = re.compile(
    r"^(.+)_([^-]+)-([A-Za-z]+)-MissingSpells\.txt$",
    re.IGNORECASE,
)
_RANK_III_RE = re.compile(r"Rk\.?\s*III\b", re.IGNORECASE)
_RANK_II_RE = re.compile(r"Rk\.?\s*II\b", re.IGNORECASE)
# Rank suffix only — never the spell-line roman numeral (Yaulp XIX, Awestruck XVII).
_RANK_SUFFIX_RE = re.compile(r"\s*Rk\.?\s*(?:III|II|I)\b", re.IGNORECASE)


@dataclass(frozen=True)
class PersonaBinding:
    character: str
    server: str
    class_abbr: str | None
    inventory_path: Path
    spell_path: Path | None
    include_gear: bool = True


@dataclass(frozen=True)
class PersonaDiscoveryResult:
    bindings: list[PersonaBinding]
    warnings: list[str]


@dataclass(frozen=True)
class SpellDiscoveryResult:
    paths: dict[str, Path]
    warnings: list[str]


def persona_key(character: str, server: str, class_abbr: str | None = None) -> str:
    """Stable key for a character persona (optionally class-specific)."""
    base = f"{character}_{server}"
    if class_abbr:
        return f"{base}_{class_abbr.upper()}"
    return base


@dataclass(frozen=True)
class MissingSpellLine:
    level: int
    name: str


def is_missing_rank_iii(spell_name: str) -> bool:
    return bool(_RANK_III_RE.search(spell_name))


def is_missing_rank_ii(spell_name: str) -> bool:
    return bool(_RANK_II_RE.search(spell_name))


def strip_spell_rank(spell_name: str) -> str:
    """Remove trailing ``Rk. I/II/III`` suffix for deduplication keys.

    Spell-line roman numerals (``Yaulp XIX``, ``Awestruck XVII``) are kept.
    Rank 1 dumps omit ``Rk. I`` entirely, so those names are already bare.
    """
    return _RANK_SUFFIX_RE.sub("", spell_name).strip()


def normalize_spell_rank_iii(spell_name: str) -> str:
    """Display name for a missing Rank III spell (Rk. II / unpurchased → Rk. III)."""
    return f"{strip_spell_rank(spell_name)} Rk. III"


def counts_as_missing_rk3(spell_name: str) -> bool:
    """True when the dump lists a missing Rk. II or Rk. III line."""
    return is_missing_rank_iii(spell_name) or is_missing_rank_ii(spell_name)


def lacks_rank_suffix(spell_name: str) -> bool:
    """True when the dump has no ``Rk. II`` / ``Rk. III`` (unpurchased rank 1)."""
    return not counts_as_missing_rk3(spell_name)


def spell_rank_priority(spell_name: str) -> int:
    """Higher wins when the same spell appears at multiple ranks."""
    if is_missing_rank_iii(spell_name):
        return 3
    if is_missing_rank_ii(spell_name):
        return 2
    return 1


def parse_missing_spells_file(path: str | Path) -> list[MissingSpellLine]:
    """Parse tab-separated level and spell name lines."""
    lines: list[MissingSpellLine] = []
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        try:
            level = int(parts[0].strip())
        except ValueError:
            continue
        name = parts[1].strip()
        if not name:
            continue
        lines.append(MissingSpellLine(level=level, name=name))
    return lines


def parse_missing_spells_filename(path: str | Path) -> tuple[str, str, str] | None:
    """Return (character, server, class_abbr) from the filename."""
    m = _FILENAME_RE.match(Path(path).name)
    if not m:
        return None
    return m.group(1), m.group(2), m.group(3).upper()


def is_inventory_file(path: str | Path) -> bool:
    return Path(path).name.lower().endswith(_INVENTORY_SUFFIX)


def is_missing_spells_file(path: str | Path) -> bool:
    return Path(path).name.lower().endswith(_MISSING_SPELLS_SUFFIX)


def inventory_character_key(path: str | Path) -> str:
    """``Deflub_bristle-Inventory.txt`` -> ``Deflub_bristle``."""
    character, server, _class_abbr = parse_inventory_filename(path)
    return persona_key(character, server)


def inventory_persona_key(path: str | Path) -> str:
    """Persona key from an inventory filename (includes class when present)."""
    character, server, class_abbr = parse_inventory_filename(path)
    return persona_key(character, server, class_abbr)


def missing_spells_persona_key(path: str | Path) -> str | None:
    """``Deflub_bristle-PAL-MissingSpells.txt`` -> ``Deflub_bristle_PAL``."""
    parsed = parse_missing_spells_filename(path)
    if parsed is None:
        return None
    return persona_key(parsed[0], parsed[1], parsed[2])


def missing_spells_character_key(path: str | Path) -> str | None:
    """``Deflub_bristle-PAL-MissingSpells.txt`` -> ``Deflub_bristle``."""
    parsed = parse_missing_spells_filename(path)
    if parsed is None:
        return None
    return f"{parsed[0]}_{parsed[1]}"


def split_input_paths(
    paths: list[Path],
) -> tuple[list[Path], list[Path], list[Path]]:
    """Separate inventory, MissingSpells, and achievement dumps in a mixed file list."""
    from inventory_parser.achievement_files import is_achievements_file

    inventory_paths: list[Path] = []
    spell_paths: list[Path] = []
    achievement_paths: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if is_inventory_file(path):
            inventory_paths.append(path)
        elif is_missing_spells_file(path):
            spell_paths.append(path)
        elif is_achievements_file(path):
            achievement_paths.append(path)
    return inventory_paths, spell_paths, achievement_paths


def _search_dirs_for_inventory(inventory_path: Path) -> list[Path]:
    parent = inventory_path.parent
    dirs = [parent]
    spell_data = parent / "SpellData"
    if spell_data.is_dir():
        dirs.append(spell_data)
    return dirs


def _inventory_search_dirs_for_spell(spell_path: Path) -> list[Path]:
    parent = spell_path.parent
    if parent.name.casefold() == "spelldata":
        return [parent, parent.parent]
    return [parent]


def discover_missing_spells_files(folder: Path) -> list[Path]:
    """Find ``*-MissingSpells.txt`` files in a folder (non-recursive)."""
    return sorted(
        (p for p in folder.glob("*-MissingSpells.txt") if p.is_file()),
        key=lambda p: p.name.casefold(),
    )


def _glob_spell_candidates(folder: Path, pattern: str) -> list[Path]:
    return sorted(
        (p for p in folder.glob(pattern) if p.is_file()),
        key=lambda p: p.name.casefold(),
    )


def _char_server_key(character: str, server: str) -> str:
    return f"{character.casefold()}\0{server.casefold()}"


def superseded_generic_inventory_keys(inventory_paths: list[Path]) -> set[str]:
    """Char+server keys that have at least one class-tagged inventory among inputs."""
    keys: set[str] = set()
    for raw in inventory_paths:
        character, server, class_abbr = parse_inventory_filename(raw)
        if class_abbr:
            keys.add(_char_server_key(character, server))
    return keys


def filter_inventories_for_bindings(inventory_paths: list[Path]) -> list[Path]:
    """Drop generic inventories when class-tagged dumps exist for the same character."""
    superseded = superseded_generic_inventory_keys(inventory_paths)
    if not superseded:
        return list(inventory_paths)
    filtered: list[Path] = []
    for raw in inventory_paths:
        character, server, class_abbr = parse_inventory_filename(raw)
        if class_abbr is None and _char_server_key(character, server) in superseded:
            continue
        filtered.append(raw)
    return filtered


def _find_inventory_for_spell(
    spell_path: Path,
    character: str,
    server: str,
    class_abbr: str,
    *,
    superseded_generics: set[str],
) -> Path | None:
    """Prefer class-tagged inventory; fall back to generic unless superseded."""
    class_name = f"{character}_{server}-{class_abbr}-Inventory.txt"
    generic_name = f"{character}_{server}-Inventory.txt"
    search_dirs = _inventory_search_dirs_for_spell(spell_path)
    for folder in search_dirs:
        candidate = folder / class_name
        if candidate.is_file():
            return candidate.resolve()
    if _char_server_key(character, server) in superseded_generics:
        return None
    for folder in search_dirs:
        candidate = folder / generic_name
        if candidate.is_file():
            return candidate.resolve()
    return None


def _collect_spell_paths(
    inventory_paths: list[Path],
    extra_spell_paths: list[Path] | None,
) -> list[Path]:
    spells: dict[str, Path] = {}
    if extra_spell_paths:
        for raw in extra_spell_paths:
            path = Path(raw).resolve()
            if is_missing_spells_file(path):
                spells[str(path)] = path
        return sorted(spells.values(), key=lambda p: p.name.casefold())
    for inv_path in inventory_paths:
        character, server, _class_abbr = parse_inventory_filename(inv_path)
        pattern = f"{character}_{server}-*-MissingSpells.txt"
        for folder in _search_dirs_for_inventory(inv_path):
            for candidate in _glob_spell_candidates(folder, pattern):
                spells[str(candidate.resolve())] = candidate.resolve()
    return sorted(spells.values(), key=lambda p: p.name.casefold())


def _persona_display_label(character: str, class_abbr: str | None) -> str:
    if class_abbr:
        return f"{character} ({class_abbr})"
    return character


def _apply_gear_eligibility(bindings: list[PersonaBinding]) -> tuple[list[PersonaBinding], list[str]]:
    """Mark bindings whose inventory is shared across multiple spell personas."""
    warnings: list[str] = []
    by_inventory: dict[Path, list[PersonaBinding]] = defaultdict(list)
    for binding in bindings:
        if binding.spell_path is not None:
            by_inventory[binding.inventory_path.resolve()].append(binding)

    shared_inventories = {inv for inv, group in by_inventory.items() if len(group) > 1}

    updated: list[PersonaBinding] = []
    for binding in bindings:
        if binding.spell_path is not None and binding.inventory_path.resolve() in shared_inventories:
            updated.append(replace(binding, include_gear=False))
            warnings.append(
                f"Skipping team gear for {_persona_display_label(binding.character, binding.class_abbr)}: "
                "inventory file is shared with other personas (equipped gear reflects the active persona only)."
            )
        else:
            updated.append(binding)
    return updated, warnings


def discover_persona_bindings(
    inventory_paths: list[Path],
    *,
    spell_paths: list[Path] | None = None,
) -> PersonaDiscoveryResult:
    """
    Pair inventory dumps with MissingSpells files into persona bindings.

    Class-tagged inventories (``{Char}_{Server}-{CLASS}-Inventory.txt``) each form
    their own persona. When any class-tagged dump exists for a character+server,
    the generic ``{Char}_{Server}-Inventory.txt`` is ignored for that character.

    When multiple spell files share one generic inventory and are auto-discovered
    (not explicitly selected), those personas appear on spell tabs only (not Team
    Gear / Gear T-Level). Explicitly selected MissingSpells files always produce
    gear columns labeled with that class.
    """
    warnings: list[str] = []
    explicit_spell_selection = bool(spell_paths)
    bindings: list[PersonaBinding] = []
    seen_persona_keys: set[str] = set()
    char_servers_with_spell_bindings: set[str] = set()
    superseded_generics = superseded_generic_inventory_keys(inventory_paths)
    usable_inventories = filter_inventories_for_bindings(inventory_paths)

    for spell_path in _collect_spell_paths(inventory_paths, spell_paths):
        parsed = parse_missing_spells_filename(spell_path)
        if parsed is None:
            continue
        character, server, class_abbr = parsed
        pk = persona_key(character, server, class_abbr)
        if pk in seen_persona_keys:
            warnings.append(
                f"Duplicate persona '{character} ({class_abbr})': keeping first spell file, "
                f"skipping {spell_path.name}"
            )
            continue

        inventory_path = _find_inventory_for_spell(
            spell_path,
            character,
            server,
            class_abbr,
            superseded_generics=superseded_generics,
        )
        if inventory_path is None:
            warnings.append(
                f"No inventory file for {character} ({class_abbr}) "
                f"(expected {character}_{server}-{class_abbr}-Inventory.txt or "
                f"{character}_{server}-Inventory.txt near {spell_path.name})"
            )
            continue

        bindings.append(
            PersonaBinding(
                character=character,
                server=server,
                class_abbr=class_abbr,
                inventory_path=inventory_path,
                spell_path=spell_path.resolve(),
            )
        )
        seen_persona_keys.add(pk)
        char_servers_with_spell_bindings.add(_char_server_key(character, server))

    for inv_path in usable_inventories:
        path = Path(inv_path).resolve()
        if not path.is_file():
            warnings.append(f"Could not read inventory file: {path}")
            continue

        character, server, class_abbr = parse_inventory_filename(path)
        cs_key = _char_server_key(character, server)
        pk = persona_key(character, server, class_abbr)
        if pk in seen_persona_keys:
            continue
        # Generic inventory already covered by spell-driven bindings for this character
        if class_abbr is None and cs_key in char_servers_with_spell_bindings:
            continue

        bindings.append(
            PersonaBinding(
                character=character,
                server=server,
                class_abbr=class_abbr,
                inventory_path=path,
                spell_path=None,
            )
        )
        seen_persona_keys.add(pk)

    bindings.sort(key=lambda b: (b.character.casefold(), (b.class_abbr or "").casefold()))
    if not explicit_spell_selection:
        bindings, gear_warnings = _apply_gear_eligibility(bindings)
        warnings.extend(gear_warnings)
    return PersonaDiscoveryResult(bindings=bindings, warnings=warnings)


def bindings_include_personas(bindings: list[PersonaBinding]) -> bool:
    """True when multiple personas share a character name."""
    char_servers = [_char_server_key(b.character, b.server) for b in bindings if b.spell_path]
    return len(char_servers) != len(set(char_servers))


def inventories_include_personas(
    inventory_paths: list[Path],
    *,
    spell_paths: list[Path] | None = None,
) -> bool:
    """True when inputs resolve to multiple personas for one character."""
    result = discover_persona_bindings(inventory_paths, spell_paths=spell_paths)
    return bindings_include_personas(result.bindings)


def spell_path_for_persona(
    character: str,
    server: str,
    class_abbr: str | None,
    spell_paths: dict[str, Path],
) -> Path | None:
    """Resolve a MissingSpells file for a team column / persona."""
    key = persona_key(character, server, class_abbr)
    if key in spell_paths:
        return spell_paths[key]
    prefix = f"{character}_{server}_"
    matches = {k: v for k, v in spell_paths.items() if k.startswith(prefix)}
    if len(matches) == 1:
        return next(iter(matches.values()))
    return None


def discover_missing_spells_for_inventories(
    inventory_paths: list[Path],
    *,
    extra_spell_paths: list[Path] | None = None,
) -> SpellDiscoveryResult:
    """Map persona keys to MissingSpells file paths via persona bindings."""
    result = discover_persona_bindings(inventory_paths, spell_paths=extra_spell_paths)
    paths: dict[str, Path] = {}
    for binding in result.bindings:
        if binding.spell_path is not None:
            pk = persona_key(binding.character, binding.server, binding.class_abbr)
            paths[pk] = binding.spell_path
    return SpellDiscoveryResult(paths=paths, warnings=result.warnings)
