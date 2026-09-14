#!/usr/bin/env python3
"""One-shot local warmer for EQGM Web ``cache/`` (EQ Resource + Raidloot).

Run on your PC from the repo root. Writes catalogs, item details (stats/inspect),
sockets, classes, gear tiers, expansions, and icons into ``cache/``. Commit and
push that folder to GitHub so Render ships the richer baked-in cache.

Example:
  py -3 scripts/warm_eqresource_cache.py
  py -3 scripts/warm_eqresource_cache.py path\\to\\Examples
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CACHE = REPO_ROOT / "cache"


def _configure_path() -> None:
    root = str(REPO_ROOT)
    src = str(REPO_ROOT / "src")
    for entry in (root, src):
        if entry not in sys.path:
            sys.path.insert(0, entry)


def _log(msg: str) -> None:
    print(msg, flush=True)


def _status(message: str, done: int = 0, total: int = 1) -> None:
    if total > 1:
        _log(f"  {message} ({done}/{total})")
    else:
        _log(f"  {message}")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Warm EQGM Web cache/ from EQ Resource on this PC, then commit cache/ to GitHub."
        )
    )
    p.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Optional inventory .txt files and/or folders to expand known item IDs",
    )
    p.add_argument(
        "--cache-dir",
        type=Path,
        default=DEFAULT_CACHE,
        help=f"Cache directory (default: {DEFAULT_CACHE})",
    )
    p.add_argument(
        "--no-force-refresh",
        action="store_true",
        help="Reuse existing catalog JSON when present (default is force-refresh)",
    )
    p.add_argument(
        "--polite-delay",
        type=float,
        default=0.05,
        help="Delay between live item page fetches (seconds)",
    )
    return p.parse_args(argv)


def _collect_ids_from_obj(obj: Any, out: set[int]) -> None:
    if isinstance(obj, dict):
        raw_id = obj.get("item_id")
        if raw_id is None:
            raw_id = obj.get("itemId")
        if raw_id is not None:
            try:
                iid = int(raw_id)
            except (TypeError, ValueError):
                iid = 0
            if iid > 0:
                out.add(iid)
        for key, value in obj.items():
            if str(key).isdigit() and isinstance(value, dict):
                try:
                    out.add(int(key))
                except ValueError:
                    pass
            _collect_ids_from_obj(value, out)
    elif isinstance(obj, list):
        for item in obj:
            _collect_ids_from_obj(item, out)


def _ids_from_existing_cache(cache_dir: Path) -> set[int]:
    ids: set[int] = set()
    for path in sorted(cache_dir.glob("*.json")):
        if path.name in {"settings.json"}:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        _collect_ids_from_obj(data, ids)
    return ids


def _inventory_files(paths: Iterable[Path]) -> list[Path]:
    files: list[Path] = []
    for raw in paths:
        path = raw.expanduser()
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()
        else:
            path = path.resolve()
        if path.is_file() and path.suffix.lower() == ".txt":
            files.append(path)
        elif path.is_dir():
            files.extend(sorted(path.rglob("*-Inventory.txt")))
            files.extend(
                p
                for p in sorted(path.rglob("*.txt"))
                if p not in files and "inventory" in p.name.casefold()
            )
    # Preserve order, drop dupes
    seen: set[Path] = set()
    out: list[Path] = []
    for path in files:
        if path in seen:
            continue
        seen.add(path)
        out.append(path)
    return out


def _ids_from_inventories(paths: Iterable[Path]) -> set[int]:
    from inventory_parser.parser import collect_owned_item_ids, parse_inventory_file

    ids: set[int] = set()
    files = _inventory_files(paths)
    if not files:
        return ids
    _log(f"Parsing {len(files)} inventory dump(s)…")
    for path in files:
        data = parse_inventory_file(path)
        if data is None:
            _log(f"  skip (unreadable): {path}")
            continue
        found = collect_owned_item_ids(data)
        ids |= found
        _log(f"  {path.name}: {len(found)} item ids")
    return ids


def _icon_ids_from_cache(cache_dir: Path) -> set[str]:
    icons: set[str] = set()

    def add(raw: Any) -> None:
        if raw is None:
            return
        text = str(raw).strip()
        if text.isdigit():
            icons.add(text)

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            add(obj.get("icon_id"))
            add(obj.get("iconId"))
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    for path in sorted(cache_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        walk(data)
    return icons


def _expansion_codes_from_item_cache(cache_dir: Path) -> set[str]:
    codes: set[str] = set()
    path = cache_dir / "raid_bis_item_cache.json"
    if not path.is_file():
        return codes
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return codes
    for entry in data.values():
        if not isinstance(entry, dict):
            continue
        inspect = entry.get("inspect")
        if not isinstance(inspect, dict):
            continue
        code = str(inspect.get("expansionCode") or inspect.get("expansion_code") or "").strip()
        if code:
            codes.add(code.lower())
    return codes


def _file_count(path: Path) -> int:
    if not path.is_file():
        return 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    if not isinstance(data, dict):
        return 0
    if path.name == "raid_bis_catalog.json":
        catalog = data.get("catalog") or {}
        items = catalog.get("items") if isinstance(catalog, dict) else None
        return len(items) if isinstance(items, list) else 0
    if path.name == "eqresource_search_cache.json":
        total = 0
        for value in data.values():
            if isinstance(value, dict) and isinstance(value.get("rows"), list):
                total += len(value["rows"])
        return total
    if path.name == "eqresource_type18_catalog_cache.json":
        rows = data.get("rows")
        return len(rows) if isinstance(rows, list) else 0
    return len([k for k in data if k != "_version" and not str(k).startswith("_")])


def _print_summary(cache_dir: Path) -> None:
    from inventory_parser.slot2_augs.paths import CACHE_FILENAMES, ICON_CACHE_DIRNAME

    _log("")
    _log("Cache coverage summary")
    _log("-" * 40)
    for name in CACHE_FILENAMES:
        path = cache_dir / name
        if path.is_file():
            _log(f"  {name}: {_file_count(path)} entries ({path.stat().st_size:,} bytes)")
        else:
            _log(f"  {name}: missing")
    icons = cache_dir / ICON_CACHE_DIRNAME
    if icons.is_dir():
        pngs = list(icons.glob("*.png"))
        jpgs = list(icons.glob("expac-*.jpg")) + list(icons.glob("expac-*.png"))
        _log(f"  {ICON_CACHE_DIRNAME}/: {len(pngs)} png, {len(jpgs)} expac thumbs")
    else:
        _log(f"  {ICON_CACHE_DIRNAME}/: missing")
    _log("-" * 40)
    _log("Next: review git status, then commit and push cache/ to GitHub.")


def warm(cache_dir: Path, *, force_refresh: bool, polite_delay: float, inventory_paths: list[Path]) -> int:
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ["EQGM_APPDATA"] = str(cache_dir.resolve())

    from inventory_parser.item_inspect import (
        cached_inspect_map,
        collect_expansion_data_uris,
    )
    from inventory_parser.raid_bis.catalog import fetch_catalog, hydrate_item_ids
    from inventory_parser.raid_bis.icons import collect_icon_data_uris, icon_cache_dir
    from inventory_parser.slot2_augs.chest_class import fetch_item_classes
    from inventory_parser.slot2_augs.eqresource_augs import (
        resolve_eqresource_augs,
        resolve_item_expansions,
    )
    from inventory_parser.slot2_augs.eqresource_gear_tier import resolve_item_gear_tiers
    from inventory_parser.slot2_augs.item_sockets import resolve_type78_slots
    from inventory_parser.slot2_augs.profiles import PROFILES
    from inventory_parser.slot2_augs.raidloot import fetch_catalog as fetch_slot2_catalog
    from inventory_parser.type18_augs.catalog import fetch_type18_catalog

    failures: list[str] = []
    known_ids: set[int] = set()
    gear_ids: set[int] = set()
    aug_ids: set[int] = set()

    # --- Stage 1: Raid BiS ---
    _log("1/6 Raid BiS catalog (force_refresh=%s)…" % force_refresh)
    try:
        bis = fetch_catalog(
            force_refresh=force_refresh,
            allow_network=True,
            hydrate=True,
            polite_delay_s=polite_delay,
            on_status=_status,
        )
        for item in bis.items:
            if item.item_id > 0:
                known_ids.add(item.item_id)
                gear_ids.add(item.item_id)
        if bis.vendor is not None:
            for item in bis.vendor.items:
                if item.item_id > 0:
                    known_ids.add(item.item_id)
                    gear_ids.add(item.item_id)
        warn = f" — {bis.warning}" if bis.warning else ""
        _log(
            f"  Raid BiS: {len(bis.items)} items"
            f"{' (from cache)' if bis.from_cache else ''}"
            f"{warn}"
        )
        if not bis.items:
            failures.append("Raid BiS catalog returned no items")
    except Exception as exc:
        failures.append(f"Raid BiS failed: {exc}")
        _log(f"  ERROR: {exc}")

    # --- Stage 2: Slot2 profiles ---
    _log("2/6 Slot2 type 7/8 catalogs (dex/int/wis)…")
    for profile in PROFILES:
        try:
            result = fetch_slot2_catalog(profile, force_refresh=force_refresh)
            for aug in result.augs:
                if aug.item_id > 0:
                    known_ids.add(aug.item_id)
                    aug_ids.add(aug.item_id)
            _log(
                f"  {profile}: {len(result.augs)} augs"
                f"{' (from cache)' if result.from_cache else ''}"
            )
            if len(result.augs) < 3:
                failures.append(f"Slot2 {profile} catalog too small ({len(result.augs)})")
        except Exception as exc:
            failures.append(f"Slot2 {profile} failed: {exc}")
            _log(f"  ERROR {profile}: {exc}")

    # --- Stage 3: Type 18/19 ---
    _log("3/6 Type 18/19 catalog…")
    try:
        t18 = fetch_type18_catalog(
            force_refresh=force_refresh,
            allow_network=True,
            on_progress=lambda done, total: _status(
                "Type 18/19 item meta…", done, total
            ),
        )
        for entry in t18.entries:
            if entry.item_id > 0:
                known_ids.add(entry.item_id)
                aug_ids.add(entry.item_id)
        _log(
            f"  Type 18/19: {len(t18.entries)} entries"
            f"{' (from cache)' if t18.from_cache else ''}"
        )
        if not t18.entries:
            failures.append("Type 18/19 catalog returned no entries")
    except Exception as exc:
        failures.append(f"Type 18/19 failed: {exc}")
        _log(f"  ERROR: {exc}")

    # --- Merge existing cache + optional inventories ---
    existing = _ids_from_existing_cache(cache_dir)
    known_ids |= existing
    _log(f"Existing cache contributed {len(existing)} item ids")

    if inventory_paths:
        inv_ids = _ids_from_inventories(inventory_paths)
        known_ids |= inv_ids
        gear_ids |= inv_ids
        _log(f"Inventory dumps contributed {len(inv_ids)} item ids")

    gear_ids |= {
        iid
        for iid in known_ids
        if iid not in aug_ids
    }

    _log(f"Known item-id universe: {len(known_ids)} ({len(gear_ids)} gear-ish, {len(aug_ids)} aug)")

    # --- Stage 4: hydrate item pages (stats + inspect) ---
    _log("4/6 Hydrating item pages (stats / inspect)…")
    try:
        hydrate_item_ids(
            sorted(known_ids),
            allow_network=True,
            polite_delay_s=polite_delay,
            on_status=_status,
        )
        inspect_n = len(cached_inspect_map())
        _log(f"  Inspect cards cached: {inspect_n}")
    except Exception as exc:
        failures.append(f"Item hydrate failed: {exc}")
        _log(f"  ERROR: {exc}")

    # Deepen aug stats for all profiles
    _log("  Resolving aug stats for all profiles…")
    for profile in PROFILES:
        try:
            resolved = resolve_eqresource_augs(
                sorted(aug_ids),
                profile,
                force_refresh=False,
                polite_delay_s=polite_delay,
                allow_network=True,
            )
            _log(f"  aug/{profile}: {len(resolved)} resolved")
        except Exception as exc:
            _log(f"  WARN aug/{profile}: {exc}")

    # --- Stage 5: sockets / classes / tiers / expansions ---
    _log("5/6 Sockets, classes, gear tiers, expansions…")
    gear_list = sorted(gear_ids)

    try:
        def sock_progress(done: int, total: int) -> None:
            _status("Item sockets…", done, total)

        maps = resolve_type78_slots(
            gear_list,
            force_refresh=False,
            polite_delay_s=polite_delay,
            on_progress=sock_progress,
        )
        _log(f"  Sockets: {len(maps)} items")
    except Exception as exc:
        _log(f"  WARN sockets: {exc}")

    try:
        class_ok = 0
        total = len(gear_list)
        for i, item_id in enumerate(gear_list, start=1):
            if i > 1 and polite_delay > 0:
                time.sleep(polite_delay)
            classes = fetch_item_classes(item_id, force_refresh=False)
            if classes:
                class_ok += 1
            if i == 1 or i == total or i % 25 == 0:
                _status("Item classes…", i, total)
        _log(f"  Classes: {class_ok}/{total} with class lists")
    except Exception as exc:
        _log(f"  WARN classes: {exc}")

    try:
        tiers = resolve_item_gear_tiers(
            gear_list,
            force_refresh=False,
            polite_delay_s=polite_delay,
            allow_network=True,
            on_progress=lambda done, total: _status("Gear tiers…", done, total),
        )
        _log(f"  Gear tiers: {len(tiers)} resolved")
    except Exception as exc:
        _log(f"  WARN gear tiers: {exc}")

    try:
        expansions = resolve_item_expansions(
            sorted(known_ids),
            force_refresh=False,
            polite_delay_s=polite_delay,
            allow_network=True,
            on_progress=lambda done, total: _status("Expansions…", done, total),
        )
        _log(f"  Expansions: {len(expansions)} resolved")
    except Exception as exc:
        _log(f"  WARN expansions: {exc}")

    # --- Stage 6: icons + expac thumbs ---
    _log("6/6 Icons and expansion thumbnails…")
    icon_cache_dir()
    icon_ids = _icon_ids_from_cache(cache_dir)
    for inspect in cached_inspect_map().values():
        if inspect.icon_id:
            icon_ids.add(str(inspect.icon_id))
    try:
        uris = collect_icon_data_uris(
            icon_ids,
            allow_network=True,
            on_status=_status,
        )
        _log(f"  Item icons ready: {len(uris)}/{len(icon_ids)}")
    except Exception as exc:
        _log(f"  WARN icons: {exc}")

    codes = _expansion_codes_from_item_cache(cache_dir)
    for inspect in cached_inspect_map().values():
        if inspect.expansion_code:
            codes.add(str(inspect.expansion_code).lower())
    try:
        exp_uris = collect_expansion_data_uris(
            codes,
            allow_network=True,
            on_status=_status,
        )
        _log(f"  Expansion thumbs ready: {len(exp_uris)}/{len(codes)}")
    except Exception as exc:
        _log(f"  WARN expansion thumbs: {exc}")

    _print_summary(cache_dir)

    if failures:
        _log("")
        _log("Completed with errors:")
        for msg in failures:
            _log(f"  - {msg}")
        return 1
    _log("")
    _log("Warm complete.")
    return 0


def main(argv: list[str] | None = None) -> int:
    _configure_path()
    args = _parse_args(argv)
    cache_dir = args.cache_dir.expanduser()
    if not cache_dir.is_absolute():
        cache_dir = (Path.cwd() / cache_dir).resolve()
    else:
        cache_dir = cache_dir.resolve()

    _log(f"EQGM cache warmer")
    _log(f"  cache dir: {cache_dir}")
    _log(f"  force refresh catalogs: {not args.no_force_refresh}")
    _log(f"  polite delay: {args.polite_delay}s")
    return warm(
        cache_dir,
        force_refresh=not args.no_force_refresh,
        polite_delay=args.polite_delay,
        inventory_paths=list(args.paths),
    )


if __name__ == "__main__":
    raise SystemExit(main())
