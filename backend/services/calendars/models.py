"""Phase I1.7.c.3 · Feb-2026 — Shared Calendar-BYO models."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ── Domain objects ───────────────────────────────────────────────
class CalendarEvent(BaseModel):
    """Normalised calendar event returned by every provider."""
    provider_event_id: str
    title: str = ""
    start_iso: str            # RFC3339 datetime
    end_iso: str
    tz: str = "UTC"
    all_day: bool = False
    description: str = ""
    location: str = ""
    attendees: List[str] = Field(default_factory=list)
    source: str = "provider"  # "provider" | "crm"
    raw: Dict[str, Any] = Field(default_factory=dict)


class CalendarPushResult(BaseModel):
    """Return-shape from ``push_event`` — CRM job → Calendar."""
    provider_event_id: str
    html_link: Optional[str] = None
    provider_key: str
    provider_used: str        # "tenant:google_calendar" | "tenant:outlook" | "mock:google_calendar" ...
    technician_user_id: str
    tenant_id: str
    raw: Dict[str, Any] = Field(default_factory=dict)


class CalendarPullDelta(BaseModel):
    """Return-shape from ``pull_delta`` — provider → CRM availability."""
    events: List[CalendarEvent] = Field(default_factory=list)
    next_sync_token: Optional[str] = None
    provider_key: str
    provider_used: str
    technician_user_id: str
    tenant_id: str
    raw: Dict[str, Any] = Field(default_factory=dict)


# ── Per-technician OAuth link ────────────────────────────────────
class TechnicianCalendarLink(BaseModel):
    """Full row shape (internal use — access/refresh tokens go through
    ``services.secrets`` so this model never crosses the wire)."""
    id: str
    tenant_id: str
    technician_user_id: str
    provider_key: str
    provider: str                       # short-name: "google_calendar" | "outlook"
    connected_email: Optional[str] = None
    calendar_id: Optional[str] = None
    sync_token: Optional[str] = None    # Google syncToken / Graph deltaLink
    expires_at: Optional[str] = None    # access token expiry (iso)
    created_at: str
    updated_at: str


class TechnicianCalendarLinkSummary(BaseModel):
    """Safe-to-serve summary — NEVER includes tokens."""
    technician_user_id: str
    technician_name: Optional[str] = None
    technician_email: Optional[str] = None
    provider_key: str                       # "calendars_google" | "calendars_outlook"
    provider: str                           # "google_calendar" | "outlook"
    connected: bool
    connected_email: Optional[str] = None
    calendar_id: Optional[str] = None
    last_synced_at: Optional[str] = None
    updated_at: Optional[str] = None


# ── Usage snapshot returned by /calendars/usage ──────────────────
class CalendarProviderUsage(BaseModel):
    provider: str                       # "google_calendar" | "outlook"
    period_yyyymm: str
    push_event: int = 0
    pull_delta: int = 0
    total: int = 0
    monthly_sync_op_cap: Optional[int] = None   # None = unlimited
    connected_technicians: int = 0
    pct_used: Optional[float] = None
    status: str = "ok"                          # "ok" | "warn" | "blocked"


class CalendarUsageResponse(BaseModel):
    tenant_id: str
    period_yyyymm: str
    providers: List[CalendarProviderUsage]


# ── Errors ───────────────────────────────────────────────────────
class CalendarError(Exception):
    pass


class TenantCalendarsNotConnected(CalendarError):
    """No technician OAuth link for this tenant + provider."""


class UnknownCalendarProvider(CalendarError):
    """Provider key not registered."""


class InvalidCalendarProviderConfig(CalendarError):
    """Missing / blank required config field at save-time."""


class TenantCalendarsSyncOpCapExceeded(CalendarError):
    """Tenant's monthly sync-op cap has been reached — surfaced as
    HTTP 429 with NO platform fallback."""

    def __init__(self, provider: str, cap: int, used: int) -> None:
        super().__init__(
            f"tenant Calendars sync-op cap reached for provider={provider}: "
            f"used={used}/{cap} ops this month"
        )
        self.provider = provider
        self.cap = cap
        self.used = used


# ── Operation enum-ish ───────────────────────────────────────────
OPERATIONS = ("push_event", "pull_delta")
