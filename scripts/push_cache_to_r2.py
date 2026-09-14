"""Upload local cache/ tree to Cloudflare R2 (one-time seed).

Requires EQGM_R2_* env vars. Example (PowerShell):

  $env:PYTHONPATH = ".;src"
  $env:EQGM_APPDATA = "cache"
  $env:EQGM_R2_ACCOUNT_ID = "..."
  $env:EQGM_R2_ACCESS_KEY_ID = "..."
  $env:EQGM_R2_SECRET_ACCESS_KEY = "..."
  $env:EQGM_R2_BUCKET = "eqgm-cache"
  .\\.venv\\Scripts\\python.exe scripts\\push_cache_to_r2.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from app.cache_seed import configure_cache_dir  # noqa: E402
from app.shared_cache import enabled, sync_push_tree  # noqa: E402


def main() -> int:
    root = configure_cache_dir()
    if not enabled():
        print("R2 is not configured. Set EQGM_R2_BUCKET, EQGM_R2_ACCESS_KEY_ID,")
        print("EQGM_R2_SECRET_ACCESS_KEY, and EQGM_R2_ACCOUNT_ID or EQGM_R2_ENDPOINT.")
        return 1
    print(f"Uploading from {root} …")
    uploaded = sync_push_tree(root)
    print(f"Uploaded {len(uploaded)} object(s).")
    for key in uploaded[:20]:
        print(f"  {key}")
    if len(uploaded) > 20:
        print(f"  … and {len(uploaded) - 20} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
