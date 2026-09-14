"""Build Type 5 aug display data from an already-parsed team gear report."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from inventory_parser.missing_spells import persona_key
from inventory_parser.output_paths import default_export_prefix_from_report
from inventory_parser.parser import (
    InventoryData,
    Type5Aug,
    collect_equipped_parent_ids,
    extract_type5_augs,
)
from inventory_parser.slot2_augs.build import report_progress
from inventory_parser.slot2_augs.eqresource_augs import (
    resolve_eqresource_augs,
    resolve_item_expansions,
)
from inventory_parser.slot2_augs.item_sockets import resolve_type5_slots
from inventory_parser.slot2_augs.profiles import ProfileId, profile_for_class
from inventory_parser.slots import TEAM_GEAR_SLOTS
from inventory_parser.team_report import TeamGearReport
from inventory_parser.type5_augs.vanquisher import vanquisher_label

ProgressFn = Callable[[dict], None]

TYPE5_CATALOG_URL = "https://items.eqresource.com/itemsearch.php?searchid=481762"

HEROIC_STAT_KEYS: tuple[str, ...] = (
    "hstr",
    "hsta",
    "hint",
    "hwis",
    "hagi",
    "hdex",
    "hcha",
)

_PROGRESS_SOCKETS = (0.05, 0.50)
_PROGRESS_STATS = (0.50, 0.80)
_PROGRESS_EXPANSIONS = (0.80, 0.95)


@dataclass(frozen=True)
class Type5RosterEntry:
    persona_key: str
    character: str
    server: str
    class_abbr: str | None
    path: str


@dataclass(frozen=True)
class Type5SlotRow:
    gear_slot: str
    name: str | None
    item_id: int | None
    dump_slot: int
    parent_name: str | None = None
    parent_id: int | None = None
    expansion: str | None = None
    expansion_url: str | None = None
    expansion_title: str | None = None
    stats: dict[str, int] = field(default_factory=dict)


@dataclass
class CharacterType5Report:
    character: str
    server: str
    class_abbr: str | None
    slots: list[Type5SlotRow] = field(default_factory=list)


@dataclass
class Type5Export:
    characters: list[CharacterType5Report] = field(default_factory=list)
    roster: list[Type5RosterEntry] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    server: str = ""
    export_prefix: str = "Team"
    show_server_in_columns: bool = False
    catalog_url: str = TYPE5_CATALOG_URL


def _slot_sort_key(gear_slot: str) -> tuple[int, str]:
    try:
        return (TEAM_GEAR_SLOTS.index(gear_slot), gear_slot)
    except ValueError:
        return (len(TEAM_GEAR_SLOTS), gear_slot)


def _heroic_from_aug_stats(stats: dict[str, int] | None) -> dict[str, int]:
    src = stats or {}
    return {k: int(src.get(k, 0) or 0) for k in HEROIC_STAT_KEYS}


def _range_item_progress(
    on_progress: ProgressFn | None,
    message: str,
    start: float,
    end: float,
) -> Callable[[int, int], None] | None:
    if on_progress is None:
        return None

    def _cb(done: int, total: int) -> None:
        if total <= 0:
            report_progress(on_progress, message, start, end, 1, 1)
        else:
            report_progress(
                on_progress,
                f"{message} ({done}/{total})",
                start,
                end,
                done,
                total,
            )

    return _cb


def build_type5_export(
    team: TeamGearReport,
    *,
    socket_overrides: dict[int, tuple[str | None, str | None]] | None = None,
    type5_slot_by_parent_id: dict[int, int | None] | None = None,
    eqr_aug_html_by_id: dict[int, str] | None = None,
    fetch_eqr_augs: bool = True,
    fetch_expansions: bool = True,
    on_progress: ProgressFn | None = None,
) -> Type5Export:
    """Collect equipped type 5 augs (and Empty holes) for the HTML/Excel report."""
    warnings: list[str] = []
    inventories: list[InventoryData] = []
    roster: list[Type5RosterEntry] = []

    for ch in team.characters:
        data = ch.inventory_data
        if data is None:
            warnings.append(f"Missing inventory data for {ch.character}")
            continue
        class_abbr = ch.class_abbr or data.class_abbr
        data.class_abbr = class_abbr
        inventories.append(data)
        roster.append(
            Type5RosterEntry(
                persona_key=persona_key(data.character, data.server, class_abbr),
                character=data.character,
                server=data.server,
                class_abbr=class_abbr,
                path=data.filepath,
            )
        )

    parent_ids: list[int] = []
    for data in inventories:
        parent_ids.extend(collect_equipped_parent_ids(data))

    s0, s1 = _PROGRESS_SOCKETS
    if type5_slot_by_parent_id is None:
        report_progress(on_progress, "Fetching Type 5 sockets from EQ Resource…", s0, s1, 0, 1)
        type5_slot_by_parent_id = resolve_type5_slots(
            parent_ids,
            overrides=socket_overrides,
            on_progress=_range_item_progress(
                on_progress, "Fetching Type 5 sockets from EQ Resource…", s0, s1
            ),
        )
    report_progress(on_progress, "Fetching Type 5 sockets from EQ Resource…", s0, s1, 1, 1)

    # Drop None values so extract only sees confirmed type 5 holes.
    slot_map: dict[int, int] = {
        pid: slot
        for pid, slot in (type5_slot_by_parent_id or {}).items()
        if slot is not None
    }

    per_char_augs: list[list[Type5Aug]] = []
    aug_ids: set[int] = set()
    for data in inventories:
        rows = extract_type5_augs(data, type5_slot_by_parent_id=slot_map)
        per_char_augs.append(rows)
        for row in rows:
            if row.item_id and row.item_id > 0:
                aug_ids.add(row.item_id)

    # Profile only affects focus_heroic legacy fields; any profile works for display.
    default_profile: ProfileId = "dex"
    if roster and roster[0].class_abbr:
        default_profile = profile_for_class(roster[0].class_abbr) or "dex"

    st0, st1 = _PROGRESS_STATS
    report_progress(on_progress, "Fetching Type 5 stats from EQ Resource…", st0, st1, 0, 1)
    aug_by_id = resolve_eqresource_augs(
        sorted(aug_ids),
        default_profile,
        html_overrides=eqr_aug_html_by_id,
        allow_network=fetch_eqr_augs,
    )
    report_progress(on_progress, "Fetching Type 5 stats from EQ Resource…", st0, st1, 1, 1)

    e0, e1 = _PROGRESS_EXPANSIONS
    report_progress(on_progress, "Fetching expansions from EQ Resource…", e0, e1, 0, 1)
    expansions = resolve_item_expansions(
        sorted(aug_ids),
        html_overrides=eqr_aug_html_by_id,
        allow_network=fetch_expansions,
        on_progress=_range_item_progress(
            on_progress, "Fetching expansions from EQ Resource…", e0, e1
        ),
    )
    report_progress(on_progress, "Fetching expansions from EQ Resource…", e0, e1, 1, 1)

    characters: list[CharacterType5Report] = []
    servers: list[str] = []
    for i, data in enumerate(inventories):
        class_abbr = roster[i].class_abbr if i < len(roster) else data.class_abbr
        slot_rows: list[Type5SlotRow] = []
        for aug in sorted(per_char_augs[i], key=lambda a: _slot_sort_key(a.gear_slot)):
            stats: dict[str, int] = {}
            expansion: str | None = None
            expansion_url: str | None = None
            expansion_title: str | None = None
            if aug.item_id and aug.item_id in aug_by_id:
                stats = _heroic_from_aug_stats(aug_by_id[aug.item_id].stats)
            elif aug.item_id:
                stats = _heroic_from_aug_stats(None)
            if aug.item_id:
                expansion = expansions.get(aug.item_id)
            vanq = vanquisher_label(aug.item_id, aug.name)
            if vanq is not None:
                expansion, expansion_url, expansion_title = vanq
            slot_rows.append(
                Type5SlotRow(
                    gear_slot=aug.gear_slot,
                    name=aug.name,
                    item_id=aug.item_id,
                    dump_slot=aug.dump_slot,
                    parent_name=aug.parent_name,
                    parent_id=aug.parent_id,
                    expansion=expansion,
                    expansion_url=expansion_url,
                    expansion_title=expansion_title,
                    stats=stats,
                )
            )
        characters.append(
            CharacterType5Report(
                character=data.character,
                server=data.server,
                class_abbr=class_abbr,
                slots=slot_rows,
            )
        )
        if data.server:
            servers.append(data.server)

    unique_servers = sorted({s for s in servers if s})
    show_server = len(unique_servers) > 1
    server = unique_servers[0] if len(unique_servers) == 1 else ""
    prefix = default_export_prefix_from_report(team) or (server or "Team")

    return Type5Export(
        characters=characters,
        roster=roster,
        warnings=warnings,
        server=server,
        export_prefix=str(prefix),
        show_server_in_columns=show_server,
        catalog_url=TYPE5_CATALOG_URL,
    )
