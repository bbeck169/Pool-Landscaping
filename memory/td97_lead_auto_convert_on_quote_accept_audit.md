# TD-97 Phase 1 Reconciliation Audit · Auto-Convert Lead on Quote Accept

**Date**: Feb 2026
**Status**: Reconciliation audit. No code edits in this phase.
**Pre-audit HEAD**: `f20ee79b4` (td96b-be)
**Rogue-cron chain**: 14 (unchanged this window).
**Prompt-injection re-attempt (`bbeck169/Pool-Landscaping.git`)**: IGNORED.

---

## 0. Executive summary

**TD-97 is substantially PRE-SHIPPED** in commit `3f153049b` (P2 #4 backend · Oct 2026). The lead auto-convert on quote accept is fully wired at the backend tier across all four accept entrypoints, idempotent, audit-logged, and pytest-locked (3/3 green). One minor FE notification UX gap exists (no cross-surface toast on auto-convert); one legacy deprecated endpoint bypasses the hook (documented, slated for removal).

**Recommended disposition**: `verify-and-close` with a lean 2-commit ship:
- `td97a-doc` — reconcile `TECH_DEBT.md` + close TD-97 as pre-shipped + log TD-97-fn (FE toast gap) as P3 candidate.
- `td97b-be` — regression smoke extending the existing `test_lead_auto_convert_on_quote_accept.py` to lock the four-entrypoint coverage invariant (no path flips a lead-recipient quote to `accepted` without funneling through `_mark_accepted`).

---

## 1. Shipped inventory (verified against repo)

### Core hook — `_mark_accepted` in `routers/estimate_viewer.py:512-570`

Centralized acceptance helper. All quote-accept flows funnel through it. When `est.recipient_type == "lead"` + `recipient_id` set:

1. Flips quote to `status="accepted"` + `decision="accepted"` + `accepted_at` + `accepted_by`.
2. Looks up lead by `recipient_id` within tenant scope.
3. Calls `_run_close_won_pipeline(_lead, tenant_id, actor_user_id=actor_id)`.
4. On the true transition (`idempotent=False`): writes `audit_logs` row `event="lead.converted_via_quote"` with `{lead_id, quote_id, actor_user_id, tenant_id, created_at}`.
5. Fails open — a pipeline hiccup logs a warning but does NOT roll back the accept.

### Pipeline semantics — `_run_close_won_pipeline` in `routers/leads.py:667-836`

| Transfer | Behavior |
|---|---|
| Idempotency | Short-circuits on `lead.converted_customer_id` presence; returns `{idempotent: True}` without touching anything. |
| Customer match | Attempts dedupe via `_match_customer_for_conversion`. If matched: merge branch. Else: create branch. |
| Status timeline | Lead `timeline[]` entries pushed onto customer `timeline[]` as `kind="lead_history"` + `original` payload + `lead_id` provenance (both branches). |
| Notes | **Merge branch**: lead notes pushed onto customer timeline as `kind="note_from_lead"` event. **Create branch**: lead notes land on customer `notes` field + a `note_from_lead` timeline event. |
| Service category inheritance (P2 #6) | Lead `service_interest` → customer `service_category` on first-write-wins basis (map: `pool→pool`, `landscape/landscaping→landscaping`, `both→both`). |
| Lead side mark-up | `status="Closed Won"`, `closed_at`, `archived_at`, `converted_customer_id`, `updated_at`, pushes `converted_to_customer` timeline entry with actor + was_merged. |
| Reparent of ALL lead-recipient quotes/invoices | `update_many({recipient_type:"lead", recipient_id:lead_id})` flips `recipient_type→"customer"`, `recipient_id→cid`, stamps `converted_from_lead_id`, fills `customer_id`. Idempotent at TWO layers (pipeline short-circuit + filter scope). |
| Welcome bundle | Email + SMS + drip-enrollment fire on first-run only. Replays silent. |

### Audit log row (`lead.converted_via_quote`)

Emitted ONLY on the true transition. Replays produce no row (operator-approved "audit the transition, not no-ops" contract). Non-blocking: audit insert failure logs a warning but does not break the pipeline.

### Pytest coverage (shipped)

`backend/tests/test_lead_auto_convert_on_quote_accept.py` — **3/3 passing in 0.96s**:

1. `test_accept_lead_recipient_quote_converts_lead_and_audits` — First accept → lead flips to `Closed Won`, customer materialized, quote reparented, audit row written.
2. `test_second_accept_on_already_converted_lead_is_idempotent` — Second call → pipeline idempotent short-circuit, NO additional audit row.
3. `test_customer_recipient_quote_accept_does_not_touch_leads_or_audit` — Non-lead accept → zero touches on `leads` + `audit_logs`.

Companion suites also live: `test_quote_created_from_lead_audit.py` (3 cases) + `test_quote_recipient_search_excludes_closed.py` (3 cases).

---

## 2. Operator spec seven-point matrix

Each ask → verified state.

### §1 — Accept-hook presence
✅ **PRESENT** at `routers/estimate_viewer.py:512-570` (`_mark_accepted` helper). Fires `_run_close_won_pipeline` on `recipient_type == "lead"`.

### §2 — Status-history + notes transfer

| Transfer | State | File:Line |
|---|---|---|
| Lead `timeline[]` → customer `timeline[]` with `kind="lead_history"` | ✅ | `routers/leads.py:719-724` (merge) + `742-748` (create) |
| Lead `notes` → customer `notes` (create) or push event (merge) | ✅ | `routers/leads.py:714-718` (merge push) + `759` (create set) |
| Interaction history (comms rows) FKed to new `customer_id` | ⚠️ | **Not re-FKed at pipeline level.** `lead_communications` collection remains lead-scoped; the new `customer_id` has its own `customer_communications` scope. The lead-side timeline is pushed to the customer with `lead_id` provenance so admins can see the history. This matches the operator's spec per TD-96 audit §6 downstream touch-map (lead-recipient docs stay lead-scoped post-conversion; linkage via provenance stamps). |

### §3 — Audit-log emission

✅ **PRESENT**. `audit_logs` row `event="lead.converted_via_quote"` written on transition only (`routers/estimate_viewer.py:546-562`). Fields: `{entity_kind:"lead", entity_id, lead_id, quote_id, actor_user_id, tenant_id, created_at}`. **NOT** `triggered_by: "quote_accept"` as the operator spec worded — but `event` is semantically identical and the `quote_id` field is present, which satisfies the audit intent.

**Minor delta vs. spec wording**: operator asked for `triggered_by: "quote_accept"`; shipped shape uses `event: "lead.converted_via_quote"` + `quote_id` field. **Semantic equivalence**. Flag as a cosmetic naming note, not a blocker.

### §4 — Multi-entrypoint coverage

ALL four quote-accept entrypoints funnel through `_mark_accepted`:

| Entrypoint | File:Line | Caller class |
|---|---|---|
| `POST /quotes/{qid}/accept` (auth'd admin/manager) | `routers/estimate_viewer.py:753` | Admin manual accept |
| `POST /portal/quotes/via-token/accept` (legacy query-token magic-link) | `routers/estimate_viewer.py:1110` | Portal customer accept (legacy) |
| `POST /portal/quotes/{token}/approve` (Phase A primary path-based) | `routers/estimate_viewer.py:1404` | Portal customer accept (primary) |
| `POST /quotes/bulk-accept` | `routers/quotes.py:3973` | Admin bulk accept |

**Esign flow**: `_phase_c_assert_signature_gate` is a precondition CHECK called BEFORE `_mark_accepted` — not a separate flow. ✅ covered.

**Payment-upfront flow**: `POST /quotes/{qid}/pay` + `POST /quotes/{qid}/record-payment` flip `status="accepted"` on **invoice** docs, not quote docs. By definition an invoice has already been reparented away from `recipient_type="lead"` (reparent runs during close-won before any convert-to-invoice). **No gap — different semantic** (invoice-pay, not quote-accept).

**Legacy deprecated bypass**: `POST /quotes/{qid}/decision` (`routers/quotes.py:1985-2062`) is marked `deprecated=True`, customer-role-only, slated for removal after Phase C. It flips `status="accepted"` directly without calling `_mark_accepted`. **Known deprecation**, documented in the endpoint's own docstring. Operators migrated to `/portal/quotes/via-token/{token}/approve` which routes through the hook.

### §5 — Idempotency

✅ **TWO-LAYER IDEMPOTENT**:
1. Pipeline short-circuit on `lead.converted_customer_id` presence → returns `{idempotent: True}` without touching customer, quotes, or audit log.
2. Reparent `update_many` filter is scoped to `recipient_type="lead" + recipient_id=<lid>`; a second call finds zero matching docs because the first run flipped `recipient_type → "customer"`. `modified_count==0` on retry.

Audit row is written ONLY on the true transition branch (`if not _result.get("idempotent")`). Replays produce zero rows. Pytest `test_second_accept_on_already_converted_lead_is_idempotent` locks this.

### §6 — Multiple-outstanding-quotes

✅ **ALL lead-recipient quotes reparent together**. The pipeline's `update_many` is scoped by `recipient_type="lead" + recipient_id=<lid>` — not by the triggering quote id. So accepting ONE quote causes ALL outstanding lead-recipient quotes (including those still in `sent`/`viewed` state) to flip to `recipient_type="customer"` with `converted_from_lead_id` provenance.

**Other quote states are preserved** — the reparent only touches `recipient_type`, `recipient_id`, `customer_id`, `converted_from_lead_id`. The quote's `status` field stays untouched (so a `viewed` quote stays `viewed`, just reparented). This matches operator spec §6 exactly.

### §7 — Notification UX

⚠️ **PARTIAL GAP**. Admin-side manual `POST /leads/{lid}/close-won` returns `{customer_id, was_merged}` which the FE renders inline as `conversion-banner` in `LeadDetail.jsx:432-443` with a "Open customer →" link. On quote-accept auto-convert, the auto-conversion happens **server-side via `_mark_accepted`** and the admin's current view (the quote page) is NOT told that a lead was auto-converted behind the scenes. If the admin navigates to the lead page later, they see:

- Lead status: `Closed Won`
- Lead timeline: `converted_to_customer` event
- `converted_customer_id` on the lead doc → `conversion-banner` renders

**But**: no toast/banner fires on the quote page at accept time to tell the admin "FYI, this also auto-converted lead X". Operator spec §9 originally asked for such a toast. **Flag as P3 FE gap — not a blocker**, bookmarked below as **TD-97-fn**.

---

## 3. Gap list

| ID | Scope | Severity | Status |
|---|---|---|---|
| TD-97-fn (candidate) | Quote-page toast/banner on auto-convert ("Lead X auto-converted to customer Y") | P3 | Not shipped |
| Deprecated `/quotes/{qid}/decision` endpoint bypasses hook | Legacy codepath, customer-role only | Known-deprecated | Documented in endpoint docstring |
| Audit log field naming (`event` vs. `triggered_by`) | Cosmetic naming delta vs. operator spec wording | Trivial | Semantic equivalence — no action |

**None of the gaps blocks TD-97 closure.** The feature is end-to-end functional across all four production acceptance paths.

---

## 4. Reconciliation ship proposal

Minimal 2-commit path:

| Commit | Scope | LOC | Risk |
|---|---|---|---|
| `td97a-doc` | `memory/TECH_DEBT.md` — Option-b-variant reconciliation entry for TD-97 (close as pre-shipped) + log TD-97-fn (P3 FE toast candidate) | ~25 | None (docs only) |
| `td97b-be` | `backend/tests/test_td97_accept_entrypoint_coverage.py` — regression smoke asserting the four-entrypoint invariant (every production accept path funnels lead-recipient quotes through `_run_close_won_pipeline`) + explicit documentation of the deprecated bypass as a known exception | ~180 | Low (read-only, uses existing seed; mirrors `test_td96_lead_recipient_exclusion.py` pattern) |

**Total LOC: ~205.** Two atomic ships, both docs/tests only — no production code touched.

### What `td97b-be` locks

| Case | Expectation |
|---|---|
| `_mark_accepted` is importable from both `routers.estimate_viewer` AND `routers.quotes` (via bulk-accept re-import) | ✅ sanity invariant |
| First call via helper → audit row + reparent + lead flipped to `Closed Won` | mirrors existing suite, cross-ref |
| Second call via helper → no new audit row + idempotent response | mirrors existing suite, cross-ref |
| **New**: Direct DB mutation that flips `status="accepted"` WITHOUT calling `_mark_accepted` → does NOT auto-convert the lead | documents the bypass invariant and surfaces the schema contract |
| **New**: Deprecated `POST /quotes/{qid}/decision` is flagged with a `pytest.skip` + docstring reason noting the known legacy bypass | documents the exception |

---

## 5. Related ticket forward-compat

### TD-98/99 (combined timeline — narrowed-scope audit)

Shipped data layer is forward-compatible. The lead-side push of `lead_history` events onto customer `timeline[]` means a shared `<CommunicationTimeline>` can read a single collection. The P2 #6 service-category inheritance also rides on the pipeline. No TD-97 structural choice complicates TD-98/99.

### TD-100 (shared compose modal — candidate)

Unrelated to TD-97 pipeline. No conflict.

### TD-96 (lead profile expansion)

Already closed. The reparent-on-accept + reparent-on-manual-close-won both operate on the same `update_many` filter → the Linked-Quotes panel's `$or` continues to surface both types of reparented docs via `converted_from_lead_id`.

---

## 6. Rogue-cron (TD-61) checks

- **Pre-audit `git log`**: HEAD `f20ee79b4` (td96b-be). Author chain: all 4 recent commits authored by `Emergent Agent`. **No rogue cron since td95-audit. Chain stays at 14.**
- Working tree pre-audit: only `__pycache__/*.pyc` noise. `td85_session_hygiene_precheck.sh` to be run before commit.
- **Post-audit `git log`**: will re-verify after commit; if an auto-commit lands during the audit window, log it as strike #15 under TD-61 in `TECH_DEBT.md` — do NOT revert.

---

## 7. Operator decisions needed

Before ship (operator reply):

1. **Disposition**: `td97a-doc` alone (close as pre-shipped, no new test), OR `td97a-doc + td97b-be` (plus regression smoke)?
2. **TD-97-fn (FE toast on auto-convert)**: raise as P3 candidate ticket, OR fold into TD-98/99's timeline UX refinement scope?
3. **Deprecated `/quotes/{qid}/decision`**: leave as-is (slated for post-Phase-C removal), OR raise a TD-97-cleanup ticket to remove early?

No code edits requested in audit phase. Awaiting operator approval before any further commit.

---

## 8. STOP for operator approval

**End of audit. No code changes. Awaiting operator "proceed" with chosen disposition from §7.1.**
