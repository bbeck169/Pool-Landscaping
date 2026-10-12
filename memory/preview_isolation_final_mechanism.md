# Preview Data Leak · Final Mechanism

Feb-2026 P0 · final mechanism after Stage 2 commits
``be9ebdc69 → 21b919f90 → 9937fb78d → 46d0895ba``.

This file supplements the RCA at
``/app/memory/preview_data_leak_rca.md``. The RCA diagnosed the
root cause; this file documents the mechanism that landed and
why it can't regress silently.

## The four layers

### Layer 1 — Ingress decorator (``services/preview_isolation/``)

ASGI middleware installed on every FastAPI boot. On production env
(``APP_ENV=production``) it's a strict no-op — the single
``is_production_env()`` branch at ``PreviewMiddleware.__call__``
short-circuits before any body work.

On preview env, for every request whose path matches an entry in
``PII_INGRESS_REGISTRY`` (41 declared routes), the middleware:

1. Buffers the JSON request body.
2. Recurses through dicts + lists via ``sanitize_pii_payload``.
3. Replaces every known PII field with its deterministic synthetic
   equivalent via SHA-256 hash into a 10,000-bucket namespace.
4. REJECTs live Stripe pm_live_* / cus_live_*, raw SSN, DOB-in-dob-
   field, CC numbers, DL numbers with HTTP 400 and
   ``code=pii.ingress_rejected``.
5. Redacts PII tokens embedded in free-text fields (notes,
   service_notes, description, internal_notes, custom_fields
   values) via regex while preserving business text ("Gate code
   is 4321", "Prefers Thursdays").
6. Re-emits the sanitized body to the handler.

Non-JSON ingress (CSV, PDF, multipart) requires explicit handler-
side calls to ``sanitize_csv_rows`` / ``sanitize_pdf_extracted_rows``
— wired on ``POST /api/import/customers`` and the PDF-invoice
extractor pipeline in ``routers/imports.py``.

### Layer 2 — Boot-time scrubber
(``services/preview_isolation/scrubber.py``)

Runs ONCE per pod boot via ``asyncio.create_task`` from the
``startup`` event. Guards:

* Production env → strict no-op (identical ``is_production_env()``
  branch).
* Localhost-only Mongo (``MONGO_URL`` must contain ``localhost``
  / ``127.0.0.1`` — mirrors the ``scripts/scrub_preview_pii.py``
  guard).
* 24h dedup via ``audit_logs.event ∈ {pii_boot_scrub, pii_scrub}``
  — a crash-loop restart storm does zero work.

Scrubs 15 collections: primary customer-shape (customers, leads,
outreach_prospects, marketing_subscribers, widget_form_submissions,
instaquote_submissions, users role=customer), denormalized
snapshots (quotes/invoices/jobs/estimates/contracts/signed_contracts
/csat_responses/calendar_events ``customer_name`` + ``bill_to_*`` +
``signer_*``), free-text redaction (messages, communication_timeline,
outbound_emails, email_templates, sms_templates, webhook_events,
audit_logs), and drops stale geocode_cache rows.

### Layer 3 — Healthcheck
(``routers/preview_isolation_admin.py``)

``GET /api/admin/preview-isolation-status`` — admin-only on preview,
HTTP 404 on production. Reports:

* ``env``, ``db_name``, ``connected_mongo_host``.
* Registry status (declared PII routes vs app route table).
* PII shape audit (real-PII customer count — RED if > 0).
* Last boot-scrub summary.
* ``overall_status`` = roll-up of registry + PII shape (GREEN /
  AMBER / RED).

Returned to the admin dashboard; a persistent banner surfaces when
RED. CI test asserts production env returns 404 so the endpoint
can't accidentally leak its presence.

### Layer 4 — One-shot cleanup
(``memory/preview_scrub_commit4_report.md``)

Operational commit that invoked ``run_once(db, force=True)`` on
preview to clear the 120 real-PII customer rows that pre-dated
layer 1. Result: 2,283 rows scrubbed across 10 collections. PII
shape audit flipped RED → GREEN. The audit_logs row stamped by
this run satisfies the 24h dedup for subsequent boot scrubs.

## Why it can't regress silently

Documented up-front so future code reviews can enforce this
contract:

1. **ASGI middleware installed at app-boot** — on preview, every
   JSON request to a registered PII-ingress route is sanitized
   BEFORE the handler sees the body. Zero reliance on handler-
   level discipline. Adding a new JSON ingress route under the
   registry's regex scope (``/api/customers/*``, ``/api/leads/*``,
   ``/api/marketing/subscribers/*``, etc.) is auto-covered.
2. **Boot-time route-registry audit** — on preview env startup,
   ``audit_route_registry(app)`` walks the live FastAPI route
   table and reports registry status. AMBER = new PII-shaped
   routes shipped without being added to the registry. The admin
   healthcheck surfaces this; a follow-up commit promotes AMBER
   from log-WARN to hard-fail-boot once the current 20 advisories
   are addressed.
3. **Idempotent boot scrubber + 24h dedup** — catches rows that
   somehow bypass the decorator (one-off migrations, pre-existing
   data). Immutable deterministic synthetic mint — same real
   value always collapses to the same bucket, so admins can
   reproduce "which demo rows correspond to which prior real
   rows" via the mapping even without storing the plaintext.
4. **Production safety invariant proven by test** —
   ``tests/test_preview_isolation_decorator.py::
   TestProductionIsStrictNoOp`` asserts identity semantics on
   ``APP_ENV=production``. CI blocks any change that breaks that
   invariant.
5. **Healthcheck RED signal** — admin dashboard shows a RED
   banner whenever ``pii_shape_audit.customers_with_real_pii_shape
   > 0``. Prevents silent degradation — the next admin to open
   the dashboard sees the leak.
6. **Documented accepted risks** — the shared ``tenant_id`` with
   production is called out in ``/app/memory/preview_tenants.md``
   so a reviewer can't accidentally remove the sanitization
   mechanism thinking "tenant_id filters cover it".

## Commit chain

```
be9ebdc69  commit 1/5  decorator + registry + production safety tests
21b919f90  commit 2/5  boot scrubber + 24h dedup + production no-op
9937fb78d  commit 3/5  admin healthcheck + production 404
46d0895ba  commit 4/5  one-shot preview DB scrub + report (2,283 rows)
<HEAD>     commit 5/5  docs: whitelist + final mechanism (this file)
```

## Follow-up work (NOT in scope for this P0)

1. Promote the registry audit from WARN-only to hard-fail on
   preview once the 20 unregistered PII-shaped routes
   (``/api/signup/verify``, ``/api/leads/{lead_id}/send-sms``,
   ``/api/leads/{lead_id}/send-email``,
   ``/api/customer-portal/tos/{document_id}/accept``, etc.) are
   either added to the registry or declared exempt.
2. Wire the ``POST /api/signatures/public/sign/{token}/submit``,
   ``POST /api/public/csat/{token}/submit``, and other
   signature-capture routes to the sanitizer. Currently
   registered as ``kind=generic`` → no field synthesis, only
   free-text redaction via middleware fallback.
3. Admin dashboard banner that reads
   ``/api/admin/preview-isolation-status`` on page load and
   surfaces the RED status visually. Frontend work tracked
   separately.
4. Flip Fiber/Airtable/etc. webhook ingress to the sanitizer
   once those integrations ship.
