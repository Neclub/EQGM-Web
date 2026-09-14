"""Cache and embed EQ Resource item icons at generate time."""

from __future__ import annotations

import base64
import urllib.error
from collections.abc import Callable
from pathlib import Path

from inventory_parser.cache_io import ensure_local_bytes, write_bytes
from inventory_parser.http_fetch import MAX_ICON_BYTES, http_get_bytes, is_png
from inventory_parser.slot2_augs.eqresource_augs import USER_AGENT
from inventory_parser.slot2_augs.paths import appdata_dir

ICON_URL = "https://items.eqresource.com/itemimages/{icon_id}.png"

StatusFn = Callable[[str, int, int], None]


def icon_cache_dir() -> Path:
    path = appdata_dir() / "item_icons"
    path.mkdir(parents=True, exist_ok=True)
    return path


def collect_icon_data_uris(
    icon_ids: set[str],
    *,
    allow_network: bool = True,
    on_status: StatusFn | None = None,
) -> dict[str, str]:
    """Return icon_id → data URI. Missing icons are omitted (name links still work).

    PNGs under ``icon_cache_dir()`` (and shared R2) are used first. EQ Resource is
    contacted only for ids that are not already cached (and only when
    ``allow_network`` is True).
    """
    ids = [str(icon_id) for icon_id in sorted(icon_ids) if icon_id and str(icon_id).isdigit()]
    cache_dir = icon_cache_dir()
    # Pull any R2-only icons into local before deciding what is missing.
    for icon_id in ids:
        path = cache_dir / f"{icon_id}.png"
        if not path.is_file():
            ensure_local_bytes(path)
    missing = [
        icon_id
        for icon_id in ids
        if not (cache_dir / f"{icon_id}.png").is_file()
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
    path = icon_cache_dir() / f"{icon_id}.png"
    data = ensure_local_bytes(path)
    if data and is_png(data):
        return data
    if path.is_file():
        try:
            data = path.read_bytes()
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
    try:
        write_bytes(path, data)
    except OSError:
        # Cache write failed; still return the fetched icon bytes for this run.
        pass
    return data
