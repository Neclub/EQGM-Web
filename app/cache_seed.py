"""Point live EQGM caches at the repo cache/ directory and sync from R2."""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def configure_cache_dir() -> Path:
    """Ensure ``EQGM_APPDATA`` points at repo ``cache/`` (live read/write store).

    Catalog JSON is read from and written into this folder so newly fetched items
    can be committed to GitHub. No AppData seed copy is performed.
    """
    existing = os.environ.get("EQGM_APPDATA", "").strip()
    if existing:
        root = Path(existing).expanduser()
        if not root.is_absolute():
            root = project_root() / root
    else:
        seed_env = os.environ.get("EQGM_CACHE_SEED", "").strip()
        if seed_env:
            root = Path(seed_env)
            if not root.is_absolute():
                root = project_root() / root
        else:
            root = project_root() / "cache"
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    os.environ["EQGM_APPDATA"] = str(root)
    return root


def seed_disk_caches() -> list[str]:
    """Configure live cache dir and pull shared R2 objects into it."""
    root = configure_cache_dir()
    try:
        from app.shared_cache import enabled, sync_pull

        if enabled():
            pulled = sync_pull(root)
            logger.info("R2 sync_pull: %s object(s)", len(pulled))
            return pulled
    except Exception as exc:
        logger.warning("R2 sync_pull skipped: %s", exc)
    return []


def sync_catalogs_from_r2() -> list[str]:
    """Pull JSON catalogs from R2 (call before generate)."""
    root = configure_cache_dir()
    try:
        from app.shared_cache import enabled, sync_pull_catalogs

        if enabled():
            return sync_pull_catalogs(root)
    except Exception as exc:
        logger.warning("R2 catalog sync skipped: %s", exc)
    return []
