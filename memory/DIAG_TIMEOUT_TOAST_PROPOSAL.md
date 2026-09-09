# DIAGNOSTIC — Recurring 30s "Request timed out" red toast

**Status:** PROPOSAL ONLY (no code shipped yet). Human approval requested before implementation.

**Problem:** users see a red toast reading "Request timed out" after ~30s on certain flows. We have no ambient telemetry telling us WHICH request(s), from WHOM, or under what backend load. The current ask ("share the DevTools cURL") depends on the user having devtools open at the right moment. That's flaky.

**Goal:** replace user-side devtools dependency with ambient signal — both server-side (long-running requests get logged with all the context we need) and client-side (when the toast actually fires, telemetry POSTs the offending request context back to us).

---

## 1. Server-side slow-request log

### 1.1 Middleware
Add a FastAPI middleware (or extend the existing request-logging middleware if one exists — need to grep before implementing) that:

- Measures wall-time from request start to response send.
- If `duration_ms > 5000` OR `status_code == 504`, logs a structured line:

```
slow_request_warn method=<GET|POST|...> path=<url> tenant=<tid> user=<uid> role=<role> duration_ms=<int> status=<int> request_id=<uuid>
```

- `request_id` = a `uuid4()` generated on request arrival, echoed in an `X-Request-Id` response header (see §2.4).
- No PII in the log line — no query strings, no body. Just method + path (bucketed) + tenant + user id.

### 1.2 Threshold choice
- **5s WARN** (log-only)
- **10s WARN + prometheus counter increment `crm_slow_request_total`** (metrics counter, no alerting yet)
- **25s ERROR** (about to hit the 30s client timeout — surface loudly in `backend.err.log`)

### 1.3 Storage
- Log-only into `backend.err.log` at WARN/ERROR. No DB table. Existing log-shipping (if any) picks it up.
- Prometheus counter for aggregate rate — no per-request timeseries (cardinality explosion risk).

### 1.4 Sampling
- No sampling at 5s+ — the volume should be low. If it turns out to be noisy, add `SLOW_REQUEST_LOG_SAMPLE_RATE` env var (default 1.0) later.

---

## 2. Client-side timeout telemetry

### 2.1 What fires the toast?
The 30s "Request timed out" toast is fired by `/app/frontend/src/api.js` (need to confirm — grep in Phase A of implementation). Wrap the fetch/axios timeout handler.

### 2.2 New endpoint
```
POST /api/admin/client-telemetry/timeout
Auth: existing session JWT (must be a logged-in user, any role)
Body:
{
  "request_url": "/api/foo/bar",
  "request_method": "POST",
  "started_at": "2026-02-09T18:00:00.000Z",
  "ended_at":   "2026-02-09T18:00:30.000Z",
  "duration_ms": 30001,
  "route_path": "/dispatch",         # current React Router path
  "user_agent":  "...",              # navigator.userAgent (redact IP)
  "request_id":  "<X-Request-Id-if-caught>",
  "app_version": "<git sha / build id>"
}
```

- Rate-limit: max 20 posts per session per minute (protects the endpoint from a runaway loop).
- Persists to `db.client_timeout_events` with a 30-day TTL index on `created_at`.

### 2.3 Auth
- Behind `get_current_user` — no anonymous posts. If the user isn't logged in when the timeout fires, the toast renders as today but no telemetry is sent (fine — logged-out timeouts are usually the login endpoint itself, which is already visible in backend logs).

### 2.4 Correlation via `X-Request-Id`
- Backend middleware attaches `X-Request-Id: <uuid4>` on every response.
- `api.js` grabs it (accessible on the failed-response object even on 504s) and includes it in the telemetry POST.
- When we cross-reference: one client telemetry event ↔ zero-or-one server slow-request log line (server may not have logged it if it responded < 5s but the client still timed out on network egress).

### 2.5 UX
- Toast copy: same as today. No user-facing change.
- Optional (behind a feature flag): append `"Report: {short_id}"` to the toast so if the user does complain, we can search for that id in the DB. Nice-to-have, not required for Phase 1 of this proposal.

---

## 3. Admin console — read-only surface

Deferred to a follow-up (once we have 1-2 weeks of data). For now the DB collection + backend logs are enough for us to grep manually.

Sketch for the follow-up:
- `GET /api/admin/client-telemetry/timeouts?since=<ts>&limit=100` — admin-only list view.
- Simple table in Admin → Diagnostics: last 100 client timeouts with tenant, user, url, duration, and a "correlate with server log" pointer.

---

## 4. Guardrails

1. **No PII in telemetry.** URLs must be normalized (strip query strings, replace `/customers/{uuid}` with `/customers/:id` at write-time in the middleware if a whitelist is available). Fallback: log the full path but never the query or body.
2. **No sensitive headers in the client POST.** No cookies, no bearer tokens. The endpoint uses the existing auth session, not a re-transmitted token.
3. **BYO fallback compatibility.** This work is purely observational — no changes to Resend/RC/AI/Maps adapters. Cannot regress the P0 BYO empty-credentials fix.
4. **Rate limit + 30-day TTL** on `db.client_timeout_events` — bounded storage cost.
5. **No feature flags required to disable — but** a kill-switch env var `CLIENT_TIMEOUT_TELEMETRY_ENABLED=false` lets the operator turn it off instantly without a deploy if it turns out to be noisy.

---

## 5. Phasing

### Phase 1 (this proposal — ship first)
- Server middleware for slow-request logging (§1).
- `X-Request-Id` header on all responses (§2.4).
- Client-side wrap of the timeout toast handler → POST to new endpoint (§2.1-2.4).
- New endpoint + `db.client_timeout_events` with TTL.

**Acceptance criteria:**
- Force a 30s timeout in preview (curl `/api/health/slow?sleep=35s` if such a hook exists, else pause the backend). Verify:
  1. Server logs a WARN line at 5s and an ERROR line at 25s with tenant + user + path + request_id.
  2. Client fires the toast + POSTs to `/api/admin/client-telemetry/timeout` with the same request_id.
  3. `db.client_timeout_events` has a row with duration_ms > 30000.
- No regressions in Resend/RC/Stripe/Maps flows (grep-based sanity).

**Estimate:** ~0.5 day.

### Phase 2 (deferred)
- Admin diagnostics UI (§3).
- Prometheus scraping wiring if not already in place.

---

## 6. What this does NOT do

- Does not fix the underlying slowness. It gives us observation.
- Does not distinguish "backend is slow" from "network egress is slow from the customer's ISP". The client telemetry captures the latter; server logs the former; the intersection is where we point the finger.
- Does not alter the 30s timeout value in `api.js` (do that later if the data suggests it should be higher/lower).

---

**Status:** PROPOSAL. Awaiting human approval before Phase 1 implementation.
