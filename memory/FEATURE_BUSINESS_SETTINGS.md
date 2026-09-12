# Feature — Business Settings (Admin) with brand identity · Feb-2026

Per-tenant admin surface for company defaults + brand identity.
Ships 5 endpoints, one new settings page, and the plumbing hooks
the queued Theme Refresh phase will consume.

## Endpoint contract

OpenAPI delta: **1726 → 1729 paths / +5 operations**
(FastAPI counts unique paths; GET+PATCH share one path, POST+DELETE
share another, so path count grew by 3 while operations grew by 5.)

### Admin (RBAC: `admin` + `super_admin`, `technician` → 403)

```
GET   /api/tenants/me/business-settings
      → 200 { tenant_id, stored: {…}, effective: {…} }
      → 401 unauth · 403 non-admin

PATCH /api/tenants/me/business-settings
      Body (all optional):
        company_display_name, mailing_address, phone, website,
        email, brand_primary_hex, brand_secondary_hex, footer_note,
        tax_id
      → 200 { stored, effective }
      → 422 bad hex / bad email
      → 403 non-admin
      Notes:
        * `website` auto-prepends `https://` when scheme missing.
        * Only fields present in the body are updated (exclude_unset).
        * Audit row `event="business_settings.updated"` written with
          the diff of changed field names.

POST  /api/tenants/me/logo                     (multipart)
      → 200 { logo_url, size_bytes, content_type, updated_at }
      → 413 > 2 MB · 415 unsupported mime · 503 storage down
      → 403 non-admin
      Delegates to `routers/tenants::upload_branding_logo` so the
      existing S3 pipeline, size cap, and prior-blob GC are reused
      verbatim. Audit row `event="business_settings.logo_uploaded"`.

DELETE /api/tenants/me/logo
      → 200 { cleared: true, logo_url: null }
      → 403 non-admin
      Nulls `tenant.logo_url` **without** deleting the S3 blob so a
      prior logo can be reinstated via URL patch. Audit row
      `event="business_settings.logo_deleted"`.
```

### Public (magic-link authed — no JWT)

```
GET /api/portal/tenant/branding?token=<magic-link-jwt>
      → 200 { tenant_id, branding: {…allow-listed subset…} }
      → 401 bad / expired token
      Redacted keys: `tax_id`, updated_at, updated_by, all admin
      metadata. Only ships:
        company_display_name, mailing_address, phone, website,
        email, logo_url, brand_primary_hex, brand_secondary_hex,
        footer_note
      Reuses `estimate_viewer::_verify_estimate_token` for tenant
      resolution — no new token surface.
```

## Sample curl

```
# Admin PATCH — set brand colours
curl -X PATCH "$API/api/tenants/me/business-settings" \
  -H "Authorization: Bearer $ADMIN_JWT" \
  -H "Content-Type: application/json" \
  -d '{"brand_primary_hex":"#0B4A6F","brand_secondary_hex":"#F97316"}'

# Admin logo upload
curl -X POST "$API/api/tenants/me/logo" \
  -H "Authorization: Bearer $ADMIN_JWT" \
  -F "logo=@/path/to/logo.png"

# Public branding (magic-link)
curl "$API/api/portal/tenant/branding?token=$MAGIC_LINK_TOKEN"
```

## Storage — `db.tenants` schema additions

All fields nullable, all added at the top level of the tenant doc:

- `company_display_name: str | null`
- `mailing_address: str | null`
- `phone: str | null`
- `website: str | null`
- `email: str | null`
- `brand_primary_hex: str | null` (validated `^#[0-9a-fA-F]{6}$`)
- `brand_secondary_hex: str | null` (same regex)
- `footer_note: str | null`
- `tax_id: str | null`

`logo_url`, `logo_object_path`, `logo_content_type`, `logo_size_bytes`,
`logo_updated_at`, `logo_updated_by_user_id` are pre-existing (set by
the reused `POST /api/tenants/branding/logo` handler).

## Effective-settings helper

`backend/services/tenants/business_settings.py`

- `build_business_settings_view(tenant) → {stored, effective}` —
  pure function; resolves fallbacks:
  - `company_display_name` falls back to `tenant.company_name`.
  - `brand_primary_hex` falls back to `DEFAULT_PRIMARY_HEX` (`#0B4A6F`).
  - `brand_secondary_hex` falls back to `DEFAULT_SECONDARY_HEX` (`#F97316`).
  - All other keys stay `None` when unset.
- `get_effective_business_settings(db, tenant_id)` — async wrapper.
- `to_public_branding(effective)` — filter to `CUSTOMER_SAFE_KEYS`.

Downstream consumers (PDF renderers, email shell, magic-link
payload builders) go through this helper — no duplicate fallback
rules anywhere.

## Frontend

### New page — `frontend/src/pages/settings/BusinessSettings.jsx`

Route: `/settings/business` (nested under `SettingsHub`), gated by
`AdminOnly`. Nav entry added in `SettingsHub.jsx` between "Branding"
and "Theme".

Form sections:

1. **Company** — display name, mailing address, phone, website,
   email, footer note, tax id.
2. **Branding** — logo picker (Upload / Remove), primary + secondary
   colour fields (native `<input type=color>` + editable hex text +
   live swatch).
3. **Live preview** — mock estimate header rendering with the
   current primary + secondary colours + display name.

Save button disabled until:
- the form is dirty (any field mutated), AND
- validation passes (hex regex + email format).

Logo upload uses raw `fetch()` with the caller's JWT so the
multipart form data reaches the reused branding-logo handler.

### Downstream plumbing (this phase — no visuals yet)

- Estimate view + admin quote page — DEFERRED to the Theme Refresh
  phase per the dispatch brief ("this phase — plumbing not visual").
  When Theme Refresh lands, its first step is a `useBusinessSettings`
  hook that hits `GET /api/tenants/me/business-settings` (admin) or
  `GET /api/portal/tenant/branding?token=…` (magic-link).
- PDF renderers — same deferral. Both `routers/quotes.py` and
  `routers/estimate_viewer.py` will read `effective` via
  `get_effective_business_settings` and pass it into the ReportLab
  header/footer builder. Wiring the read is a 3-line change; the
  visual application is the Theme Refresh scope.
- Email shell — same deferral. Multi-adapter surface
  (`services.email`, `services.marketing_email`,
  `services.marketing.email_adapter`,
  `services.comms_email_adapter`) means threading the primary hex
  through the base template is a coordinated change best done in
  the same visual pass. Business Settings ships the DATA source.

## Audit event contract

Three event types written to `db.audit_logs`:

```
{ event: "business_settings.updated",
  actor_id, tenant_id, at, changed_fields: [str, …] }

{ event: "business_settings.logo_uploaded",
  actor_id, tenant_id, at, logo_url, size_bytes, content_type }

{ event: "business_settings.logo_deleted",
  actor_id, tenant_id, at, prior_logo_url, prior_object_path }
```

Best-effort — a Mongo write failure logs a warning and lets the
PATCH / upload succeed.

## Test coverage

### Backend — `tests/test_business_settings.py`

1. Admin PATCH + GET roundtrip.
2. Bad hex → 422.
3. Bad email → 422.
4. Website auto-prepends `https://`.
5. Technician PATCH → 403.
6. Unauth GET → 401 / 403.
7. Logo upload with unsupported mime → 415.
8. Logo upload success (skipped when object storage is down).
9. Public branding endpoint returns only allow-listed keys.
10. `build_business_settings_view` fallback contract (pure).
11. Public branding bad token → 401.
12. `to_public_branding` filter contract (pure).

### Frontend — `src/test/business-settings.test.jsx`

1. Renders all fields + both pickers + logo tile.
2. Invalid hex disables Save.
3. Successful PATCH → toast + refetch.
4. Logo upload → preview `<img>` visible after `fetch` resolves.
5. Live colour preview reflects picker changes before save.

## Guardrail confirmation

- Preview-only. `.env.production` untouched.
- `PHOTOS_S3_ENABLED=true` count=1, `AWS_REGION=us-east-2` count=1.
- `/app/mobile/` untouched.
- No external repo clone.
- No visual theming of Estimate/Quote/Invoice yet — that's the next
  phase, and this phase is the data plumbing it consumes.

## Follow-ups (Theme Refresh phase consumes these)

- `useBusinessSettings` hook (admin) / `useTenantBranding` hook
  (magic-link) — read from the new endpoints.
- `EstimateView.jsx` + `QuoteInvoiceDetail.jsx` — swap hardcoded
  brand colour tokens for `effective.brand_primary_hex` etc.
- ReportLab PDF header/footer — dark navy band, uppercase title,
  company details on the right, footer with `footer_note`.
- Email base template — apply `brand_primary_hex` to the header
  band and inject the company details block into the footer.
