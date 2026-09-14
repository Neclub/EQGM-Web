"""Serialize Type 5 report payload for the HTML team report section."""

from __future__ import annotations

from inventory_parser import __version__
from inventory_parser.items import EQRESOURCE_ITEM_URL
from inventory_parser.missing_spells import persona_key
from inventory_parser.team_report import format_character_display_name
from inventory_parser.type5_augs.build import HEROIC_STAT_KEYS, Type5Export


def serialize_type5_section(bundle: Type5Export) -> dict:
    """Serialize Type 5 equipped/Empty rows for the team HTML report."""
    char_meta: list[dict] = []
    rows: list[dict] = []

    for i, ch in enumerate(bundle.characters):
        pk = (
            bundle.roster[i].persona_key
            if i < len(bundle.roster)
            else persona_key(ch.character, ch.server, ch.class_abbr)
        )
        column_label = (
            f"{ch.character} ({ch.server})"
            if bundle.show_server_in_columns and ch.server
            else ch.character
        )
        display_name = format_character_display_name(ch.character, ch.class_abbr)
        char_meta.append(
            {
                "character": ch.character,
                "server": ch.server,
                "classAbbr": ch.class_abbr,
                "columnLabel": column_label,
                "displayName": display_name,
                "personaKey": pk,
            }
        )
        for slot in ch.slots:
            stats = slot.stats or {}
            rows.append(
                {
                    "personaKey": pk,
                    "character": column_label,
                    "displayName": display_name,
                    "gearSlot": slot.gear_slot,
                    "expansion": slot.expansion,
                    "expansionUrl": slot.expansion_url,
                    "expansionTitle": slot.expansion_title,
                    "name": slot.name,
                    "itemId": slot.item_id,
                    "dumpSlot": slot.dump_slot,
                    "parentName": slot.parent_name,
                    "parentId": slot.parent_id,
                    "empty": slot.name is None or slot.item_id is None,
                    "hstr": int(stats.get("hstr", 0)),
                    "hsta": int(stats.get("hsta", 0)),
                    "hint": int(stats.get("hint", 0)),
                    "hwis": int(stats.get("hwis", 0)),
                    "hagi": int(stats.get("hagi", 0)),
                    "hdex": int(stats.get("hdex", 0)),
                    "hcha": int(stats.get("hcha", 0)),
                }
            )

    title_name = (bundle.export_prefix or "").strip()
    if len(bundle.characters) == 1:
        ch = bundle.characters[0]
        title_name = (ch.character or title_name or "EQ").strip()
        abbr = (ch.class_abbr or "").strip().upper()
        if abbr:
            title_name = f"{title_name} - {abbr}"
    elif not title_name and bundle.characters:
        title_name = bundle.characters[0].character
    if not title_name:
        title_name = "EQ"

    return {
        "reportTitle": f"{title_name} Type 5 Augs",
        "catalogUrl": bundle.catalog_url,
        "warnings": bundle.warnings,
        "appVersion": __version__,
        "showServerInColumns": bundle.show_server_in_columns,
        "characters": char_meta,
        "rows": rows,
        "heroicKeys": list(HEROIC_STAT_KEYS),
        "eqResourceItemUrl": EQRESOURCE_ITEM_URL,
    }
