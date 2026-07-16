"""Per-visitor session cookie middleware for the demo backend.

Responsibilities:

- On every request, look for a ``winnow_session`` cookie. If present and
  the corresponding ``demo_sessions`` row is unexpired, refresh
  ``last_seen_at``. Otherwise mint a new session.
- Attach the session id to ``request.state.session_id`` so route
  handlers don't have to re-parse cookies.
- Set the cookie on the response.

IP hashing uses HMAC-SHA256 with a server-side salt from
``WINNOW_IP_HASH_SALT``. Plain SHA256 of an IPv4 address is trivially
reversible with a rainbow table; the salt makes stored hashes useless
outside this process.
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from winnow_api.config import Settings
from winnow_api.db.models import DemoSession

COOKIE_NAME = "winnow_session"
log = structlog.get_logger(__name__)


def hash_ip(ip: str, salt: str) -> str:
    """HMAC-SHA256(salt, ip) → hex."""
    return hmac.new(salt.encode("utf-8"), ip.encode("utf-8"), hashlib.sha256).hexdigest()


class DemoSessionMiddleware(BaseHTTPMiddleware):
    """Attach a demo session to every request, minting one if needed."""

    def __init__(self, app: ASGIApp, session_factory, settings: Settings) -> None:
        super().__init__(app)
        # session_factory is a zero-arg callable returning a Session — usually
        # ``lambda: Session(engine)``. Kept generic so tests can inject.
        self._session_factory = session_factory
        self._settings = settings

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        ip = _client_ip(request)
        ip_h = hash_ip(ip, self._settings.ip_hash_salt or "")

        raw_cookie = request.cookies.get(COOKIE_NAME)
        session_id, is_new = self._resolve_session(raw_cookie, ip_h)

        request.state.session_id = session_id
        request.state.session_is_new = is_new

        response = await call_next(request)

        # Refresh cookie on every response so its Max-Age slides forward.
        ttl_seconds = self._settings.demo_session_ttl_hours * 3600
        response.set_cookie(
            key=COOKIE_NAME,
            value=str(session_id),
            max_age=ttl_seconds,
            httponly=True,
            samesite="lax",
            secure=False,  # dev over http; production behind TLS proxy sets Secure=True
            path="/",
        )
        return response

    def _resolve_session(self, raw_cookie: str | None, ip_hash: str) -> tuple[uuid.UUID, bool]:
        """Return (session_id, is_new). Reuses an existing valid session or mints one."""
        now = datetime.now(timezone.utc)
        with self._session_factory() as db:  # type: Session
            if raw_cookie:
                try:
                    candidate = uuid.UUID(raw_cookie)
                except ValueError:
                    candidate = None
                if candidate is not None:
                    row = db.execute(
                        select(DemoSession).where(DemoSession.id == candidate)
                    ).scalar_one_or_none()
                    if row is not None and row.expires_at > now:
                        row.last_seen_at = now
                        db.commit()
                        return row.id, False

            expires = now + timedelta(hours=self._settings.demo_session_ttl_hours)
            new_row = DemoSession(ip_hash=ip_hash, expires_at=expires)
            db.add(new_row)
            db.commit()
            db.refresh(new_row)
            log.info("demo_session_created", session_id=str(new_row.id))
            return new_row.id, True


def _client_ip(request: Request) -> str:
    # X-Forwarded-For wins when behind a proxy (Fly.io). Fall back to the
    # peer address. Only the leftmost XFF hop matters for rate-limiting.
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "0.0.0.0"
