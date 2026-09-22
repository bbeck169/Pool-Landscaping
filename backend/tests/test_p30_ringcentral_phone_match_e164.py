"""Phase P30 · Feb-2026 — RingCentral E.164 phone-match parity.

Locks in that ``_to_e164`` + ``_match_customer_by_phone`` normalize
BOTH sides of the comparison — an inbound RingCentral SMS carrying
``+14805550102`` matches a seeded customer whose ``phone`` was
stored as ``(480) 555-0102``, ``480-555-0102``, or even
``+1 (480) 555-0102`` (with leading whitespace).

Prior to P30 the router normalized only the incoming side and
relied on a permissive regex over the stored side. That worked for
most shapes but dropped matches when the stored value contained
whitespace inside the E.164 form (regex anchor got confused).
Introducing the canonical ``_to_e164`` helper (P30 spec name) and
applying it symmetrically eliminates the surface.

Runs on the F7 loop-bound Mongo so the router hits the same
``db.customers`` collection the webhook uses in production.
"""
from __future__ import annotations

import uuid

import pytest

from tests._f7_loop_fixture import run_test


# ═════════════════════════════════════════════════════════════════════
# _to_e164 — the canonical P30 helper name.
# ═════════════════════════════════════════════════════════════════════
class TestToE164:
    def test_bare_10_digit_us_becomes_plus_1(self):
        from routers.ringcentral import _to_e164
        assert _to_e164("4805550102") == "+14805550102"

    def test_dashed_us_number(self):
        from routers.ringcentral import _to_e164
        assert _to_e164("480-555-0102") == "+14805550102"

    def test_parens_us_number(self):
        from routers.ringcentral import _to_e164
        assert _to_e164("(480) 555-0102") == "+14805550102"

    def test_leading_1_11_digit_form(self):
        from routers.ringcentral import _to_e164
        assert _to_e164("14805550102") == "+14805550102"
        assert _to_e164("1-480-555-0102") == "+14805550102"

    def test_already_e164(self):
        from routers.ringcentral import _to_e164
        assert _to_e164("+14805550102") == "+14805550102"

    def test_e164_with_stray_whitespace_and_parens(self):
        """Regression — stored `+1 (480) 555-0102` MUST normalize to
        `+14805550102`. Prior digit-regex approach failed on the
        leading `+` inside the anchored end-of-string pattern."""
        from routers.ringcentral import _to_e164
        assert _to_e164("+1 (480) 555-0102") == "+14805550102"

    def test_foreign_e164_preserved(self):
        from routers.ringcentral import _to_e164
        # UK: 44 20 7946 0958 (Ofcom docs example).
        assert _to_e164("+442079460958") == "+442079460958"

    def test_empty_and_none_return_none(self):
        from routers.ringcentral import _to_e164
        assert _to_e164(None) is None
        assert _to_e164("") is None
        assert _to_e164("   ") is None

    def test_short_junk_returns_none(self):
        from routers.ringcentral import _to_e164
        # 6 digits — too short to be a US number, no `+` prefix.
        assert _to_e164("555102") is None

    def test_alias_of_normalize_phone_e164(self):
        """The two names MUST resolve to the same behaviour so
        existing callers keep working."""
        from routers.ringcentral import _to_e164, _normalize_phone_e164
        for sample in ("4805550102", "+14805550102", "480-555-0102"):
            assert _to_e164(sample) == _normalize_phone_e164(sample)


# ═════════════════════════════════════════════════════════════════════
# _match_customer_by_phone — end-to-end matching against Mongo.
# ═════════════════════════════════════════════════════════════════════
def _seed_customer(db, *, tenant_id, cid, phone_field=None,
                     phones_field=None, name="Match Test"):
    doc = {
        "id": cid, "tenant_id": tenant_id, "name": name,
    }
    if phone_field is not None:
        doc["phone"] = phone_field
    if phones_field is not None:
        doc["phones"] = phones_field
    return doc


def test_p30_inbound_plus_1_matches_dashed_stored():
    """Stored `480-555-0102`, incoming `+14805550102` → match."""
    from routers.ringcentral import _match_customer_by_phone

    async def _go(db):
        tid = f"t-p30-{uuid.uuid4().hex[:6]}"
        cid = f"c-{uuid.uuid4().hex[:8]}"
        await db.customers.insert_one(_seed_customer(
            db, tenant_id=tid, cid=cid,
            phone_field="480-555-0102",
        ))
        try:
            match = await _match_customer_by_phone(tid, "+14805550102")
            assert match is not None
            assert match["id"] == cid
        finally:
            await db.customers.delete_one({"id": cid})

    run_test(_go)


def test_p30_inbound_plus_1_matches_parens_stored():
    """Stored `(480) 555-0102`, incoming `+14805550102` → match."""
    from routers.ringcentral import _match_customer_by_phone

    async def _go(db):
        tid = f"t-p30-{uuid.uuid4().hex[:6]}"
        cid = f"c-{uuid.uuid4().hex[:8]}"
        await db.customers.insert_one(_seed_customer(
            db, tenant_id=tid, cid=cid,
            phone_field="(480) 555-0102",
        ))
        try:
            match = await _match_customer_by_phone(tid, "+14805550102")
            assert match is not None
            assert match["id"] == cid
        finally:
            await db.customers.delete_one({"id": cid})

    run_test(_go)


def test_p30_inbound_dashed_matches_stored_e164():
    """Reverse — stored `+14805550102`, incoming `480-555-0102`.
    Bidirectional normalization is the whole point of `_to_e164`."""
    from routers.ringcentral import _match_customer_by_phone

    async def _go(db):
        tid = f"t-p30-{uuid.uuid4().hex[:6]}"
        cid = f"c-{uuid.uuid4().hex[:8]}"
        await db.customers.insert_one(_seed_customer(
            db, tenant_id=tid, cid=cid,
            phone_field="+14805550102",
        ))
        try:
            match = await _match_customer_by_phone(tid, "480-555-0102")
            assert match is not None
            assert match["id"] == cid
        finally:
            await db.customers.delete_one({"id": cid})

    run_test(_go)


def test_p30_match_on_phones_array_field():
    """Customer with `phones: ["+14805550102", "6025557890"]` —
    incoming `+14805550102` matches on the ARRAY side."""
    from routers.ringcentral import _match_customer_by_phone

    async def _go(db):
        tid = f"t-p30-{uuid.uuid4().hex[:6]}"
        cid = f"c-{uuid.uuid4().hex[:8]}"
        await db.customers.insert_one(_seed_customer(
            db, tenant_id=tid, cid=cid,
            phones_field=["+14805550102", "6025557890"],
        ))
        try:
            match = await _match_customer_by_phone(tid, "+14805550102")
            assert match is not None
            assert match["id"] == cid
        finally:
            await db.customers.delete_one({"id": cid})

    run_test(_go)


def test_p30_mismatched_number_returns_none():
    """Sanity — a truly foreign number MUST NOT match."""
    from routers.ringcentral import _match_customer_by_phone

    async def _go(db):
        tid = f"t-p30-{uuid.uuid4().hex[:6]}"
        cid = f"c-{uuid.uuid4().hex[:8]}"
        await db.customers.insert_one(_seed_customer(
            db, tenant_id=tid, cid=cid,
            phone_field="+14805550102",
        ))
        try:
            # Different area code + last-7 → no possible collision.
            match = await _match_customer_by_phone(tid, "+16025559999")
            assert match is None
        finally:
            await db.customers.delete_one({"id": cid})

    run_test(_go)


def test_p30_empty_phone_returns_none():
    from routers.ringcentral import _match_customer_by_phone

    async def _go(db):
        match = await _match_customer_by_phone("t-any", "")
        assert match is None

    run_test(_go)


def test_p30_tenant_scoping_prevents_cross_tenant_match():
    """A number belonging to tenant A MUST NOT match when the query
    scopes to tenant B — even if the digits are identical."""
    from routers.ringcentral import _match_customer_by_phone

    async def _go(db):
        tid_a = f"t-p30a-{uuid.uuid4().hex[:6]}"
        tid_b = f"t-p30b-{uuid.uuid4().hex[:6]}"
        cid = f"c-{uuid.uuid4().hex[:8]}"
        await db.customers.insert_one(_seed_customer(
            db, tenant_id=tid_a, cid=cid,
            phone_field="+14805550102",
        ))
        try:
            match_wrong = await _match_customer_by_phone(
                tid_b, "+14805550102",
            )
            assert match_wrong is None
            match_right = await _match_customer_by_phone(
                tid_a, "+14805550102",
            )
            assert match_right is not None
            assert match_right["id"] == cid
        finally:
            await db.customers.delete_one({"id": cid})

    run_test(_go)


def test_p30_tenant_none_permits_cross_tenant_match():
    """When the webhook can't derive a tenant (unknown-sender path)
    we call with ``tenant_id=None``. Every customer in the DB is
    then a candidate — this preserves the pre-P30 behaviour used
    by the anonymous inbound-SMS flow."""
    from routers.ringcentral import _match_customer_by_phone

    async def _go(db):
        tid = f"t-p30-{uuid.uuid4().hex[:6]}"
        cid = f"c-{uuid.uuid4().hex[:8]}"
        await db.customers.insert_one(_seed_customer(
            db, tenant_id=tid, cid=cid,
            phone_field="480-555-0102",
        ))
        try:
            match = await _match_customer_by_phone(
                None, "+14805550102",
            )
            # We can't assert `match["id"] == cid` here because the
            # global DB may contain other customers with the same
            # last-10 digits from other test rows — but SOMETHING
            # should come back rather than None.
            assert match is not None
        finally:
            await db.customers.delete_one({"id": cid})

    run_test(_go)
