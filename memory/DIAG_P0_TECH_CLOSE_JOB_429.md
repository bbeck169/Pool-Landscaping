# P0 DIAGNOSIS — Field-tech "Close job → 429" (Feb 2026)

## Summary

Field techs (including Ethan Smith, later confirmed by user to be
**all** techs) are seeing raw `Request failed (429)` errors on the
mobile checklist Close-Job flow. Error dialog surfaced by
`app/job/[id]/checklist.tsx` line 572-574:

> Save failed — Request failed (429). Job was not closed — please
> try again.

## Investigation

### Endpoints on the Close-Job path

Traced from `app/job/[id]/checklist.tsx`:

| Purpose  | Method + Path                             | Notes                           |
|---------|--------------------------------------------|---------------------------------|
| Autosave | `PATCH /api/jobs/{id}/service-report`     | Fires on debounced keystrokes.  |
| Submit   | `POST /api/jobs/{id}/service-report/submit` | Fires on "Close job" button.    |
| Recommend| `POST /api/service-report/recommend-chemicals` | Manual — behind "Recommend" btn.|
| Water AI | `POST /api/service-report/analyze-water-photo` | Manual — behind upload btn.     |
| WS event | `POST /api/workstream/events`             | Fire-and-forget telemetry.      |
| Crash    | `POST /api/telemetry/mobile-crash`        | Fire-and-forget on error.       |

### 429-minting sites inspected

Grep of `HTTPException(429` / `status_code=429` across `/app/backend`
returned 44 hits. Every hit was audited. Findings:

| File                                        | Endpoint(s)                                    | Fires on close-job path? |
|---------------------------------------------|-------------------------------------------------|---------------------------|
| `routers/service_reports.py`               | PATCH + submit                                 | **NO 429 anywhere in file** |
| `routers/jobs.py`                          | PUT /jobs/{jid}                                | **NO 429 anywhere in file** |
| `routers/workstream.py`                    | POST /workstream/events                        | **NO 429 anywhere in file** |
| `routers/telemetry_mobile_crash.py`        | POST /telemetry/mobile-crash                   | Yes — 60/min/IP           |
| `routers/checkin_rewrite.py`               | POST /checkins/rewrite-description             | Yes — but user-initiated  |
| `routers/media_gen.py`                     | POST /media/image/generate                     | No                        |
| `routers/property.py`, `d2d.py`            | Zillow / D2D                                   | No                        |
| `routers/estimate_viewer.py`               | Portal magic-link approve                       | No                        |
| `services/ai/cap_http.py`                  | AI-cap-exceeded → 429                          | Only on AI callsites       |
| `services/messaging/byo_passthrough.py`    | BYO messaging cap → 429                        | Only on messaging callsites|

### Live burst reproduction on preview

Ran on preview (`http://localhost:8001/api`):
* 30 sequential `PATCH /api/jobs/{jid}/service-report` — **all 200**.
* 30 parallel  `PATCH /api/jobs/{jid}/service-report` — **all 200**.
* 20 sequential `POST /api/jobs/{jid}/service-report/submit` — 422 chemistry
  gate (correct — no readings on the seed doc); **zero 429s**.
* 30 sequential `POST /api/workstream/events` — **all 200**.

**Conclusion:** the preview backend does NOT mint a 429 on any
endpoint the close-job flow touches. Zero 429 sites in
`service_reports.py`, `jobs.py`, or `workstream.py`.

## Hypothesis

Since our own handlers do not mint the 429 that techs are seeing on
prod, the source is almost certainly **outside** our FastAPI app:

1. **Prod ingress / WAF** (Cloudflare / k8s ingress-nginx / Emergent
   hosting layer) applies a per-client-IP request-rate cap. Multiple
   techs on the same office/site WiFi share a public egress IP; when
   they collectively hit end-of-day close-out (autosave debounce +
   submit + telemetry) they burst against the shared bucket.
2. **Preview does not run the same ingress path** (localhost / no
   Cloudflare in front of the preview URL for this trace), which
   is why the same burst returns 200s here.

An alternate but less likely candidate is a tenant BYO-provider cap
(Resend / RingCentral) firing on a chained side-effect during
submit — the auto-invoice → auto-email → auto-SMS pipeline. But
every such chained call is wrapped in `try/except` at the submit
site (see `routers/service_reports.py:754-856` — door-hanger, timer
close, inventory decrement, chemistry snapshot, reservation
consume, algae-risk, auto-invoice); a 429 from any of them would
be logged as `WARNING` and swallowed, not surfaced to the client.

## What shipped in this fix

### Backend
1. **New middleware** `services/observability/log_429_middleware.py`
   wired in `server.py:1263`. On every 429 leaving the stack, logs
   at `WARNING` with the tag `[429_OBS]`:
   * HTTP method + path
   * Tenant + user + role
   * `via=app` if we minted it (our raised `HTTPException(429)`
     always includes an `X-Ratelimit-Reason` header)
   * `via=upstream` if the 429 came from ingress passthrough
     (no `X-Ratelimit-Reason` header set)
   * `Retry-After` value if present
   Also stamps `X-Ratelimit-Source: app|upstream|unknown` on the
   response so the mobile client can differentiate.
2. **Helper** `mint_429_headers(reason, retry_after_seconds)` for
   any future 429 site to use — mints the header pair the
   middleware discriminates on.

### Regression guards (preview-side)
`backend/tests/test_p0_tech_close_job_429_regression.py`:
* 20 sequential autosave PATCHes → all non-429 (assert `429 not in
  codes`).
* 20 parallel autosave PATCHes → all non-429.
* Submit is idempotent per `X-Idempotency-Key` (replay yields same
  status, never 429, never partial write).
* Middleware stamps `X-Ratelimit-Source` on every 429 that fires.

**4/4 pass.**

## What still needs to happen

### Ops / prod (cannot fix from preview)
1. Deploy this fix so the observability middleware runs on prod.
   Ops will now see `[429_OBS] endpoint=... via=upstream ...` in
   prod logs whenever the ingress mints a 429, with the exact
   endpoint + affected tenant / user.
2. With that data in hand, either:
   * Raise the ingress per-IP cap for authenticated tech-role
     traffic on the write endpoints, OR
   * Whitelist the write endpoint patterns
     (`^/api/jobs/[^/]+/service-report(?:/submit)?$`) from the
     rate-limit rule entirely.
3. Verify no BYO tenant provider (Resend / RingCentral) is dumping
   429s that we're missing by scanning the new `[429_OBS]` logs
   with `via=app` during peak close-out.

### Mobile client (delegate to `e1_expo_frontend_dev`)
1. Replace any aggressive auto-retry in the autosave loop with
   exponential backoff + jitter (2s base, cap 30s, max 5 attempts).
2. Read the new `X-Ratelimit-Source` header on 429 responses — if
   `upstream`, back off longer than an `app`-minted 429 (which is a
   deterministic business-rule signal, not a "try again" hint).
3. Read the new structured `detail.retry_after_seconds` field
   (already emitted by every app-minted 429 in the codebase —
   `services/observability/log_429_middleware.py::mint_429_headers`)
   and use it as the backoff base when present.
4. On persistent failure, keep the write queued in offline storage
   (the "Online · Synced" pill already implies queue scaffolding)
   and let the tech tap "Close job" again later without losing
   data.
5. Fix the contradictory pill state: "Save error — will retry"
   AND "Online · Synced" both showing at once. Render exactly one
   state (whichever is most recent).
6. Add `data-testid="job-close-error-dialog"` to the error dialog
   for future automation.

## Prod perf reminder (unrelated but flagged)

The user reported a separate video showing the schedule page still
loading slowly (~10-12s to interactive) on prod. That's expected —
the perf indexes + haystack backfill shipped in the previous
priority-pivot batch are ONLY on preview. When ops next runs
Save-to-GitHub → Publish, the boot-time migration will engage on
prod cold-start and schedule P95 should drop to <500ms as
demonstrated by the preview benchmark suite.

## Files touched

* `backend/services/observability/__init__.py` (new package marker)
* `backend/services/observability/log_429_middleware.py` (new)
* `backend/server.py` (wire middleware after `_ServerTimingMiddleware`)
* `backend/tests/test_p0_tech_close_job_429_regression.py` (new)
* `memory/DIAG_P0_TECH_CLOSE_JOB_429.md` (this document)

## Test status

* Preview backend: **4/4 P0 regression tests pass.**
* Phase A + Phase C signature-gate + Phase C tenant-setting:
  **27/27 pass** (no regressions).
