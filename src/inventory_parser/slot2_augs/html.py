"""Serialize Slot2 report payload for the HTML team report section."""

from __future__ import annotations

from inventory_parser import __version__
from inventory_parser.slot2_augs.build import Slot2Export
from inventory_parser.slot2_augs.compare import NEEDS_UPGRADE_STATUSES, REPORT_ROW_STATUSES
from inventory_parser.slot2_augs.profiles import PROFILE_FOCUS_LABEL, PROFILE_LABELS
from inventory_parser.slot2_augs.raidloot import AugCandidate
from inventory_parser.items import EQRESOURCE_ITEM_URL
from inventory_parser.missing_spells import persona_key
from inventory_parser.team_report import format_character_display_name


def format_catalog_fetched_at(iso: str) -> str:
    """Shorten ISO catalog timestamps for report meta (e.g. 2026-08-12 18:59 UTC)."""
    text = (iso or "").strip()
    if len(text) >= 16 and text[10] == "T":
        return f"{text[:10]} {text[11:16]} UTC"
    return text


def ranked_aug_type(aug: AugCandidate) -> str:
    """Bucket for HTML reference-aug filtering."""
    if aug.shield_only:
        return "Shield"
    if aug.ear_only:
        return "Ear"
    fits_charm = aug.fits_gear_slot("Charm")
    fits_range = aug.fits_gear_slot("Range")
    if fits_charm and fits_range:
        return "Charm/Range"
    if fits_charm:
        return "Charm"
    if fits_range:
        return "Range"
    return "General"


def serialize_slot2_section(bundle: Slot2Export) -> dict:
    """Serialize Slot2 cards for the team HTML report (no template chrome)."""
    rows: list[dict] = []
    char_meta: list[dict] = []
    stat_summary_rows: list[dict] = []

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
                "profile": ch.profile,
                "profileLabel": PROFILE_LABELS.get(ch.profile, ch.profile),
                "columnLabel": column_label,
                "displayName": display_name,
                "personaKey": pk,
            }
        )
        summary = ch.stat_summary or {}
        stat_summary_rows.append(
            {
                "personaKey": pk,
                "character": ch.character,
                "columnLabel": column_label,
                "displayName": display_name,
                "focusLabel": PROFILE_FOCUS_LABEL.get(ch.profile, "HDex"),
                "slotsChanged": ch.slots_changed,
                "focus": int(summary.get("focus", 0)),
                "ac": int(summary.get("ac", 0)),
                "hp": int(summary.get("hp", 0)),
                "atk": int(summary.get("atk", 0)),
                "healAmount": int(summary.get("heal_amount", 0)),
                "spellDamage": int(summary.get("spell_damage", 0)),
                "clairvoyance": int(summary.get("clairvoyance", 0)),
            }
        )
        for cmp_ in ch.comparisons:
            if cmp_.status not in REPORT_ROW_STATUSES:
                continue
            show_upgrade = cmp_.status in NEEDS_UPGRADE_STATUSES
            rows.append(
                {
                    "personaKey": pk,
                    "character": column_label,
                    "displayName": display_name,
                    "gearSlot": cmp_.gear_slot,
                    "currentName": cmp_.current_name,
                    "currentId": cmp_.current_id,
                    "recommendedName": cmp_.recommended_name if show_upgrade else None,
                    "recommendedId": cmp_.recommended_id if show_upgrade else None,
                    "recommendedFocus": (
                        cmp_.recommended_focus if show_upgrade else None
                    ),
                    "recommendedOwned": (
                        cmp_.recommended_owned if show_upgrade else None
                    ),
                    "recommendedExpansion": (
                        cmp_.recommended_expansion if show_upgrade else None
                    ),
                    "moveFromSlot": (
                        cmp_.move_from_slot if show_upgrade else None
                    ),
                    "craftComponentName": (
                        cmp_.craft_component_name if show_upgrade else None
                    ),
                    "craftComponentId": (
                        cmp_.craft_component_id if show_upgrade else None
                    ),
                    "craftComponentOwned": (
                        cmp_.craft_component_owned if show_upgrade else None
                    ),
                    "status": cmp_.status,
                    "note": cmp_.note,
                }
            )

    farm_rows: list[dict] = []
    class_by_persona = {c["personaKey"]: c for c in char_meta}
    for entry in bundle.farm_list:
        column_label = (
            f"{entry.character} ({entry.server})"
            if bundle.show_server_in_columns and entry.server
            else entry.character
        )
        meta = class_by_persona.get(entry.persona_key) or next(
            (c for c in char_meta if c["character"] == entry.character),
            {},
        )
        farm_rows.append(
            {
                "personaKey": entry.persona_key,
                "character": column_label,
                "displayName": meta.get("displayName")
                or format_character_display_name(entry.character, None),
                "gearSlot": entry.gear_slot,
                "name": entry.name,
                "itemId": entry.item_id,
                "expansion": entry.expansion,
                "craftComponentName": entry.craft_component_name,
                "craftComponentId": entry.craft_component_id,
                "craftComponentOwned": entry.craft_component_owned,
            }
        )

    ranked_profiles = sorted(
        {a.profile for a in bundle.ranked_augs},
        key=lambda p: ("dex", "int", "wis").index(p)
        if p in ("dex", "int", "wis")
        else 99,
    )
    if "dex" in ranked_profiles:
        default_focus = PROFILE_FOCUS_LABEL["dex"]
    elif ranked_profiles:
        default_focus = PROFILE_FOCUS_LABEL.get(ranked_profiles[0], "HDex")
    else:
        default_focus = PROFILE_FOCUS_LABEL.get(bundle.profile, "HDex")

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
        "reportTitle": f"{title_name} Type 7/8 Augs",
        "profile": bundle.profile,
        "profileLabel": bundle.profile_label,
        "focusLabel": PROFILE_FOCUS_LABEL.get(bundle.profile, "HDex"),
        "defaultFocusFilter": default_focus,
        "rankedProfiles": [
            {
                "id": p,
                "label": PROFILE_FOCUS_LABEL.get(p, p),
                "profileLabel": PROFILE_LABELS.get(p, p),
            }
            for p in ranked_profiles
        ],
        "artisansPrizeOwned": bundle.artisans_prize_owned,
        "includeAnniversary": bundle.include_anniversary,
        "server": bundle.server,
        "warnings": bundle.warnings,
        "appVersion": __version__,
        "catalogFetchedAt": format_catalog_fetched_at(bundle.catalog.fetched_at),
        "catalogFromCache": bundle.catalog.from_cache,
        "catalogUrl": bundle.catalog.url,
        "showServerInColumns": bundle.show_server_in_columns,
        "characters": char_meta,
        "statSummary": stat_summary_rows,
        "upgrades": rows,
        "farmList": farm_rows,
        "rankedAugs": [
            {
                "name": a.name,
                "itemId": a.item_id,
                "profile": a.profile,
                "focusLabel": PROFILE_FOCUS_LABEL.get(a.profile, "HDex"),
                "focusHeroic": a.focus_heroic,
                "ac": a.ac,
                "hp": a.hp,
                "atk": a.atk or int((a.stats or a.effective_stats()).get("atk", 0)),
                "healAmount": int((a.stats or a.effective_stats()).get("heal_amount", 0)),
                "spellDamage": int((a.stats or a.effective_stats()).get("spell_damage", 0)),
                "clairvoyance": int((a.stats or a.effective_stats()).get("clairvoyance", 0)),
                "slotText": a.slot_text,
                "earOnly": a.ear_only,
                "shieldOnly": a.shield_only,
                "excluded": sorted(a.excluded_bases),
                "allowed": sorted(a.allowed_bases),
                "source": a.source,
                "refType": ranked_aug_type(a),
                "stats": dict(a.stats or a.effective_stats()),
            }
            for a in bundle.ranked_augs
        ],
        "eqResourceItemUrl": EQRESOURCE_ITEM_URL,
    }
