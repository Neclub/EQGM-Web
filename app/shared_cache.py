"""Cloudflare R2 shared cache (S3-compatible). No-op when env is unset."""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_client_lock = threading.Lock()
_client: Any | None = None
_client_failed = False


def enabled() -> bool:
    return bool(
        os.environ.get("EQGM_R2_BUCKET", "").strip()
        and os.environ.get("EQGM_R2_ACCESS_KEY_ID", "").strip()
        and os.environ.get("EQGM_R2_SECRET_ACCESS_KEY", "").strip()
        and (
            os.environ.get("EQGM_R2_ENDPOINT", "").strip()
            or os.environ.get("EQGM_R2_ACCOUNT_ID", "").strip()
        )
    )


def _endpoint() -> str:
    explicit = os.environ.get("EQGM_R2_ENDPOINT", "").strip()
    if explicit:
        return explicit.rstrip("/")
    account = os.environ.get("EQGM_R2_ACCOUNT_ID", "").strip()
    return f"https://{account}.r2.cloudflarestorage.com"


def _bucket() -> str:
    return os.environ.get("EQGM_R2_BUCKET", "").strip()


def _get_client() -> Any | None:
    global _client, _client_failed
    if not enabled() or _client_failed:
        return None
    with _client_lock:
        if _client is not None:
            return _client
        try:
            import boto3
            from botocore.config import Config

            _client = boto3.client(
                "s3",
                endpoint_url=_endpoint(),
                aws_access_key_id=os.environ["EQGM_R2_ACCESS_KEY_ID"].strip(),
                aws_secret_access_key=os.environ["EQGM_R2_SECRET_ACCESS_KEY"].strip(),
                region_name=os.environ.get("EQGM_R2_REGION", "auto").strip() or "auto",
                config=Config(signature_version="s3v4"),
            )
            return _client
        except Exception as exc:
            logger.warning("EQGM R2 client unavailable: %s", exc)
            _client_failed = True
            return None


def key_for_local(path: Path, *, root: Path | None = None) -> str | None:
    """Return R2 object key for a path under the EQGM cache root."""
    from inventory_parser.slot2_augs.paths import appdata_dir

    base = (root or appdata_dir()).resolve()
    try:
        rel = path.resolve().relative_to(base)
    except ValueError:
        return None
    key = rel.as_posix()
    if not key or key.startswith(".."):
        return None
    # Do not sync settings / logs
    name = Path(key).name
    if name in {"settings.json", "last_report.log"}:
        return None
    return key


def get_bytes(key: str) -> bytes | None:
    client = _get_client()
    if client is None or not key:
        return None
    try:
        resp = client.get_object(Bucket=_bucket(), Key=key)
        body = resp["Body"].read()
        return body if isinstance(body, (bytes, bytearray)) else None
    except Exception as exc:
        # Missing key is normal
        code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
        if code in {"NoSuchKey", "404", "NotFound"}:
            return None
        logger.debug("R2 get %s failed: %s", key, exc)
        return None


def put_bytes(key: str, data: bytes, *, content_type: str | None = None) -> bool:
    client = _get_client()
    if client is None or not key:
        return False
    try:
        extra: dict[str, Any] = {}
        if content_type:
            extra["ContentType"] = content_type
        client.put_object(Bucket=_bucket(), Key=key, Body=data, **extra)
        return True
    except Exception as exc:
        logger.warning("R2 put %s failed: %s", key, exc)
        return False


def publish(local_path: Path, *, root: Path | None = None) -> bool:
    """Upload one local cache file to R2."""
    if not enabled():
        return False
    path = Path(local_path)
    if not path.is_file():
        return False
    key = key_for_local(path, root=root)
    if not key:
        return False
    try:
        data = path.read_bytes()
    except OSError as exc:
        logger.warning("R2 publish read failed %s: %s", path, exc)
        return False
    ctype = None
    if key.endswith(".json"):
        ctype = "application/json"
    elif key.endswith(".png"):
        ctype = "image/png"
    elif key.endswith(".jpg") or key.endswith(".jpeg"):
        ctype = "image/jpeg"
    return put_bytes(key, data, content_type=ctype)


def sync_pull(
    local_root: Path | None = None,
    *,
    keys: list[str] | None = None,
    prefix: str = "",
) -> list[str]:
    """Download R2 objects into local cache. If ``keys`` given, only those."""
    from inventory_parser.slot2_augs.paths import CACHE_FILENAMES, appdata_dir

    client = _get_client()
    if client is None:
        return []
    root = (local_root or appdata_dir()).resolve()
    root.mkdir(parents=True, exist_ok=True)
    pulled: list[str] = []

    to_fetch: list[str]
    if keys is not None:
        to_fetch = list(keys)
    else:
        to_fetch = list(CACHE_FILENAMES)
        # Also pull icons + any other objects under prefix via list
        try:
            paginator = client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=_bucket(), Prefix=prefix):
                for obj in page.get("Contents") or []:
                    key = obj.get("Key") or ""
                    if key and key not in to_fetch:
                        to_fetch.append(key)
        except Exception as exc:
            logger.warning("R2 list failed: %s", exc)

    for key in to_fetch:
        if not key or key.endswith("/"):
            continue
        target = root / key
        remote = get_bytes(key)
        if remote is None:
            continue
        if target.is_file():
            try:
                if target.stat().st_size == len(remote) and target.read_bytes() == remote:
                    continue
            except OSError:
                pass
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(remote)
            pulled.append(key)
        except OSError as exc:
            logger.warning("R2 sync write %s failed: %s", target, exc)
    return pulled


def sync_pull_catalogs(local_root: Path | None = None) -> list[str]:
    """Pull only JSON catalog files (fast path before generate)."""
    from inventory_parser.slot2_augs.paths import CACHE_FILENAMES

    return sync_pull(local_root, keys=list(CACHE_FILENAMES))


def sync_push_tree(local_root: Path | None = None) -> list[str]:
    """Upload all files under local cache root to R2 (seed script)."""
    from inventory_parser.slot2_augs.paths import appdata_dir

    if not enabled():
        return []
    root = (local_root or appdata_dir()).resolve()
    if not root.is_dir():
        return []
    uploaded: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if publish(path, root=root):
            key = key_for_local(path, root=root)
            if key:
                uploaded.append(key)
    return uploaded
