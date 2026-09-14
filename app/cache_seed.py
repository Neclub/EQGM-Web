"""Point live EQGM caches at the repo cache/ directory."""

from __future__ import annotations

import os
from pathlib import Path


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
    """Configure live cache dir; return empty list (no copy — cache/ is the store)."""
    configure_cache_dir()
    return []
