# Preview Tenants Whitelist

Feb-2026 P0 · authoritative list of ``tenant_id`` values that are
LEGIT preview tenants on the preview environment. Consulted by:

* ``services/preview_isolation/config.py::PREVIEW_TENANT_WHITELIST``
  (reads this file at import).
* ``services/preview_isolation/scrubber.py`` (future: scope the
  scrubber to whitelist tenants when per-tenant selectivity is
  wanted — current scrubber scans the full DB because the pod
  only hosts preview + aquaterra data).
* ``routers/preview_isolation_admin.py`` (healthcheck reports
  the whitelist size).

Any UUID-shaped token appearing inside a code fence or inline
backticks below is picked up by the parser. One UUID per line is
preferred.

## Legitimate preview tenants

### aquaterra demo tenant
```
affdfbfa-88b9-4baa-ae45-2ef78531b6e4
```
Slug: ``aquaterra``.  Name: ``Pool & Landscaping of Vistancia``.

## Accepted Risk — Shared ``tenant_id`` with Production

Preview and production share tenant_id
``affdfbfa-88b9-4baa-ae45-2ef78531b6e4`` because preview was seeded
with the real business brand on 2026-08-19. Re-FK would touch 10+
collections (customers, jobs, quotes, invoices, service_reports,
estimates, photos, videos, email_templates, sms_templates,
contracts, etc.) and is a tracked future-work item.

Risk is accepted because:

* Preview and production share the same pod (verified Feb-2026 —
  single ``mongodb://localhost:27017`` on the Emergent-managed
  container). There is no cross-env Mongo surface to protect
  against via tenant_id separation.
* The PII-sanitization decorator at ingress + the boot-time
  scrubber are the enforcement mechanism — ``tenant_id`` is NOT
  the safety boundary. See
  ``/app/memory/preview_data_leak_rca.md`` for the full RCA.
* The RCA + commit chain
  (``be9ebdc69 → 21b919f90 → 9937fb78d → 46d0895ba``) ships four
  independent layers that each have to fail for a real PII row to
  persist: ingress decorator, boot scrubber, 24h-dedup audit, +
  the healthcheck RED alert on the admin dashboard.

## Future preview tenants

If a NEW preview environment is provisioned, it MUST:

1. Carry a tenant with slug prefix ``preview-`` or ``demo-``
   (checked by the advisory warning in the tenant-provisioning
   path).
2. Add its ``tenant_id`` here BEFORE the first PII-bearing
   ingress runs, so the healthcheck recognizes it as legit.
3. Keep its ``MONGO_URL`` pointed at a localhost mongod — the
   scrubber refuses to run against a remote cluster.

## Tenants explicitly OUT of scope

Every other UUID observed in the ``tenants`` collection — the
1,700+ demo/test tenants under slugs like ``test-autogen-*``,
``p22c-*``, ``TEST-uncat-*`` — are regression-test fixtures and
not real preview tenants. They are PII-scrubbed by the same boot
scrubber (which iterates the full ``customers`` collection, not a
per-tenant whitelist) and don't need to be enumerated here.
