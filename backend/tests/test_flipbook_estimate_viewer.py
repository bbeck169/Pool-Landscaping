"""Feb-2026 · Interactive Flipbook Estimate Viewer — backend contract.

Tests the three surfaces landed in Part 2:

    1. ``PUT /api/quotes/{qid}`` accepts + validates
       ``flipbook_enabled`` + ``flipbook_background_ids``.
    2. ``GET /api/quotes/{qid}/full`` (and the magic-link customer
       viewer) return the two fields on the payload.
    3. ``backfill_flipbook_defaults`` migration is idempotent + the
       ``POST /admin/migrations/backfill-flipbook-defaults`` admin
       endpoint runs it under the super_admin gate.

All e2e paths use ``httpx.ASGITransport`` with the standard stub-DB
pattern already used across ``test_status_gate_super_admin_silent_bypass``
so the router runs against real code without a Motor loop.
"""
from __future__ import annotations

from typing import Any, Dict, List

import httpx
import pytest
from httpx import ASGITransport
from fastapi import HTTPException


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


_TENANT = {"id": "t-flip", "slug": "flip", "timezone": "America/Phoenix"}


async def _tenant_dep():
    return _TENANT


def _super_user():
    return {"id": "u-super", "email": "super@ex.test",
             "role": "super_admin", "tenant_id": "t-flip"}


def _admin_user():
    return {"id": "u-admin", "email": "admin@ex.test",
             "role": "admin", "tenant_id": "t-flip"}


# ─── shared in-memory stubs ────────────────────────────────────────


class _StubCursor:
    def __init__(self, rows): self._rows = rows

    def sort(self, *_a, **_k): return self
    def skip(self, *_a, **_k): return self
    def limit(self, *_a, **_k): return self
    async def to_list(self, _n): return self._rows

    def __aiter__(self):
        self._i = 0; return self

    async def __anext__(self):
        if self._i >= len(self._rows):
            raise StopAsyncIteration
        v = self._rows[self._i]; self._i += 1
        return v


class _StubColl:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.updates: List[Dict[str, Any]] = []
        self.inserts: List[Dict[str, Any]] = []

    async def find_one(self, query, projection=None):
        for r in self.rows:
            if all(r.get(k) == v for k, v in query.items()
                    if not isinstance(v, dict)):
                # Emulate ``$exists`` for the backfill query.
                ok = True
                for k, v in query.items():
                    if isinstance(v, dict) and "$exists" in v:
                        present = k in r
                        ok = ok and (present == bool(v["$exists"]))
                if ok:
                    return dict(r)
        return None

    def find(self, query=None, projection=None):
        return _StubCursor([dict(r) for r in self.rows])

    def aggregate(self, pipeline):
        # Only the tiny group-by-tenant pipeline used by the dry-run
        # is exercised in these tests.
        match = {}
        for stage in pipeline:
            if "$match" in stage:
                match = stage["$match"] or {}
        rows = [r for r in self.rows if self._match(r, match)]
        by = {}
        for r in rows:
            by[r.get("tenant_id")] = by.get(r.get("tenant_id"), 0) + 1
        return _StubCursor([{"_id": k, "n": v} for k, v in by.items()])

    @staticmethod
    def _match(row, query):
        for k, v in (query or {}).items():
            if k == "$or":
                if not any(_StubColl._match(row, sub) for sub in v):
                    return False
                continue
            if isinstance(v, dict) and "$exists" in v:
                present = k in row
                if present != bool(v["$exists"]):
                    return False
            elif row.get(k) != v:
                return False
        return True

    async def update_one(self, query, update):
        for r in self.rows:
            if all(r.get(k) == v for k, v in query.items()
                    if not isinstance(v, dict)):
                if "$set" in update:
                    r.update(update["$set"])
                self.updates.append({"query": query, "update": update})
                return {"matched": 1}
        return {"matched": 0}

    async def update_many(self, query, update):
        matched = 0; modified = 0
        for r in self.rows:
            if self._match(r, query):
                matched += 1
                before = dict(r)
                if "$set" in update:
                    r.update(update["$set"])
                if r != before:
                    modified += 1
                self.updates.append({"query": query, "update": update})

        class _Res:
            def __init__(self, m, mo):
                self.matched_count = m; self.modified_count = mo

        return _Res(matched, modified)

    async def insert_one(self, doc): self.inserts.append(doc)

    async def count_documents(self, query, *_a, **_k):
        return sum(1 for r in self.rows if self._match(r, query))


class _StubDB:
    def __init__(self, *, quote, media_rows=None):
        self.quotes = _StubColl([quote])
        self.customers = _StubColl([{"id": "c1", "tenant_id": "t-flip",
                                       "name": "Test", "email": "c@x.y"}])
        self.audit_logs = _StubColl([])
        self.marketing_media = _StubColl(media_rows or [])
        self.items = _StubColl([])
        self.properties = _StubColl([])
        self.documents = _StubColl([])
        self.document_snapshots = _StubColl([])
        self.document_versions = _StubColl([])
        self.dunning_settings = _StubColl([])
        # Required by estimate_viewer / invoice_viewer helpers so the
        # payload builder can inflate tenant + service_category context
        # without reaching the real Motor connection (which lives on a
        # different event loop in this test harness).
        self.tenants = _StubColl([{"id": "t-flip",
                                     "name": "Flip Test Tenant",
                                     "timezone": "America/Phoenix",
                                     "support_email": "s@ex.test",
                                     "support_phone_number": "5551234567"}])
        self.service_categories = _StubColl([])
        self.files = _StubColl([])
        self.tenant_secrets = _StubColl([])


def _seed_estimate() -> Dict[str, Any]:
    return {
        "id": "est-e2e", "tenant_id": "t-flip",
        "doc_type": "quote",
        "customer_id": "c1", "customer_name": "Test",
        "status": "draft",
        "line_items": [{"id": "li-1", "description": "L", "quantity": 1,
                         "unit_price": 100, "retail_price_snapshot": 100}],
        "tax_rate": 0, "subtotal": 100, "tax": 0, "total": 100,
        "amount_paid": 0, "notes": "", "terms": "",
    }


def _seed_image(mid: str, mime="image/png", tid="t-flip") -> Dict[str, Any]:
    return {"id": mid, "tenant_id": tid, "mime_type": mime, "deleted_at": None}


def _seed_doc(mid: str) -> Dict[str, Any]:
    return {"id": mid, "tenant_id": "t-flip",
             "mime_type": "application/pdf", "deleted_at": None}


async def _client_for(*, user_fn, quote, media_rows=None):
    from server import app
    from utils import get_current_user, require_admin
    from routers.tenants import get_current_tenant
    from routers import quotes as _q

    stub = _StubDB(quote=quote, media_rows=media_rows or [])

    async def _u(): return user_fn()

    async def _admin_dep():
        u = user_fn()
        if u.get("role") not in ("admin", "super_admin", "manager"):
            raise HTTPException(403, "admin only")
        return u

    app.dependency_overrides[get_current_user] = _u
    app.dependency_overrides[require_admin] = _admin_dep
    app.dependency_overrides[get_current_tenant] = _tenant_dep

    return app, stub, _q


# ═══════════════════════════════════════════════════════════════════
# 1 · PUT /api/quotes/{qid} — happy path
# ═══════════════════════════════════════════════════════════════════


async def test_put_persists_flipbook_fields_on_draft_estimate():
    from unittest.mock import patch as _p
    media = [_seed_image("m-1"), _seed_image("m-2")]
    app, stub, qmod = await _client_for(
        user_fn=_admin_user, quote=_seed_estimate(), media_rows=media,
    )
    with _p.object(qmod, "db", stub):
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t"
        ) as ac:
            r = await ac.put(
                "/api/quotes/est-e2e",
                json={"flipbook_enabled": True,
                       "flipbook_background_ids": ["m-1", "m-2"]},
            )
    assert r.status_code == 200, r.text
    upd_set = stub.quotes.updates[0]["update"]["$set"]
    assert upd_set["flipbook_enabled"] is True
    assert upd_set["flipbook_background_ids"] == ["m-1", "m-2"]


async def test_put_normalises_whitespace_and_empty_entries():
    """Belt-and-braces — leading/trailing space + empty strings are
    stripped so downstream consumers never see junk IDs."""
    from unittest.mock import patch as _p
    media = [_seed_image("m-1"), _seed_image("m-2")]
    app, stub, qmod = await _client_for(
        user_fn=_admin_user, quote=_seed_estimate(), media_rows=media,
    )
    with _p.object(qmod, "db", stub):
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t"
        ) as ac:
            r = await ac.put(
                "/api/quotes/est-e2e",
                json={"flipbook_background_ids": [
                    " m-1 ", "", "  ", "m-2",
                ]},
            )
    assert r.status_code == 200, r.text
    upd_set = stub.quotes.updates[0]["update"]["$set"]
    assert upd_set["flipbook_background_ids"] == ["m-1", "m-2"]


# ═══════════════════════════════════════════════════════════════════
# 2 · PUT — validation failures
# ═══════════════════════════════════════════════════════════════════


async def test_put_rejects_non_image_background_id():
    from unittest.mock import patch as _p
    media = [_seed_image("m-1"), _seed_doc("d-1")]
    app, stub, qmod = await _client_for(
        user_fn=_admin_user, quote=_seed_estimate(), media_rows=media,
    )
    with _p.object(qmod, "db", stub):
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t"
        ) as ac:
            r = await ac.put(
                "/api/quotes/est-e2e",
                json={"flipbook_background_ids": ["m-1", "d-1"]},
            )
    assert r.status_code == 400, r.text
    body = r.json()
    assert body["detail"]["error"] == "background_must_be_image"
    assert body["detail"]["id"] == "d-1"
    # Doc must NOT have mutated on validation failure.
    assert stub.quotes.updates == []


async def test_put_rejects_more_than_10_backgrounds():
    from unittest.mock import patch as _p
    media = [_seed_image(f"m-{i}") for i in range(1, 12)]
    app, stub, qmod = await _client_for(
        user_fn=_admin_user, quote=_seed_estimate(), media_rows=media,
    )
    ids = [f"m-{i}" for i in range(1, 12)]  # 11 items
    with _p.object(qmod, "db", stub):
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t"
        ) as ac:
            r = await ac.put(
                "/api/quotes/est-e2e",
                json={"flipbook_background_ids": ids},
            )
    assert r.status_code == 400, r.text
    body = r.json()
    assert body["detail"]["error"] == "too_many_backgrounds"
    assert body["detail"]["max"] == 10
    assert body["detail"]["got"] == 11
    assert stub.quotes.updates == []


async def test_put_rejects_cross_tenant_background_id():
    """A media row from another tenant returns 404 ``file_not_found`` —
    tenant isolation must hold; we don't leak existence."""
    from unittest.mock import patch as _p
    media = [_seed_image("m-mine"),
              _seed_image("m-other", tid="t-other")]
    app, stub, qmod = await _client_for(
        user_fn=_admin_user, quote=_seed_estimate(), media_rows=media,
    )
    with _p.object(qmod, "db", stub):
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t"
        ) as ac:
            r = await ac.put(
                "/api/quotes/est-e2e",
                json={"flipbook_background_ids": ["m-mine", "m-other"]},
            )
    assert r.status_code == 404, r.text
    body = r.json()
    assert body["detail"]["error"] == "file_not_found"
    assert body["detail"]["id"] == "m-other"
    assert stub.quotes.updates == []


async def test_put_rejects_non_list_backgrounds():
    from unittest.mock import patch as _p
    app, stub, qmod = await _client_for(
        user_fn=_admin_user, quote=_seed_estimate(), media_rows=[],
    )
    with _p.object(qmod, "db", stub):
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t"
        ) as ac:
            # Pydantic will 422 on `List[str]` schema mismatch — we
            # send an explicit string and expect a schema failure
            # (either 422 or 400 depending on FastAPI's version).
            r = await ac.put(
                "/api/quotes/est-e2e",
                json={"flipbook_background_ids": "m-1"},
            )
    assert r.status_code in (400, 422), r.text
    assert stub.quotes.updates == []


# ═══════════════════════════════════════════════════════════════════
# 3 · Payload — GET /quotes/{qid}/full returns the new fields
# ═══════════════════════════════════════════════════════════════════


async def test_get_full_returns_flipbook_fields():
    """The customer-facing magic-link viewer and the auth'd admin
    surface both go through ``_build_payload``, so a single assert
    on ``/quotes/{qid}/full`` covers both surfaces."""
    from unittest.mock import patch as _p
    quote = _seed_estimate()
    quote["flipbook_enabled"] = True
    quote["flipbook_background_ids"] = ["m-1", "m-2"]
    app, stub, qmod = await _client_for(
        user_fn=_admin_user, quote=quote,
        media_rows=[_seed_image("m-1"), _seed_image("m-2")],
    )
    from routers import estimate_viewer as _ev
    from routers import invoice_viewer as _iv
    with _p.object(qmod, "db", stub), \
          _p.object(_ev, "db", stub), \
          _p.object(_iv, "db", stub):
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t"
        ) as ac:
            r = await ac.get("/api/quotes/est-e2e/full")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["flipbook_enabled"] is True
    assert body["flipbook_background_ids"] == ["m-1", "m-2"]
    # Feb-2026 follow-up · the payload MUST also carry the pre-signed
    # HMAC download URL for each background so anonymous customer
    # ``<img>`` tags can load the asset without an ``Authorization``
    # header (same trust model as the SMS attachment surface).
    #
    # Phase P1.2 · Feb 2026 — every signed URL now embeds an ``exp``
    # claim. We can't hard-compare the URLs (``exp`` is time-based)
    # so we parse each one and round-trip it through the verifier.
    from routers.marketing_media import _verify_media_sig
    from urllib.parse import urlparse, parse_qs
    urls = body["flipbook_background_urls"]
    assert len(urls) == 2
    for url, mid in zip(urls, ["m-1", "m-2"]):
        parsed = urlparse(url)
        assert parsed.path == f"/api/marketing/media/{mid}/download"
        q = parse_qs(parsed.query)
        assert "exp" in q and "sig" in q, (
            f"missing exp/sig on {url!r}"
        )
        assert "tid" not in q, (
            "P1.2 dropped ``tid=`` from the URL shape — carrying "
            "it would leak the tenant id on the wire"
        )
        exp_i = int(q["exp"][0])
        assert _verify_media_sig(
            "t-flip", mid, exp_i, q["sig"][0],
        ) is None


async def test_signed_url_matches_hmac_verifier():
    """Round-trip guard on the shared HMAC helper. If the signer or
    verifier drift, this test breaks the flipbook payload contract
    along with the SMS attachment path — surfacing the shared-helper
    regression before it ships.

    Phase P1.2 · Feb 2026 — verifier returns an error slug (or None
    on success) and both signer + verifier require an ``exp`` epoch
    baked into the HMAC input.
    """
    from routers.marketing_media import (
        _signed_download_url, _verify_media_sig,
    )
    from urllib.parse import urlparse, parse_qs
    url = _signed_download_url("t-flip", "m-99")
    parsed = urlparse(url)
    q = parse_qs(parsed.query)
    assert "tid" not in q      # P1.2 dropped tenant leak from URL
    assert "exp" in q and "sig" in q
    exp_i = int(q["exp"][0])
    sig = q["sig"][0]
    # Happy path — None means "OK".
    assert _verify_media_sig("t-flip", "m-99", exp_i, sig) is None
    # Cross-tenant guess → signature_invalid.
    assert _verify_media_sig("t-other", "m-99", exp_i, sig) == "signature_invalid"
    # Cross-mid guess → signature_invalid.
    assert _verify_media_sig("t-flip", "m-other", exp_i, sig) == "signature_invalid"
    # Tampered exp → signature_invalid.
    assert _verify_media_sig("t-flip", "m-99", exp_i + 60, sig) == "signature_invalid"
    # Missing sig → signature_missing.
    assert _verify_media_sig("t-flip", "m-99", exp_i, None) == "signature_missing"
    # Past exp → signature_expired (fake ``now`` well past exp).
    assert _verify_media_sig(
        "t-flip", "m-99", exp_i, sig, now_epoch=exp_i + 1,
    ) == "signature_expired"


async def test_get_full_returns_defaults_when_fields_missing():
    """Legacy estimates that never went through the backfill get
    safe defaults (``False`` / ``[]``) from the payload builder so
    the frontend never sees ``undefined``."""
    from unittest.mock import patch as _p
    app, stub, qmod = await _client_for(
        user_fn=_admin_user, quote=_seed_estimate(),  # no flipbook fields
    )
    from routers import estimate_viewer as _ev
    from routers import invoice_viewer as _iv
    with _p.object(qmod, "db", stub), \
          _p.object(_ev, "db", stub), \
          _p.object(_iv, "db", stub):
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t"
        ) as ac:
            r = await ac.get("/api/quotes/est-e2e/full")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["flipbook_enabled"] is False
    assert body["flipbook_background_ids"] == []
    # Empty ID list → empty URL list (no signing on empty input).
    assert body["flipbook_background_urls"] == []


# ═══════════════════════════════════════════════════════════════════
# 4 · Migration — dry-run + real-run + idempotent
# ═══════════════════════════════════════════════════════════════════


async def test_backfill_dry_run_counts_only():
    from migrations.backfill_flipbook_defaults import backfill_flipbook_defaults
    stub = _StubDB(quote=_seed_estimate())
    # Seed 3 legacy quotes (missing fields) + 1 already-migrated.
    stub.quotes.rows = [
        {"id": "q1", "tenant_id": "t-flip", "doc_type": "quote"},
        {"id": "q2", "tenant_id": "t-flip", "doc_type": "quote"},
        {"id": "q3", "tenant_id": "t-other", "doc_type": "quote"},
        {"id": "q4", "tenant_id": "t-flip", "doc_type": "quote",
          "flipbook_enabled": False, "flipbook_background_ids": []},
    ]
    r = await backfill_flipbook_defaults(stub, dry_run=True)
    assert r["dry_run"] is True
    assert r["matched"] == 3  # q4 already has both fields
    assert r["modified"] == 0
    assert r["tenants"] == {"t-flip": 2, "t-other": 1}
    # Docs must NOT have mutated.
    assert stub.quotes.rows[0].get("flipbook_enabled") is None


async def test_backfill_real_run_and_idempotent():
    from migrations.backfill_flipbook_defaults import backfill_flipbook_defaults
    stub = _StubDB(quote=_seed_estimate())
    stub.quotes.rows = [
        {"id": "q1", "tenant_id": "t-flip", "doc_type": "quote"},
        {"id": "q2", "tenant_id": "t-flip", "doc_type": "quote"},
    ]
    r = await backfill_flipbook_defaults(stub, dry_run=False)
    assert r["matched"] == 2
    assert r["modified"] == 2
    for row in stub.quotes.rows:
        assert row["flipbook_enabled"] is False
        assert row["flipbook_background_ids"] == []
    # Second run — nothing to migrate.
    r2 = await backfill_flipbook_defaults(stub, dry_run=False)
    assert r2["matched"] == 0
    assert r2["modified"] == 0


# ═══════════════════════════════════════════════════════════════════
# 5 · Admin trigger endpoint — super_admin only + dry_run default
# ═══════════════════════════════════════════════════════════════════


async def test_admin_backfill_endpoint_super_admin_only():
    from unittest.mock import patch as _p
    app, stub, qmod = await _client_for(
        user_fn=_admin_user, quote=_seed_estimate(),
    )
    from routers import admin_migrations as _am
    with _p.object(_am, "db", stub):
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t"
        ) as ac:
            r = await ac.post(
                "/api/admin/migrations/backfill-flipbook-defaults",
                json={"dry_run": True},
            )
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == "super_admin_only"


async def test_admin_backfill_endpoint_reports_matched_count():
    from unittest.mock import patch as _p
    app, stub, qmod = await _client_for(
        user_fn=_super_user, quote=_seed_estimate(),
    )
    stub.quotes.rows = [
        {"id": "q1", "tenant_id": "t-flip", "doc_type": "quote"},
    ]
    from routers import admin_migrations as _am
    with _p.object(_am, "db", stub):
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t"
        ) as ac:
            # Dry-run first — no mutations.
            r = await ac.post(
                "/api/admin/migrations/backfill-flipbook-defaults",
                json={"dry_run": True},
            )
            assert r.status_code == 200, r.text
            assert r.json()["matched"] == 1
            assert r.json()["modified"] == 0
            # Real run.
            r = await ac.post(
                "/api/admin/migrations/backfill-flipbook-defaults",
                json={"dry_run": False},
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["matched"] == 1
            assert body["modified"] == 1
