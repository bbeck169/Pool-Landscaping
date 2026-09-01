# Phase S3 · Feb-2026 — Soshie LLM Moderation Gate

Conservative content-safety check that runs BEFORE any autopilot
publish. Gates every drafted social post through Claude Sonnet via
the Emergent Universal LLM Key so profanity, PII, competitor
bashing, and misleading claims never leak out of the CRM.

## Model + wire

- Provider: `emergentintegrations` → `anthropic / claude-sonnet-4-5`
  (mirrors every other LLM caller in the codebase; see
  `services/llm_provider.py::call_llm_with_fallback`).
- Entry point: `services.soshie.llm_moderation.moderate_post(
    post_id, tenant_id, text, media_urls)`.
- Return shape:
  ```json
  {
    "decision": "approve" | "flag" | "block",
    "reasons": ["short strings"],
    "risk_level": "low" | "medium" | "high",
    "model": "claude-sonnet-4-5",
    "tokens_in": 512,
    "tokens_out": 24,
    "cost_estimate_usd": 0.0026,
    "from_cache": false
  }
  ```

## System prompt (verbatim, kept short so it fits in the audit trail)

```
You are a conservative content-safety reviewer for social posts
authored by a family-run pool + landscaping services business.
Return JSON ONLY (no prose, no markdown) with this exact shape:
{"decision": "approve" | "flag" | "block",
 "reasons": [<short strings>],
 "risk_level": "low" | "medium" | "high"}.

Decision rubric:
- BLOCK for: profanity, hate speech, adult / NSFW content, medical
  or legal advice, competitor bashing, misleading claims (e.g.
  'guaranteed', 'cure', 'risk-free'), PII (customer names,
  addresses, phone numbers, emails), pricing outside the pricebook.
- FLAG for: aggressive or sarcastic tone, unusual claims,
  low-confidence assertions, mentions of dangerous chemistry,
  anything a family business owner would want to eyeball before it
  goes live.
- APPROVE for: clean, on-brand pool / landscape / family-business
  voice with no risk signals.

Return AT MOST 4 reasons, each < 60 characters. When in doubt,
prefer FLAG over APPROVE — a human will review flagged posts.
```

## Decision matrix

| LLM output       | Autopilot routing                                   | Publisher fires? |
| ---------------- | --------------------------------------------------- | ---------------- |
| `approve`        | proceeds to `_dispatch_one` on the next tick        | yes              |
| `flag`           | action row → `status="awaiting_review"`             | no (human gates) |
| `block`          | action row → `status="blocked"`                     | no (human can override via approve) |
| LLM error / timeout | `flag` + reason `moderation_service_unavailable` | no               |
| Tenant over credit floor (< 5) | `flag` + reason `quota_exceeded`     | no               |

Approving from the queue via `POST /api/soshie/moderation/{id}/approve`
stamps `moderation_override=true` and re-queues at `status="pending"`
so the next autopilot tick dispatches. Rejecting via
`POST /api/soshie/moderation/{id}/reject` marks `status="rejected"`
and the autopilot scheduler skips it forever.

Every decision (including cache replays and kill-switch bypasses)
writes a row to `soshie_moderation_results` for audit + cost accounting.

## Idempotency + cache

Content hash: `sha256(text + "|".join(sorted(media_urls)))`. The most
recent non-error row for a hash within a tenant replays the prior
decision without another LLM round-trip. Cache entries never expire —
new content = new hash = new call. Errors are NOT cached; a failed
moderation call will retry on the next autopilot tick.

## Cost accounting

Roughly $0.003 / 1K input tokens + $0.015 / 1K output tokens (Claude
Sonnet public rate at Feb-2026 sign-off). A typical 200-char draft +
1 media URL comes in around **~$0.002 – $0.003 per moderation call**.
Costs are persisted per row in `soshie_moderation_results.cost_estimate_usd`
so ops can `db.aggregate` monthly.

## Quota interaction

Reuses the Soshie AI-credits floor (`services.soshie.autopilot_scheduler.CREDIT_FLOOR = 5`).
When a tenant's `ai_credits_balance < 5` the moderation call
short-circuits to `flag` with reason `quota_exceeded` — we never burn
LLM cycles on tenants that can't afford the surrounding publish
anyway. The autopilot deferral already handles the actual credit gate;
this second layer just keeps the moderation surface honest.

## Endpoints (admin+)

| Method | Path                                              | Purpose                                          |
| ------ | ------------------------------------------------- | ------------------------------------------------ |
| GET    | `/api/soshie/moderation/queue?status=…`           | list `awaiting_review` / `blocked` / `rejected` |
| POST   | `/api/soshie/moderation/{post_id}/approve`        | human override → re-queue for publish            |
| POST   | `/api/soshie/moderation/{post_id}/reject`         | mark rejected, drop from queue                   |
| GET    | `/api/soshie/publishing/today-summary`            | dashboard-tile counters + next-up preview        |

Approve and reject both write `audit_events` rows with types
`soshie_moderation_approve` / `soshie_moderation_reject` so the audit
trail is durable.

## Kill switch (emergency escape hatch)

Set `SOSHIE_MODERATION_ENABLED=false` in `backend/.env` and restart the
backend supervisor. `moderate_post()` immediately returns
`decision="approve"` with reason `moderation_disabled`, no LLM call.
Every bypass still writes a row to `soshie_moderation_results` (with
`model="kill-switch"`) so post-incident audit remains complete.

Un-flip: unset the var (or set it to `true` / any non-falsy value) and
restart the backend supervisor.

## Rollback

- To pause moderation without a redeploy: use the kill switch above.
- To undo an accidental `reject`: flip `ai_employee_actions.status`
  back to `awaiting_review` or `pending` directly in Mongo — the
  autopilot will pick it up on the next tick (or the admin can
  approve via the queue UI).
- To drop the queue router entirely (unlikely — the endpoints are
  additive): remove the `api_router.include_router(_phase_f3_...)`
  block in `backend/server.py`; no schema migration needed.


## Phase H7 · Feb-2026 — Regex + LLM combo pipeline

**Two-stage moderation for cost savings**

`services.soshie.llm_moderation.moderate_post` now runs in this order:

1. Kill switch — `SOSHIE_MODERATION_ENABLED=false` → approve.
2. **Stage 1 · Regex prefilter ($0)** — `services.soshie.moderation.prefilter`:
   - **High**-confidence sources (`brand_brain.dont_say`, `banned_phrases`) → short-circuit to `block`. **LLM is not called.**
   - **Low**-confidence sources (`email`, `phone`, `ssn`, `credit_card`) → fall through to Stage 2; the low-confidence flag is folded via `_more_conservative` after the LLM verdict.
3. Cache hit — replay a prior decisive LLM verdict; combined with any current regex-low flags (never downgrades a cached block).
4. Credit floor gate.
5. **Stage 2 · Live LLM call** — Claude Sonnet.

**New env: `SOSHIE_REGEX_PREFILTER_ENABLED`**
Default `true`. Set `false` / `0` / `off` / `no` to skip Stage 1 and force every draft through the LLM. Use for A/B validation or when you want to isolate a suspected regex false-positive.

**New audit fields on `soshie_moderation_results`:**
- `regex_short_circuit: bool` — true only when Stage 1 short-circuited to block. H6 monthly rollup exposes the count as `soshie_moderation.regex_short_circuits`.
- `regex_high_flags` / `regex_low_flags` — full flag payloads captured on every row for auditability.

**Expected cost savings:** ~15% on a realistic pool/landscape mix (measured on a synthetic 100-post batch with 15% policy-blocked drafts).
