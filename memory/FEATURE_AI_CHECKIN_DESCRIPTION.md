# Feature: AI check-in description button ("✨ AI Write")

**Date**: Feb-2026
**Status**: Backend + web frontend complete. Mobile parity delegated
separately (mobile team runs after web verifies).

Adds a one-tap AI-generated description button to the admin
check-in moderation edit view. Backend endpoint synthesises a
concise, SEO-safe 1-2 sentence write-up from the check-in's
context (job service type, customer city + ZIP, tenant brand
voice). Sits next to the existing "Rewrite with AI" pill — the
two buttons serve different purposes:

* **AI Write** — generate FROM SCRATCH when the tech didn't leave
  a note (or the moderator wants a clean, on-brand version).
* **Rewrite with AI** — polish an existing draft (unchanged; pre-
  existing endpoint).

---

## 1. Endpoint contract

`POST /api/checkins/{checkin_id}/ai-description`

### Path parameter

`{checkin_id}` — accepts EITHER:

* A raw `checkins.id` (the tech-created draft), OR
* A `public_checkins.id` (the moderation-queue row).

The endpoint tries `db.checkins` first and falls back to
`db.public_checkins`. This lets the admin moderation UI pass the
row id it already has, and the mobile client pass the draft id
it just created.

### Request body (optional)

```json
{ "tone": "neutral_factual" }
```

`tone` is reserved for future extensibility. Only
`neutral_factual` is supported in v1 — any other value falls
through to the default template. An empty POST (`{}`) or no
body at all is also valid.

### Response — 200

```json
{
  "description": "Completed weekly pool service in Chandler (ZIP 85226), including filter cleaning and chemistry balancing.",
  "model": "claude-sonnet-4-5",
  "generated_at": "2026-02-14T15:30:00Z"
}
```

`model` is `"claude-sonnet-4-5"` when the Emergent path served
the response, `"gpt-4o"` when the direct OpenAI fallback did.

### Response — 429 (rate limit)

```json
{
  "detail": {
    "code": "rate_limit_exceeded",
    "retry_after_seconds": 1740
  }
}
```

Also sets `Retry-After: 1740` on the response header (RFC-standard).

### Response — 502 (LLM unavailable)

```json
{ "detail": { "code": "llm_unavailable" } }
```

### Response — 403 / 404

* `403` — caller isn't `technician` / `admin` / `super_admin` /
  `manager`, OR is a technician who isn't the check-in's
  `technician_id`.
* `404` — `checkin_id` doesn't exist for this tenant in either
  `db.checkins` or `db.public_checkins`.

### Authorization

Mirrors `submit_public_checkin`:

* `super_admin` / `admin` (matching tenant) — always allowed.
* `technician` — only when they own the check-in
  (`checkins.technician_id == caller.id`) OR they own the source
  check-in linked from a `public_checkins` row.
* Anything else — 403.

---

## 2. Rate limit

**10 successful calls per tenant per UTC-hour window.**

Enforced via an atomic `find_one_and_update` on
`db.ai_description_events`:

```
db.ai_description_events {
  tenant_id: "…",
  action: "checkin_ai_description",
  window_start_utc: "2026-02-14T15:00:00+00:00",   // ← unique key
  window_end_utc:   "2026-02-14T16:00:00+00:00",
  call_count: 7,
  last_called_at: "…",
  last_user_id: "u-42",
  events: [
    { id, user_id, checkin_id, description_chars, provider, at },
    ...
  ]
}
```

* Windows are FIXED UTC-hour boundaries — same design + trade-off
  as `checkin_rewrite`'s rate limiter (see the "rolling vs fixed
  window" comment in `routers/checkin_rewrite.py`).
* Worst-case boundary drift: 20 calls in ~2 minutes if a user
  straddles the boundary. Acceptable for a soft cost/abuse limit.
* `429` response body carries `retry_after_seconds` computed from
  the current window's tail, so the frontend can show "Try again
  in {N} minutes."
* When the counter's `$inc` pushes past 10, the endpoint rolls
  the increment back so a hammer-attack doesn't inflate the
  counter past its cap.
* Idempotent unique index on `(tenant_id, action, window_start_utc)`
  created on server boot via `ensure_indexes()`.

---

## 3. Prompt template

```
System:
You are a home-service copywriter. Compose a concise, customer-
facing description of a completed service visit.
Requirements:
  * Exactly 1 to 2 sentences. No more.
  * Tone: neutral, factual, SEO-safe.
  * Do NOT stuff keywords. Do NOT use marketing hyperbole
    (no words like 'amazing', 'best-in-class', 'top-rated').
  * Weave the service type, city, and (if present) ZIP into
    natural prose. Each keyword appears at most once.
  * Return plain text only. No quotes, no markdown, no
    headings, no bullet points.

User:
Service type: Weekly Pool Service
City: Chandler ZIP 85226
Optional brand voice: Friendly, concise, homeowner-first.

Write the description now.
```

### Context resolution priority

| Slot | Source (in order) | Fallback |
| ---- | ----------------- | -------- |
| `service_type` | Job's `service_name` → `title` → `service_category` → (public_checkin row snapshot) | `"a service visit"` |
| `city` | Customer's `address_city` → `city` → `property.city` → public_checkin `raw_address.city` | `"the local area"` |
| `zip` | Customer's `address_zip` → `zip` → `property.zip` → public_checkin `raw_address.zip` | omitted from prompt |
| `brand_voice` | `tenants.business_settings.brand_voice` | omitted from prompt |

`"the local area"` is spec-mandated — never leave the city slot
blank in the prompt, so the model doesn't hallucinate one.

### Prompt-tone reasoning

Two explicit anti-patterns baked into the system prompt:

1. **No keyword stuffing.** Google's Search Spam Policy calls out
   [Keyword stuffing](https://developers.google.com/search/docs/essentials/spam-policies#keyword-stuffing)
   as a demotable behaviour. A naive AI copywriter told "add
   service type, city, ZIP" tends to shove all three into the
   same sentence repeatedly. The "each keyword appears at most
   once" clause guards against this.
2. **No marketing hyperbole.** Search engines (and human readers)
   distrust "amazing / best-in-class / top-rated" copy — it
   reads as ad boilerplate and hurts on-page trust signals. The
   explicit ban keeps the output SEO-safe and homeowner-neutral.

The 1-2 sentence hard cap is a length gate: short blurbs are
easier to skim on the moderation UI + easier to render on the
public map card. Longer output was also more likely to
paraphrase into hyperbole.

---

## 4. Frontend UX

### Where it lives

`frontend/src/pages/admin/ModerationCheckinsPage.jsx` →
`LabelledTextareaWithAI` component → new `AIWriteButton` mounted
next to the existing `AIDescriptionRewriteButton`. Both sit above
the description textarea.

### Component

`frontend/src/components/ai/AIWriteButton.jsx` — reusable pill.

Props:

| Prop | Purpose |
| ---- | ------- |
| `checkinId` | Passed into the URL path. Required — the button is disabled when missing. |
| `currentValue` | The textarea's current string. Stashed as `preAiValue` when AI generates. |
| `onGenerated` | Callback `(text) => void`. Fires on both AI generation AND on Undo. |
| `disabled` | External disable (parent-level). Combined with the internal `busy` flag. |
| `size` / `className` / `testid` | Style/testid overrides. Default testid = `checkin-ai-write-btn` (per spec). |

### Two-state behaviour

```
┌─────────────────┐   click → POST → prefill    ┌─────────────────┐
│   ✨ AI Write   │  ─────────────────────────▶  │   ↶ Undo AI    │
│ (write mode)    │ ◀─────────────────────────  │  (undo mode)    │
│ data-state=write│    click → restore stash    │ data-state=undo │
└─────────────────┘                              └─────────────────┘
```

* **Write click**: `preAiValue = currentValue`, POST, `onGenerated(text)`,
  flip to undo mode.
* **Undo click**: `onGenerated(preAiValue)`, `preAiValue = null`,
  flip to write mode. Never re-fetches.
* `data-state` attribute is exposed so Vitest can assert the mode
  without inspecting the button's caption.

### Toasts

| Status | Toast copy |
| ------ | ---------- |
| 429 with `retry_after_seconds` | `"AI Write rate limit reached. Try again in {N} minutes."` where `N = ceil(retry_after_seconds / 60)`, min 1. |
| 429 with no `retry_after_seconds` | Same copy with default `60` minutes. |
| 500 / network / empty response | `"AI Write failed. Please write manually."` |
| Success | No toast — the textarea update IS the feedback. |

### Testids

* `checkin-ai-write-btn` — the button itself.
* `checkin-ai-write-btn-icon` — the inner lucide icon (Sparkles /
  Loader2 / Undo2).
* `data-state="write"` or `"undo"` — the current mode.

---

## 5. Telemetry

Every successful call appends an event to the current window's
row in `db.ai_description_events`:

```json
{
  "id": "…",
  "user_id": "u-42",
  "checkin_id": "chk-…",
  "description_chars": 187,
  "provider": "claude-sonnet-4-5",  // or "gpt-4o"
  "at": "2026-02-14T15:30:00Z"
}
```

* Failure to append the event MUST NOT surface a 500 to the caller
  — the `_log_event` helper swallows exceptions and logs a
  warning. The client already has the AI text at that point.
* Tenant admins can inspect usage via a Mongo query on the row
  itself (`call_count`) or its `events` array — no separate
  audit_logs entry is written for now (tracked as P3 backlog).

---

## 6. Files touched

| File | Change |
| ---- | ------ |
| `backend/routers/checkin_ai_description.py` | **NEW** — endpoint + rate limit + telemetry + context resolver + prompt builder. |
| `backend/server.py` | Wired `_checkin_ai_desc.router` into `api_router`. +1 OpenAPI path. |
| `backend/tests/test_checkin_ai_description.py` | **NEW** — 9 tests: happy path × 3, auth × 4, rate limit × 1, telemetry × 1. |
| `frontend/src/components/ai/AIWriteButton.jsx` | **NEW** — pill button with write/undo state machine + toast handling. |
| `frontend/src/pages/admin/ModerationCheckinsPage.jsx` | Mounted `AIWriteButton` next to the existing rewrite pill (both in `LabelledTextareaWithAI`). |
| `frontend/src/test/checkin-ai-write.test.jsx` | **NEW** — 3 Vitest cases per spec. |
| `memory/FEATURE_AI_CHECKIN_DESCRIPTION.md` | This memo. |

---

## 7. Test counts

* **Backend** (`pytest backend/tests/test_checkin_ai_description.py`):
  **9 passed, 0 failed, 15.79s wall**.
* **Frontend** (`yarn test:unit` — full suite):
  **579 files passed | 1 skipped · 4348 passed | 34 skipped** (was
  4345 → +3 from the new file). Total wall 132 s.
* **OpenAPI paths**: **1739** (was 1738 → **+1** as expected per
  spec).

---

## 8. Out of scope

* Mobile parity — deferred; delegated to `e1_expo_frontend_dev`
  after web verifies.
* JSON-LD SEO on the public feed — separately queued.
* AI Employees / `ai_knowledge_base` RAG grounding of the
  description — separately queued.
* Per-tenant BYO AI cap enforcement on this endpoint — skipped in
  v1 because the BYO dispatch hop re-enters `call_llm_with_fallback`
  with the default `parse_json=True` and would corrupt the
  plaintext contract with an `"emptyjson"` error. The endpoint's
  own 10/tenant/hour rate limit is the primary abuse gate; BYO
  cap tracking can be re-plumbed once the dispatcher exposes a
  `parse_json` passthrough (tracked as P3).
* Server-side audit_logs entry (per spec "audit_logs OR
  ai_description_events" — we chose the latter which doubles as
  the counter row).
* A–F backlog items.
