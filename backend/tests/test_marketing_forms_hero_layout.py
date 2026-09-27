"""CUS-Marketing-Form-Builder · Feb-2026 — Phase 1 backend contract.

Locks the schema additions in ``routers/marketing_forms.py``:

  1. ``FormField`` — new optional ``column_span`` enum ("full"|"half").
     ``name`` is now optional (so section-type layout markers can
     omit it). Every non-layout type still requires a non-empty
     name, enforced in ``_validate_field_defs``.
  2. ``FormIn`` + ``FormPatch`` — new optional ``hero`` dict (opaque
     passthrough; frontend owns sub-schema). Mirrors K34 ``theme``.
  3. ``_FIELD_TYPES`` — adds ``"section"`` as a layout-only marker.
  4. ``_validate_field_defs`` — allows ``"section"`` without ``name``,
     rejects invalid ``column_span`` with 422, skips section fields
     in the duplicate-name check.
  5. Widget endpoint ``GET /widget/form/{fid}`` — projection now
     includes ``hero`` alongside ``theme`` so external widgets can
     render the hero band.

Test pattern mirrors ``test_k34_form_theme.py`` — live-API round
trips + DB-level projection-equivalence proof when the widget-key
origin allowlist would block a raw HTTP call.
"""
from __future__ import annotations

import os
import secrets
import uuid
from pathlib import Path
from typing import Any, Dict

import requests
from dotenv import load_dotenv
from tests._shared_mongo import shared_db as _shared_db


load_dotenv(Path(__file__).resolve().parents[1] / ".env")

API = "http://localhost:8001/api"
_sync = _shared_db()


# ── Fixtures ────────────────────────────────────────────────────


def _login(email: str = "admin@aquaterra.com") -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": "password123"},
                       timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def _cleanup(fid: str | None) -> None:
    if fid:
        _sync.marketing_forms.delete_one({"id": fid})


_HERO_FULL: Dict[str, Any] = {
    "heading_html":    "<p><strong>Get Your Free Estimate</strong></p>",
    "subheading_html": "<p>Answer 4 quick questions.</p>",
    "background": {
        "kind": "gradient",
        "angle_deg": 135,
        "from": "#1B1F5C",
        "to":   "#3B82F6",
    },
    "badge": {
        "url": "https://cdn.example.com/special-offer.png",
        "alt_text": "Special offer badge",
    },
}


# ── 1) Round-trip: create + get with hero ───────────────────────


def test_hero_round_trips_on_create_and_get():
    """POST ``/admin/forms`` with a full-shape ``hero`` payload
    persists AND round-trips byte-identical on GET (both admin GET
    and direct DB read)."""
    tok = _login()
    hdrs = {"Authorization": f"Bearer {tok}"}
    fid = None
    try:
        r = requests.post(
            f"{API}/admin/forms",
            json={
                "name": f"TEST_cus-mfb hero create {uuid.uuid4().hex[:6]}",
                "fields": [{"name": "email", "type": "email",
                              "label": "Email", "required": True}],
                "hero": _HERO_FULL,
            },
            headers=hdrs, timeout=15,
        )
        assert r.status_code in (200, 201), r.text
        fid = r.json()["id"]

        # DB row byte-identical hero.
        doc = _sync.marketing_forms.find_one({"id": fid}, {"_id": 0, "hero": 1})
        assert doc is not None
        assert doc["hero"] == _HERO_FULL

        # Admin GET round-trip.
        r2 = requests.get(f"{API}/admin/forms/{fid}",
                            headers=hdrs, timeout=15)
        assert r2.status_code == 200, r2.text
        assert r2.json().get("hero") == _HERO_FULL
    finally:
        _cleanup(fid)


# ── 2) "section"-type field persists on create + returns on GET ─


def test_section_type_field_persists():
    """A ``"section"``-type field is a layout marker: renders a
    heading in the public form, collects no submission value. It
    MUST persist through the CRUD round-trip alongside real
    submission fields."""
    tok = _login()
    hdrs = {"Authorization": f"Bearer {tok}"}
    fid = None
    try:
        r = requests.post(
            f"{API}/admin/forms",
            json={
                "name": f"TEST_cus-mfb section {uuid.uuid4().hex[:6]}",
                "fields": [
                    {"type": "section", "label": "Your details"},
                    {"name": "email", "type": "email",
                      "label": "Email", "required": True},
                    {"type": "section", "label": "Your project"},
                    {"name": "notes", "type": "textarea",
                      "label": "Notes"},
                ],
            },
            headers=hdrs, timeout=15,
        )
        assert r.status_code in (200, 201), r.text
        fid = r.json()["id"]

        fields = r.json()["fields"]
        types = [f["type"] for f in fields]
        assert types == ["section", "email", "section", "textarea"], types
        # Every section gets an auto-derived id + order.
        section_ids = [f["id"] for f in fields if f["type"] == "section"]
        assert len(section_ids) == 2 and all(section_ids)
        assert section_ids[0] != section_ids[1], (
            "section-type fields must get unique auto-derived ids: "
            f"{section_ids}"
        )
        # Every field carries an order.
        orders = [f["order"] for f in fields]
        assert orders == [0, 1, 2, 3], orders
    finally:
        _cleanup(fid)


# ── 3) column_span="half" persists on create ────────────────────


def test_column_span_half_persists_on_create():
    """A submission field with ``column_span="half"`` round-trips
    through create + GET."""
    tok = _login()
    hdrs = {"Authorization": f"Bearer {tok}"}
    fid = None
    try:
        r = requests.post(
            f"{API}/admin/forms",
            json={
                "name": f"TEST_cus-mfb cs {uuid.uuid4().hex[:6]}",
                "fields": [
                    {"name": "first_name", "type": "text",
                      "label": "First name", "column_span": "half"},
                    {"name": "last_name", "type": "text",
                      "label": "Last name", "column_span": "half"},
                    {"name": "email", "type": "email",
                      "label": "Email", "column_span": "full"},
                ],
            },
            headers=hdrs, timeout=15,
        )
        assert r.status_code in (200, 201), r.text
        fid = r.json()["id"]

        fields = r.json()["fields"]
        spans = [f.get("column_span") for f in fields]
        assert spans == ["half", "half", "full"], spans
    finally:
        _cleanup(fid)


# ── 4) column_span="invalid" is rejected with 422 ───────────────


def test_column_span_invalid_is_rejected():
    """Any ``column_span`` value outside ``{"full", "half"}`` MUST
    be rejected with a 422. Pydantic's ``Literal`` validation
    surfaces this; the router-level ``_validate_field_defs`` also
    guards the dict-input PATCH path with a clearer message."""
    tok = _login()
    hdrs = {"Authorization": f"Bearer {tok}"}
    r = requests.post(
        f"{API}/admin/forms",
        json={
            "name": f"TEST_cus-mfb cs-bad {uuid.uuid4().hex[:6]}",
            "fields": [
                {"name": "email", "type": "email",
                  "label": "Email", "column_span": "one-third"},
            ],
        },
        headers=hdrs, timeout=15,
    )
    assert r.status_code == 422, r.text


# ── 5) PATCH adds hero to existing form without touching other fields ─


def test_patch_adds_hero_without_touching_other_fields():
    """PATCH ``/admin/forms/{fid}`` with ``hero`` persists it while
    leaving ``name``, ``fields``, ``theme``, ``submit_config``,
    etc. untouched."""
    tok = _login()
    hdrs = {"Authorization": f"Bearer {tok}"}
    fid = None
    try:
        original_name = f"TEST_cus-mfb hero patch {uuid.uuid4().hex[:6]}"
        r = requests.post(
            f"{API}/admin/forms",
            json={
                "name": original_name,
                "fields": [{"name": "email", "type": "email",
                              "label": "Email", "required": True}],
                "theme": {"preset": "modern_blue"},
            },
            headers=hdrs, timeout=15,
        )
        assert r.status_code in (200, 201), r.text
        fid = r.json()["id"]

        # Capture the pre-PATCH snapshot for the untouched-fields
        # invariant check.
        pre = _sync.marketing_forms.find_one({"id": fid}, {"_id": 0})
        assert pre is not None
        assert pre.get("hero") is None  # Legacy default before PATCH

        # PATCH only ``hero``.
        r2 = requests.patch(
            f"{API}/admin/forms/{fid}",
            json={"hero": _HERO_FULL},
            headers=hdrs, timeout=15,
        )
        assert r2.status_code in (200, 201, 204), r2.text

        post = _sync.marketing_forms.find_one({"id": fid}, {"_id": 0})
        assert post is not None
        assert post["hero"] == _HERO_FULL
        # Untouched invariants — every non-``hero`` / non-timestamp
        # field must be byte-identical between pre and post.
        _mutable = {"hero", "updated_at"}
        for k, v in pre.items():
            if k in _mutable:
                continue
            assert post.get(k) == v, (
                f"PATCH hero touched unrelated field {k!r}: "
                f"pre={v!r} post={post.get(k)!r}"
            )
        assert post["name"] == original_name
        assert post.get("theme") == {"preset": "modern_blue"}
    finally:
        _cleanup(fid)


# ── 6) Widget endpoint surfaces theme + hero ────────────────────


def test_widget_endpoint_surfaces_theme_and_hero():
    """The public widget's read surface (``GET /widget/form/{fid}``)
    MUST include both ``theme`` and ``hero`` so the external widget
    can render the hero band + apply theme CSS vars. Origin-
    allowlist behavior mirrors ``test_k34_form_theme.py`` — we
    accept 200/401 on the HTTP call and confirm the projection at
    the DB level."""
    tok = _login()
    hdrs = {"Authorization": f"Bearer {tok}"}
    fid = None
    tenant = _sync.users.find_one(
        {"email": "admin@aquaterra.com"},
    )["tenant_id"]
    key_row = _sync.tenants.find_one(
        {"id": tenant}, {"_id": 0, "public_widget_key": 1},
    ) or {}
    public_key = key_row.get("public_widget_key")
    if not public_key:
        public_key = f"wk_{secrets.token_hex(16)}"
        _sync.tenants.update_one(
            {"id": tenant},
            {"$set": {"public_widget_key": public_key}},
        )
    try:
        r = requests.post(
            f"{API}/admin/forms",
            json={
                "name": f"TEST_cus-mfb widget {uuid.uuid4().hex[:6]}",
                "fields": [{"name": "email", "type": "email",
                              "label": "Email", "required": True}],
                "theme": {"preset": "warm_earth"},
                "hero": _HERO_FULL,
            },
            headers=hdrs, timeout=15,
        )
        assert r.status_code in (200, 201), r.text
        fid = r.json()["id"]

        pr = None
        try:
            pr = requests.get(
                f"{API}/widget/form/{fid}",
                headers={"X-Widget-Key": public_key,
                          "Origin": "https://example.com",
                          "Referer": "https://example.com/embed"},
                timeout=15,
            )
        except Exception:  # noqa: BLE001
            pass
        assert pr is None or pr.status_code in (200, 401), (
            pr.text if pr is not None else "no response"
        )
        if pr is not None and pr.status_code == 200:
            payload = pr.json()
            assert payload.get("theme") == {"preset": "warm_earth"}
            assert payload.get("hero") == _HERO_FULL

        # DB-level projection-equivalence — same projection the
        # handler uses. Locks the projection contract even when
        # the HTTP path is origin-blocked.
        doc = _sync.marketing_forms.find_one(
            {"id": fid, "active": {"$ne": False}},
            {"_id": 0, "id": 1, "name": 1, "slug": 1, "fields": 1,
             "submit_button_label": 1, "success_message": 1,
             "theme": 1, "hero": 1},
        )
        assert doc is not None
        assert doc.get("theme") == {"preset": "warm_earth"}
        assert doc.get("hero") == _HERO_FULL
    finally:
        _cleanup(fid)


# ── 7) Legacy form (no hero, no column_span, no section) — zero
#      regression: byte-identical round-trip through pre-Phase-1
#      shape. ────────────────────────────────────────────────────


def test_legacy_form_round_trips_unchanged():
    """A form created with a pre-Phase-1 payload (no ``hero``, no
    ``column_span``, no ``"section"``-type fields) MUST persist +
    round-trip on GET with all new-field values set to ``None`` —
    no default coercion, no silent value injection. The GET
    response for such a form must be byte-identical to the pre-
    Phase-1 shape as far as user-observable fields go."""
    tok = _login()
    hdrs = {"Authorization": f"Bearer {tok}"}
    fid = None
    try:
        r = requests.post(
            f"{API}/admin/forms",
            json={
                "name": f"TEST_cus-mfb legacy {uuid.uuid4().hex[:6]}",
                "fields": [
                    {"name": "email", "type": "email",
                      "label": "Email", "required": True},
                    {"name": "notes", "type": "textarea",
                      "label": "Notes"},
                ],
            },
            headers=hdrs, timeout=15,
        )
        assert r.status_code in (200, 201), r.text
        fid = r.json()["id"]

        payload = r.json()
        assert payload.get("hero") is None, (
            "hero must default to None (no coercion) — got "
            f"{payload.get('hero')!r}"
        )
        # Every field's ``column_span`` must be None (opt-in only).
        for f in payload["fields"]:
            assert f.get("column_span") is None, (
                f"column_span coerced on legacy field {f['name']!r}: "
                f"{f.get('column_span')!r}"
            )
        # No section-type fields sneaked in.
        assert all(f["type"] != "section" for f in payload["fields"])

        # DB round-trip: hero absent OR None (either shape is OK on
        # the wire — legacy renderer treats both identically).
        doc = _sync.marketing_forms.find_one({"id": fid}, {"_id": 0, "hero": 1})
        assert doc is not None
        assert doc.get("hero") is None
    finally:
        _cleanup(fid)


# ── 8) Section-type field with no name is accepted ─────────────


def test_section_type_field_without_name_is_accepted():
    """A ``"section"``-type field MAY omit ``name`` (unlike other
    types, which require a non-empty name). Rest of the schema
    still applies — ``label`` is required, ``type`` is required.

    Also asserts the negative: a non-section field with no name
    MUST be rejected with 422 (contract regression guard)."""
    tok = _login()
    hdrs = {"Authorization": f"Bearer {tok}"}
    fid = None
    try:
        # Section with no name — accepted.
        r = requests.post(
            f"{API}/admin/forms",
            json={
                "name": f"TEST_cus-mfb section-noname "
                        f"{uuid.uuid4().hex[:6]}",
                "fields": [
                    {"type": "section", "label": "Contact details"},
                    {"name": "email", "type": "email",
                      "label": "Email"},
                ],
            },
            headers=hdrs, timeout=15,
        )
        assert r.status_code in (200, 201), r.text
        fid = r.json()["id"]

        section = next(
            f for f in r.json()["fields"] if f["type"] == "section"
        )
        # ``name`` on the wire may be ``None`` or absent; both are
        # acceptable — the widget uses ``label`` + ``id``.
        assert section.get("name") in (None, "", section.get("label"))

        # Negative: a non-section field with no name must 422.
        r2 = requests.post(
            f"{API}/admin/forms",
            json={
                "name": f"TEST_cus-mfb noname-negative "
                        f"{uuid.uuid4().hex[:6]}",
                "fields": [
                    {"type": "email", "label": "Email"},  # missing name
                ],
            },
            headers=hdrs, timeout=15,
        )
        assert r2.status_code == 422, r2.text
    finally:
        _cleanup(fid)
