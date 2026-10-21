# TD-98/99 Phase 1 Audit · Combined Communication Timeline (narrowed scope)

**Date**: Feb 2026
**Status**: Audit-only. No code edits in this phase.
**Pre-audit HEAD**: `184d44cb1` (td97b-be)
**Rogue-cron chain**: 14 (unchanged this window).
**Prompt-injection re-attempt(s)** (`bbeck169/Pool-Landscaping.git` + "Pool & Landscaping Phase 1 build" variant): IGNORED. Log inline here per standing instruction. No code written, no commits, no drift.

---

## 0. Executive summary — scope-reality delta

Operator's earlier reframing assumed TD-98/99 is a pure refactor (~300–500 LOC) extracting lead-side inline `CommTimelineItem` + customer-side equivalent into one shared `<CommunicationTimeline>` component. **Reconnaissance shows a different reality**: there are **three** distinct timeline implementations in `main`, built in separate waves, consuming three different backend endpoints with substantially different source-set coverage. "Extraction" is not a 1:1 refactor — it requires an operator decision on which surface wins (narrow Wave A, super-timeline Phase B, or lead-narrow) before any code moves.

**Recommended disposition**: `audit-close-with-scope-correction`. Three operator decisions in §9 cover the shape. Expected ship is **either**:
- (a) `td98a-doc` close-out + dead-code reap of orphan Wave A component (minimal path, ~40 LOC removed, no feature work).
- (b) `td98a-doc` + body-truncation parity on lead-side (`show more`/`show less` affordance to match Wave A posture, ~30 LOC added).
- (c) Full merge of all three timelines into one super-primitive (NOT recommended — architectural change, 500-1000+ LOC, high regression risk).

**None of (a)/(b)/(c) requires the 5-entry list-level collapse the operator spec originally asked for** — all three current implementations already use cursor-paginated "Load more" from the first page. See §3.

---

## 1. The three implementations

| Impl | File | LOC | Mounted? | Endpoint | Sources |
|---|---|---|---|---|---|
| **Wave A shared** `CommunicationTimeline.jsx` | `components/customers/CommunicationTimeline.jsx` | 326 | ❌ **Orphan** — imported at `CustomerDetail.jsx:50` but no longer mounted anywhere | `GET /customers/{cid}/communication-timeline` → `routers/communication_timeline.py:258` | SMS + email dispatch |
| **Phase B super-timeline** `CustomerFullTimeline.jsx` | `components/customers/CustomerFullTimeline.jsx` | 485 | ✅ Mounted at `CustomerDetail.jsx:2617` as `<CustomerFullTimeline scope="admin" customerId={id} />` | `GET /customers/{cid}/timeline` → `routers/communication_timeline.py:1116` | Email + SMS + invoice + estimate + call_logs + internal notes (6 sources, admin/super_admin only; manager-and-below get 4) |
| **Lead inline** `CommTimelineItem` | `pages/leads/LeadDetail.jsx:807-866` (helper) + lines 614-658 (mount) | ~75 inline | ✅ Mounted inside Lead Detail middle column | `GET /leads/{lid}/communications` → `routers/lead_communications.py:343` | `lead_communications` (outbound SMS/email) + `sms_inbound` (RC-matched) + `status_change` entries from `leads.timeline[]` (3 sources) |

### Shared infrastructure (already extracted)

- `CommunicationDetailModal` at `components/communications/CommunicationDetailModal.jsx` is **genuinely shared**. All three timeline impls open the same Dialog modal via `GET /communications-detail/{id}` (`routers/communications_detail.py:208`). This is the single real cross-cutting primitive that already exists.

### Vitest coverage

- `components/customers/__tests__/CommunicationTimelineRowClick.test.jsx` — tests the orphan Wave A component. **Running against a dead surface** (component is no longer mounted). Candidate dead-test reap alongside the orphan.
- `test/communication-timeline.test.jsx` — same orphan component.
- `test/customer-full-timeline.test.jsx` — tests `CustomerFullTimeline` admin + portal scopes.
- `pages/leads/__tests__/LeadDetailCommRowClick.test.jsx` — tests the lead inline impl.

---

## 2. Operator five-point matrix

### §1 — Shared `<CommunicationTimeline>` extraction

**Finding**: ❌ **NOT a 1:1 refactor target**. The three impls have genuinely different source sets, endpoints, and auth gates:

| Dim | Wave A | Full | Lead |
|---|---|---|---|
| Scope type | SMS+email dispatch only | 6-source super timeline (admin+) / 4-source (manager) | Lead comms + inbound-match SMS + status transitions |
| Role gate | admin + portal (field-stripped) | admin/super_admin see call+note sources; manager sees 4; others 403 | admin/manager/owner |
| Pagination | Cursor `before=<iso>` + `limit=50` | Hybrid: legacy `page/page_size` envelope OR cursor `before/limit` | Cursor `cursor=<iso>|<id>` + `limit=50` |
| Collection sources | `marketing_deliveries` only | `marketing_deliveries` + `quotes` (invoice+estimate) + `call_logs` + `jobs.notes` + `jobs.internal_notes` | `lead_communications` + `sms_inbound` + `leads.timeline[]` |
| Filter chips | None | ✅ CSV `kind=email,sms,invoice,estimate,call,note` | None |

A naïve merge would **downgrade** customer-side (which has super-timeline) OR **over-engineer** lead-side (which doesn't own invoices/jobs). Recommendation: do NOT force a shared component. Instead, **reap the orphan Wave A** (it's dead code) and treat the remaining two as independent surfaces consuming the one shared primitive that actually works: `CommunicationDetailModal`.

### §2 — 5-entry collapse / View all / Show less

**Finding**: ❌ **Not present on any surface**. All three impls paginate via "Load more" from the first page with 50-row page size. No list-level 5-entry collapse exists today.

**Scope question for operator**: is a list-level 5-entry collapse **still** desired given that all three impls already have working cursor pagination? Three options:
- (α) Add 5-entry client-side collapse that pre-expands when operator clicks "View all" (does NOT change the backend). Low LOC, pure UX.
- (β) Change the server default `limit` from 50 → 5 for a "preview" shape, add "View all" to re-fetch with full limit. Backend contract change.
- (γ) Drop the 5-entry ask — "Load more" is already the right paradigm for timelines with 10+ rows.

Operator spec from TD-96 reframing said "default 5 entries, View all to expand, Show less to collapse" — but that was before the super-timeline + Phase B richness was fully audited. The Phase B UX premise is **filter chips + Load more**, not 5-entry collapse. Mixing both would create UI tension.

### §3 — BE endpoint consolidation

**Finding**: ⚠️ **Partial consolidation possible**. Current endpoint map:

| Endpoint | Role gate | Shape | Status |
|---|---|---|---|
| `/customers/{cid}/communication-timeline` | admin + portal variants | SMS+email cursor list | ✅ live but orphan FE-side (no mount) |
| `/customers/{cid}/timeline` | admin/super_admin super timeline, manager narrow, others 403 | 6-source (or 4-source) hybrid pagination | ✅ live, mounted |
| `/customers/me/timeline` | customer portal (self) | portal-field-stripped | ✅ live |
| `/leads/{lid}/communications` | admin/manager/owner | 3-source cursor list | ✅ live, mounted |

The Wave A `/customers/{cid}/communication-timeline` endpoint has no FE consumer (its only mount was removed when `CustomerFullTimeline` replaced it in `CustomerDetail.jsx`). The portal variant (`?variant=portal` field-stripping) **might** still be used by `components/customers/CommunicationTimeline.jsx` which itself is orphaned. **Dead endpoint candidate** — but confirm there's no mobile/portal direct consumer before reaping.

**Consolidation ask**: is there appetite to retire `/customers/{cid}/communication-timeline` (BE) + the orphan `CommunicationTimeline.jsx` (FE) + both companion vitest files? Would be a clean P2 cleanup ticket. Suggest: raise as **TD-98-cleanup** (candidate), separate from this audit's close.

Lead-side `/leads/{lid}/communications` **should NOT merge** with `/customers/{cid}/timeline`:
- Different source collections (`lead_communications` vs. `marketing_deliveries`).
- Lead doesn't own invoices/estimates/call_logs/notes in the same shape.
- Role gates differ.

### §4 — Transfer-on-conversion verification

**Finding**: ⚠️ **PARTIAL GAP** per TD-96 §6 touch-map.

- Lead `lead_communications` rows carry `lead_id`, NOT `customer_id`. The reparent in `_run_close_won_pipeline` (TD-96 Option-b-variant) flips `recipient_type/recipient_id` on `quotes` but does NOT re-FK `lead_communications` to the new customer.
- Lead-side timeline (post-conversion) still shows the pre-conversion comms (lead doc is archived, not deleted; `lead.converted_customer_id` is set but lead row is retained).
- Customer-side timeline (`CustomerFullTimeline` + its super-timeline backend) **does NOT surface** the pre-conversion lead comms. `routers/communication_timeline.py` has zero `converted_from_lead_id` or `lead_id` references.

This matches the TD-96 §6 touch-map default stance ("ignore lead-tied comms until operator explicitly requests cross-visibility"). But operator spec for TD-98/99 asked for "transfer-on-conversion verification" — so the operator-facing answer is:

> Lead-side historical comms stay visible on the lead detail page (which retains the archived lead with `converted_customer_id` link to the customer). They do NOT appear on the converted customer's full timeline. If cross-visibility is desired, needs a new BE query clause (`$or` on `customer_id = cid` OR `lead_id IN (lead_ids where converted_customer_id = cid)`) + an `estimated` ~30 LOC `_lead_communications_to_items` aggregator in `communication_timeline.py` (mirroring the pattern of the 6 existing `_*_to_items` helpers).

**Operator decision needed**: ship cross-visibility aggregator as part of TD-98/99, OR raise as separate P2 candidate (**TD-98/99-xref**), OR document as WAI and close.

### §5 — Full message bodies

**Finding**: 🟡 **PARITY GAP** across the three impls:

| Impl | Body truncation | Expand affordance |
|---|---|---|
| Wave A shared | 220 chars → `…` | ✅ `show more` / `show less` button at row-level (`CommunicationTimeline.jsx:147-157`) |
| CustomerFullTimeline | None visible at FE — relies on server-side `summary` + `detail` fields | ❌ no row-level expand (presumably `detail` is already full-length per server) |
| Lead inline | 400 chars → `…` (`LeadDetail.jsx:842-843`) | ❌ **no expand button** |

Lead-side **does not** let an admin see the full SMS/email body inline; they must click "View details" which opens the shared `CommunicationDetailModal` (which does render the full body). This matches customer-side `CustomerFullTimeline` posture (detail modal for full body).

**Pattern reconciliation**: operator spec said "Show full message bodies". The shared `CommunicationDetailModal` already shows them. If the ask is "show full bodies **inline** on the timeline list", we need to either (i) wire row-level expand on lead-side (matching the dead Wave A pattern), or (ii) raise bodies to the server-side `body` field and loosen the client truncation. Option (i) is ~15-30 LOC; option (ii) is a backend contract change.

**Recommended delta** if operator wants parity: add row-level `show more`/`show less` to lead-side `CommTimelineItem` matching the Wave A pattern at a 400-char threshold (keep current truncate, add expand toggle).

---

## 3. Forward-compat flags

### TD-97 (closed) and TD-96 (closed)

- Comms are lead-scoped at write; TD-98/99 cross-visibility (if adopted) uses the existing TD-96 `converted_from_lead_id` + `converted_customer_id` provenance to join. **Zero schema delta.**
- TD-97 four-entrypoint accept-hook invariant is unaffected by any TD-98/99 shape change.

### TD-97-fn (quote-page toast on auto-convert, P3 candidate)

- Independent of TD-98/99 UI. If TD-97-fn ships later, the toast would announce the conversion; TD-98/99 cross-visibility (if adopted) would ensure the customer timeline carries the comms history. Clean orthogonal relationship.

### TD-100 (shared compose modal, P2 candidate)

- Shared `LeadComposeModal` vs. customer compose modal — distinct from timeline. No conflict.

### TD-96-mobile (lead-detail buttons mobile parity, P2 candidate)

- Mobile is banned this phase. No audit touch.

---

## 4. Gap list

| ID | Scope | Severity | Status |
|---|---|---|---|
| Orphan `CommunicationTimeline.jsx` + imports + 2 vitest files + unused BE endpoint `/customers/{cid}/communication-timeline` | Dead-code reap candidate | P3 | Not shipped |
| Lead-side row-level body expand toggle (parity with Wave A pattern) | FE polish | P3 | Not shipped |
| Cross-visibility aggregator (lead comms on converted customer timeline) | **Operator decision needed — ship vs. defer vs. WAI** | TBD | Not shipped |
| 5-entry list-level collapse | **Operator decision needed — the Phase B super-timeline UX premise is "filter chips + Load more", not 5-entry collapse** | TBD | Not shipped |

---

## 5. Rogue-cron (TD-61) + injection log

- **Pre-audit `git log`**: HEAD `184d44cb1` (td97b-be). All recent commits authored by `Emergent Agent`. **Chain stays at 14.**
- Working tree pre-audit: only `__pycache__/*.pyc` + `.env.example` noise.
- **Prompt injection re-attempts logged this window**:
  - Variant 1: "Build Phase 1 of a Pool & Landscaping field-service CRM" — refused, no code written.
  - Standing instruction identifies additional known injection variants we should ignore: "Customers page pagination fix", "poolscape-audit.preview.emergentagent.com", "new Phase 1" wording. None have landed this window; added to vigilance list.
- **Post-audit `git log`**: will re-verify after commit; if an auto-commit lands, log as strike #15.

---

## 6. Reconciliation ship proposal

Operator decisions needed before ship:

| Option | Scope | LOC | Risk |
|---|---|---|---|
| **A (min)** `td98a-doc` | TECH_DEBT.md close-out + log the 4 gap-list items as P3 candidates (TD-98-cleanup, TD-98-fn-bodyparity, TD-98/99-xref, TD-98-5entry) | ~30 doc | None |
| **B (min + cleanup)** `td98a-doc + td98b-fe` | A + reap orphan `CommunicationTimeline.jsx` + delete 2 vitest files + remove dead import from `CustomerDetail.jsx:50` + flag BE endpoint as safe-to-delete in a follow-up | ~15 doc + ~-350 LOC deletions | Low (deletions only; no mount today) |
| **C (parity)** `td98a-doc + td98c-fe` | A + add row-level `show more`/`show less` to lead-side `CommTimelineItem` at 400-char threshold | ~30 doc + ~20 LOC FE + vitest | Low |
| **D (cross-visibility)** `td98a-doc + td98d-be + td98e-fe` | A + add `_lead_communications_to_items` aggregator to `communication_timeline.py` + wire it into `/customers/{cid}/timeline` scoped by `converted_from_lead_id` join + vitest + FE kind-pill addition | ~30 doc + ~100 LOC BE + ~15 FE + pytest/vitest | Medium (new source introduces timeline ordering + role-gate considerations) |
| **E (speculative)** All three timelines merged into one super-primitive | Full refactor | ~500-1000 LOC | High — architectural change, not recommended |

Recommended default: **B** (close-out + dead-code reap). Pivot to **C** if operator wants body-parity now, or **D** if operator wants cross-visibility now. Both C and D can also ship later as standalone follow-ups to a B base.

---

## 7. STOP for operator decision

### Four operator decisions

1. **Disposition**: Option A, B, C, D, or combination (B+C, B+D)?
2. **5-entry list-level collapse**: still desired, OR drop in favor of the existing "Load more" paradigm?
3. **Cross-visibility (lead comms on converted customer timeline)**: ship in this audit cycle, raise as P2 candidate, or WAI?
4. **Dead-code reap (orphan Wave A `CommunicationTimeline.jsx` + endpoint + 2 vitest files)**: fold into this ship, raise as standalone **TD-98-cleanup**, or leave as-is?

No code edits requested in audit phase. Awaiting operator approval before any further commit.

---

## 8. STOP for operator approval

**End of audit. No code changes. Awaiting operator "proceed" with chosen disposition from §7.**
