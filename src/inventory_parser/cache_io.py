"""Local cache file helpers with optional Cloudflare R2 publish / pull."""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _publish(path: Path) -> None:
    try:
        from app.shared_cache import publish

        publish(path)
    except Exception as exc:
        logger.debug("cache publish skipped: %s", exc)


def _r2_get(key: str) -> bytes | None:
    try:
        from app.shared_cache import get_bytes

        return get_bytes(key)
    except Exception as exc:
        logger.debug("cache r2 get skipped: %s", exc)
        return None


def _key_for(path: Path) -> str | None:
    try:
        from app.shared_cache import key_for_local

        return key_for_local(path)
    except Exception:
        return None


def write_bytes(path: Path, data: bytes, *, publish: bool = True) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    if publish:
        _publish(path)


def write_json(path: Path, data: dict, *, indent: int = 2, publish: bool = True) -> None:
    text = json.dumps(data, indent=indent)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if publish:
        _publish(path)


def ensure_local_bytes(path: Path) -> bytes | None:
    """Return file bytes from local disk, or pull from R2 into local if missing."""
    path = Path(path)
    if path.is_file():
        try:
            return path.read_bytes()
        except OSError:
            return None
    key = _key_for(path)
    if not key:
        return None
    remote = _r2_get(key)
    if remote is None:
        return None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(remote)
    except OSError as exc:
        logger.debug("cache ensure write failed: %s", exc)
        return remote
    return remote
