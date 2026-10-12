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

## Synthetic PII Shapes (reference for testers)

The preview isolation layer rewrites PII fields on ingress to a
narrow deterministic shape. Testers running regex checks on the
healthcheck or raw DB rows MUST use the shapes below — common
first-pass regex guesses (e.g. ``^555-\d{4,5}$``) are too narrow
and false-fail on legitimate synthetic rows.

### Phones — ``555-0BNNNN`` (10 chars total, 6 digits after ``555-``)

Format: ``555`` + ``-`` + band digit ``0`` + per-channel band digit
``B`` + 4-digit bucket slug ``NNNN``.

| Channel | Band | Example | Notes |
|---|---|---|---|
| Customer `phone` | ``01`` | ``555-012345`` | Primary customer phone. |
| Customer `mobile` / `phone_mobile` | ``02`` | ``555-029876`` | Mobile companion. |
| Lead `phone` | ``03`` | ``555-035432`` | Marketing/leads channel. |
| Subscriber `phone` | ``04`` | ``555-041987`` | Marketing subscribers. |

Compiled regexes used by the healthcheck + scrubber (keep tests in
lockstep with these):

```
# Full-strict (used by the healthcheck's non-synthetic detection):
^555-?0[1-4]\d{4}$

# Hyphen-optional (used by phone_raw / mobile_raw audit — digits-
# only companion fields):
^555-?0[1-4]\d{4}$
```

Reserved NANP namespace: ``555-0100`` through ``555-0199`` is the
fictional-use block per NANPA — the synthesizer stays well inside
it (``555-01xx…04xx`` ranges above). Any phone outside this pattern
on a preview row is PII and MUST be scrubbed.

### Emails — ``preview-<channel><bucket>@preview.local``

Example: ``preview-customer4163@preview.local``. Regex:
``^preview-(customer|lead|subscriber|portal)\d{4}@preview\.local$``.

### Names — ``Preview <Role><bucket-slug>``

Examples: ``Preview Customer4163``, ``Preview Lead0085``,
``Preview Subscriber2952``. Regex: ``^Preview (Customer|Lead|
Subscriber|Co )\s*\d{4}``.

### Addresses — ``<bucket> Preview St, Testville, AZ 85000``

The street number equals the bucket slug (collisions use the
same ``-ab`` nibble-suffix convention as names). City / state /
zip are fixed. Regex for the street component:
``^\d+ Preview\b``.

### Geocode hash — SHA-1 of the synthetic street

``customers.geocode_address_hash`` on preview is a SHA-1 of
``"<bucket> Preview St"`` (lowercased, whitespace-collapsed). It
is NOT a hash of the real address. See
``/app/memory/preview_isolation_blocker1_investigation.md`` for
the DB-level proof. The healthcheck audit (post-I2) treats a
non-null hash as benign IF the row's address matches the
``^\d+ Preview\b`` signature.

### Allowlisted demo-seed emails

Two emails are intentionally exempt from the email audit rule:
``customer@aquaterra.com`` and ``customer2@aquaterra.com``. These
are the seeded portal-demo accounts the ``seed_demo_second_
customer`` boot migration re-creates every start. Preserving the
exact email string is required for the portal login flow to
work; see the inline justification at
``routers/preview_isolation_admin.py:165-174``.

