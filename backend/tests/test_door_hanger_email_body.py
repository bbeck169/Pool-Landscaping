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
            for _label in ("Free Chlorine", "pH",
                           "Alkalinity", "Cyanuric Acid"):
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
            # Feb-2026 · Slice 4 — chemical cost hide. The customer-facing
            # door hanger MUST NOT render a Chemical cost total. The
            # priced resolver still computes ``chem_total_cents`` (used
            # by internal surfaces / auto-invoice) but the template
            # drops the ``Chemical cost: $x.xx`` line.
            assert "$8.00" not in body, (
                "chemical cost leaked into customer-facing door hanger"
            )
            assert "Chemical cost" not in body, (
                "'Chemical cost' label leaked into customer-facing door hanger"
            )
            # Scope-limited: no dollar signs anywhere in the Chemicals
            # Used section (label + list). Other UI (e.g., tenant
            # phone, portal CTA copy) is out of scope for this rule.
            _ch_start = body.index("Chemicals Used</h3>")
            _ch_end = body.index("</ul>", _ch_start) + len("</ul>")
            _ch_section = body[_ch_start:_ch_end]
            for _needle in ("$", "cost", "price", "total"):
                assert _needle not in _ch_section.lower(), (
                    f"pricing signal {_needle!r} leaked into Chemicals Used "
                    f"section: {_ch_section!r}"
                )
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
                "free_chlorine": 1.8,
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
            assert "Cyanuric Acid" in body
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
        # renders them in the product-spec display order (Free
        # Chlorine → Total Chlorine → pH → Alkalinity → Cyanuric Acid,
        # matching ``_DH_DISPLAY_ORDER`` in workstream_service_log.py).
        await _db().service_reports.insert_one({
            "id": new_id(), "tenant_id": tid, "job_id": jid,
            "tech_id": "mike-tech",
            "submitted_at": now_iso(),
            "chemical_readings": [
                {"key": "cyanuric_acid",  "value": 45},
                {"key": "ph",             "value": 7.4},
                {"key": "alkalinity",     "value": 90},
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
            # Every core rendered, in display order.
            positions = {
                lbl: _wt.index(f">{lbl}</td>") for lbl in
                ("Free Chlorine", "pH",
                 "Alkalinity", "Cyanuric Acid")
            }
            ordered = sorted(positions.items(), key=lambda kv: kv[1])
            assert [k for k, _ in ordered] == [
                "Free Chlorine", "pH",
                "Alkalinity", "Cyanuric Acid",
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


# ═════════════════════════════════════════════════════════════════════
# Feb-2026 · Extended range-badge coverage (product spec).
# ═════════════════════════════════════════════════════════════════════
#
# Customer-facing email now renders every configured reading with a
# qualitative band (Calcium Hardness, Salt, TDS, Phosphates joined
# the badged set). Water Temp stays informational (raw value only).
# Combined Chlorine is REMOVED entirely.  Zero-valued OPTIONAL
# readings are treated as "not measured" and omitted.
# ═════════════════════════════════════════════════════════════════════
def test_door_hanger_extended_readings_render_with_bands(monkeypatch):
    """Calcium Hardness, Salt, TDS, and Phosphates each get a band
    chip instead of a raw ppm number when a real reading is
    submitted."""
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
                {"key": "ph",              "value": 7.4},
                {"key": "alkalinity",      "value": 90},
                {"key": "cyanuric_acid",   "value": 45},
                # Extended banded readings — mix of bands.
                {"key": "calcium_hardness", "value": 300, "unit": "ppm"},  # Average [200,400)
                {"key": "salt",             "value": 3600, "unit": "ppm"}, # Above Avg [3400,4000)
                {"key": "tds",              "value": 2500, "unit": "ppm"}, # Elevated (>=2000)
                {"key": "phosphates",       "value": 50, "unit": "ppb"},   # Below Avg (<100)
                {"key": "water_temp",       "value": 82, "unit": "°F"},
            ],
        })
        captured = _stub_email_send(monkeypatch)
        try:
            r = await _call_email_door_hanger(jid, tid)
            assert r["ok"] is True
            body = captured.get("html") or ""
            _wt = body[body.index("Water Test</h3>"):
                       body.index("</table>", body.index("Water Test</h3>"))]

            # Every extended banded reading is present with its label.
            for label in ("Calcium Hardness", "Salt", "TDS", "Phosphates"):
                assert f">{label}</td>" in _wt, f"missing {label!r}"

            # Raw ppm values must NOT leak into the banded rows.
            for raw in ("300 ppm", "3600 ppm", "2500 ppm", "50 ppb"):
                assert raw not in _wt, f"raw {raw!r} leaked into a banded row"

            # Each extended reading gets its correct band.
            _ch = _wt.index(">Calcium Hardness</td>")
            _sa = _wt.index(">Salt</td>")
            _td = _wt.index(">TDS</td>")
            _ph = _wt.index(">Phosphates</td>")
            _end = len(_wt)
            # Slice each row from label to next label — chip lives inside.
            def _row_after(pos, next_pos):
                return _wt[pos:next_pos]
            assert "<b>Average</b>" in _row_after(_ch, _sa)
            assert "<b>Above Average</b>" in _row_after(_sa, _td)
            assert "<b>Elevated</b>" in _row_after(_td, _ph)
            assert "<b>Below Average</b>" in _row_after(_ph, _end)
        finally:
            await _drain(tid, jid, cid)

    _run(_go())


def test_door_hanger_combined_chlorine_never_rendered(monkeypatch):
    """Combined Chlorine is dropped from the customer email even when
    the tech recorded a real value (product spec, Feb-2026)."""
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
                {"key": "free_chlorine",     "value": 2.5},
                {"key": "combined_chlorine", "value": 0.5, "unit": "ppm"},
                {"key": "ph",                "value": 7.4},
                {"key": "alkalinity",        "value": 90},
                {"key": "cyanuric_acid",     "value": 45},
            ],
        })
        captured = _stub_email_send(monkeypatch)
        try:
            r = await _call_email_door_hanger(jid, tid)
            assert r["ok"] is True
            body = captured.get("html") or ""
            _wt = body[body.index("Water Test</h3>"):
                       body.index("</table>", body.index("Water Test</h3>"))]
            assert "Combined Chlorine" not in _wt
            assert "combined" not in _wt.lower()
            # Free Chlorine (the sibling) still renders — sanity check
            # that we didn't accidentally drop the wrong row.
            assert ">Free Chlorine</td>" in _wt
        finally:
            await _drain(tid, jid, cid)

    _run(_go())


def test_door_hanger_new_customer_labels(monkeypatch):
    """Customer-facing email uses long-form labels; tech-facing
    ``DISPLAY_LABELS`` shorthand ('Free Cl', 'CYA') must NOT leak."""
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
                {"key": "free_chlorine",  "value": 2.5},
                {"key": "ph",             "value": 7.4},
                {"key": "alkalinity",     "value": 90},
                {"key": "cyanuric_acid",  "value": 45},
            ],
        })
        captured = _stub_email_send(monkeypatch)
        try:
            r = await _call_email_door_hanger(jid, tid)
            assert r["ok"] is True
            body = captured.get("html") or ""
            _wt = body[body.index("Water Test</h3>"):
                       body.index("</table>", body.index("Water Test</h3>"))]
            # New customer-facing labels present.
            assert ">Free Chlorine</td>" in _wt
            assert ">Cyanuric Acid</td>" in _wt
            # Phase CHEM1 · Total Chlorine removed — must not surface.
            assert ">Total Chlorine</td>" not in _wt
            # Tech-facing shorthand must NOT leak into the customer email.
            assert ">Free Cl</td>" not in _wt
            assert ">Total Cl</td>" not in _wt
            assert ">CYA</td>" not in _wt
        finally:
            await _drain(tid, jid, cid)

    _run(_go())


def test_door_hanger_zero_value_optionals_are_unmeasured_sentinel(monkeypatch):
    """A tech skipping optional readings leaves them at 0.0 in the
    default checklist state. Treat 0-valued OPTIONAL readings as
    'not measured' and omit them for a cleaner customer email.
    CORE readings still render at 0 (chemistry gate requires them)."""
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
                # Core readings real.
                {"key": "free_chlorine",  "value": 2.5},
                {"key": "ph",             "value": 7.4},
                {"key": "alkalinity",     "value": 90},
                {"key": "cyanuric_acid",  "value": 45},
                # Optionals all zero — reproduces the screenshot symptom.
                {"key": "calcium_hardness", "value": 0.0},
                {"key": "salt",             "value": 0.0},
                {"key": "tds",              "value": 0.0},
                {"key": "phosphates",       "value": 0.0},
                {"key": "water_temp",       "value": 0.0, "unit": "°F"},
            ],
        })
        captured = _stub_email_send(monkeypatch)
        try:
            r = await _call_email_door_hanger(jid, tid)
            assert r["ok"] is True
            body = captured.get("html") or ""
            _wt = body[body.index("Water Test</h3>"):
                       body.index("</table>", body.index("Water Test</h3>"))]
            for label in ("Calcium Hardness", "Salt", "TDS",
                          "Phosphates", "Water Temp"):
                assert label not in _wt, (
                    f"unmeasured optional {label!r} leaked into email"
                )
        finally:
            await _drain(tid, jid, cid)

    _run(_go())


def test_door_hanger_water_temp_renders_raw_not_banded(monkeypatch):
    """Water Temp is informational — must render its raw value + unit,
    never a band chip. Confirms the renderer's raw-fallback branch."""
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
                {"key": "free_chlorine",  "value": 2.5},
                {"key": "ph",             "value": 7.4},
                {"key": "alkalinity",     "value": 90},
                {"key": "cyanuric_acid",  "value": 45},
                {"key": "water_temp",     "value": 84, "unit": "°F"},
            ],
        })
        captured = _stub_email_send(monkeypatch)
        try:
            r = await _call_email_door_hanger(jid, tid)
            assert r["ok"] is True
            body = captured.get("html") or ""
            _wt = body[body.index("Water Test</h3>"):
                       body.index("</table>", body.index("Water Test</h3>"))]
            assert ">Water Temp</td>" in _wt
            # Slice just the Water Temp row.
            _wt_pos = _wt.index(">Water Temp</td>")
            _wt_row = _wt[_wt_pos:_wt.index("</tr>", _wt_pos)]
            assert "84" in _wt_row
            # Note: ``resolve_water_test`` currently drops the ``unit``
            # field for non-canonical readings before this renderer
            # sees them (see ``service_report_view._coerce_readings``).
            # Water Temp therefore renders as a bare "84" without
            # "°F". Flagged as a follow-up; not fixed in this PR.
            # No band chip on this row.
            for band in ("Below Average", "Average",
                         "Above Average", "Elevated"):
                assert f"<b>{band}</b>" not in _wt_row, (
                    f"Water Temp incorrectly rendered a band: {band}"
                )
        finally:
            await _drain(tid, jid, cid)

    _run(_go())



# ═════════════════════════════════════════════════════════════════════
# Feb-2026 · Slice 5 — Elevated readings follow-up CTA tests.
# ═════════════════════════════════════════════════════════════════════
#
# Trigger rule: when 2+ core readings land in the ``Elevated`` band,
# render a service-recommendation card between Water Test and
# Chemicals Used with a Reply-to-Schedule mailto + Call tel button.
#
# Suppression rules covered below:
#   * 0 or 1 elevated cores → no block
#   * landscape job → no block (no water test)
#   * customer.unsubscribed → no block (Water Test card still shows)
#   * tenant.phone missing → Reply button full-width, Call absent
_ELEVATED_CTA_HEADING = "A few readings look elevated"
_ELEVATED_CTA_EYEBROW = "NEXT STEPS"
_ELEVATED_REPLY_LABEL = "Reply to Schedule Follow-Up"


def _elevated_seed_readings(elevated_count: int) -> list:
    """Return a canonical 5-core reading seed with the first
    ``elevated_count`` cores pushed into the Elevated band and the
    rest in the Average band. Free Cl >10 → Elevated; pH >8.4 →
    Elevated; alkalinity >180 → Elevated; CYA >150 → Elevated. Total
    Cl matches Free Cl for the Elevated case so the gate doesn't fire.
    """
    all_core = [
        ("free_chlorine",  12.0, 2.5),   # (>10 elevated, average)
        ("ph",             8.6,  7.4),
        ("alkalinity",     200,  90),
        ("cyanuric_acid",  180,  45),
    ]
    seed = []
    for i, (key, hi, ok) in enumerate(all_core):
        seed.append({"key": key, "value": hi if i < elevated_count else ok})
    return seed


def test_door_hanger_elevated_cta_absent_when_zero_elevated(monkeypatch):
    async def _go():
        tid = await _tenant_id()
        cid = await _mk_customer(tid)
        jid = await _mk_pool_job(tid, cid)
        from utils import now_iso, new_id
        await _db().service_reports.insert_one({
            "id": new_id(), "tenant_id": tid, "job_id": jid,
            "tech_id": "mike-tech", "submitted_at": now_iso(),
            "chemical_readings": _elevated_seed_readings(0),
        })
        captured = _stub_email_send(monkeypatch)
        try:
            r = await _call_email_door_hanger(jid, tid)
            assert r["ok"] is True
            body = captured.get("html") or ""
            assert _ELEVATED_CTA_HEADING not in body
            assert _ELEVATED_CTA_EYEBROW not in body
            assert _ELEVATED_REPLY_LABEL not in body
        finally:
            await _drain(tid, jid, cid)

    _run(_go())


def test_door_hanger_elevated_cta_absent_when_one_elevated(monkeypatch):
    async def _go():
        tid = await _tenant_id()
        cid = await _mk_customer(tid)
        jid = await _mk_pool_job(tid, cid)
        from utils import now_iso, new_id
        await _db().service_reports.insert_one({
            "id": new_id(), "tenant_id": tid, "job_id": jid,
            "tech_id": "mike-tech", "submitted_at": now_iso(),
            "chemical_readings": _elevated_seed_readings(1),
        })
        captured = _stub_email_send(monkeypatch)
        try:
            r = await _call_email_door_hanger(jid, tid)
            assert r["ok"] is True
            body = captured.get("html") or ""
            # Single Elevated reading still shows in Water Test chip.
            _wt = body[body.index("Water Test</h3>"):body.index("</table>",
                       body.index("Water Test</h3>"))]
            assert "<b>Elevated</b>" in _wt
            # But the follow-up CTA MUST NOT render (threshold is 2+).
            assert _ELEVATED_CTA_HEADING not in body
        finally:
            await _drain(tid, jid, cid)

    _run(_go())


def test_door_hanger_elevated_cta_renders_when_two_elevated(monkeypatch):
    async def _go():
        tid = await _tenant_id()
        cid = await _mk_customer(tid)
        jid = await _mk_pool_job(tid, cid)
        from utils import now_iso, new_id
        await _db().service_reports.insert_one({
            "id": new_id(), "tenant_id": tid, "job_id": jid,
            "tech_id": "mike-tech", "submitted_at": now_iso(),
            "chemical_readings": _elevated_seed_readings(2),
        })
        # Force a known tenant phone so the Call button is present
        # in this positive-path test. The seeded tenant doc doesn't
        # write a phone field by default.
        await _db().tenants.update_one(
            {"id": tid}, {"$set": {"phone": "+1 (602) 555-0199"}},
        )
        captured = _stub_email_send(monkeypatch)
        try:
            r = await _call_email_door_hanger(jid, tid)
            assert r["ok"] is True
            body = captured.get("html") or ""
            # Block present.
            assert _ELEVATED_CTA_EYEBROW in body
            assert _ELEVATED_CTA_HEADING in body
            assert _ELEVATED_REPLY_LABEL in body
            assert "Call " in body
            # Positional: Water Test < Elevated CTA < Chemicals Used
            # (chemicals section is empty in this seed; use portal
            # CTA / footer as end sentinel).
            wt_idx = body.index("Water Test</h3>")
            ecta_idx = body.index(_ELEVATED_CTA_HEADING)
            footer_idx = body.index("We appreciate your business")
            assert wt_idx < ecta_idx < footer_idx, (wt_idx, ecta_idx, footer_idx)
        finally:
            await _db().tenants.update_one(
                {"id": tid}, {"$unset": {"phone": ""}},
            )
            await _drain(tid, jid, cid)

    _run(_go())


def test_door_hanger_elevated_cta_renders_when_three_plus_elevated(monkeypatch):
    async def _go():
        tid = await _tenant_id()
        cid = await _mk_customer(tid)
        jid = await _mk_pool_job(tid, cid)
        from utils import now_iso, new_id
        await _db().service_reports.insert_one({
            "id": new_id(), "tenant_id": tid, "job_id": jid,
            "tech_id": "mike-tech", "submitted_at": now_iso(),
            "chemical_readings": _elevated_seed_readings(4),
        })
        captured = _stub_email_send(monkeypatch)
        try:
            r = await _call_email_door_hanger(jid, tid)
            assert r["ok"] is True
            body = captured.get("html") or ""
            assert _ELEVATED_CTA_HEADING in body
            assert _ELEVATED_REPLY_LABEL in body
        finally:
            await _drain(tid, jid, cid)

    _run(_go())


def test_door_hanger_elevated_cta_absent_for_landscape_job(monkeypatch):
    async def _go():
        tid = await _tenant_id()
        cid = await _mk_customer(tid)
        # Explicitly landscape job — no water test resolved regardless
        # of any chemistry rows the DB happens to hold.
        from utils import new_id, now_iso
        jid = f"test-job-{uuid.uuid4().hex[:12]}"
        await _db().jobs.insert_one({
            "id": jid, "tenant_id": tid, "customer_id": cid,
            "customer_name": "Kaylan Testcase",
            "service_type": "Landscape Maintenance",
            "status": "completed", "completed_at": now_iso(),
            "scheduled_date": now_iso(),
            "title": "Yard Clean-Up", "created_at": now_iso(),
        })
        await _db().service_reports.insert_one({
            "id": new_id(), "tenant_id": tid, "job_id": jid,
            "tech_id": "mike-tech", "submitted_at": now_iso(),
            # Even with elevated readings on file, the landscape kind
            # short-circuits water_test resolution to [].
            "chemical_readings": _elevated_seed_readings(4),
        })
        captured = _stub_email_send(monkeypatch)
        try:
            r = await _call_email_door_hanger(jid, tid)
            assert r["ok"] is True
            body = captured.get("html") or ""
            assert "Water Test" not in body
            assert _ELEVATED_CTA_HEADING not in body
        finally:
            await _drain(tid, jid, cid)

    _run(_go())


def test_door_hanger_elevated_cta_suppressed_when_customer_unsubscribed(monkeypatch):
    async def _go():
        tid = await _tenant_id()
        cid = await _mk_customer(tid)
        # Flip the customer to unsubscribed AFTER creation.
        await _db().customers.update_one(
            {"id": cid, "tenant_id": tid},
            {"$set": {"unsubscribed": True}},
        )
        jid = await _mk_pool_job(tid, cid)
        from utils import now_iso, new_id
        await _db().service_reports.insert_one({
            "id": new_id(), "tenant_id": tid, "job_id": jid,
            "tech_id": "mike-tech", "submitted_at": now_iso(),
            "chemical_readings": _elevated_seed_readings(3),
        })
        captured = _stub_email_send(monkeypatch)
        try:
            # Manual endpoint bypasses opt-out on the whole email BUT
            # the CTA-level suppression still fires — Water Test card
            # renders, Elevated CTA does not.
            r = await _call_email_door_hanger(jid, tid)
            assert r["ok"] is True
            body = captured.get("html") or ""
            assert "Water Test</h3>" in body
            _wt = body[body.index("Water Test</h3>"):body.index("</table>",
                       body.index("Water Test</h3>"))]
            assert "<b>Elevated</b>" in _wt
            assert _ELEVATED_CTA_HEADING not in body
        finally:
            await _drain(tid, jid, cid)

    _run(_go())


def test_door_hanger_elevated_cta_hides_call_button_when_tenant_phone_missing(monkeypatch):
    async def _go():
        tid = await _tenant_id()
        cid = await _mk_customer(tid)
        jid = await _mk_pool_job(tid, cid)
        from utils import now_iso, new_id
        await _db().service_reports.insert_one({
            "id": new_id(), "tenant_id": tid, "job_id": jid,
            "tech_id": "mike-tech", "submitted_at": now_iso(),
            "chemical_readings": _elevated_seed_readings(3),
        })
        # Wipe both tenant.phone and tenant.rc_sms_from_number so the
        # CTA button-row falls back to the full-width Reply layout.
        # (Footer still renders the hardcoded fallback phone; the
        # CTA does NOT use that.)
        prev_phone = None
        prev_rc = None
        t = await _db().tenants.find_one({"id": tid}, {"_id": 0, "phone": 1,
                                                        "rc_sms_from_number": 1})
        if t:
            prev_phone = t.get("phone")
            prev_rc = t.get("rc_sms_from_number")
        await _db().tenants.update_one(
            {"id": tid},
            {"$unset": {"phone": "", "rc_sms_from_number": ""}},
        )
        captured = _stub_email_send(monkeypatch)
        try:
            r = await _call_email_door_hanger(jid, tid)
            assert r["ok"] is True
            body = captured.get("html") or ""
            assert _ELEVATED_CTA_HEADING in body
            assert _ELEVATED_REPLY_LABEL in body
            # Scope the Call-button check to the Elevated CTA card:
            # the footer contains the hardcoded fallback phone but
            # NOT a ``tel:`` link.  A ``tel:`` scheme anywhere in the
            # body signals a Call button rendered — assert none.
            assert "tel:" not in body, (
                "Call button rendered even though tenant.phone + "
                "rc_sms_from_number were both unset"
            )
        finally:
            # Restore the phone fields so subsequent tests aren't
            # polluted (autouse fixture doesn't reset tenants).
            restore = {}
            if prev_phone is not None:
                restore["phone"] = prev_phone
            if prev_rc is not None:
                restore["rc_sms_from_number"] = prev_rc
            if restore:
                await _db().tenants.update_one({"id": tid}, {"$set": restore})
            await _drain(tid, jid, cid)

    _run(_go())


def test_door_hanger_elevated_cta_reply_button_uses_mailto_scheme(monkeypatch):
    async def _go():
        tid = await _tenant_id()
        cid = await _mk_customer(tid)
        jid = await _mk_pool_job(tid, cid)
        from utils import now_iso, new_id
        await _db().service_reports.insert_one({
            "id": new_id(), "tenant_id": tid, "job_id": jid,
            "tech_id": "mike-tech", "submitted_at": now_iso(),
            "chemical_readings": _elevated_seed_readings(3),
        })
        captured = _stub_email_send(monkeypatch)
        try:
            r = await _call_email_door_hanger(jid, tid)
            assert r["ok"] is True
            body = captured.get("html") or ""
            # Locate the Reply button's <a> tag and inspect its href.
            import re
            m = re.search(
                r'<a href="([^"]+)"[^>]*>\s*Reply to Schedule Follow-Up',
                body,
            )
            assert m, "Reply-to-Schedule button not found"
            href = m.group(1)
            # MUST be a mailto: scheme, NOT https://.
            assert href.startswith("mailto:"), (
                f"Reply CTA href must use mailto:, got {href!r}"
            )
            assert "http://" not in href and "https://" not in href
            # Subject includes the job id for admin triage.
            assert f"Job%20{jid}" in href, href
        finally:
            await _drain(tid, jid, cid)

    _run(_go())


def test_door_hanger_elevated_cta_call_button_uses_tel_scheme(monkeypatch):
    async def _go():
        tid = await _tenant_id()
        cid = await _mk_customer(tid)
        jid = await _mk_pool_job(tid, cid)
        from utils import now_iso, new_id
        await _db().service_reports.insert_one({
            "id": new_id(), "tenant_id": tid, "job_id": jid,
            "tech_id": "mike-tech", "submitted_at": now_iso(),
            "chemical_readings": _elevated_seed_readings(3),
        })
        # Force a known tenant.phone so the assertion is deterministic.
        await _db().tenants.update_one(
            {"id": tid}, {"$set": {"phone": "+1 (602) 555-0199"}},
        )
        captured = _stub_email_send(monkeypatch)
        try:
            r = await _call_email_door_hanger(jid, tid)
            assert r["ok"] is True
            body = captured.get("html") or ""
            import re
            m = re.search(
                r'<a href="(tel:[^"]+)"[^>]*>\s*Call [^<]+</a>',
                body,
            )
            assert m, "Call button not found or missing tel: scheme"
            tel = m.group(1)
            # Digits-only after ``tel:`` (with a leading +).
            digits = tel.split("tel:", 1)[1]
            assert digits.startswith("+") or digits[0].isdigit()
            assert all(ch.isdigit() or ch == "+" for ch in digits)
        finally:
            # Restore tenant phone.
            await _db().tenants.update_one(
                {"id": tid}, {"$unset": {"phone": ""}},
            )
            await _drain(tid, jid, cid)

    _run(_go())


def test_door_hanger_elevated_cta_body_copy_is_two_sentences_max(monkeypatch):
    async def _go():
        tid = await _tenant_id()
        cid = await _mk_customer(tid)
        jid = await _mk_pool_job(tid, cid)
        from utils import now_iso, new_id
        await _db().service_reports.insert_one({
            "id": new_id(), "tenant_id": tid, "job_id": jid,
            "tech_id": "mike-tech", "submitted_at": now_iso(),
            "chemical_readings": _elevated_seed_readings(3),
        })
        captured = _stub_email_send(monkeypatch)
        try:
            r = await _call_email_door_hanger(jid, tid)
            assert r["ok"] is True
            body = captured.get("html") or ""
            # Eyebrow + heading present.
            assert _ELEVATED_CTA_EYEBROW in body
            assert _ELEVATED_CTA_HEADING in body
            # Extract the body paragraph following the heading. It
            # sits inside a single <p> tag between the heading and the
            # button row.
            import re
            m = re.search(
                r'A few readings look elevated</p>\s*'
                r'<p [^>]*>([^<]+)</p>',
                body,
            )
            assert m, "elevated CTA body paragraph not found"
            para = m.group(1).strip()
            # Sentence count ≤ 2 (via terminal punctuation counter).
            sentence_count = sum(1 for ch in para if ch in ".!?")
            assert sentence_count <= 2, (
                f"CTA body must be ≤ 2 sentences, got {sentence_count}: "
                f"{para!r}"
            )
        finally:
            await _drain(tid, jid, cid)

    _run(_go())


# ═════════════════════════════════════════════════════════════════════
# Feb-2026 · Slice 5 — Email-safety guards for the visual redesign.
# ═════════════════════════════════════════════════════════════════════
#
# Belt-and-braces regression net: the redesigned template MUST stay
# inline-styles-only so Gmail/Outlook/iOS Mail can't strip layout.
def test_door_hanger_uses_inline_styles_only_and_no_class_attrs(monkeypatch):
    async def _go():
        tid = await _tenant_id()
        cid = await _mk_customer(tid)
        jid = await _mk_pool_job(tid, cid)
        captured = _stub_email_send(monkeypatch)
        try:
            r = await _call_email_door_hanger(jid, tid)
            assert r["ok"] is True
            body = captured.get("html") or ""
            # No ``<style>`` blocks anywhere in the body.
            import re
            assert not re.search(r'<\s*style\b', body, re.IGNORECASE), (
                "email template must not include <style> blocks — "
                "many email clients strip them"
            )
            # No ``class=`` attribute — spec is inline-only.
            assert not re.search(r'\sclass=', body), (
                "email template must not use class= — inline styles only"
            )
            # Card layout uses <table role="presentation"> wrappers.
            assert 'role="presentation"' in body, (
                "expected email-safe table-based card layout"
            )
        finally:
            await _drain(tid, jid, cid)

    _run(_go())



# ═════════════════════════════════════════════════════════════════════
# Feb-2026 · Slice 5 add-on — Elevated CTA measurability ledger.
# ═════════════════════════════════════════════════════════════════════
#
# When the Elevated CTA renders we emit ONE
# ``marketing_event_ledger`` row per job keyed
# ``elevated_followup_shown:{job_id}`` so ops can count how many
# customers saw the follow-up prompt. Idempotent — manual resends of
# the same job never duplicate rows. NO row is written when the CTA
# is suppressed (landscape / unsubscribed / <2 elevated / etc.).
async def _count_ledger(tid: str, jid: str) -> int:
    return await _db().marketing_event_ledger.count_documents({
        "tenant_id": tid,
        "event_key": f"elevated_followup_shown:{jid}",
    })


def test_door_hanger_elevated_ledger_written_when_cta_renders(monkeypatch):
    async def _go():
        tid = await _tenant_id()
        cid = await _mk_customer(tid)
        jid = await _mk_pool_job(tid, cid)
        from utils import now_iso, new_id
        await _db().service_reports.insert_one({
            "id": new_id(), "tenant_id": tid, "job_id": jid,
            "tech_id": "mike-tech", "submitted_at": now_iso(),
            "chemical_readings": _elevated_seed_readings(3),
        })
        # Purge any pre-existing ledger row for this job (drain-safe).
        await _db().marketing_event_ledger.delete_many(
            {"tenant_id": tid, "event_key": f"elevated_followup_shown:{jid}"},
        )
        captured = _stub_email_send(monkeypatch)
        try:
            r = await _call_email_door_hanger(jid, tid)
            assert r["ok"] is True
            body = captured.get("html") or ""
            assert _ELEVATED_CTA_HEADING in body
            # Exactly one ledger row with the right shape.
            rows = await _db().marketing_event_ledger.find(
                {"tenant_id": tid,
                 "event_key": f"elevated_followup_shown:{jid}"},
                {"_id": 0},
            ).to_list(5)
            assert len(rows) == 1, rows
            row = rows[0]
            assert row["trigger_type"] == "elevated_followup_shown"
            assert row["correlation_id"] == jid
            assert row["customer_id"] == cid
            assert row.get("meta", {}).get("job_id") == jid
            assert row.get("processed_at")
        finally:
            await _db().marketing_event_ledger.delete_many(
                {"tenant_id": tid, "event_key": f"elevated_followup_shown:{jid}"},
            )
            await _drain(tid, jid, cid)

    _run(_go())


def test_door_hanger_elevated_ledger_absent_when_suppressed(monkeypatch):
    """No ledger row on any suppression path — <2 elevated /
    landscape / unsubscribed / do_not_contact.
    """
    async def _one_case(seed_readings, *, landscape=False,
                          unsubscribed=False, do_not_contact=False):
        tid = await _tenant_id()
        cid = await _mk_customer(tid)
        from utils import now_iso, new_id
        if landscape:
            jid = f"test-job-{uuid.uuid4().hex[:12]}"
            await _db().jobs.insert_one({
                "id": jid, "tenant_id": tid, "customer_id": cid,
                "customer_name": "Kaylan Testcase",
                "service_type": "Landscape Maintenance",
                "status": "completed", "completed_at": now_iso(),
                "scheduled_date": now_iso(),
                "title": "Yard Clean-Up", "created_at": now_iso(),
            })
        else:
            jid = await _mk_pool_job(tid, cid)
        await _db().service_reports.insert_one({
            "id": new_id(), "tenant_id": tid, "job_id": jid,
            "tech_id": "mike-tech", "submitted_at": now_iso(),
            "chemical_readings": seed_readings,
        })
        if unsubscribed:
            await _db().customers.update_one(
                {"id": cid, "tenant_id": tid},
                {"$set": {"unsubscribed": True}},
            )
        if do_not_contact:
            await _db().customers.update_one(
                {"id": cid, "tenant_id": tid},
                {"$set": {"do_not_contact": True}},
            )
        await _db().marketing_event_ledger.delete_many(
            {"tenant_id": tid, "event_key": f"elevated_followup_shown:{jid}"},
        )
        captured = _stub_email_send(monkeypatch)
        try:
            r = await _call_email_door_hanger(jid, tid)
            assert r["ok"] is True
            body = captured.get("html") or ""
            assert _ELEVATED_CTA_HEADING not in body, (
                f"CTA rendered on a suppressed case — landscape={landscape}, "
                f"unsub={unsubscribed}, dnc={do_not_contact}"
            )
            n = await _count_ledger(tid, jid)
            assert n == 0, (
                f"ledger row written for suppressed case — landscape="
                f"{landscape}, unsub={unsubscribed}, dnc={do_not_contact}"
            )
        finally:
            await _db().marketing_event_ledger.delete_many(
                {"tenant_id": tid, "event_key": f"elevated_followup_shown:{jid}"},
            )
            await _drain(tid, jid, cid)

    # 4 suppression paths.
    _run(_one_case(_elevated_seed_readings(0)))                       # <2 elevated
    _run(_one_case(_elevated_seed_readings(1)))                       # 1 elevated
    _run(_one_case(_elevated_seed_readings(3), landscape=True))       # landscape
    _run(_one_case(_elevated_seed_readings(3), unsubscribed=True))    # unsubscribed
    _run(_one_case(_elevated_seed_readings(3), do_not_contact=True)) # DNC


def test_door_hanger_elevated_ledger_is_idempotent_on_resend(monkeypatch):
    """Manual resend of the SAME job MUST keep the ledger count at
    exactly 1. Second render is idempotent via the compound-unique
    index on ``marketing_event_ledger``.
    """
    async def _go():
        tid = await _tenant_id()
        cid = await _mk_customer(tid)
        jid = await _mk_pool_job(tid, cid)
        from utils import now_iso, new_id
        await _db().service_reports.insert_one({
            "id": new_id(), "tenant_id": tid, "job_id": jid,
            "tech_id": "mike-tech", "submitted_at": now_iso(),
            "chemical_readings": _elevated_seed_readings(3),
        })
        await _db().marketing_event_ledger.delete_many(
            {"tenant_id": tid, "event_key": f"elevated_followup_shown:{jid}"},
        )
        # Clear any manual-cooldown row too so the second send lands.
        await _db().marketing_deliveries.delete_many(
            {"tenant_id": tid, "trigger_entity.id": jid,
             "trigger_entity.kind": "job_door_hanger"},
        )
        _stub_email_send(monkeypatch)
        try:
            r1 = await _call_email_door_hanger(jid, tid)
            assert r1["ok"] is True
            n1 = await _count_ledger(tid, jid)
            assert n1 == 1

            # Drain cooldown so the second manual send goes through.
            await _db().marketing_deliveries.delete_many(
                {"tenant_id": tid, "trigger_entity.id": jid,
                 "trigger_entity.kind": "job_door_hanger"},
            )
            r2 = await _call_email_door_hanger(jid, tid)
            assert r2["ok"] is True
            n2 = await _count_ledger(tid, jid)
            assert n2 == 1, (
                f"resend must not duplicate the ledger row (found {n2})"
            )
        finally:
            await _db().marketing_event_ledger.delete_many(
                {"tenant_id": tid, "event_key": f"elevated_followup_shown:{jid}"},
            )
            await _db().marketing_deliveries.delete_many(
                {"tenant_id": tid, "trigger_entity.id": jid,
                 "trigger_entity.kind": "job_door_hanger"},
            )
            await _drain(tid, jid, cid)

    _run(_go())

