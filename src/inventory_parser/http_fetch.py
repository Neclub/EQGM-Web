"""HTTPS fetches limited to EQ Resource and raidloot hosts.

Includes per-URL singleflight, optional network disable, and an hourly request budget
so EQGM Web does not hammer upstream catalogs.
"""

from __future__ import annotations

import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from urllib.parse import urlparse

ALLOWED_HOSTS = frozenset(
    {
        "eqresource.com",
        "www.eqresource.com",
        "items.eqresource.com",
        "sor.eqresource.com",
        "raidloot.com",
        "www.raidloot.com",
    }
)

_MAX_HTML_BYTES = 5_000_000
MAX_ICON_BYTES = 256_000
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"

_DEFAULT_HOURLY_BUDGET = 120
_MIN_SPACING_SECONDS = 0.05

_gate_lock = threading.Lock()
_inflight: dict[str, threading.Event] = {}
_inflight_result: dict[str, bytes | BaseException] = {}
_request_times: list[float] = []
_last_request_at = 0.0


class NetworkBudgetExceeded(urllib.error.URLError):
    """Raised when the hourly EQ Resource / Raidloot budget is exhausted."""


def network_allowed() -> bool:
    raw = os.environ.get("EQGM_ALLOW_NETWORK", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def hourly_budget() -> int:
    raw = os.environ.get("EQGM_EQR_MAX_REQUESTS_PER_HOUR", "").strip()
    if not raw:
        return _DEFAULT_HOURLY_BUDGET
    try:
        return max(0, int(raw))
    except ValueError:
        return _DEFAULT_HOURLY_BUDGET


def _budget_ok() -> bool:
    limit = hourly_budget()
    if limit <= 0:
        return False
    now = time.time()
    with _gate_lock:
        cutoff = now - 3600
        while _request_times and _request_times[0] < cutoff:
            _request_times.pop(0)
        return len(_request_times) < limit


def _record_request() -> None:
    global _last_request_at
    now = time.time()
    wait = 0.0
    with _gate_lock:
        _request_times.append(now)
        elapsed = now - _last_request_at
        if _last_request_at and elapsed < _MIN_SPACING_SECONDS:
            wait = _MIN_SPACING_SECONDS - elapsed
        _last_request_at = now + wait
    if wait > 0:
        time.sleep(wait)


class _AllowedHostRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follow HTTPS redirects only while the host stays on the allowlist."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _require_allowed_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _require_allowed_url(url: str, *, allowed_hosts: frozenset[str] = ALLOWED_HOSTS) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").casefold()
    if parsed.scheme != "https":
        raise urllib.error.URLError("Refusing non-HTTPS request.")
    if parsed.username or parsed.password:
        raise urllib.error.URLError("Refusing URL with userinfo.")
    if parsed.port not in (None, 443):
        raise urllib.error.URLError("Refusing unexpected HTTPS port.")
    if host not in allowed_hosts:
        raise urllib.error.URLError(f"Refusing request to {host or parsed.netloc}.")


def http_get_bytes(
    url: str,
    *,
    timeout: float,
    user_agent: str,
    max_bytes: int = _MAX_HTML_BYTES,
    allowed_hosts: frozenset[str] = ALLOWED_HOSTS,
) -> bytes:
    """GET ``url`` and return the body, capped at ``max_bytes``."""
    return _http_bytes(
        url,
        timeout=timeout,
        user_agent=user_agent,
        max_bytes=max_bytes,
        allowed_hosts=allowed_hosts,
        data=None,
        content_type=None,
    )


def http_get_text(
    url: str,
    *,
    timeout: float,
    user_agent: str,
    max_bytes: int = _MAX_HTML_BYTES,
) -> str:
    return http_get_bytes(
        url, timeout=timeout, user_agent=user_agent, max_bytes=max_bytes
    ).decode("utf-8", errors="replace")


def http_post_text(
    url: str,
    payload: dict[str, str],
    *,
    timeout: float,
    user_agent: str,
    max_bytes: int = _MAX_HTML_BYTES,
) -> str:
    body = urllib.parse.urlencode(payload).encode("utf-8")
    raw = _http_bytes(
        url,
        timeout=timeout,
        user_agent=user_agent,
        max_bytes=max_bytes,
        allowed_hosts=ALLOWED_HOSTS,
        data=body,
        content_type="application/x-www-form-urlencoded",
    )
    return raw.decode("utf-8", errors="replace")


def is_png(data: bytes, *, max_bytes: int = MAX_ICON_BYTES) -> bool:
    return bool(data) and data.startswith(PNG_MAGIC) and len(data) <= max_bytes


def is_jpeg(data: bytes, *, max_bytes: int = MAX_ICON_BYTES) -> bool:
    return bool(data) and data.startswith(JPEG_MAGIC) and len(data) <= max_bytes


def _flight_key(url: str, data: bytes | None) -> str:
    if data:
        return f"POST:{url}:{hash(data)}"
    return f"GET:{url}"


def _http_bytes(
    url: str,
    *,
    timeout: float,
    user_agent: str,
    max_bytes: int,
    allowed_hosts: frozenset[str],
    data: bytes | None,
    content_type: str | None,
) -> bytes:
    if not network_allowed():
        raise urllib.error.URLError("Network fetches disabled (EQGM_ALLOW_NETWORK=0).")
    if not _budget_ok():
        raise NetworkBudgetExceeded(
            f"EQ Resource hourly request budget exceeded ({hourly_budget()}/hour)."
        )

    key = _flight_key(url, data)
    leader = False
    event: threading.Event
    with _gate_lock:
        existing = _inflight.get(key)
        if existing is not None:
            event = existing
        else:
            event = threading.Event()
            _inflight[key] = event
            leader = True

    if not leader:
        event.wait(timeout=max(timeout + 5.0, 30.0))
        result = _inflight_result.get(key)
        if isinstance(result, BaseException):
            raise result
        if isinstance(result, (bytes, bytearray)):
            return bytes(result)
        raise urllib.error.URLError("Shared fetch failed.")

    try:
        _record_request()
        body = _http_bytes_uncached(
            url,
            timeout=timeout,
            user_agent=user_agent,
            max_bytes=max_bytes,
            allowed_hosts=allowed_hosts,
            data=data,
            content_type=content_type,
        )
        with _gate_lock:
            _inflight_result[key] = body
        return body
    except BaseException as exc:
        with _gate_lock:
            _inflight_result[key] = exc
        raise
    finally:
        with _gate_lock:
            _inflight.pop(key, None)
        event.set()
        # Drop cached result shortly after waiters wake
        def _clear() -> None:
            time.sleep(1.0)
            with _gate_lock:
                _inflight_result.pop(key, None)

        threading.Thread(target=_clear, daemon=True).start()


def _http_bytes_uncached(
    url: str,
    *,
    timeout: float,
    user_agent: str,
    max_bytes: int,
    allowed_hosts: frozenset[str],
    data: bytes | None,
    content_type: str | None,
) -> bytes:
    _require_allowed_url(url, allowed_hosts=allowed_hosts)
    headers = {"User-Agent": user_agent}
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=data, headers=headers)
    opener = urllib.request.build_opener(_AllowedHostRedirectHandler)
    with opener.open(req, timeout=timeout) as resp:
        final = resp.geturl()
        _require_allowed_url(final, allowed_hosts=allowed_hosts)
        raw = resp.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise urllib.error.URLError("Response too large.")
    return raw
