# Auth Testing Notes — Pool & Landscaping of Vistancia

**Last verified:** Feb 2026 (K61 ship — `/api/auth/login` returns
`{access_token, user}` with a 233-char JWT).

## Login flow

```
POST /api/auth/login
Content-Type: application/json
{
  "email":    "super@aquaterra.com",
  "password": "password123"
}

→ 200 {
  "access_token": "<233-char JWT>",
  "user": {
    "id":     "…",
    "email":  "super@aquaterra.com",
    "role":   "super_admin",
    "name":   "Super Admin",
    ...
  }
}
```

Every subsequent call requires `Authorization: Bearer <access_token>`.
Token expiry is refresh-token-backed on the mobile client but each
individual `access_token` is short-lived (verify via `/api/auth/me`
if a stale token surfaces during a long test session).

## Seeded accounts (from `test_credentials.md`)

| Role         | Email                       | Password    |
|--------------|-----------------------------|-------------|
| super_admin  | super@aquaterra.com         | password123 |
| manager      | manager@aquaterra.com       | password123 |
| admin        | admin@aquaterra.com         | password123 |
| technician   | carlos@aquaterra.com        | password123 |
| technician   | landscaper@aquaterra.com    | password123 |
| technician   | mike@aquaterra.com          | password123 |
| customer     | customer@aquaterra.com      | password123 |

For any changes to auth logic (login, register, change-password, JWT
lifecycle, role gating) refer to `test_credentials.md` for the
change-password policy quirk (demo password `password123` deliberately
violates the new-password policy).

## Mobile-specific test notes

* Mobile app auth uses **fetch** (not axios).  All API errors thrown
  by `mobile/src/api.ts::request()` are now `ApiError` instances (K61
  · Feb-2026 ship) carrying:
    * `err.status`    — HTTP status code (number)
    * `err.detail`    — raw parsed FastAPI ``detail`` field (string / array / dict)
    * `err.message`   — humanised string (safe for `<Text>{err.message}</Text>`)
    * `err.kind`      — `"http"` for `ApiError`, `"network"` for `ApiNetworkError`.
* Network failures still throw `ApiNetworkError` with `err.kind === "network"`.
  The write-queue retries these on reconnect using the same
  `X-Idempotency-Key`; 4xx / 5xx are NOT retried automatically.
* Preview URL: use `REACT_APP_BACKEND_URL` from `frontend/.env`.  Local
  curls hit `http://127.0.0.1:8001` directly (Cloudflare 429s on the
  preview URL during aggressive automation).

## Common test flows

**Save-draft (K61.b.2, mobile)** —
```
PATCH /api/jobs/{id}/service-report
{
  "chemical_readings": [ {"key": "ph", "value": 7.5, "unit": ""}, ... ],
  "chemicals_added":   [ ... ],
  "checklist_items":   [ ... ],
  "notes":             "..."
}
→ 200 { …updated report doc… }
```

**Close-job (K61.a.2 + K61.c, mobile)** —
```
POST /api/jobs/{id}/service-report/submit
{}
→ 200 { …closed report… }
--- OR ---
→ 422 {
  "detail": {
    "detail":           "chemistry_core_readings_missing",
    "missing_fields":   ["free_cl","total_cl","alkalinity","ph","cya"],
    "missing_labels":   ["Free Cl","Total Cl","Alkalinity","pH","CYA"],
    "message":          "Cannot close job — required chemistry readings missing"
  }
}
```

Post-K61 the mobile client detects the 422 shape via
`err instanceof ApiError && err.status === 422 &&
err.detail?.detail === "chemistry_core_readings_missing"` and:
1. Highlights the missing fields inline via `setHighlightBodies({bodyIndex: [readingKeys]})`.
2. Runs the labels through `expandChemistryLabel()` (K60) and surfaces
   a single alert listing them.

Pre-K61 the equivalent detection ran on `e.response.data.detail`
(axios-shaped) and was **dead code** on the fetch-based client — every
close-job failure fell through to a generic "Close failed" alert with
no missing-field highlight.
