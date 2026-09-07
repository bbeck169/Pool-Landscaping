"""services.calendars — Tenant Calendar BYO adapter registry (Phase I1.7.c.3).

Skips Apple/CalDAV/iCloud — Google Calendar + Outlook only.
Two-way sync is polling-only for MVP (webhooks scheduled as follow-up).

Env vars driving OAuth::

    GOOGLE_CALENDAR_CLIENT_ID
    GOOGLE_CALENDAR_CLIENT_SECRET
    GOOGLE_CALENDAR_REDIRECT_URI   # e.g. https://<host>/api/tenants/me/integrations/calendars_google/oauth/callback

    OUTLOOK_CLIENT_ID
    OUTLOOK_CLIENT_SECRET
    OUTLOOK_REDIRECT_URI

    CALENDARS_TESTMODE_MOCK=true    # short-circuits every provider

State-token env::

    SECRETS_MASTER_KEY   # reused as the HMAC key for OAuth state signing.
"""
from .dispatcher import (  # noqa: F401
    dispatch_calendars_push_event,
    dispatch_calendars_pull_delta,
    TenantCalendarsSyncOpCapExceeded,
)
from .models import (  # noqa: F401
    CalendarEvent,
    CalendarPushResult,
    CalendarPullDelta,
    CalendarProviderUsage,
    CalendarUsageResponse,
    TechnicianCalendarLink,
    TechnicianCalendarLinkSummary,
    CalendarError,
    InvalidCalendarProviderConfig,
    TenantCalendarsNotConnected,
    UnknownCalendarProvider,
    OPERATIONS,
)
from .oauth_state import (  # noqa: F401
    build_state_token,
    verify_state_token,
    OAuthStateError,
    OAuthStateExpired,
    OAuthStateReplayed,
    OAuthStateTampered,
)
from .registry import (  # noqa: F401
    get_calendar_provider,
    list_registered_calendar_provider_keys,
    list_short_names,
    short_name_for,
    reset_cache_for_tests,
    get_provider_field_schemas,
)
