"""Phase I1.7.c.3 · Feb-2026 — Calendar provider abstract base class."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from .models import CalendarPullDelta, CalendarPushResult


class CalendarProvider(ABC):
    """Tenant-scoped Calendar provider contract."""

    provider_key: str = "abstract_calendar"
    #: Short name used in ``tenant_calendars_usage.provider`` + the
    #: ``/usage`` response — e.g. ``"google_calendar"``, ``"outlook"``.
    short_name: str = "abstract"

    #: Non-secret config the ``PUT /calendars_{provider}`` endpoint
    #: accepts (cap + optional per-tenant knobs). Secrets are held
    #: per-technician via services.secrets, keyed by
    #: ``calendars_{provider}:{technician_user_id}``.
    config_fields: Dict[str, Dict[str, Any]] = {}

    # ── OAuth ─────────────────────────────────────────────────────
    @abstractmethod
    def build_auth_url(
        self, *, state: str, extra_scopes: Optional[List[str]] = None,
    ) -> str:
        """Return the provider's authorize URL for the OAuth start."""

    @abstractmethod
    async def exchange_code(
        self, *, code: str,
    ) -> Dict[str, Any]:
        """Exchange the authorization ``code`` for tokens. Returns::

            {
              "access_token": str,
              "refresh_token": Optional[str],
              "expires_at":   iso datetime,
              "connected_email": Optional[str],
              "calendar_id":  Optional[str],
              "raw":          Dict[str, Any],
            }
        """

    # ── Two-way sync (polling MVP) ────────────────────────────────
    @abstractmethod
    async def push_event(
        self, *, tenant_id: str, technician_user_id: str,
        event: Dict[str, Any],
    ) -> CalendarPushResult:
        """Create/update a CRM job's calendar event."""

    @abstractmethod
    async def pull_delta(
        self, *, tenant_id: str, technician_user_id: str,
        sync_token: Optional[str] = None,
    ) -> CalendarPullDelta:
        """Fetch events changed since ``sync_token``. Returns a batch
        + a new ``next_sync_token`` for the following poll cycle."""
