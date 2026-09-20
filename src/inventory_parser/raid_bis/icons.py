"""Cache and embed EQ Resource item icons at generate time."""

from __future__ import annotations

import base64
import urllib.error
from collections.abc import Callable
from pathlib import Path

from inventory_parser.http_fetch import MAX_ICON_BYTES, http_get_bytes, is_png
from inventory_parser.slot2_augs.eqresource_augs import USER_AGENT
from inventory_parser.slot2_augs.paths import appdata_dir

ICON_URL = "https://items.eqresource.com/itemimages/{icon_id}.png"
# Shard so each folder stays under GitHub's ~1000-file directory listing limit.
ICON_SHARD_SIZE = 1000

StatusFn = Callable[[str, int, int], None]


def icon_cache_dir() -> Path:
    path = appdata_dir() / "item_icons"
    path.mkdir(parents=True, exist_ok=True)
    return path


def icon_shard_name(icon_id: str | int) -> str:
    """Return shard folder name for an icon id (``id // 1000``)."""
    return str(int(icon_id) // ICON_SHARD_SIZE)


def icon_png_path(icon_id: str | int, *, cache_dir: Path | None = None) -> Path:
    """Canonical on-disk path: ``item_icons/{id//1000}/{id}.png``."""
    root = cache_dir if cache_dir is not None else icon_cache_dir()
    text = str(icon_id)
    return root / icon_shard_name(text) / f"{text}.png"


def resolve_icon_png_path(icon_id: str | int, *, cache_dir: Path | None = None) -> Path | None:
    """Return an existing icon path (sharded preferred, flat legacy fallback)."""
    root = cache_dir if cache_dir is not None else icon_cache_dir()
    text = str(icon_id)
    if not text.isdigit():
        return None
    sharded = root / icon_shard_name(text) / f"{text}.png"
    if sharded.is_file():
        return sharded
    legacy = root / f"{text}.png"
    if legacy.is_file():
        return legacy
    return None


def migrate_flat_icons_to_shards(*, cache_dir: Path | None = None) -> int:
    """Move ``item_icons/{id}.png`` into ``item_icons/{id//1000}/{id}.png``.

    Expac thumbs (``expac-*.jpg``/``.png``) stay at the icon root. Returns the
    number of files moved.
    """
    root = cache_dir if cache_dir is not None else icon_cache_dir()
    if not root.is_dir():
        return 0
    moved = 0
    for path in sorted(root.glob("*.png")):
        stem = path.stem
        if not stem.isdigit():
            continue
        dest = icon_png_path(stem, cache_dir=root)
        if dest.resolve() == path.resolve():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.is_file():
            # Prefer existing shard copy; drop the flat duplicate.
            try:
                path.unlink()
            except OSError:
                pass
            continue
        try:
            path.replace(dest)
            moved += 1
        except OSError:
            continue
    return moved


def collect_icon_data_uris(
    icon_ids: set[str],
    *,
    allow_network: bool = True,
    on_status: StatusFn | None = None,
) -> dict[str, str]:
    """Return icon_id → data URI. Missing icons are omitted (name links still work).

    PNGs under ``icon_cache_dir()`` (sharded or flat) are used first. EQ Resource
    is contacted only for ids that are not already cached (and only when
    ``allow_network`` is True).
    """
    ids = [str(icon_id) for icon_id in sorted(icon_ids) if icon_id and str(icon_id).isdigit()]
    missing = [
        icon_id
        for icon_id in ids
        if resolve_icon_png_path(icon_id) is None
    ]
    if missing and allow_network and on_status is not None:
        on_status("Fetching item icons from EQ Resource…", 0, len(missing))
    elif ids and on_status is not None:
        cached_n = len(ids) - len(missing)
        on_status(f"Using cached item icons… ({cached_n}/{len(ids)})", 1, 1)

    out: dict[str, str] = {}
    fetched = 0
    for icon_id in ids:
        png = _load_icon_png(icon_id, allow_network=allow_network)
        if not png:
            if icon_id in missing and allow_network:
                fetched += 1
                if on_status is not None:
                    on_status(
                        f"Fetching item icons from EQ Resource… ({fetched}/{len(missing)})",
                        fetched,
                        len(missing),
                    )
            continue
        b64 = base64.b64encode(png).decode("ascii")
        out[icon_id] = f"data:image/png;base64,{b64}"
        if icon_id in missing and allow_network:
            fetched += 1
            if on_status is not None:
                on_status(
                    f"Fetching item icons from EQ Resource… ({fetched}/{len(missing)})",
                    fetched,
                    len(missing),
                )
    return out


def _load_icon_png(icon_id: str, *, allow_network: bool) -> bytes | None:
    if not icon_id.isdigit():
        return None
    existing = resolve_icon_png_path(icon_id)
    if existing is not None:
        try:
            data = existing.read_bytes()
        except OSError:
            data = b""
        if is_png(data):
            return data
    if not allow_network:
        return None
    try:
        data = http_get_bytes(
            ICON_URL.format(icon_id=icon_id),
            timeout=20,
            user_agent=USER_AGENT,
            max_bytes=MAX_ICON_BYTES,
        )
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None
    if not is_png(data):
        return None
    path = icon_png_path(icon_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    except OSError:
        # Cache write failed; still return the fetched icon bytes for this run.
        pass
    return data
