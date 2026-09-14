"""AppData root for EQGM caches (same folder as settings)."""

from __future__ import annotations

import shutil
from pathlib import Path

from inventory_parser.character_column_order import settings_path

# Disk caches rebuilt on the next Generate Report (settings / weight overrides kept).
CACHE_FILENAMES: tuple[str, ...] = (
    "eqresource_aug_cache.json",
    "eqresource_expansion_cache.json",
    "eqresource_search_cache.json",
    "eqresource_gear_tier_cache.json",
    "eqresource_type18_catalog_cache.json",
    "eqresource_type18_item_meta_cache.json",
    "item_sockets_cache.json",
    "item_class_cache.json",
    "raidloot_cache.json",
    "raid_bis_catalog.json",
    "raid_bis_item_cache.json",
)
ICON_CACHE_DIRNAME = "item_icons"


def appdata_dir() -> Path:
    root = settings_path().parent
    root.mkdir(parents=True, exist_ok=True)
    return root


def clear_disk_caches() -> dict:
    """Delete AppData catalog/item/icon caches. Does not touch settings or weight overrides."""
    root = appdata_dir()
    deleted: list[str] = []
    errors: list[str] = []

    for name in CACHE_FILENAMES:
        path = root / name
        if not path.exists():
            continue
        try:
            path.unlink()
            deleted.append(name)
        except OSError as exc:
            errors.append(f"{name}: {exc}")

    icons = root / ICON_CACHE_DIRNAME
    if icons.exists():
        try:
            shutil.rmtree(icons)
            deleted.append(ICON_CACHE_DIRNAME)
        except OSError as exc:
            errors.append(f"{ICON_CACHE_DIRNAME}: {exc}")

    return {
        "ok": len(errors) == 0,
        "deleted": deleted,
        "errors": errors,
    }
