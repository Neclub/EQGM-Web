"""Seed EQ Resource disk caches and expose helpers for the web app."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def seed_disk_caches() -> list[str]:
    """Copy baked JSON caches into the EQGM appdata directory before first generate."""
    from inventory_parser.slot2_augs.paths import CACHE_FILENAMES, appdata_dir

    seed_env = os.environ.get("EQGM_CACHE_SEED", "").strip()
    seed_dir = Path(seed_env) if seed_env else project_root() / "cache"
    if not seed_dir.is_absolute():
        seed_dir = project_root() / seed_dir
    if not seed_dir.is_dir():
        return []

    dest = appdata_dir()
    copied: list[str] = []
    for name in CACHE_FILENAMES:
        src = seed_dir / name
        if not src.is_file():
            continue
        target = dest / name
        if target.is_file() and target.stat().st_size >= src.stat().st_size:
            continue
        shutil.copy2(src, target)
        copied.append(name)
    return copied
