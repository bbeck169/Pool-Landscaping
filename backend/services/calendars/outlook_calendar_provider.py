"""Phase I1.7.c.3 · Feb-2026 — Microsoft Outlook Calendar BYO provider.

Uses Microsoft Graph OAuth. Same MVP shape as
``GoogleCalendarProvider`` — OAuth end-to-end and mocked sync ops.
"""
from __future__ import annotations

import urllib.parse
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from ._helpers import calendars_testmode_mock, now_iso, outlook_oauth_env
from .models import (
    CalendarEvent,
    CalendarPullDelta,
    CalendarPushResult,
    InvalidCalendarProviderConfig,
    TenantCalendarsNotConnected,
)
from .tenant_base import CalendarProvider


_AUTH_ENDPOINT = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
_TOKEN_ENDPOINT = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
_DEFAULT_SCOPES = [
    "offline_access",
    "Calendars.ReadWrite",
    "User.Read",
]


class OutlookCalendarProvider(CalendarProvider):
    provider_key = "calendars_outlook"
    short_name = "outlook"

    config_fields: Dict[str, Dict[str, Any]] = {
        "monthly_sync_op_cap": {"required": False, "secret": False,
                                  "type": "int_or_null",
                                  "label": "Monthly sync-op cap (null=unlimited, 0=block-all)"},
        "default_calendar_id": {"required": False, "secret": False,
                                  "label": "Default calendar ID (leave blank for user's primary)"},
    }

    def build_auth_url(
        self, *, state: str, extra_scopes: Optional[List[str]] = None,
    ) -> str:
        env = outlook_oauth_env()
        if not env["client_id"] or not env["redirect_uri"]:
            if not calendars_testmode_mock():
                raise InvalidCalendarProviderConfig(
                    "OUTLOOK_CLIENT_ID + OUTLOOK_REDIRECT_URI must be set"
                )
        scopes = list(_DEFAULT_SCOPES) + list(extra_scopes or [])
        params = {
            "client_id":     env["client_id"] or "MOCK_OUTLOOK_CLIENT_ID",
            "redirect_uri":  env["redirect_uri"] or "http://mock/callback",
            "response_type": "code",
            "response_mode": "query",
            "scope":         " ".join(scopes),
            "state":         state,
        }
        return f"{_AUTH_ENDPOINT}?{urllib.parse.urlencode(params)}"

    async def exchange_code(self, *, code: str) -> Dict[str, Any]:
        if calendars_testmode_mock():
            return {
                "access_token":  f"mock_outlook_at_{uuid.uuid4().hex[:12]}",
                "refresh_token": f"mock_outlook_rt_{uuid.uuid4().hex[:12]}",
                "expires_at":    (datetime.now(timezone.utc)
                                    + timedelta(seconds=3599)).isoformat(),
                "connected_email": "tech-mock@outlook.example",
                "calendar_id":     "primary",
                "raw": {"mock": True, "code_echo": code[:8]},
            }
        env = outlook_oauth_env()
        if not env["client_id"] or not env["client_secret"] or not env["redirect_uri"]:
            raise InvalidCalendarProviderConfig(
                "Outlook OAuth env vars missing"
            )
        import httpx
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(_TOKEN_ENDPOINT, data={
                "code":          code,
                "client_id":     env["client_id"],
                "client_secret": env["client_secret"],
                "redirect_uri":  env["redirect_uri"],
                "grant_type":    "authorization_code",
                "scope":         " ".join(_DEFAULT_SCOPES),
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
            eid = f"mock_outlook_evt_{uuid.uuid4().hex[:12]}"
            return CalendarPushResult(
                provider_event_id=eid,
                html_link=f"https://outlook.office.com/calendar/mock/{eid}",
                provider_key=self.provider_key,
                provider_used=f"mock:{self.short_name}",
                technician_user_id=technician_user_id,
                tenant_id=tenant_id,
                raw={"mock": True, "at": now_iso(), "in": event},
            )
        raise TenantCalendarsNotConnected(
            "Outlook live-mode push not wired yet (I1.7.e).",
        )

    async def pull_delta(
        self, *, tenant_id: str, technician_user_id: str,
        sync_token: Optional[str] = None,
    ) -> CalendarPullDelta:
        if calendars_testmode_mock():
            demo_start = (datetime.now(timezone.utc) + timedelta(days=2)
                          ).replace(microsecond=0)
            demo_end = demo_start + timedelta(hours=1)
            events = [CalendarEvent(
                provider_event_id=f"mock_outlook_pull_{uuid.uuid4().hex[:8]}",
                title="Mocked Outlook availability block",
                start_iso=demo_start.isoformat(),
                end_iso=demo_end.isoformat(),
                tz="UTC",
                source="provider",
                raw={"mock": True},
            )] if not sync_token else []
            return CalendarPullDelta(
                events=events,
                next_sync_token=f"mock_outlook_deltalink_{uuid.uuid4().hex[:8]}",
                provider_key=self.provider_key,
                provider_used=f"mock:{self.short_name}",
                technician_user_id=technician_user_id,
                tenant_id=tenant_id,
                raw={"mock": True, "in_sync_token": sync_token},
            )
        raise TenantCalendarsNotConnected(
            "Outlook live-mode pull not wired yet (I1.7.e).",
        )
