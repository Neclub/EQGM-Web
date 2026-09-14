"""Assemble all export data shared by Excel and HTML writers."""

from __future__ import annotations

import gc
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from inventory_parser.achievement_report import AchievementReport, build_achievement_report
from inventory_parser.character_column_order import (
    apply_character_column_order,
    reorder_unmade_entries,
)
from inventory_parser.team_report import TeamGearReport, build_team_report
from inventory_parser.missing_spells import split_input_paths
from inventory_parser.slots import SlotFilter
from inventory_parser.spell_report import SpellRuneReport, build_spell_rune_report
from inventory_parser.rune_inventory import RuneInventoryReport, build_rune_inventory_report
from inventory_parser.unmade_gear import UnmadeGearEntry, build_unmade_gear_report
from inventory_parser.useful_spells import (
    MissingUsefulSpellsReport,
    build_missing_useful_spells_report,
)
from inventory_parser.raid_bis.build import RaidBisExport, build_raid_bis_export
from inventory_parser.item_inspect import ItemInspectExport, build_item_inspect_export
from inventory_parser.slot2_augs.build import Slot2Export, build_slot2_export, report_progress
from inventory_parser.slot2_augs.chest_class import apply_resolved_classes_to_team
from inventory_parser.slot2_augs.eqresource_gear_tier import apply_resolved_gear_tiers_to_team
from inventory_parser.type5_augs.build import Type5Export, build_type5_export
from inventory_parser.type18_augs.build import Type18Export, build_type18_export


@dataclass
class ExportBundle:
    team: TeamGearReport
    spell_report: SpellRuneReport | None = None
    missing_useful_report: MissingUsefulSpellsReport | None = None
    achievement_report: AchievementReport | None = None
    unmade_entries: list[UnmadeGearEntry] = field(default_factory=list)
    rune_inventory_report: RuneInventoryReport | None = None
    warnings: list[str] = field(default_factory=list)
    slot_filter: SlotFilter = "all"
    slot2: Slot2Export | None = None
    type5: Type5Export | None = None
    type18: Type18Export | None = None
    raid_bis: RaidBisExport | None = None
    item_inspect: ItemInspectExport | None = None


def release_export_memory() -> None:
    """Drop large export allocations and encourage the GC to reclaim memory."""
    gc.collect()


def build_export_bundle(
    input_paths: list[Path],
    *,
    slot_filter: SlotFilter = "all",
    include_spells: bool = True,
    include_achievements: bool = True,
    include_slot2: bool = True,
    include_type5: bool = False,
    include_type18: bool = False,
    include_raid_bis: bool = False,
    include_item_cards: bool = False,
    include_anniversary: bool = False,
    session_weights: dict[str, float] | None = None,
    on_progress: Callable[[dict], None] | None = None,
    character_column_order: list[str] | None = None,
    **slot2_kwargs,
) -> ExportBundle:
    """Parse inputs and build reports for Excel/HTML export."""
    inventory_paths, spell_file_paths, achievement_file_paths = split_input_paths(input_paths)
    if not inventory_paths:
        raise ValueError(
            "No inventory files were provided. Add *-Inventory.txt files."
        )

    report = build_team_report(inventory_paths, spell_paths=spell_file_paths)
    if not report.characters:
        raise ValueError("No inventory files were parsed successfully.")

    fetch_chest_class = slot2_kwargs.get("fetch_chest_class", True)
    chest_class_overrides = slot2_kwargs.get("chest_class_overrides")

    def _item_progress(message: str, start: float, end: float):
        if on_progress is None:
            return None

        def _cb(done: int, total: int) -> None:
            label = message if total <= 0 else f"{message} ({done}/{total})"
            report_progress(on_progress, label, start, end, done, total or 1)

        return _cb

    apply_resolved_classes_to_team(
        report,
        overrides=chest_class_overrides,
        allow_network=bool(fetch_chest_class),
        on_progress=_item_progress("Resolving character classes…", 0.0, 0.04),
    )

    fetch_eqr_gear_tiers = slot2_kwargs.pop("fetch_eqr_gear_tiers", True)
    eqr_gear_tier_html = slot2_kwargs.pop("eqr_gear_tier_html", None)
    apply_resolved_gear_tiers_to_team(
        report,
        html_overrides=eqr_gear_tier_html,
        allow_network=bool(fetch_eqr_gear_tiers),
        on_progress=_item_progress("Fetching gear T-levels from EQ Resource…", 0.04, 0.16),
    )

    apply_character_column_order(report, character_column_order)

    warnings = list(report.warnings)
    spell_report = None
    missing_useful_report = None
    if include_spells:
        spell_report = build_spell_rune_report(
            report,
            inventory_paths=inventory_paths,
            extra_spell_paths=spell_file_paths,
        )
        if spell_report is not None:
            warnings.extend(spell_report.warnings)
        missing_useful_report = build_missing_useful_spells_report(
            report,
            inventory_paths=inventory_paths,
            extra_spell_paths=spell_file_paths,
        )
        if missing_useful_report is not None:
            warnings.extend(missing_useful_report.warnings)

    achievement_report = None
    if include_achievements:
        achievement_report = build_achievement_report(
            report,
            inventory_paths=inventory_paths,
            extra_achievement_paths=achievement_file_paths,
        )
        if achievement_report is not None:
            warnings.extend(achievement_report.warnings)

    unmade_entries = reorder_unmade_entries(
        build_unmade_gear_report(report),
        report,
        character_column_order,
    )
    rune_inventory_report = build_rune_inventory_report(report)

    raid_bis_overrides = slot2_kwargs.pop("raid_bis_html_overrides", None)
    raid_bis_item_html = slot2_kwargs.pop("raid_bis_item_html", None)
    raid_bis_allow_network = slot2_kwargs.pop("raid_bis_allow_network", True)
    raid_bis_hydrate = slot2_kwargs.pop("raid_bis_hydrate", True)
    raid_bis_embed_icons = slot2_kwargs.pop("raid_bis_embed_icons", True)
    item_inspect_html = slot2_kwargs.pop("item_inspect_html_by_id", None)
    item_inspect_allow_network = slot2_kwargs.pop("item_inspect_allow_network", None)
    item_inspect_embed_icons = slot2_kwargs.pop("item_inspect_embed_icons", True)

    type5_socket_overrides = slot2_kwargs.pop("type5_socket_overrides", None)
    type5_slot_by_parent_id = slot2_kwargs.pop("type5_slot_by_parent_id", None)
    type5_eqr_aug_html_by_id = slot2_kwargs.pop("type5_eqr_aug_html_by_id", None)
    type5_fetch_eqr_augs = slot2_kwargs.pop("type5_fetch_eqr_augs", True)

    type18_html_by_page = slot2_kwargs.pop("type18_html_by_page", None)
    type19_html_overrides = slot2_kwargs.pop("type19_html_overrides", None)
    type18_item_html_by_id = slot2_kwargs.pop("type18_item_html_by_id", None)
    type18_allow_network = slot2_kwargs.pop("type18_allow_network", True)
    type18_catalog = slot2_kwargs.pop("type18_catalog", None)

    slot2 = None
    if include_slot2:
        slot2 = build_slot2_export(
            report,
            include_anniversary=include_anniversary,
            session_weights=session_weights,
            on_progress=on_progress,
            **slot2_kwargs,
        )
        warnings.extend(slot2.warnings)

    type5 = None
    if include_type5:
        type5 = build_type5_export(
            report,
            socket_overrides=type5_socket_overrides
            or slot2_kwargs.get("socket_overrides"),
            type5_slot_by_parent_id=type5_slot_by_parent_id,
            eqr_aug_html_by_id=type5_eqr_aug_html_by_id
            or slot2_kwargs.get("eqr_aug_html_by_id"),
            fetch_eqr_augs=bool(type5_fetch_eqr_augs),
            on_progress=on_progress,
        )
        warnings.extend(type5.warnings)

    type18 = None
    if include_type18:
        from inventory_parser.parser import (
            collect_equipped_aug_locations,
            collect_owned_item_ids,
            collect_owned_item_names,
        )
        from inventory_parser.type18_augs.build import Type18Character

        type18_characters: list[Type18Character] = []
        type18_class_abbrs: list[str] = []
        for ch in report.characters:
            abbr = (ch.class_abbr or "").strip().upper()
            if not abbr:
                continue
            type18_class_abbrs.append(abbr)
            owned_ids: set[int] = set()
            owned_names: set[str] = set()
            equipped_by_id: dict[int, str] = {}
            equipped_by_name: dict[str, str] = {}
            if ch.inventory_data is not None:
                owned_ids = collect_owned_item_ids(ch.inventory_data)
                owned_names = collect_owned_item_names(ch.inventory_data)
                equipped_by_id, equipped_by_name = collect_equipped_aug_locations(
                    ch.inventory_data
                )
            type18_characters.append(
                Type18Character(
                    key=ch.persona_key,
                    name=ch.character,
                    display_name=ch.display_name,
                    class_abbr=abbr,
                    owned_ids=owned_ids,
                    owned_names=owned_names,
                    equipped_locations_by_id=equipped_by_id,
                    equipped_locations_by_name=equipped_by_name,
                )
            )
        type18 = build_type18_export(
            allow_network=bool(type18_allow_network),
            type18_html_by_page=type18_html_by_page,
            type19_html_overrides=type19_html_overrides,
            item_html_by_id=type18_item_html_by_id,
            catalog=type18_catalog,
            class_abbrs=type18_class_abbrs,
            characters=type18_characters,
            on_progress=on_progress,
        )
        warnings.extend(type18.warnings)

    raid_bis = None
    if include_raid_bis:
        raid_bis = build_raid_bis_export(
            report,
            on_progress=on_progress,
            allow_network=bool(raid_bis_allow_network),
            html_overrides=raid_bis_overrides,
            item_html_by_id=raid_bis_item_html,
            hydrate=bool(raid_bis_hydrate),
            embed_icons=bool(raid_bis_embed_icons),
        )
        warnings.extend(raid_bis.warnings)

    item_inspect = None
    if include_item_cards:
        merged_item_html: dict[int, str] = {}
        if isinstance(raid_bis_item_html, dict):
            merged_item_html.update(raid_bis_item_html)
        if isinstance(item_inspect_html, dict):
            merged_item_html.update(item_inspect_html)
        allow_cards_network = raid_bis_allow_network if item_inspect_allow_network is None else bool(item_inspect_allow_network)
        item_inspect = build_item_inspect_export(
            report,
            raid_bis_icons=raid_bis.icon_data_uris if raid_bis is not None else None,
            item_html_by_id=merged_item_html or None,
            allow_network=allow_cards_network,
            on_progress=on_progress,
            embed_icons=bool(item_inspect_embed_icons),
        )

    return ExportBundle(
        team=report,
        spell_report=spell_report,
        missing_useful_report=missing_useful_report,
        achievement_report=achievement_report,
        unmade_entries=unmade_entries,
        rune_inventory_report=rune_inventory_report,
        warnings=warnings,
        slot_filter=slot_filter,
        slot2=slot2,
        type5=type5,
        type18=type18,
        raid_bis=raid_bis,
        item_inspect=item_inspect,
    )
