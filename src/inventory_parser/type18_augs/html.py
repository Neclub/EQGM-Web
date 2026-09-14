"""Serialize Type 18/19 suggestions + catalog for the HTML team report."""

from __future__ import annotations

from inventory_parser import __version__
from inventory_parser.items import EQRESOURCE_ITEM_URL
from inventory_parser.type18_augs.build import Type18Character, Type18Export
from inventory_parser.type18_augs.categories import HEROIC_STAT_KEYS
from inventory_parser.type18_augs.suggestions import SuggestionPick, SuggestionRow


def _pick_dict(pick: SuggestionPick | None) -> dict | None:
    if pick is None:
        return None
    stats = pick.stats or {}
    return {
        "itemId": pick.item_id,
        "name": pick.name,
        "augType": pick.aug_type,
        "typeLabel": pick.type_label,
        "category": pick.category,
        "loreGroup": pick.lore_group,
        "anniversary": bool(pick.anniversary),
        "ac": int(stats.get("ac", 0) or 0),
        "hp": int(stats.get("hp", 0) or 0),
        "mana": int(stats.get("mana", 0) or 0),
        "spellDamage": int(stats.get("spell_damage", 0) or 0),
        "endurance": int(stats.get("endurance", 0) or 0),
        "hstr": int(stats.get("hstr", 0) or 0),
        "hsta": int(stats.get("hsta", 0) or 0),
        "hint": int(stats.get("hint", 0) or 0),
        "hwis": int(stats.get("hwis", 0) or 0),
        "hagi": int(stats.get("hagi", 0) or 0),
        "hdex": int(stats.get("hdex", 0) or 0),
        "hcha": int(stats.get("hcha", 0) or 0),
    }


def _row_dict(row: SuggestionRow) -> dict:
    suggested = _pick_dict(row.suggested)
    return {
        "priority": row.priority,
        "rank": row.rank,
        "guideName": row.guide_name,
        "suggested": suggested,
        "alternative": _pick_dict(row.alternative),
        "anniversary": bool(
            (row.suggested.anniversary if row.suggested else False)
            or (suggested or {}).get("anniversary")
        ),
        "upgraded": bool(row.upgraded),
    }


def _character_dict(ch: Type18Character) -> dict:
    return {
        "key": ch.key,
        "name": ch.name,
        "displayName": ch.display_name,
        "classAbbr": ch.class_abbr,
        "ownedIds": sorted(int(i) for i in ch.owned_ids if int(i) > 0),
        "ownedNames": sorted(ch.owned_names),
        "equippedLocationsById": {
            str(int(iid)): loc
            for iid, loc in sorted(ch.equipped_locations_by_id.items())
            if int(iid) > 0 and loc
        },
        "equippedLocationsByName": {
            name: loc
            for name, loc in sorted(ch.equipped_locations_by_name.items())
            if name and loc
        },
    }


def serialize_type18_section(bundle: Type18Export) -> dict:
    """Serialize Type 18/19 suggestions and catalog for the team HTML report."""
    catalog_rows: list[dict] = []
    for e in bundle.entries:
        stats = e.stats or {}
        catalog_rows.append(
            {
                "itemId": e.item_id,
                "name": e.name,
                "augType": e.aug_type,
                "typeLabel": e.type_label
                or ("18/19" if e.aug_type == 18 else str(e.aug_type)),
                "category": e.category,
                "loreGroup": e.lore_group,
                "itemLore": e.item_lore,
                "anniversary": bool(e.anniversary),
                "ac": int(stats.get("ac", 0) or 0),
                "hp": int(stats.get("hp", 0) or 0),
                "mana": int(stats.get("mana", 0) or 0),
                "spellDamage": int(stats.get("spell_damage", 0) or 0),
                "endurance": int(stats.get("endurance", 0) or 0),
                "hstr": int(stats.get("hstr", 0) or 0),
                "hsta": int(stats.get("hsta", 0) or 0),
                "hint": int(stats.get("hint", 0) or 0),
                "hwis": int(stats.get("hwis", 0) or 0),
                "hagi": int(stats.get("hagi", 0) or 0),
                "hdex": int(stats.get("hdex", 0) or 0),
                "hcha": int(stats.get("hcha", 0) or 0),
            }
        )

    suggestions = []
    for block in bundle.suggestions:
        suggestions.append(
            {
                "classAbbr": block.class_abbr,
                "className": block.class_name,
                "casterStats": bool(block.caster_stats),
                "dexStats": bool(block.dex_stats),
                "primary": [_row_dict(r) for r in block.primary],
                "optional": [_row_dict(r) for r in block.optional],
                "filler": [_row_dict(r) for r in block.filler],
            }
        )

    return {
        "reportTitle": "Type 18/19 Augs",
        "type18Url": bundle.type18_url,
        "type19Url": bundle.type19_url,
        "cheatSheetUrl": bundle.cheat_sheet_url,
        "fetchedAt": bundle.fetched_at,
        "fromCache": bundle.from_cache,
        "warnings": bundle.warnings,
        "appVersion": __version__,
        "categories": list(bundle.categories),
        "teamClassAbbrs": list(bundle.team_class_abbrs),
        "characters": [_character_dict(c) for c in bundle.characters],
        "suggestions": suggestions,
        "rows": catalog_rows,
        "heroicKeys": list(HEROIC_STAT_KEYS),
        "eqResourceItemUrl": EQRESOURCE_ITEM_URL,
    }
