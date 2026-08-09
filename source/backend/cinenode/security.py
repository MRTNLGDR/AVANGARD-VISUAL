from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, status

from .config import AppConfig

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._()\- ]+")


def sanitize_filename(name: str, fallback: str = "file") -> str:
    clean = Path(name).name.replace("\x00", "")
    clean = _SAFE_NAME_RE.sub("_", clean).strip(" .")
    if not clean:
        clean = fallback
    return clean[:180]


def ensure_within(base: Path, candidate: Path) -> Path:
    base_resolved = base.resolve()
    candidate_resolved = candidate.resolve()
    try:
        candidate_resolved.relative_to(base_resolved)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Path escapes the allowed application directory",
        ) from exc
    return candidate_resolved


def require_local_request(request: Request, config: AppConfig) -> None:
    client_host = (request.client.host if request.client else "").lower()
    request_host = (request.url.hostname or "").lower()
    local_clients = {"127.0.0.1", "::1", "localhost", "testclient"}
    local_hosts = {"127.0.0.1", "::1", "localhost", "testserver"}

    # Reject DNS rebinding even when the TCP peer itself is loopback.
    if request_host not in local_hosts:
        raise HTTPException(status_code=403, detail="Loopback Host header required")
    proxied_loopback = config.allow_loopback_proxy and request_host in local_hosts
    if client_host not in local_clients and not proxied_loopback:
        raise HTTPException(status_code=403, detail="Local access only")

    # A browser opened from another origin must not be able to mutate the local app.
    if request.headers.get("Sec-Fetch-Site", "").lower() == "cross-site":
        raise HTTPException(status_code=403, detail="Cross-site request denied")
    origin = request.headers.get("Origin")
    if origin and origin.lower() != "null":
        parsed = urlsplit(origin)
        origin_host = (parsed.hostname or "").lower()
        default_port = 443 if parsed.scheme == "https" else 80
        origin_port = parsed.port or default_port
        request_port = request.url.port or (443 if request.url.scheme == "https" else 80)
        if origin_host != request_host or origin_port != request_port or parsed.scheme != request.url.scheme:
            raise HTTPException(status_code=403, detail="Cross-origin request denied")

    configured = request.headers.get("X-CineNode-Token")
    # Same-origin browser requests are accepted. Explicit tokens, when supplied,
    # must match; this prevents a stale or accidental token from being ignored.
    if configured is not None and configured != config.local_access_token:
        raise HTTPException(status_code=401, detail="Invalid local access token")
