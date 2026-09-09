# PHASE — Customer per-line-item decline + top-level approve/decline

**Status:** SCOPE ONLY (no code shipped yet). Awaiting human answers to §7 open questions before Phase A kickoff.

**Reference:** User Msg 297 — "On customer quotes/estimates, add a decline button next to each line item, and a final approve/decline at top. On approval, send email to admin, text to admin number, and mark approved in customer portal."

**Author:** main agent · Feb 2026

---

## 1. Surface audit — where quotes/estimates render for the customer today

### 1.1 Customer-portal routes
| Route (App.js) | Component | Uses `doc_type` | Notes |
|---|---|---|---|
| `/portal/estimates` (list) | `PortalPages.jsx` L266-289 | `api.get("/quotes?doc_type=quote")` | Testid `portal-estimates`; renders one row per quote with a `StatusPill status={r.decision || r.status}`. Tour anchor `data-tour-id="estimates-list"`. |
| `/portal/estimates/:id` (detail) | `PortalPages.jsx` L292-304 → `EstimateView estimateId={id} isAdmin={false}` | reads via `_authorised_estimate` (portal user's `customer_id` scoped) | Fetches through `/api/quotes/{qid}` behind the scenes. |
| `/portal/quotes` (list) | `PortalPages.jsx` L162-172 | `api.get("/quotes?doc_type=invoice")` | This route is actually **invoices** in disguise (K48 rename lag). NOT the quote/estimate accept-flow surface. Rename or clarify later — out of scope for this feature. |

### 1.2 The single shared rendering component
`/app/frontend/src/components/EstimateView.jsx` is the ONE surface a customer uses to review a proposal.

Key test-ids already present:
- `estimate-view`
- `estimate-toolbar-customer` (the customer-facing toolbar)
- `estimate-toolbar-accept-btn`, `estimate-toolbar-decline-btn`, `estimate-toolbar-request-changes-btn`
- `estimate-accepted-pill`, `estimate-declined-pill`
- `estimate-status-banner`
- `estimate-line-items-table`
- `estimate-line-item-row-${i}` (per line, no per-line action buttons today)
- `estimate-totals-subtotal`, `estimate-totals-taxes`, etc.

### 1.3 Parity between "quotes" and "estimates"

**Modeled unified.** Both live in `db.quotes` with `doc_type in {"quote", "invoice"}`. The customer-portal ONLY exposes `doc_type=quote` on the accept/decline surface (via `EstimateView`). `doc_type=invoice` renders read-only on `/portal/quotes` and has no decline concept (invoices are payable, not decline-able).

**Invoices are OUT of scope** for this feature — the customer portal offers no decline path on invoices, and we're not adding one. Confirmed.

**Estimator estimates (`db.estimator_estimates`)** are a separate collection used by the AI-estimator wizard. They are NOT rendered on the customer portal today — they must be `POST /estimator/estimates/{eid}/convert-to-quote` first, which creates a `db.quotes` row that flows through the standard portal. So Msg 297's "quotes/estimates" refers to the unified `db.quotes` doc; no changes needed in `db.estimator_estimates` for this feature.

**Parity gap confirmed:** there is NO gap. A single `EstimateView.jsx` component + a single `db.quotes` collection covers both terms.

### 1.4 Existing acceptance / decline pathways (already partially built)

Two overlapping paths already exist for top-level approve/decline. Any Phase A implementation MUST unify or delegate to these, not create a third:

| Endpoint | File | Auth | Effect | Notify? |
|---|---|---|---|---|
| `POST /api/quotes/{qid}/accept` (alias `/estimates/...`) | `routers/estimate_viewer.py:313-331` | logged-in user (customer or staff) | Sets `status=accepted`, `decision=accepted`, `accepted_at`, `accepted_by`; fires drip event `estimate_accepted`; emits custom-trigger `estimate_signed`. | `_notify_admins()` → bell notifications to admin/super_admin users of the tenant. **NO email or SMS today.** |
| `POST /api/quotes/{qid}/decline` (alias `/estimates/...`) | `routers/estimate_viewer.py:334-352` | logged-in user | Sets `status=declined`, `decision=declined`, `declined_at`, `declined_by`, `decline_reason`. | Same bell-only. |
| `POST /api/quotes/{qid}/request-changes` | `routers/estimate_viewer.py:355-375` | logged-in user | Sets `status=changes_requested`, `decision=changes_requested`, `changes_requested_message`. | Same. |
| `POST /api/portal/quotes/via-token/accept` (magic-link) | `routers/estimate_viewer.py:442-460` | token in query | Same as auth'd `/accept`. | Same. |
| `POST /api/portal/quotes/via-token/decline` (magic-link) | `routers/estimate_viewer.py:462-490` | token in query | Same as auth'd `/decline`. | Same. |
| `POST /api/quotes/{qid}/decision?decision=approve\|decline` | `routers/quotes.py:799-834` | role=customer only | LEGACY — sets `status=accepted/declined` but does NOT populate `decision`, `accepted_by`, or fire drips. Suggests earlier prototype before `estimate_viewer.py` landed. | **NO admin notify at all.** |

**Recommendation for §5:** unify on `estimate_viewer.py`. Retire the legacy `routers/quotes.py::customer_quote_decision` in a follow-up cleanup (out of this scope).

### 1.5 Frontend accept/decline hooks in `EstimateView.jsx`
- Modal `declineOpen` + `submitDecline()` (lines 55-56, 92-95). Already calls `/quotes/{id}/decline` (auth'd) or the via-token variant. **Reason-text captured** in a modal today.
- The customer-facing toolbar collapses to a locked status pill (`ev-locked-pill`) once decision ∈ `{accepted, declined}` (line 133 `locked`). No un-decline / un-accept path in code today.

---

## 2. Data model proposal

### 2.1 Per-line-item state — NEW fields on `line_items[i]`

Add three fields to each entry in `db.quotes.line_items` (schema is currently loose — `LineItemModel` accepts extra dict keys):

```
line_items[i].customer_status:   "pending" | "declined"    # default "pending"
line_items[i].customer_declined_at:  ISO datetime | null
line_items[i].customer_decline_reason: str | null           # optional short note
```

Defensive: existing rows without `customer_status` are treated as `"pending"` client-side.

### 2.2 Top-level doc status transitions

Keep the current top-level `status` / `decision` fields intact. NO new top-level enum values. Mapping:

| Event | `status` after | `decision` after | Extra fields |
|---|---|---|---|
| Customer clicks per-line **Decline** | unchanged (still `sent`) | unchanged | just `line_items[i].customer_status = "declined"` |
| Customer clicks per-line **Undecline** (Phase A follow) | unchanged | unchanged | `line_items[i].customer_status = "pending"`; clears `customer_declined_at` |
| Customer clicks top-level **Approve** | `accepted` | `accepted` | `accepted_at`, `accepted_by` (existing) |
| Customer clicks top-level **Decline** | `declined` | `declined` | `declined_at`, `declined_by`, `decline_reason` (existing) |

**Invoices (`doc_type="invoice"`):** unchanged, out of scope. No new fields. The portal does NOT render approve/decline on invoices.

**Estimator estimates (`db.estimator_estimates`):** unchanged. Never customer-visible; if the operator wants a customer decline, they convert to quote first (`convert_to_quote`).

**Confirmation:** invoices are OUT of scope for this feature — customer portal only exposes `doc_type=quote` on the accept-flow surface. Confirmed in §1.3.

### 2.3 Do declined line items reduce the doc total?

**RECOMMENDATION: NO. Do not auto-reduce.**

Rationale:
1. The customer's decline is a **signal**, not a re-quote. Auto-reducing the total misrepresents what the operator originally offered.
2. Tax/discount math on a partially-declined bundle gets ambiguous fast (a % discount can turn into a re-negotiation).
3. Admin retains agency: they see the flagged lines, decide whether to regenerate a new quote with lines removed, then re-send.

**UI treatment:** annotate + strike-through the declined line in `EstimateView.jsx`. Show a "Declined by customer" chip on the row. Keep `totals.subtotal / total` unchanged. Show a top-of-page banner: *"You've flagged N line item(s) as declined. The total below still reflects the original proposal — we'll follow up with a revised quote."*

**1-line alternative if the human wants auto-reduce:** compute `active_line_items = [li for li in line_items if li.customer_status != "declined"]`, run `_compute_totals()` on that filtered slice, expose `active_subtotal / active_total` as SEPARATE fields (never overwrite the original totals) — the UI shows both.

### 2.4 Backwards-compat rule
- Old quotes with no `customer_status` on any line render exactly as today (all lines "pending"; no strike-through; no banner).
- No migration required.

---

## 3. Notifications

### 3.1 Where the admin recipients come from

The sanctioned admin-notify sink on this codebase is **`tenants.lead_notification_recipients`** (see `backend/routers/tenant_lead_notifications.py`). Schema:

```
tenants.lead_notification_recipients: [
  { email: "ops@aquaterra.com", phone: "+16025551234" },
  ...
]
```

Managed via `GET/PUT /api/tenants/{tid}/lead-notifications`. Every entry can have email, phone, or both. The dispatcher lives at `services/lead_notifications.py`.

**Fallback path when unset:** fan out to `db.users` where `role in {admin, super_admin}` and use their `email` + `phone` (the same rowset `_notify_admins()` already targets for bell notifications). Same fallback the lead-notification dispatcher uses today. This preserves the current admin-bell behavior + adds email/SMS.

**Do NOT ask the human for a new `notification_email` / `notification_phone` setting.** Reuse `lead_notification_recipients` and the workforce fallback.

### 3.2 Channel plumbing — reuse existing adapters ONLY

- **Email:** `services/notifications._dispatch_email` (line 437) → Resend via `RESEND_API_KEY` + `RESEND_FROM`. Already BYO-key-aware via the hardened `byo_common` empty-credentials fallback (P0 hotfix from earlier this session). **Do not bypass.**
- **SMS:** `services/notifications._dispatch_sms` (line 510) → RingCentral. Same BYO fallback.

Both dispatchers already handle: quiet-hours, mute preferences, DRY-RUN in preview via `COMMS_TEST_ALLOWLIST_*`, and dedupe by `kind + correlation_id`. Piggyback on them. Do NOT write a new email/SMS sender.

### 3.3 When do we notify?

| Trigger | Email admin? | SMS admin? | Bell? | Notes |
|---|---|---|---|---|
| Top-level **Approve** | **YES** (per Msg 297) | **YES** (per Msg 297) | YES (already) | Correlation key: `quote_accepted:{qid}` |
| Top-level **Decline** | YES (recommended, configurable) | YES (recommended, configurable) | YES (already) | Msg 297 only mandates the approve path; decline is a strong signal too. Gate behind `tenants.notify_on_decline` (default `True`, admin can flip off in Settings). |
| Per-line **Decline** | NO by default (would spam) | NO | Optional — **RECOMMENDATION: batch** into a single "N lines flagged" bell after 5 min of no further activity, then no email/SMS. | The customer is likely to decline multiple lines in one session; a batched summary avoids notification storm. |
| Per-line **Undecline** | NO | NO | NO | Silent. Only useful for the customer's own UI feedback. |
| **Approve** on a quote with any declined line items | Email/SMS both fire as normal; body includes *"N line items were declined before approval"* callout. | | | |

### 3.4 Copy — proposed subject + body templates

All templates render via `services/notifications._dispatch_email` / `_dispatch_sms`, which already merge tenant name + doc title + href. Placeholders below use `{tenant}`, `{customer}`, `{doc_title}`, `{admin_href}`.

**Approve — quote — email:**
```
Subject: Estimate approved by {customer} — {doc_title}
Body:
Hi team,

{customer} just approved the estimate "{doc_title}" ({tenant}).

Open it: {admin_href}

You can schedule it as a job from the admin console.

— {tenant}
```

**Approve — quote — SMS (≤ 160 chars):**
```
{tenant}: {customer} approved "{doc_title}". Open: {admin_href}
```

**Decline — quote — email:**
```
Subject: Estimate declined by {customer} — {doc_title}
Body:
Hi team,

{customer} declined the estimate "{doc_title}" ({tenant}).

Reason: {decline_reason_or_dash}

Open it: {admin_href}

— {tenant}
```

**Decline — quote — SMS:**
```
{tenant}: {customer} declined "{doc_title}". Reason: {short_reason}. Open: {admin_href}
```

No separate estimate variant needed — same doc type. If the human wants distinct wording later, the templates can key off `doc.title` or a per-tenant override.

### 3.5 Guardrails
- All sends go through the existing `_dispatch_*` helpers → BYO empty-credentials fallback + preview allowlist + dry-run stay honored.
- `kind` value: reuse `quote_accepted` and `quote_declined` (add if missing; today `_notify_admins` fires only `quote_accepted` even on decline — see `estimate_viewer.py:344`; that's a small pre-existing bug to fix in Phase A).
- Dedupe: `correlation_id = f"{kind}:{qid}"`. Prevents double-fire when a customer double-clicks Approve.

---

## 4. UI/UX rules

### 4.1 Per-line Decline button

**Placement:** rightmost cell of every row in `estimate-line-items-table` (`EstimateView.jsx` L370-384). Renders ONLY when the doc is in an un-locked state (`decision !∈ {accepted, declined}`) AND the viewer role is customer (or via-token). Admin toolbar keeps its own delete/edit buttons.

**Testid:** `estimate-line-decline-btn-${i}` (per row); after decline, replaces with `estimate-line-undecline-btn-${i}`.

**Confirm dialog copy:**
```
Title: Decline this line item?

You're telling us you don't want:
  "{line_item.description}" ({fmt(line_item.total)})

You can undo this until you approve or decline the whole estimate.

[Cancel]  [Decline this line]
```

**Post-decline row treatment:** strike-through the description text, muted color, small `"Declined"` chip inline, `undecline` button replaces the decline button. Total column stays unchanged (per §2.3).

**Undecline:** yes, allowed until the doc is finalized. Single click, no confirm needed (low-risk).

### 4.2 Top-level Approve / Decline buttons

Already exist in `EstimateView.jsx` (`estimate-toolbar-accept-btn` / `estimate-toolbar-decline-btn`). Rules:
- **Visible** when: viewer role is customer OR via-token, AND `decision !∈ {accepted, declined}`, AND `status ∈ {sent, viewed}` (add `viewed` if we're tracking it; today `sent` is the only pre-decision status).
- **Disabled + hidden** once finalized (already handled by the `locked` variable in `EstimateView.jsx:133`).
- **Approve** on a doc with any `line_items[i].customer_status === "declined"` → confirmation modal warns: *"You've flagged N line item(s) as declined. Approving now will mark the whole estimate accepted — we'll follow up on the declined lines separately. Continue?"* [Cancel] [Approve anyway].

### 4.3 Approve + signature

Currently the signature flow is DECOUPLED from the accept flow:
- `/api/quotes/{qid}/accept` sets `decision=accepted` immediately.
- `/api/quotes/{qid}/request-signature` + `/portal/sign/*` is a SEPARATE customer flow that fills `signature_status="signed"` on the doc.

**Recommendation:** keep them decoupled. "Approve" does NOT auto-sign. The operator retains control: they either send a separate signature request via the existing button, or accept that "approval alone" is enough for the tenant's workflow. This matches Msg 297's wording (nothing about auto-sign).

**Follow-up in Phase C (below):** offer a tenant-level toggle `tenants.require_signature_before_approve` — when `True`, the Approve button on the customer surface is disabled with a helper tooltip until `signature_status === "signed"`.

### 4.4 "Mark approved in customer portal" — banner + pill copy

**Once `decision === "accepted"`**, the top of the `EstimateView` renders (already partially done by the existing `estimate-accepted-pill`):

**Green banner** (new — `estimate-approved-banner` testid):
```
✓ Approved on {accepted_at short date}. We'll be in touch to schedule your work.
```

**Status pill** (existing, keep copy):
```
Accepted on {accepted_at short date}
```

Also render a banner + pill on the customer `/portal/estimates` LIST view so the customer sees the doc status without opening it. New testid on the list row: `estimate-list-row-status-${qid}`.

**On decline:** existing red `estimate-declined-pill` copy stays. Add a matching banner: *"Declined on {declined_at short date}. We'll follow up if there's a way to make this work."*

---

## 5. API surface

### 5.1 Endpoints

All customer-portal auth: JWT (portal customer role) OR magic-link token (via-token variant). Both paths must exist (parity with existing accept/decline).

| Method + path | Purpose | Body | Response |
|---|---|---|---|
| `POST /api/quotes/{qid}/line-items/{idx}/decline` | Per-line decline (auth'd customer) | `{ "reason": "optional short note" }` | `{ line_items, totals, decision }` (full updated doc) |
| `POST /api/quotes/{qid}/line-items/{idx}/undecline` | Un-decline (auth'd customer) | `{}` | same |
| `POST /api/portal/quotes/via-token/line-items/{idx}/decline` | Per-line decline (magic-link) | `{ token, reason }` | same |
| `POST /api/portal/quotes/via-token/line-items/{idx}/undecline` | Un-decline (magic-link) | `{ token }` | same |
| **Reuse existing** `POST /api/quotes/{qid}/accept` | Top-level approve | `{}` | now ALSO fires email + SMS via `_notify_admins_via_channels()` (new helper) |
| **Reuse existing** `POST /api/quotes/{qid}/decline` | Top-level decline | `{ reason }` | now ALSO fires email + SMS |
| **Reuse existing** `POST /api/portal/quotes/via-token/accept` | Same, magic-link | `{ token }` | same channel expansion |
| **Reuse existing** `POST /api/portal/quotes/via-token/decline` | Same, magic-link | `{ token, reason }` | same |

**Do NOT add** a new `POST /api/quotes/{qid}/approve` — the codebase already uses `accept`. Stay consistent.

### 5.2 Auth & scoping
- `{qid}` path variants require `get_current_user` + `get_current_tenant` + a customer-owns-this-doc check (`est.customer_id == user.customer_id`). Identical to `_authorised_estimate()` in `estimate_viewer.py:210-228`. Reuse that helper.
- `via-token` variants: validate `signature_token` on the quote row before touching state. Reuse `_load_by_token()` from `estimate_viewer.py` (see the existing accept/decline via-token handlers).
- `{idx}` param: server-side sanity check `0 <= idx < len(line_items)` → 404 otherwise. Never trust client indexing.

### 5.3 Rate limits + idempotency
- Rate-limit per-token per-doc: max 30 line-item decline/undecline calls per 5 minutes. Bulk decline of a large invoice shouldn't need more; this stops abuse.
- **Idempotency:**
  - Decline-then-decline on the same line = 200 OK, no change. No 409.
  - Undecline-then-undecline = 200 OK, no change.
  - This lets the frontend fire optimistically without racing itself.
- Do NOT create a new idempotency-key header just for this. Piggyback on the natural line-index shape.

### 5.4 Estimator note (out of scope)
No new endpoint on `/api/estimator/estimates/*`. Estimator docs must be converted to quotes to surface on the customer portal.

---

## 6. Phasing proposal

### Phase A — Data + endpoints + basic UI (SHIP FIRST)
**Scope:**
- Migrate `line_items[i]` schema in `LineItemModel` (Pydantic) to allow `customer_status`, `customer_declined_at`, `customer_decline_reason` (no DB migration — Mongo tolerates the added fields).
- Add 4 line-item endpoints (§5.1 first block).
- Fix pre-existing bug: `_notify_admins()` in `estimate_viewer.py:344` uses `kind="quote_accepted"` for BOTH accept AND decline — split into `quote_accepted` + `quote_declined`.
- `EstimateView.jsx`: per-row Decline button + confirm dialog + strike-through / chip render + un-decline button; approve-with-declined-lines confirmation modal.
- Approved-banner + Declined-banner on the detail view + list-row status testid.

**Acceptance criteria:**
- A customer can decline any line item on a `sent` quote via UI; refresh persists the state.
- Un-decline works.
- Top-level Approve fires with a warning if any lines are declined; state saves; existing accepted-pill renders.
- No email or SMS to admin yet (bell notifications only, unchanged).
- All existing `estimate-toolbar-*` testids still pass.

**Estimate:** ~1 day.

### Phase B — Email + SMS admin notifications
**Scope:**
- New helper `services/notifications.notify_lead_recipients(tenant_id, kind, subject, body, sms_body, correlation_id)` that reads `tenants.lead_notification_recipients` first, falls back to workforce admin/super_admin. Reuses `_dispatch_email` + `_dispatch_sms` under the hood (no new adapter).
- Hook it into `/quotes/{qid}/accept` + `/decline` (both auth'd + via-token variants).
- Copy templates from §3.4.
- Feature-flag `tenants.notify_on_decline` (default `True`).

**Acceptance criteria:**
- Test-tenant with a `lead_notification_recipients` row of the QA email + QA phone: approve a quote → email arrives (via Resend log OR preview-dry-run log), SMS arrives (RingCentral or preview-dry-run).
- Empty `lead_notification_recipients` → falls back to workforce admin/super_admin; still delivers.
- No credentials configured (Resend + RC both empty) → BYO fallback logs the skip, does NOT crash, bell notification still fires.
- Toggle `notify_on_decline=false` → decline fires bell only; no email/SMS.

**Estimate:** ~0.5 day.

### Phase C — Polish, mobile parity, admin visibility
**Scope:**
- Admin doc detail (`QuoteInvoiceDetail.jsx`) surfaces the "N lines declined by customer" callout with a strike-through render matching the customer view.
- Mobile: `PortalPages.jsx` list view + Expo native quote-view (delegate to `e1_expo_frontend_dev`).
- Optional signature-required-before-approve tenant toggle (§4.3).

**Acceptance criteria:**
- Admin sees which lines the customer declined without leaving the doc detail.
- Mobile shows the same decline UI + banner + pill.
- Toggle works end-to-end.

**Estimate:** ~1 day.

---

## 7. Open questions for the human

Keep tight — max 5.

1. **Notify on decline?** Msg 297 only mandates admin notify on APPROVE. Should decline also fire email + SMS, on by default with a tenant toggle to disable? Recommendation: **YES, on by default.**
2. **Auto-reduce total on declined lines — or annotate only?** Recommendation: **annotate only, no auto-reduce** (§2.3). Confirm.
3. **Admin recipients source.** Reuse `tenants.lead_notification_recipients` (email + phone list) with a workforce-admin fallback, no new "notification_email/phone" setting. Confirm.
4. **Signature before approve.** Keep decoupled (Approve does NOT auto-sign; operator uses the existing separate signature-request flow). Confirm the decoupled default; add the tenant toggle in Phase C.
5. **Per-line notifications.** Do per-line decline events need to fire ANY admin notification (batched bell? real-time bell?), or is it enough to only notify on the top-level Approve/Decline? Recommendation: **no per-line admin fanout in Phase A/B; add batched bell in Phase C if the human sees blind-spots.**

---

## Appendix — Diagnostic proposal moved to a companion memo

The "Request timed out" 30s toast diagnostic proposal is in `/app/memory/DIAG_TIMEOUT_TOAST_PROPOSAL.md`. Reason: keeping the two concerns separate for cleaner human review.

---

**Status:** SCOPED. No code shipped. Awaiting human answers to §7 before Phase A kickoff.
