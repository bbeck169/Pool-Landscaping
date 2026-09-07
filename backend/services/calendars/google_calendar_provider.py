"""Phase I1.7.c.3 · Feb-2026 — Google Calendar BYO provider.

MVP scope: OAuth end-to-end, plus push_event/pull_delta that
short-circuit on ``CALENDARS_TESTMODE_MOCK=true``. Real Google API
calls are stubbed with clearly-marked TODOs — the router + persistence
+ cap layers are the P0 deliverable for this phase.
"""
from __future__ import annotations

import urllib.parse
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from ._helpers import calendars_testmode_mock, google_oauth_env, now_iso
from .models import (
    CalendarEvent,
    CalendarPullDelta,
    CalendarPushResult,
    InvalidCalendarProviderConfig,
    TenantCalendarsNotConnected,
)
from .tenant_base import CalendarProvider


_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
_DEFAULT_SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/userinfo.email",
]


class GoogleCalendarProvider(CalendarProvider):
    provider_key = "calendars_google"
    short_name = "google"

    #: Non-secret per-tenant config (cap + optional default calendar).
    config_fields: Dict[str, Dict[str, Any]] = {
        "monthly_sync_op_cap": {"required": False, "secret": False,
                                  "type": "int_or_null",
                                  "label": "Monthly sync-op cap (null=unlimited, 0=block-all)"},
        "default_calendar_id": {"required": False, "secret": False,
                                  "label": "Default calendar ID (leave blank for 'primary')"},
    }

    def build_auth_url(
        self, *, state: str, extra_scopes: Optional[List[str]] = None,
    ) -> str:
        env = google_oauth_env()
        if not env["client_id"] or not env["redirect_uri"]:
            # In test-mode we still hand back a URL so the router can
            # 302 to it — the callback flow is fully mocked.
            if not calendars_testmode_mock():
                raise InvalidCalendarProviderConfig(
                    "GOOGLE_CALENDAR_CLIENT_ID + GOOGLE_CALENDAR_REDIRECT_URI must be set"
                )
        scopes = list(_DEFAULT_SCOPES) + list(extra_scopes or [])
        params = {
            "client_id":       env["client_id"] or "MOCK_GOOGLE_CLIENT_ID",
            "redirect_uri":    env["redirect_uri"] or "http://mock/callback",
            "response_type":   "code",
            "scope":           " ".join(scopes),
            "access_type":     "offline",
            "include_granted_scopes": "true",
            "prompt":          "consent",
            "state":           state,
        }
        return f"{_AUTH_ENDPOINT}?{urllib.parse.urlencode(params)}"

    async def exchange_code(self, *, code: str) -> Dict[str, Any]:
        if calendars_testmode_mock():
            # Deterministic mock — deliberately does NOT hit the network.
            return {
                "access_token":  f"mock_google_at_{uuid.uuid4().hex[:12]}",
                "refresh_token": f"mock_google_rt_{uuid.uuid4().hex[:12]}",
                "expires_at":    (datetime.now(timezone.utc)
                                    + timedelta(seconds=3599)).isoformat(),
                "connected_email": "tech-mock@google.example",
                "calendar_id":     "primary",
                "raw": {"mock": True, "code_echo": code[:8]},
            }
        # Real path — imported lazily so the pytest boot never needs
        # httpx credentials.
        env = google_oauth_env()
        if not env["client_id"] or not env["client_secret"] or not env["redirect_uri"]:
            raise InvalidCalendarProviderConfig(
                "Google Calendar OAuth env vars missing"
            )
        import httpx
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(_TOKEN_ENDPOINT, data={
                "code":          code,
                "client_id":     env["client_id"],
                "client_secret": env["client_secret"],
                "redirect_uri":  env["redirect_uri"],
                "grant_type":    "authorization_code",
            })
            j = r.json() if r.content else {}
        return {
            "access_token":  j.get("access_token") or "",
            "refresh_token": j.get("refresh_token"),
            "expires_at":    (datetime.now(timezone.utc)
                                + timedelta(seconds=int(j.get("expires_in") or 0))).isoformat(),
            "connected_email": None,
            "calendar_id":     "primary",
            "raw": j,
        }

    async def push_event(
        self, *, tenant_id: str, technician_user_id: str,
        event: Dict[str, Any],
    ) -> CalendarPushResult:
        if calendars_testmode_mock():
            eid = f"mock_gcal_evt_{uuid.uuid4().hex[:12]}"
            return CalendarPushResult(
                provider_event_id=eid,
                html_link=f"https://calendar.google.com/mock/{eid}",
                provider_key=self.provider_key,
                provider_used=f"mock:{self.short_name}",
                technician_user_id=technician_user_id,
                tenant_id=tenant_id,
                raw={"mock": True, "at": now_iso(), "in": event},
            )
        # TODO(I1.7.e): Real Google Calendar API call using stored token.
        # Kept as a placeholder — the OAuth + persistence layers ship
        # in this phase; live-mode wiring is scheduled for I1.7.e.
        raise TenantCalendarsNotConnected(
            f"Google Calendar live-mode push not wired yet (I1.7.e).",
        )

    async def pull_delta(
        self, *, tenant_id: str, technician_user_id: str,
        sync_token: Optional[str] = None,
    ) -> CalendarPullDelta:
        if calendars_testmode_mock():
            demo_start = (datetime.now(timezone.utc) + timedelta(days=1)
                          ).replace(microsecond=0)
            demo_end = demo_start + timedelta(hours=1)
            events = [CalendarEvent(
                provider_event_id=f"mock_gcal_pull_{uuid.uuid4().hex[:8]}",
                title="Mocked availability block",
                start_iso=demo_start.isoformat(),
                end_iso=demo_end.isoformat(),
                tz="UTC",
                source="provider",
                raw={"mock": True},
            )] if not sync_token else []
            return CalendarPullDelta(
                events=events,
                next_sync_token=f"mock_gcal_synctoken_{uuid.uuid4().hex[:8]}",
                provider_key=self.provider_key,
                provider_used=f"mock:{self.short_name}",
                technician_user_id=technician_user_id,
                tenant_id=tenant_id,
                raw={"mock": True, "in_sync_token": sync_token},
            )
        # TODO(I1.7.e): Real Google Calendar events.list with syncToken.
        raise TenantCalendarsNotConnected(
            "Google Calendar live-mode pull not wired yet (I1.7.e).",
        )
