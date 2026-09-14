"""Serialize Raid BiS for the HTML team report section."""

from __future__ import annotations

from inventory_parser import __version__
from inventory_parser.items import EQRESOURCE_ITEM_URL
from inventory_parser.raid_bis.build import RaidBisExport
from inventory_parser.raid_bis.compare import display_delta_keys, format_stat_deltas
from inventory_parser.slot2_augs.aug_stats import STAT_DISPLAY
from inventory_parser.slot2_augs.html import format_catalog_fetched_at


def _vendor_payload(cost: int | None, name: str | None, item_id: int | None, score_gain: float) -> dict:
    payload = {"scoreGain": round(float(score_gain or 0), 4)}
    if cost is not None:
        payload["vendorCost"] = int(cost)
    if name:
        payload["vendorItemName"] = name
    if item_id:
        payload["vendorItemId"] = int(item_id)
    return payload


def serialize_raid_bis_section(bundle: RaidBisExport) -> dict:
    characters: list[dict] = []
    for ch in bundle.characters:
        delta_keys = list(display_delta_keys(ch.class_abbr))
        characters.append(
            {
                "character": ch.character,
                "server": ch.server,
                "classAbbr": ch.class_abbr,
                "displayName": ch.display_name,
                "personaKey": ch.persona_key,
                "slotsChanged": ch.slots_changed,
                "totalDeltas": dict(ch.total_deltas),
                "totalDeltaText": format_stat_deltas(
                    ch.total_deltas, class_abbr=ch.class_abbr
                ),
                "displayDeltaKeys": delta_keys,
                "statLabels": {
                    k: STAT_DISPLAY.get(k, k) for k in delta_keys
                },
                "slots": [
                    {
                        "gearSlot": s.gear_slot,
                        "status": s.status,
                        "currentName": s.current_name,
                        "currentId": s.current_id,
                        "recommendedName": s.recommended_name,
                        "recommendedId": s.recommended_id,
                        "recommendedTier": s.recommended_tier,
                        "recommendedIconId": s.recommended_icon_id,
                        "currentIconId": s.current_icon_id,
                        "currentIsEvolver": bool(s.current_is_evolver),
                        "deltas": dict(s.deltas),
                        "deltaText": format_stat_deltas(
                            s.deltas, class_abbr=ch.class_abbr
                        ),
                        "note": s.note,
                        "petFocus": s.pet_focus,
                        "scored": s.scored,
                        **_vendor_payload(
                            s.vendor_cost,
                            s.vendor_item_name,
                            s.vendor_item_id,
                            s.score_gain,
                        ),
                        **(
                            {
                                "choices": [
                                    {
                                        "effectLabel": c.effect_label,
                                        "itemId": c.item_id,
                                        "name": c.name,
                                        "tier": c.tier,
                                        "iconId": c.icon_id,
                                        "deltas": dict(c.deltas),
                                        "deltaText": format_stat_deltas(
                                            c.deltas, class_abbr=ch.class_abbr
                                        ),
                                        "status": c.status,
                                        **_vendor_payload(
                                            c.vendor_cost,
                                            c.vendor_item_name,
                                            c.vendor_item_id,
                                            c.score_gain,
                                        ),
                                    }
                                    for c in s.choices
                                ]
                            }
                            if s.choices
                            else {}
                        ),
                    }
                    for s in ch.slots
                ],
            }
        )

    title_name = (bundle.export_prefix or "").strip() or "EQ"
    if len(bundle.characters) == 1:
        ch = bundle.characters[0]
        title_name = (ch.character or title_name).strip()
        if ch.class_abbr:
            title_name = f"{title_name} - {ch.class_abbr}"

    vendor = bundle.catalog.vendor
    currency_name = (vendor.currency_name if vendor else "") or ""
    if not currency_name:
        joined = " ".join(bundle.catalog.urls or [])
        if "sor.eqresource.com" in joined:
            currency_name = "Forgotten Ruined Coin"
    return {
        "reportTitle": f"{title_name} Raid BiS",
        "appVersion": __version__,
        "warnings": bundle.warnings,
        "catalogFetchedAt": format_catalog_fetched_at(bundle.catalog.fetched_at),
        "catalogFromCache": bundle.catalog.from_cache,
        "eqResourceItemUrl": EQRESOURCE_ITEM_URL,
        "iconDataUris": bundle.icon_data_uris,
        "currencyName": currency_name,
        "currencyId": vendor.currency_id if vendor else None,
        "currencyIconId": vendor.currency_icon_id if vendor else None,
        "vendorUrl": vendor.url if vendor else "",
        "characters": characters,
    }
