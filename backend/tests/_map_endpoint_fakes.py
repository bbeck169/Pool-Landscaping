"""Feb-2026 · Widget-Embed extension · shared fakes for the map
endpoint tests.

The map endpoints in ``routers/public_checkins_map.py`` import a
few helpers from ``routers/public_widget.py`` (``_client_ip``,
``_rate_ok``, ``_tenant_by_slug``, ``_cors``). We reuse those
without mocking — the rate-limit helpers use an in-memory bucket
that we reset between tests.

Leading underscore keeps pytest from treating this as a test file.
"""
from __future__ import annotations

from tests._notif_pipeline_fakes import _Coll, _DB, _matches  # noqa: F401


def make_map_db(*, tenants=None, checkins=None):
    """Build an in-memory DB stub carrying only the collections
    the map endpoints touch (``tenants`` + ``public_checkins``)."""
    fake = _DB(tenants=tenants)
    fake.public_checkins = _Coll(checkins)
    return fake
