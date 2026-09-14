"""HTTPS fetches limited to EQ Resource and raidloot hosts."""

from __future__ import annotations

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
