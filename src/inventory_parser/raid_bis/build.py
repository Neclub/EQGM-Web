"""Build Raid BiS export data from a parsed team gear report."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from inventory_parser.output_paths import default_export_prefix_from_report
from inventory_parser.raid_bis.catalog import fetch_catalog
from inventory_parser.raid_bis.compare import (
    CharacterRaidBis,
    collect_paperdoll_icon_ids,
    compare_character,
    missing_paperdoll_icons,
    resolve_equipped_stats,
)
from inventory_parser.raid_bis.models import RaidBisCatalog
from inventory_parser.slot2_augs.build import report_progress
from inventory_parser.team_report import TeamGearReport

ProgressFn = Callable[[dict], None]


@dataclass
class RaidBisExport:
    catalog: RaidBisCatalog
    characters: list[CharacterRaidBis] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    export_prefix: str = "Team"
    icon_data_uris: dict[str, str] = field(default_factory=dict)


def build_raid_bis_export(
    team: TeamGearReport,
    *,
    on_progress: ProgressFn | None = None,
    allow_network: bool = True,
    html_overrides: dict[str, str] | None = None,
    item_html_by_id: dict[int, str] | None = None,
    hydrate: bool = True,
    embed_icons: bool = True,
) -> RaidBisExport:
    """Fetch the raid catalog and compare each character's equipped gear."""
    warnings: list[str] = []
    last_catalog_msg = ["Fetching from EQ Resource…"]

    def _catalog_status(message: str, done: int = 0, total: int = 1) -> None:
        last_catalog_msg[0] = message
        report_progress(on_progress, message, 0.0, 0.35, done, max(total, 1))

    catalog = fetch_catalog(
        allow_network=allow_network,
        html_overrides=html_overrides,
        item_html_by_id=item_html_by_id,
        hydrate=hydrate,
        on_status=_catalog_status if on_progress else None,
    )
    report_progress(on_progress, last_catalog_msg[0], 0.0, 0.35, 1, 1)
    if catalog.warning:
        warnings.append(catalog.warning)

    def _equip_status(message: str, done: int = 0, total: int = 1) -> None:
        report_progress(on_progress, message, 0.35, 0.42, done, max(total, 1))

    equipped = resolve_equipped_stats(
        team.characters,
        catalog.items,
        item_html_by_id=item_html_by_id,
        allow_network=allow_network and not html_overrides,
        on_status=_equip_status if on_progress else None,
    )
    characters: list[CharacterRaidBis] = []
    n = max(len(team.characters), 1)
    for i, ch in enumerate(team.characters, start=1):
        characters.append(
            compare_character(
                ch, catalog.items, equipped_stats=equipped, vendor=catalog.vendor
            )
        )
        report_progress(
            on_progress,
            f"Comparing equipped gear to Raid BiS… ({i}/{len(team.characters)})",
            0.42,
            0.82,
            i,
            n,
        )

    icon_data_uris: dict[str, str] = {}
    if embed_icons:
        from inventory_parser.raid_bis.icons import collect_icon_data_uris

        icon_ids = collect_paperdoll_icon_ids(characters)
        if catalog.vendor and catalog.vendor.currency_icon_id:
            icon_ids.add(str(catalog.vendor.currency_icon_id).strip())

        last_icon_msg = ["Using cached item icons…"]

        def _icon_status(message: str, done: int = 0, total: int = 1) -> None:
            last_icon_msg[0] = message
            report_progress(on_progress, message, 0.82, 0.95, done, max(total, 1))

        icon_data_uris = collect_icon_data_uris(
            icon_ids,
            allow_network=allow_network and not html_overrides,
            on_status=_icon_status if on_progress else None,
        )
        if icon_ids:
            report_progress(on_progress, last_icon_msg[0], 0.82, 0.95, 1, 1)
        warnings.extend(
            missing_paperdoll_icons(
                characters, icon_data_uris, require_embedded=True
            )
        )

    prefix = default_export_prefix_from_report(team)
    return RaidBisExport(
        catalog=catalog,
        characters=characters,
        warnings=warnings,
        export_prefix=prefix,
        icon_data_uris=icon_data_uris,
    )
