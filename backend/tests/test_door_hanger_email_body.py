"""Feb-2026 · P0 Door hanger email — body composition tests.

Pre-fix the door hanger email body was:

    We stopped by, Brian Beckman.
    Your service was completed on 2026-07-26.
    Notes: —
    (nothing else)

…for every real tech submission, because the composer only read
``job.notes`` / ``job.service_notes`` and never joined
``service_reports`` for the chemistry / chemicals / checklist / photos.

Post-fix the composer uses the same
``services/service_report_view.*`` resolvers the Workstream Service
Log page uses.  These tests exercise the composer end-to-end (via
``TestClient`` on the FastAPI app) with the Resend adapter stubbed
so no live email is sent.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any, Dict

import pytest


_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def _run(coro):
    return _LOOP.run_until_complete(coro)


@pytest.fixture(scope="module", autouse=True)
def _bind_db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    fresh = AsyncIOMotorClient(os.environ["MONGO_URL"], io_loop=_LOOP)
    fresh_db = fresh[os.environ["DB_NAME"]]
    import config as _cfg
    _cfg.db = fresh_db
    import routers.workstream_service_log as _mod
    _mod.db = fresh_db
    yield


def _db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    return AsyncIOMotorClient(
        os.environ["MONGO_URL"], io_loop=_LOOP,
    )[os.environ["DB_NAME"]]


async def _tenant_id() -> str:
    u = await _db().users.find_one(
        {"email": "admin@aquaterra.com"}, {"_id": 0, "tenant_id": 1},
    )
    return u["tenant_id"]


async def _mk_customer(tenant_id: str) -> str:
    from utils import new_id, now_iso
    cid = f"test-cust-{uuid.uuid4().hex[:12]}"
    await _db().customers.insert_one({
        "id": cid, "tenant_id": tenant_id,
        "name": "Kaylan Testcase",
        "first_name": "Kaylan", "last_name": "Testcase",
        "email": "kaylan.testcase@example.com",
        "phone": "+15555550100",
    })
    return cid


async def _mk_property(tenant_id: str, cid: str) -> str:
    pid = f"test-prop-{uuid.uuid4().hex[:12]}"
    await _db().properties.insert_one({
        "id": pid, "tenant_id": tenant_id, "customer_id": cid,
        "label": "Home", "address": {
            "line1": "12 Vistancia Blvd",
            "city": "Peoria", "state": "AZ", "zip": "85383",
        },
    })
    return pid


async def _mk_pool_job(
    tenant_id: str, cid: str, seed_fields: Dict[str, Any] | None = None,
) -> str:
    from utils import new_id, now_iso
    jid = f"test-job-{uuid.uuid4().hex[:12]}"
    doc = {
        "id": jid, "tenant_id": tenant_id, "customer_id": cid,
        "customer_name": "Kaylan Testcase",
        "service_type": "Weekly Pool Service",
        "status": "completed", "completed_at": now_iso(),
        "scheduled_date": now_iso(),
        "title": "Weekly Pool", "created_at": now_iso(),
    }
    if seed_fields:
        doc.update(seed_fields)
    await _db().jobs.insert_one(doc)
    return jid


async def _drain(tenant_id: str, jid: str, cid: str) -> None:
    for coll in ("jobs", "service_reports", "customers", "properties", "marketing_deliveries"):
        try:
            await _db()[coll].delete_many(
                {"tenant_id": tenant_id,
                 "$or": [{"id": jid}, {"id": cid}, {"job_id": jid},
                         {"customer_id": cid},
                         {"trigger_entity.id": jid}]},
            )
        except Exception:
            pass


def _stub_email_send(monkeypatch) -> Dict[str, Any]:
    """Replace ``services.email.resend_adapter.send`` with a stub that
    records the call args and returns a mock envelope.  Returns the
    dict the test can inspect to see what was sent."""
    from services.email import resend_adapter as _resend
    captured: Dict[str, Any] = {}

    async def _fake_send(**kwargs):
        captured.update(kwargs)
        return {"provider": "mock", "provider_status": "queued",
                "provider_response_id": None, "attempts": 1, "error": None}

    monkeypatch.setattr(_resend, "send", _fake_send, raising=True)
    return captured


async def _call_email_door_hanger(jid: str, tenant_id: str) -> Dict[str, Any]:
    from routers.workstream_service_log import email_door_hanger
    user = await _db().users.find_one(
        {"email": "admin@aquaterra.com"}, {"_id": 0},
    )
    tenant = await _db().tenants.find_one({"id": tenant_id}, {"_id": 0})
    return await email_door_hanger(jid, user=user, tenant=tenant)


# ═════════════════════════════════════════════════════════════════════
# 1. Full submission — every section renders in the body.
# ═════════════════════════════════════════════════════════════════════
def test_door_hanger_full_body_contains_every_section(monkeypatch):
    async def _go():
        tid = await _tenant_id()
        cid = await _mk_customer(tid)
        pid = await _mk_property(tid, cid)
        jid = await _mk_pool_job(tid, cid, seed_fields={
            "property_id": pid,
            "title": "Weekly Pool Cleaning",
            "photos": [{
                "id": "test-photo-a", "data": "data:image/png;base64,iVBORw==",
                "label": "before", "created_at": "2026-02-20T00:00:00+00:00",
            }],
        })
        # Simulate a tech PATCH → the service_report doc.
        from utils import new_id, now_iso
        await _db().service_reports.insert_one({
            "id": f"test-rep-{uuid.uuid4().hex[:8]}",
            "tenant_id": tid, "job_id": jid, "tech_id": "test-tech",
            "chemical_readings": [
                {"key": "free_chlorine",  "value": 2.5, "unit": "ppm"},
                {"key": "total_chlorine", "value": 3.0, "unit": "ppm"},
                {"key": "ph",             "value": 7.4},
                {"key": "alkalinity",     "value": 80,  "unit": "ppm"},
                {"key": "cyanuric_acid",  "value": 40,  "unit": "ppm"},
            ],
            "chemicals_added": [{"name": "Liquid Chlorine", "quantity": 1.0, "unit": "gallon"}],
            "checklist_items": [
                {"key": "skimmed_pool",     "label": "Skimmed Pool",     "checked": True},
                {"key": "brush_pool",       "label": "Brush Pool",       "checked": True},
                {"key": "tested_chemicals", "label": "Tested Chemicals", "checked": True},
            ],
            "notes": "Pump strainer basket was full. Emptied + rinsed.",
            "submitted_at": now_iso(),
        })

        captured = _stub_email_send(monkeypatch)
        try:
            r = await _call_email_door_hanger(jid, tid)
            assert r.get("ok") is True, r
            subj = captured.get("subject") or ""
            body = captured.get("html") or ""
            # ── Feb-2026 door-hanger copy + design update assertions ──
            # Subject line.
            assert subj.startswith("Job Completed - "), subj
            assert "Service door hanger" not in subj
            # Greeting — first name only, never last name anywhere in body.
            assert "Hi Kaylan, your visit has been completed." in body, body[:400]
            assert "Testcase" not in body, "customer last name leaked into door-hanger body"
            # Feb-2026 typography tweak — greeting now renders at the
            # SAME font-size as the job-title line (matches product
            # spec confirmed after live-inbox review).  The old
            # ``<h2>`` was too visually loud in most email clients.
            import re as _re
            _greeting_re = _re.search(
                r'<p\s+style="([^"]+)"[^>]*>\s*Hi Kaylan, your visit has been completed\.\s*</p>',
                body,
            )
            assert _greeting_re, "greeting must render as a <p> with an inline style"
            _greeting_style = _greeting_re.group(1)
            _title_re = _re.search(
                r'<p\s+style="([^"]+)"[^>]*>\s*<b>Weekly Pool Cleaning</b>\s*</p>',
                body,
            )
            assert _title_re, "job title <p><b> line must be present"
            _title_style = _title_re.group(1)
            _greeting_size = _re.search(r'font-size:\s*(\d+px)', _greeting_style)
            _title_size = _re.search(r'font-size:\s*(\d+px)', _title_style)
            assert _greeting_size and _title_size, (
                _greeting_style, _title_style,
            )
            assert _greeting_size.group(1) == _title_size.group(1), (
                f"greeting size {_greeting_size.group(1)} must match "
                f"job-title size {_title_size.group(1)}"
            )
            # Greeting MUST NOT render bold (it's a greeting, not a heading).
            assert "<h2" not in body.lower() or "your visit has been completed" not in body.lower().split("<h2", 1)[-1][:200], "greeting must not use <h2>"
            assert "<b>Hi Kaylan" not in body
            assert "<strong>Hi Kaylan" not in body
            # Explicit font-weight override on the greeting is normal/light.
            assert "font-weight:normal" in _greeting_style or "font-weight: normal" in _greeting_style
            # Service Date line stays SMALLER + muted (Fix must not touch it).
            assert 'font-size:14px;color:#555' in body
            # Job title + service address rendered below greeting (both bolded).
            assert "<b>Weekly Pool Cleaning</b>" in body
            assert "12 Vistancia Blvd" in body
            assert "Peoria" in body and "AZ" in body and "85383" in body
            # Logo — centered <img> before greeting.
            assert 'src="https://' in body and "/logo-full.png" in body
            assert 'text-align:center' in body
            # New footer copy — "We appreciate your business" + tenant phone;
            # the old "reply to this email" / "make it right" line MUST be gone.
            assert "We appreciate your business" in body
            assert "602-887-4400" in body or "reply to this email" not in body
            assert "make it right" not in body
            # Chemistry — Feb-2026 hotfix: customer-facing views now
            # render qualitative BANDS in place of raw ppm/pH numbers.
            # free_chlorine=2.5 → Average; total_chlorine=3.0 → Average;
            # ph=7.4 → Average; alkalinity=80 → Average; cyanuric_acid=40 → Average.
            # Every value in this test payload sits in the Average band.
            # Rendered as a two-cell table row: <td>{label}</td><td><b>{band}</b></td>.
            _wt_start = body.index("Water Test</h3>")
            _wt_end   = body.index("</table>", _wt_start)
            _wt = body[_wt_start:_wt_end]
            for _label in ("Free Cl", "Total Cl", "pH", "Alkalinity", "CYA"):
                assert f">{_label}</td>" in _wt, (
                    f"missing display label {_label!r} in Water Test section"
                )
                assert "<b>Average</b>" in _wt
            # RAW numeric readings must NOT appear in the Water Test
            # section — scope the substring check so numeric values
            # that legitimately appear elsewhere (photo URLs, cost)
            # can't false-positive.
            for _val in ("2.5", "3.0", "7.4", "40 ppm", "40.0 ppm", " 80 "):
                assert _val not in _wt, (
                    f"raw reading {_val!r} leaked into Water Test section"
                )
            # Chemicals used.
            assert "Liquid Chlorine" in body
            assert "$8.00" in body, body[:600]
            # Checklist — checked items rendered.
            assert "Skimmed Pool" in body
            assert "Brush Pool" in body
            assert "Tested Chemicals" in body
            # Notes.
            assert "Pump strainer basket was full" in body
            # Photos — inline absolute URL.
            assert "test-photo-a" in body
            assert "http" in body  # absolute URL prefix
            assert "/api/public/job-photo/" in body
        finally:
            await _drain(tid, jid, cid)

    _run(_go())


# ═════════════════════════════════════════════════════════════════════
# 2. Legacy fallback — data on the job doc still renders.
# ═════════════════════════════════════════════════════════════════════
def test_door_hanger_legacy_readings_on_job_doc_still_render(monkeypatch):
    async def _go():
        tid = await _tenant_id()
        cid = await _mk_customer(tid)
        jid = await _mk_pool_job(tid, cid, seed_fields={
            "chemical_readings": {
                "free_chlorine": 1.8, "total_chlorine": 2.4,
                "ph": 7.5, "alkalinity": 90, "cyanuric_acid": 45,
            },
            "chemicals_added": [
                {"name": "Muriatic Acid", "quantity": 0.5, "unit": "gallon"},
            ],
            "notes": "Legacy path — inline job.notes.",
        })
        captured = _stub_email_send(monkeypatch)
        try:
            r = await _call_email_door_hanger(jid, tid)
            assert r["ok"] is True
            body = captured.get("html") or ""
            assert "CYA" in body
            # Feb-2026 hotfix — raw CYA value MUST NOT leak into the
            # customer-facing email; only the band renders.
            _wt = body[body.index("Water Test</h3>"):body.index("</table>", body.index("Water Test</h3>"))]
            assert "45" not in _wt, "raw CYA value leaked into Water Test"
            assert "<b>Average</b>" in _wt   # 45 falls in 30-80 → Average
            assert "Muriatic Acid" in body
            assert "Legacy path" in body
        finally:
            await _drain(tid, jid, cid)

    _run(_go())


# ═════════════════════════════════════════════════════════════════════
# 3. Absolute photo URLs — no leading-slash-only paths.
# ═════════════════════════════════════════════════════════════════════
def test_door_hanger_photo_urls_are_absolute(monkeypatch):
    async def _go():
        tid = await _tenant_id()
        cid = await _mk_customer(tid)
        jid = await _mk_pool_job(tid, cid, seed_fields={
            "photos": [
                {"id": "abs-1", "data": "data:image/png;base64,iVBORw==",
                 "label": "front", "created_at": "2026-02-20T00:00:00+00:00"},
            ],
        })
        # Ensure a base URL is present.  Preview .env has APP_BASE_URL
        # blank so the resolver falls back to the hard-coded prod URL.
        monkeypatch.setenv("PUBLIC_APP_BASE_URL", "https://app.plofv.com")
        captured = _stub_email_send(monkeypatch)
        try:
            await _call_email_door_hanger(jid, tid)
            body = captured.get("html") or ""
            # Assert the src attribute is absolute — the composer must
            # NOT emit ``src="/api/public/job-photo/…"`` (some email
            # clients treat leading slashes as broken links).
            assert 'src="https://app.plofv.com/api/public/job-photo/' in body, body[:800]
        finally:
            await _drain(tid, jid, cid)

    _run(_go())


# ═════════════════════════════════════════════════════════════════════
# 4. No service report at all — email still renders (no crash).
# ═════════════════════════════════════════════════════════════════════
def test_door_hanger_empty_report_renders_gracefully(monkeypatch):
    async def _go():
        tid = await _tenant_id()
        cid = await _mk_customer(tid)
        jid = await _mk_pool_job(tid, cid)  # no report, no readings, no photos
        captured = _stub_email_send(monkeypatch)
        try:
            r = await _call_email_door_hanger(jid, tid)
            assert r["ok"] is True
            body = captured.get("html") or ""
            # Baseline copy still present…
            assert "your visit has been completed" in body
            assert "Hi Kaylan," in body
            # …and the empty-notes fallback line still fires.
            assert "Notes: —" in body
        finally:
            await _drain(tid, jid, cid)

    _run(_go())



# ═════════════════════════════════════════════════════════════════════
# 5. Feb-2026 · Addition 1 — Service Date line.
# ═════════════════════════════════════════════════════════════════════
def test_door_hanger_service_date_renders_long_form(monkeypatch):
    async def _go():
        tid = await _tenant_id()
        cid = await _mk_customer(tid)
        # Fixed completed_at → deterministic long-form date.
        # 2025-11-04T15:30:00Z → Tue, Nov 4, 2025 (all timezones we
        # care about show the same calendar date because completion
        # was 15:30 UTC, well past midnight in the Americas).
        jid = await _mk_pool_job(tid, cid, seed_fields={
            "completed_at": "2025-11-04T15:30:00Z",
        })
        captured = _stub_email_send(monkeypatch)
        try:
            r = await _call_email_door_hanger(jid, tid)
            assert r["ok"] is True
            body = captured.get("html") or ""
            # Long-form label + weekday + month name + year.
            assert "Service Date:" in body
            assert "Tuesday, November 4, 2025" in body, body[:600]
            # Positional assertion — greeting < Service Date < job title.
            gi = body.index("Hi Kaylan,")
            si = body.index("Service Date:")
            ti = body.index("<b>Weekly Pool</b>")
            assert gi < si < ti, (gi, si, ti)
        finally:
            await _drain(tid, jid, cid)

    _run(_go())


def test_door_hanger_service_date_falls_back_through_cascade(monkeypatch):
    """Cascade: completed_at → scheduled_end → scheduled_start → now."""
    async def _go_case(seed: Dict[str, Any], expected_date_str: str | None):
        tid = await _tenant_id()
        cid = await _mk_customer(tid)
        jid = await _mk_pool_job(tid, cid, seed_fields=seed)
        captured = _stub_email_send(monkeypatch)
        try:
            r = await _call_email_door_hanger(jid, tid)
            assert r["ok"] is True
            body = captured.get("html") or ""
            assert "Service Date:" in body
            if expected_date_str:
                assert expected_date_str in body, body[:600]
        finally:
            await _drain(tid, jid, cid)

    # Case 1 — completed_at wins over scheduled_end + scheduled_start.
    _run(_go_case({
        "completed_at":   "2025-11-04T15:30:00Z",
        "scheduled_end":  "2025-11-05T15:30:00Z",
        "scheduled_start": "2025-11-06T15:30:00Z",
    }, "November 4, 2025"))
    # Case 2 — no completed_at → scheduled_end wins.
    _run(_go_case({
        "completed_at": None,
        "scheduled_end": "2025-11-05T15:30:00Z",
        "scheduled_start": "2025-11-06T15:30:00Z",
    }, "November 5, 2025"))
    # Case 3 — only scheduled_start.
    _run(_go_case({
        "completed_at": None,
        "scheduled_end": None,
        "scheduled_start": "2025-11-06T15:30:00Z",
    }, "November 6, 2025"))
    # Case 4 — nothing at all → uses now (assert only label presence).
    _run(_go_case({
        "completed_at": None,
        "scheduled_end": None,
        "scheduled_start": None,
    }, None))


# ═════════════════════════════════════════════════════════════════════
# 6. Feb-2026 · Addition 2 — Portal deep-link CTA.
# ═════════════════════════════════════════════════════════════════════
def test_door_hanger_portal_cta_renders_after_photos_before_footer(monkeypatch):
    async def _go():
        tid = await _tenant_id()
        cid = await _mk_customer(tid)
        jid = await _mk_pool_job(tid, cid, seed_fields={
            "photos": [{
                "id": "cta-photo", "data": "data:image/png;base64,iVBORw==",
                "label": "before", "created_at": "2026-02-20T00:00:00+00:00",
            }],
        })
        monkeypatch.setenv("PUBLIC_APP_BASE_URL", "https://app.plofv.com")
        captured = _stub_email_send(monkeypatch)
        try:
            r = await _call_email_door_hanger(jid, tid)
            assert r["ok"] is True
            body = captured.get("html") or ""
            # Feb-2026 hotfix — the button href now targets the
            # backend redemption endpoint so a click auto-logs the
            # customer in.  The old ``/portal/jobs/{jid}?t=`` URL
            # 404'd (no portal-side route).
            expected_url_prefix = (
                "https://app.plofv.com/api/portal/auto-login?t="
            )
            assert expected_url_prefix in body, body[:800]
            # The bare portal-jobs path MUST no longer appear.
            assert f"/portal/jobs/{jid}?t=" not in body
            # CTA label — plaintext "paste this link" fallback removed
            # per user hotfix Feb-2026 (visual noise + double surface).
            assert "View Service Report in Portal" in body
            assert "If the button doesn't work" not in body
            assert "paste this link" not in body
            # Positional: photos section < CTA < footer.
            photos_idx = body.index("Service Photos")
            cta_idx = body.index("View Service Report in Portal")
            footer_idx = body.index("We appreciate your business")
            assert photos_idx < cta_idx < footer_idx, (
                photos_idx, cta_idx, footer_idx)
        finally:
            await _drain(tid, jid, cid)

    _run(_go())


def test_door_hanger_omits_cta_when_customer_id_missing(monkeypatch):
    """Skip rule: no customer.id → OMIT CTA, rest of email still renders."""
    async def _go():
        tid = await _tenant_id()
        cid = await _mk_customer(tid)
        jid = await _mk_pool_job(tid, cid)
        # Nuke the customer.id AFTER the job is created — simulates a
        # stale link where the customer doc has no id (should never
        # happen in prod, but the CTA must fail-safe regardless).
        await _db().customers.update_one(
            {"id": cid, "tenant_id": tid}, {"$unset": {"id": ""}},
        )
        # Also drop the ``customer_id`` from the job so the builder
        # can't recover cid via the job doc either.
        await _db().jobs.update_one(
            {"id": jid, "tenant_id": tid}, {"$unset": {"customer_id": ""}},
        )
        captured = _stub_email_send(monkeypatch)
        try:
            # Manual endpoint short-circuits on "no email" — call the
            # shared builder directly instead so we can inspect an
            # email that has NO cid available.
            from routers.workstream_service_log import _build_door_hanger_email
            job = await _db().jobs.find_one(
                {"id": jid, "tenant_id": tid}, {"_id": 0})
            tenant = await _db().tenants.find_one({"id": tid}, {"_id": 0})
            composed = await _build_door_hanger_email(
                job=job, tenant=tenant, cust={}, cid=None,
            )
            body = composed["html"]
            # CTA MUST be absent.
            assert "View Service Report in Portal" not in body
            assert "/api/portal/auto-login" not in body
            assert "/portal/jobs/" not in body
            # Rest of the email still renders — baseline copy present.
            assert "your visit has been completed" in body
            assert "We appreciate your business" in body
        finally:
            await _drain(tid, jid, cid)

    _run(_go())


def test_door_hanger_cta_omitted_gracefully_when_mint_raises(monkeypatch):
    """When the portal mint helper raises, the CTA MUST be omitted
    but the email must still render successfully — never 500."""
    async def _go():
        tid = await _tenant_id()
        cid = await _mk_customer(tid)
        jid = await _mk_pool_job(tid, cid)
        # Sabotage the URL builder — the door-hanger composer must
        # catch + log + omit the CTA.  ``build_job_view_url``
        # internally calls ``mint_job_view_token`` so patching the
        # public builder covers both entry points.
        from services import portal_magic_links as _pml

        def _boom(*a, **kw):
            raise RuntimeError("simulated mint failure")

        monkeypatch.setattr(_pml, "build_job_view_url", _boom)
        monkeypatch.setattr(_pml, "mint_job_view_token", _boom)
        # Also patch the freshly-imported name inside the builder
        # module — the builder does a local ``from ... import`` at
        # call time, so patching the module-level attribute is enough.
        captured = _stub_email_send(monkeypatch)
        try:
            r = await _call_email_door_hanger(jid, tid)
            assert r.get("ok") is True, r
            body = captured.get("html") or ""
            assert "View Service Report in Portal" not in body
            assert "/api/portal/auto-login" not in body
            # Rest of email still there.
            assert "your visit has been completed" in body
            assert "We appreciate your business" in body
        finally:
            await _drain(tid, jid, cid)

    _run(_go())



# ═════════════════════════════════════════════════════════════════════
# Feb-2026 · Water-test BANDS + optionals-omit hotfix regression tests.
# ═════════════════════════════════════════════════════════════════════
def test_door_hanger_elevated_ph_renders_band_not_number(monkeypatch):
    """A pH of 8.5 sits in the Elevated band.  The email MUST show
    ``pH: Elevated`` and MUST NOT show the raw ``8.5`` value."""
    async def _go():
        tid = await _tenant_id()
        cid = await _mk_customer(tid)
        jid = await _mk_pool_job(tid, cid)
        # Seed a service report with an Elevated pH + Average rest.
        from utils import now_iso, new_id
        await _db().service_reports.insert_one({
            "id": new_id(), "tenant_id": tid, "job_id": jid,
            "tech_id": "mike-tech",
            "submitted_at": now_iso(),
            "chemical_readings": [
                {"key": "free_chlorine",  "value": 2.5},
                {"key": "total_chlorine", "value": 3.0},
                {"key": "ph",             "value": 8.5},
                {"key": "alkalinity",     "value": 90},
                {"key": "cyanuric_acid",  "value": 45},
            ],
        })
        captured = _stub_email_send(monkeypatch)
        try:
            r = await _call_email_door_hanger(jid, tid)
            assert r["ok"] is True
            body = captured.get("html") or ""
            _wt = body[body.index("Water Test</h3>"):body.index("</table>",
                       body.index("Water Test</h3>"))]
            assert ">pH</td>" in _wt
            assert "<b>Elevated</b>" in _wt
            assert "8.5" not in _wt
        finally:
            await _drain(tid, jid, cid)

    _run(_go())


def test_door_hanger_water_test_renders_all_five_cores_in_fixed_order(monkeypatch):
    async def _go():
        tid = await _tenant_id()
        cid = await _mk_customer(tid)
        jid = await _mk_pool_job(tid, cid)
        from utils import now_iso, new_id
        # Seed readings in a SHUFFLED order to prove the email always
        # renders them in the canonical order (Free Cl → Total Cl →
        # Alkalinity → pH → CYA, matching ``chemistry_gate.CORE_READINGS``).
        await _db().service_reports.insert_one({
            "id": new_id(), "tenant_id": tid, "job_id": jid,
            "tech_id": "mike-tech",
            "submitted_at": now_iso(),
            "chemical_readings": [
                {"key": "cyanuric_acid",  "value": 45},
                {"key": "ph",             "value": 7.4},
                {"key": "alkalinity",     "value": 90},
                {"key": "total_chlorine", "value": 3.0},
                {"key": "free_chlorine",  "value": 2.5},
            ],
        })
        captured = _stub_email_send(monkeypatch)
        try:
            r = await _call_email_door_hanger(jid, tid)
            assert r["ok"] is True
            body = captured.get("html") or ""
            _wt = body[body.index("Water Test</h3>"):body.index("</table>",
                       body.index("Water Test</h3>"))]
            # Every core rendered, in canonical order.
            positions = {
                lbl: _wt.index(f">{lbl}</td>") for lbl in
                ("Free Cl", "Total Cl", "Alkalinity", "pH", "CYA")
            }
            ordered = sorted(positions.items(), key=lambda kv: kv[1])
            assert [k for k, _ in ordered] == [
                "Free Cl", "Total Cl", "Alkalinity", "pH", "CYA",
            ]
        finally:
            await _drain(tid, jid, cid)

    _run(_go())


def test_door_hanger_optional_readings_omit_when_blank(monkeypatch):
    async def _go():
        tid = await _tenant_id()
        cid = await _mk_customer(tid)
        jid = await _mk_pool_job(tid, cid)
        from utils import now_iso, new_id
        # 5 cores present + BOTH optionals blank.
        await _db().service_reports.insert_one({
            "id": new_id(), "tenant_id": tid, "job_id": jid,
            "tech_id": "mike-tech",
            "submitted_at": now_iso(),
            "chemical_readings": [
                {"key": "free_chlorine",   "value": 2.5},
                {"key": "total_chlorine",  "value": 3.0},
                {"key": "ph",              "value": 7.4},
                {"key": "alkalinity",      "value": 90},
                {"key": "cyanuric_acid",   "value": 45},
                {"key": "water_temp",      "value": None},
                {"key": "calcium_hardness", "value": ""},
            ],
        })
        captured = _stub_email_send(monkeypatch)
        try:
            r = await _call_email_door_hanger(jid, tid)
            assert r["ok"] is True
            body = captured.get("html") or ""
            # Optional rows MUST be absent — the entire optionals
            # block is omitted when every optional is blank.
            _wt = body[body.index("Water Test</h3>"):body.index("</table>",
                       body.index("Water Test</h3>"))]
            assert "Water Temp" not in _wt
            assert "Calcium Hardness" not in _wt
        finally:
            await _drain(tid, jid, cid)

    _run(_go())


def test_door_hanger_optional_reading_rendered_when_filled(monkeypatch):
    async def _go():
        tid = await _tenant_id()
        cid = await _mk_customer(tid)
        jid = await _mk_pool_job(tid, cid)
        from utils import now_iso, new_id
        await _db().service_reports.insert_one({
            "id": new_id(), "tenant_id": tid, "job_id": jid,
            "tech_id": "mike-tech",
            "submitted_at": now_iso(),
            "chemical_readings": [
                {"key": "free_chlorine",   "value": 2.5},
                {"key": "total_chlorine",  "value": 3.0},
                {"key": "ph",              "value": 7.4},
                {"key": "alkalinity",      "value": 90},
                {"key": "cyanuric_acid",   "value": 45},
                {"key": "water_temp",      "value": 82, "unit": "°F"},
                {"key": "calcium_hardness", "value": None},
            ],
        })
        captured = _stub_email_send(monkeypatch)
        try:
            r = await _call_email_door_hanger(jid, tid)
            assert r["ok"] is True
            body = captured.get("html") or ""
            _wt = body[body.index("Water Test</h3>"):body.index("</table>",
                       body.index("Water Test</h3>"))]
            # Filled optional renders with its numeric value + unit.
            assert "Water Temp" in _wt
            assert "82" in _wt
            # Blank optional stays omitted.
            assert "Calcium Hardness" not in _wt
        finally:
            await _drain(tid, jid, cid)

    _run(_go())
