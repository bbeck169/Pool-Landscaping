"""Phase 17 · Feb-2026 — QBO REST wrapper + entity fetchers.

Read-only. Every helper uses ``qbo_get`` which auto-refreshes the token
on 401 (once) and adds the ``minorversion`` param Intuit expects.

The module exposes a swap point for tests: ``set_transport`` replaces
the underlying ``httpx.AsyncClient`` factory so pytest can inject an
``httpx.MockTransport`` without patching module internals.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Awaitable, Callable, Dict, List, Optional

import httpx

from config import db
from services.qbo import oauth as qbo_oauth

logger = logging.getLogger("qbo.client")

_client_factory: Callable[[], httpx.AsyncClient] = lambda: httpx.AsyncClient(timeout=30)


def set_transport(transport: Optional[httpx.MockTransport]) -> None:
    """Testing hook — swap the httpx transport used by all QBO REST calls."""
    global _client_factory
    if transport is None:
        _client_factory = lambda: httpx.AsyncClient(timeout=30)
    else:
        _client_factory = lambda: httpx.AsyncClient(timeout=30, transport=transport)


def _base_for_conn(conn: Dict[str, Any]) -> str:
    env = (conn.get("environment") or "sandbox").lower()
    host = (
        "sandbox-quickbooks.api.intuit.com" if env == "sandbox"
        else "quickbooks.api.intuit.com"
    )
    return f"https://{host}/v3/company/{conn['qbo_realm_id']}"


async def qbo_get(
    qbo_connection_id: str, path: str,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """GET ``{base}/{path}`` with the connection's access token. Auto-refresh
    on 401 once. Raises ``QboHttpError`` on any non-2xx after retry.
    """
    conn = await db.qbo_connections.find_one(
        {"qbo_connection_id": qbo_connection_id, "status": "active"}, {"_id": 0}
    )
    if not conn:
        raise QboHttpError(400, "connection_not_active_or_missing")
    token = await qbo_oauth.get_active_access_token(qbo_connection_id)
    if not token:
        raise QboHttpError(401, "reauth_required")

    minor = (os.environ.get("QBO_API_MINOR_VERSION") or "65").strip()
    url = f"{_base_for_conn(conn)}/{path.lstrip('/')}"
    p = {"minorversion": minor, **(params or {})}

    async def _do(token_: str) -> httpx.Response:
        async with _client_factory() as client:
            return await client.get(
                url,
                params=p,
                headers={
                    "Authorization": f"Bearer {token_}",
                    "Accept": "application/json",
                },
            )

    r = await _do(token)
    if r.status_code == 401:
        rr = await qbo_oauth.refresh_access_token(qbo_connection_id)
        if not rr.get("ok"):
            raise QboHttpError(401, "reauth_required")
        r = await _do(rr["access_token"])
    if r.status_code >= 400:
        raise QboHttpError(r.status_code, r.text[:400])
    try:
        return r.json()
    except Exception:
        return {}


class QboHttpError(Exception):
    def __init__(self, status: int, body: str):
        super().__init__(f"qbo {status}: {body}")
        self.status = status
        self.body = body


# ── Entity fetchers (read-only, paginated via startPosition) ─────────
_ENTITY_QUERY = {
    "customers": "Customer",
    "vendors": "Vendor",
    "invoices": "Invoice",
    "payments": "Payment",
    "accounts": "Account",
    "journal_entries": "JournalEntry",
    "bills": "Bill",
}


async def fetch_entity_page(
    qbo_connection_id: str,
    entity: str,
    *, start_position: int = 1, max_results: int = 1000,
    changed_since: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return one page of QBO records for an entity, optionally filtered
    by ``changed_since`` (ISO-8601) via QBO's SQL-ish query language.

    The Intuit ``/query`` endpoint uses SQL-like ``SELECT * FROM Entity
    WHERE Metadata.LastUpdatedTime > 'ts'`` syntax.
    """
    if entity not in _ENTITY_QUERY:
        raise ValueError(f"unknown_entity:{entity}")
    q_name = _ENTITY_QUERY[entity]

    where = ""
    if changed_since:
        # Escape the ISO string minimally — no single quotes possible.
        safe = changed_since.replace("'", "")
        where = f" WHERE Metadata.LastUpdatedTime > '{safe}'"

    query = (
        f"SELECT * FROM {q_name}{where} "
        f"STARTPOSITION {start_position} MAXRESULTS {max_results}"
    )
    payload = await qbo_get(qbo_connection_id, "query", {"query": query})
    root = (payload or {}).get("QueryResponse") or {}
    return root.get(q_name) or []
