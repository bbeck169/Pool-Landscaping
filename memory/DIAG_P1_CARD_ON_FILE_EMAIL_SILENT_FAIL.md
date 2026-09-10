# DIAG P1 — "Card on File" email silent-fail

**Date**: Feb 10, 2026 · Preview only (no prod access)
**Reporter symptom**: Admin clicks a Card-on-File related button; UI shows a "sending email…" indicator; nothing arrives in Resend.
**Verdict**: **UX bug — the button lies about success.** The backend returns HTTP 200 even when nothing was sent; the frontend never inspects the `sent_email` / `sent_sms` booleans in the response and unconditionally toasts "Add-card link sent to <recipient>".
**Confidence**: HIGH (reproduced on preview with a null-email customer — HTTP 200 + `sent_email:false / sent_sms:false`).
**Fix classification**: primary = UX (frontend + response contract). Secondary = backend hygiene (a truthful `outcome` field so the FE never has to interpret two booleans + templates).
**Do NOT ship yet**: user wants to confirm scope first.

## 1. Enumerated "Card on File" email surfaces

| Button label | Component / file | Test-id | API route | Backend function |
|---|---|---|---|---|
| "Send add-card link" | `frontend/src/components/customers/CardOnFileWarningBanner.jsx` L64 | `card-on-file-send-link-btn` | `POST /api/customers/:id/send-card-add-link` | `routers.customers.send_card_add_link` L3651 |
| Row action "Send add-card link" | `frontend/src/pages/customers/CustomersList.jsx` L336 (`handleSendPaymentLink`) | (row-level) | Same route | Same |
| P44 no-payment-filter action | `frontend/src/test/p44-no-payment-filter.test.jsx` (test) | — | Same | Same |

All three UI paths hit **one** endpoint: `POST /api/customers/{cid}/send-card-add-link`.
Underlying sender: `services.comms_email_adapter.send_email` (Resend, HTTP 200 always — never raises) + `services.comms_sms.send_sms` (RingCentral).

## 2. Preview send-path — what actually happens

Test as `super@aquaterra.com` on `https://poolscape-audit.preview.emergentagent.com`:

### Case A — customer with email + phone
```
POST /api/customers/926cee64-4c3b-4fb6-907a-08c1fed00397/send-card-add-link
→ HTTP 200
→ {"ok":true,"sent_email":true,"sent_sms":true,
     "email_recipient":"k14tester@aquaterra.com",
     "sms_recipient":"+14805551212"}
Elapsed: 1.45s
Logs: INFO:comms.gate:[COMMS_SEND] policy=prod_bypass type=email provider=resend
Ledger row inserted with delivered=True in ``marketing_deliveries``.
```
**Preview path is healthy** when the customer has contact info + templates are seeded (25 tenants have `add_card_request_email` + `add_card_request_sms` templates).

### Case B — customer with `email = null` AND `phone = null`
```
POST /api/customers/drift-dt-fd70e7/send-card-add-link
→ HTTP 200
→ {"ok":true,"sent_email":false,"sent_sms":false,
     "email_recipient":null,"sms_recipient":null}
```
**No email + no SMS sent. Backend says so. Frontend shows a success toast anyway** (see next section).

## 3. Root cause — FE ignores the truth flags

`routers.customers.send_card_add_link` (customers.py L3700-3767) does:

```python
if email_tpl and customer.get("email"):
    try:
        res = await send_email(...)
        sent_email = res.get("status") in ("sent", "sent_no_provider_id")
    except Exception as exc:
        logger.warning(f"[phase12] add-card email send failed: {exc}")
    # persist delivery row (delivered = sent_email) regardless
# same for SMS
return {"ok": True, "sent_email": sent_email, "sent_sms": sent_sms,
        "email_recipient": customer.get("email"),
        "sms_recipient":   customer.get("phone")}
```

`services.comms_email_adapter.send_email` **never raises** — it returns one of ~10 status values, of which only `"sent"` / `"sent_no_provider_id"` mean "we actually handed the payload to Resend and got a provider id". The other 8 all resolve to `sent_email=False` while the route still returns HTTP 200:

| `send_email` status | Meaning | `sent_email` |
|---|---|---|
| `sent` | Handed off to Resend, got provider id | ✅ True |
| `sent_no_provider_id` | Provider accepted but no id returned | ✅ True |
| `failed` (empty recipient) | `to_email` was empty | ❌ False |
| `skipped_opted_out` | Recipient on opt-out list | ❌ False |
| `deferred` | Quiet hours — queued for later dispatch | ❌ False |
| BYO-passthrough | Tenant BYO provider handled it (may itself have failed) | ❌ False |
| Mock envelope | `MESSAGING_TESTMODE_MOCK` — no outbound HTTP call | ❌ False |
| `not_sent_missing_key` | `RESEND_API_KEY` unset on this pod | ❌ False |
| `suppressed_not_demo` | `services.comms.gate.is_comm_allowed` blocked it | ❌ False |
| `failed` (exception) | Resend SDK raised (network / auth / rate) | ❌ False |

**Additional silent no-ops that never even call `send_email`**:
- `email_tpl` missing → the entire `if email_tpl and customer.get("email"):` block skips. Silent.
- `customer.get("email")` empty/null → same block skips. Silent. **Reproduced above (Case B).**
- Same for the SMS branch.

### Where the FE lies

**`frontend/src/components/customers/CardOnFileWarningBanner.jsx` L21-32**:
```jsx
const res = await api.post(`/customers/${customer.id}/send-card-add-link`, {});
const to = [res.email_recipient, res.sms_recipient].filter(Boolean).join(" and ");
onSent && onSent(to ? `Card add link sent to ${to}` : "Card add link sent");
```

**`frontend/src/pages/customers/CustomersList.jsx` L343-348** (row action, identical shape):
```jsx
const to = [res.email_recipient, res.sms_recipient].filter(Boolean).join(" and ");
setToast({ tone: "success",
            message: to ? `Add-card link sent to ${to}` : "Add-card link sent" });
```

Neither call site inspects `res.sent_email` or `res.sent_sms`. Every 200 = success toast, even when nothing was sent. **This is the reported symptom.**

## 4. Hypothesis scorecard

| Hyp | Verdict | Notes |
|---|---|---|
| H1 · Customer has no email → silent short-circuit | ✅ Confirmed on preview (Case B). Contributes to the symptom when the target customer has null email. |
| H2 · Tenant BYO Resend blank fallback swallows | Not the cause on the aquaterra preview tenant (`policy=prod_bypass` fires the platform Resend path). Would repro on a BYO-enabled tenant with a blank key — the BYO passthrough returns a status other than `sent`, FE still toasts success. |
| H3 · Template resolution silently no-ops | ✅ Contributes — `if email_tpl` guard silently skips. `phase12 add_card_request_*` templates seeded 0 rows for many tenants on this pod (seed log line). If a tenant is missing the template, the branch is a silent no-op. |
| H4 · Rate-limit / dedup silently skipped | Not silent — `ensure_rate_limit(cid)` raises HTTPException(429), which the FE surfaces as "Please wait…". Not the reported symptom. |
| H5 · BackgroundTask / worker misconfig | Not applicable — send path is `await`-ed inline with `wait_for(timeout=8.0)`. No worker involved. |

**Primary root cause**: **H3 (FE truthfulness) + H1/H3 (silent backend short-circuits).** The endpoint returns HTTP 200 regardless of what happened; the FE trusts that as success.

## 5. Proposed patch scope (NOT shipped yet — awaiting user confirmation)

### Option A — Minimal (FE only, ~15 lines)
Change both FE call sites to gate the success toast on `sent_email || sent_sms`. Emit a distinct warning toast when both are false:

```jsx
if (res.sent_email || res.sent_sms) {
  onSent(`Card add link sent to ${to}`);
} else {
  onError("Nothing was sent — the customer has no email/phone or the templates are missing. Add contact info and try again.");
}
```

Pros: Zero backend risk. Ships in minutes. Closes the "toast lies" symptom.
Cons: Backend still returns 200 for silent no-ops. Any future consumer of the route inherits the ambiguity.

### Option B — Truthful contract (FE + BE, ~40 lines)
Backend: add an explicit `outcome` field to the response envelope:

```json
{
  "ok": true,
  "outcome": "sent" | "partial" | "nothing_sent",
  "email": { "sent": bool, "status": "sent|no_recipient|no_template|opted_out|deferred|not_sent_missing_key|suppressed_not_demo|failed", "reason": "..." },
  "sms":   { "sent": bool, "status": "...", "reason": "..." },
  "email_recipient": "...", "sms_recipient": "..."
}
```

- `outcome = "sent"` iff either channel status ∈ {sent, sent_no_provider_id}.
- `outcome = "nothing_sent"` iff neither channel sent AND at least one was attempted (or refused).
- `outcome = "partial"` iff exactly one channel sent.
- Keep `sent_email` / `sent_sms` for back-compat; deprecate in a follow-up.

Frontend: toast on `outcome` + surface the per-channel reason ("Not sent — customer has no email on file. Add an email and retry.").

Pros: Truthful contract. Future consumers can't misuse it. Diagnosable for ops without tailing logs.
Cons: Slightly larger diff. Need one back-compat test and one new envelope test.

**Recommendation**: **Option B**. The symptom will resurface elsewhere if we only patch the FE — every current + future silent-no-op vector inside `send_email` still returns HTTP 200. Option A is a partial mask.

## 6. Non-scope observations

Flagging but NOT fixing in this diagnostic (per user's "do not ship" instruction):
- Seed log line shows `add_card_request_*` templates inserted `0` rows for many tenants including `TEST-*`, `csv-*`, `cra-*`, `jca-*`. On aquaterra it's 0 but the collection HAS templates (verified with a direct DB read) — so `0` = "already existed, skipped." For any tenant that was seeded WITHOUT templates, every send-card-add-link call would be a silent no-op even before this diagnostic. Worth a data-quality check separate from this fix.
- The route's exception handler `except Exception as exc: logger.warning(...)` swallows ANY failure inside `send_email` (which itself never raises, but a template-render failure or DB write on `marketing_deliveries` could raise). Consider a structured audit trail so ops can filter by outcome in the reports view.
- Prod-specific: user reported preview and prod symmetrically. Prod has no visibility from this container — if `RESEND_API_KEY` is unset on the prod pod, EVERY send hits `not_sent_missing_key` and returns 200. Ask the user whether prod's Resend key is present.

## 7. Files touched by this diagnostic
None. Read-only investigation. Zero code changes.

## 8. Next Action Items
- **User to confirm**: Option A vs Option B (recommend B) — ship the fix.
- **User to confirm**: Was the reported customer missing an email address? (would confirm H1 as the exact triggering data shape.)
- **User to check on prod**: Is `RESEND_API_KEY` set on the prod pod? Preview has it (`policy=prod_bypass` in logs); prod status unknown from this container.
- **Handoff**: Mobile has no equivalent send-card action today, so no mobile parity task.
