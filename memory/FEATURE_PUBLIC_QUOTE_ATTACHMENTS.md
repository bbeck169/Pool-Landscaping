# Feb-2026 · Public Quote Attachments

Adds a customer-facing attachments surface end-to-end on the
magic-link viewer: server payload → tokenised download route →
in-viewer downloads → reminder-email links. Admin path
(`/api/files/{id}/download`) is unchanged (admin-only).

## Touched files

| File | Change | LOC delta |
| ---- | ------ | --------- |
| `backend/routers/estimate_viewer.py` | `_build_payload` now emits `attachments: [...]` when a `magic_token` is threaded in; new public route `GET /api/portal/quotes/via-token/files/{file_id}?token=…` + `_resolve_url_base` helper | +112 / −2 |
| `backend/emailer.py` | `_estimate_reminder_html` accepts `attachments` + `magic_token` and renders a click-through `<ul>` (falls back to legacy count copy); `send_estimate_reminder_email` loads per-file rows + threads token through | +80 / −7 |
| `backend/routers/quotes.py` | Two `send_estimate_reminder_email(...)` call sites now forward `magic_token=tok` | +3 |
| `frontend/src/components/EstimateView.jsx` | Attachments block injected via the existing `termsSection` slot (surgical, no shell prop bump); `_fmtAttachmentSize` helper | +52 |
| `frontend/src/components/EstimateView.css` | `.ev-attachments-*` block + `< sm` full-width Download button | +90 |
| `frontend/src/test/estimate-view-attachments.test.jsx` (NEW) | 2 Vitest tests | +180 |
| `backend/tests/test_public_quote_attachments.py` (NEW) | 3 Pytest tests (real S3 round-trip) | +230 |

## Payload contract (`GET /api/portal/quotes/via-token`)

New field on the viewer payload:

```json
{
  ...existing fields...,
  "attachments": [
    {
      "id": "file-abc123",
      "filename": "site-plan.pdf",
      "content_type": "application/pdf",
      "size": 1500000,
      "url": "https://app.plofv.com/api/portal/quotes/via-token/files/file-abc123?token=<same-jwt-as-caller>"
    }
  ]
}
```

Query used to populate it:

```py
{
    "tenant_id":           tenant["id"],
    "linked_entity_type":  "invoice",   # unified label for quotes + invoices
    "linked_entity_id":    est["id"],
    "purpose":             "invoice_attachment",
    "is_deleted":          {"$ne": True},
}
```

The `linked_entity_type` value is **`"invoice"`** (not `"quote"`) —
this is the existing convention already used by
`frontend/src/components/quotes/InvoiceAttachments.jsx` (line 8):
that component covers BOTH the invoice branch AND the estimate
branch of `QuoteInvoiceDetail`. Documented + verified via
`grep -rn "linked_entity_type" /app/backend /app/frontend`.

`url` is absolute when `APP_PUBLIC_URL` env is set (production
canonical host); otherwise reconstructed from the incoming
`Request.base_url`. Falls to a relative path only if neither is
resolvable — the browser then fills in the origin.

## New route contract

```
GET /api/portal/quotes/via-token/files/{file_id}?token=<magic-link-jwt>
```

Auth path FORKS the same `_verify_estimate_token` +
`_load_est_from_token` helpers the viewer uses — no bespoke JWT
verification. Response contract:

| Case | Status |
| ---- | ------ |
| Correct token, file belongs to the token's quote | **200** + `Content-Type: <file>` + `Content-Disposition: attachment; filename="<name>"` + `Cache-Control: private, no-store` |
| Missing token (query param absent) | **422** (FastAPI required-param validator) |
| Invalid / expired / wrong-`sub` token | **401** (`_verify_estimate_token`) |
| Token valid but file's quote / tenant differs | **403** |
| File soft-deleted (`is_deleted=True`) | **410** |
| File not found | **404** |
| File storage not configured on server | **503** |
| S3 read fails downstream | **502** |

**Filename disposition** is `attachment; filename="<sanitised>"` —
the customer explicitly clicked "Download", so we force download
in browsers rather than the admin route's `inline` fallback.

Admin `GET /api/files/{file_id}/download` is **unchanged**:
still requires admin-auth Bearer header (or `?auth=<token>` for
`<img src>` compat), still 401 for anon, still admin-tenant
scoped.

## Reminder email contract

`send_estimate_reminder_email(inv, tenant, review_url, *,
override_to=None, magic_token="")` — new `magic_token` kwarg.

When `magic_token` is provided AND ≥1 attachment is found, the
template renders a clickable `<ul>` inside a subdued card:

```html
<div style="margin-top:14px;padding:12px 16px;background:#F8FAFC;...">
  <div style="font-weight:700;color:#0F172A;font-size:13px;margin-bottom:4px;">
    Attachments
  </div>
  <ul>
    <li>
      <a href="{APP_PUBLIC_URL}/api/portal/quotes/via-token/files/{fid}?token={tok}"
         style="color:#0891b2;text-decoration:none;font-weight:600;">
        site-plan.pdf
      </a>
      <span style="color:#64748b;font-size:12px;">(1.4 MB)</span>
    </li>
    ...
  </ul>
</div>
```

When either the attachments list is empty OR the caller didn't
pass `magic_token` (legacy callsites), the template falls back to
the pre-existing "N attachments included" copy — no regression.

Both callers in `routers/quotes.py`
(`send-to-customer` + the reminder path) were updated to forward
their locally-minted `tok` as `magic_token=tok`. No bare
`/api/files/{id}/download` refs are emitted in any themed email.

## Frontend contract

`EstimateView` renders `data.attachments` immediately below the
line-items totals + above the Terms & Conditions block:

* Section container: `data-testid="estimate-attachments-section"`
  (absent when the array is empty or missing).
* Per row: `data-testid="estimate-attachment-row-<i>"`.
* Per Download button: `data-testid="estimate-attachment-download-<i>"`
  with `target="_blank" rel="noopener noreferrer"` and
  `href={att.url}` (already absolute + tokenised).
* Responsive: horizontal row at ≥ sm, full-width stacked card + 44 px
  min tap target at < sm.

`_fmtAttachmentSize(bytes)` mirrors the backend
`_human_size(bytes)` so the "1.4 MB" size string matches in both
the on-page list AND the reminder email.

## Tester runbook (curl recipes)

```bash
# Set up
API=$(grep REACT_APP_BACKEND_URL /app/frontend/.env | cut -d '=' -f2)
TOK=$(curl -s -X POST "$API/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@aquaterra.com","password":"password123"}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

# Reuse OR create a quote. Grab an existing one:
QID=$(curl -s -H "Authorization: Bearer $TOK" \
  "$API/api/quotes?limit=5" \
  | python3 -c 'import sys,json
d=json.load(sys.stdin)
items = d if isinstance(d, list) else (
  d.get("items") or d.get("quotes") or []
)
print(items[0]["id"] if items else "")')

# Upload an attachment via the admin file router.
echo "%PDF-1.4 hi %%EOF" > /tmp/probe.pdf
FID=$(curl -s -X POST "$API/api/files/upload" \
  -H "Authorization: Bearer $TOK" \
  -F "purpose=invoice_attachment" \
  -F "linked_entity_type=invoice" \
  -F "linked_entity_id=$QID" \
  -F "file=@/tmp/probe.pdf;type=application/pdf" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')

# Mint the magic-link token.
MTOK=$(curl -s -H "Authorization: Bearer $TOK" \
  "$API/api/quotes/$QID/magic-link" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')

# 1. Viewer payload shows attachments.
curl -s "$API/api/portal/quotes/via-token?token=$MTOK" \
  | python3 -c 'import sys,json;p=json.load(sys.stdin);print(p["attachments"])'

# 2. Correct-token download → 200 + PDF bytes.
curl -sD - "$API/api/portal/quotes/via-token/files/$FID?token=$MTOK" \
  -o /tmp/downloaded.pdf | head -12
file /tmp/downloaded.pdf                        # should say "PDF document"

# 3. Missing token → 422 (required query param).
curl -s -o /dev/null -w '%{http_code}\n' \
  "$API/api/portal/quotes/via-token/files/$FID"

# 4. Invalid token → 401.
curl -s -o /dev/null -w '%{http_code}\n' \
  "$API/api/portal/quotes/via-token/files/$FID?token=not-a-jwt"

# 5. Wrong-quote token → 403.  (Mint a token for a DIFFERENT quote,
# then hit FID with it.)
QID2=$( ...pick a second quote id... )
MTOK2=$(curl -s -H "Authorization: Bearer $TOK" \
  "$API/api/quotes/$QID2/magic-link" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')
curl -s -o /dev/null -w '%{http_code}\n' \
  "$API/api/portal/quotes/via-token/files/$FID?token=$MTOK2"

# 6. Admin /api/files/{id}/download still requires admin auth → 401.
curl -s -o /dev/null -w '%{http_code}\n' \
  "$API/api/files/$FID/download"
```

## Test-suite status

* **Pytest** (`test_public_quote_attachments.py`): **3 passed** in
  ~5.6 s — real S3 round-trip via `/api/files/upload` +
  `/api/portal/quotes/via-token/files/*`. Adjacent suites
  (`test_email_attachment_count.py`, `test_quote_group_decline.py`,
  `test_quote_send_to_customer.py`, `test_quote_mark_sent.py`,
  `test_email_theming.py`, `test_email_theming_logo_aspect.py`,
  `test_email_preview.py`,
  `test_outcome_c_estimate_quote_rename.py`) → **94 passed / 1
  skipped**.
* **Vitest**: `571 files passed | 1 skipped · 4307 passed | 34
  skipped · exit 0` (+2 from new file, +5 net vs baseline 4305).
  No regressions.
* **Runtime**: `curl /` → 200, `curl /api/openapi.json` → 200,
  **paths = 1735** (1734 + the new
  `GET /api/portal/quotes/via-token/files/{file_id}` route).

## Out of scope

* Mobile Expo parity — flagged, delegated separately.
* Any other email template beyond `send_estimate_reminder_email`.
* Any change to `/api/files/{id}/download` auth (still admin-only).
* Attaching real bytes to outgoing emails (Option A: links only).
