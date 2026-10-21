# TD-96 Phase 1 Audit · Lead Profile Expansion (Text / Email / Create Quote + Linked Quotes)

**Date**: Feb 2026
**Status**: Audit-only. No code edits in this phase.
**Pre-audit HEAD**: `e70dd9e1c` (td95b-fe)
**Rogue-cron chain**: 14 (unchanged this window).
**Prompt-injection re-attempt (`bbeck169/Pool-Landscaping.git`)**: IGNORED.

---

## 0. Executive summary — unexpected finding

**TD-96 scope is substantially PRE-SHIPPED.** Repo reconnaissance confirms the three asked-for primitives (SMS button, Email button, Create Quote button + count badge), the inline Linked-Quotes mini-list (brief §13), the shared compose modal, the lead-side communication timeline, the backend compose/list endpoints, the polymorphic quote recipient model, and the close-won reparent pipeline are already live in `main`. Vitest + pytest coverage was shipped alongside. See §2 for inventory. Even **TD-97** (auto-convert on quote accept) appears to have been shipped in commit `3f153049b`.

**Recommended disposition**: `verify-and-close`. One lean doc-only reconciliation ship (`td96a-doc`) that updates `TECH_DEBT.md` + adds a short pytest smoke contract check for the `GET /leads/{lid}/quotes` + close-won reparent round-trip. No feature code required. See §10.

If the operator wants a *build* ship (new feature on top), the only remaining structural gap is the deferred shared `<CommunicationTimeline>` extraction — explicitly in TD-98/99's scope, not TD-96.

---

## 1. Chosen strategy (already live) — NOT the brief's lean Option a

The brief leaned Option a (lean `lead_id` nullable FK on quote). What shipped is **Option b-variant**: polymorphic `recipient_type ∈ {customer, lead}` + `recipient_id`. Rationale on the shipped side (reconstructed from `routers/quotes.py:627-644`):

- Single column pair holds the owner for either entity kind.
- Convert-to-customer reparent flips `recipient_type → "customer"` + `recipient_id → <cid>` and stamps `converted_from_lead_id = <lid>` for provenance (`routers/leads.py:812-829`).
- Linked-quotes list uses `$or` on `(recipient_type="lead" + recipient_id=lid)` OR `converted_from_lead_id=lid` so operators keep visibility post-conversion (`routers/leads.py:333-345`).
- `GET /leads/{lid}` count badge uses the same compound index (`routers/leads.py:297-306`).

The operator's a/b/c question is therefore moot — it was decided before TD-96 was filed. Audit does NOT propose a swap to Option a; the cost of migrating indexed data back to a lean FK is strictly larger than the semantic cleanup benefit.

Flag: `TECH_DEBT.md` doesn't currently record this decision as a cross-reference. The doc-only ship below closes that gap.

---

## 2. Shipped inventory (verified against repo)

### Backend
| Surface | File:Line | Status |
|---|---|---|
| `POST /quotes` accepts `recipient_type`, `recipient_id` | `routers/quotes.py:627-644, 748-749` | ✅ live |
| Quote-create stamps `lead_id` legacy pointer (compat) | `routers/quotes.py:873` | ✅ live |
| `GET /leads/{lid}` returns `quotes_count` | `routers/leads.py:297-306` | ✅ live |
| `GET /leads/{lid}/quotes?limit=N` (pre + post-conversion `$or`) | `routers/leads.py:317-359` | ✅ live |
| Close-won `_reparent_result` on `db.quotes.update_many` | `routers/leads.py:812-829` | ✅ live |
| `POST /leads/{lid}/send-sms` | `routers/lead_communications.py:202` | ✅ live |
| `POST /leads/{lid}/send-email` | `routers/lead_communications.py:258` | ✅ live |
| `GET /leads/{lid}/communications` paginated cursor | `routers/lead_communications.py:343` | ✅ live |
| Idempotency on reparent (short-circuit on `converted_customer_id` + scope on `recipient_type="lead"`) | `routers/leads.py:803-820` | ✅ live |
| Compound index `(tenant_id, recipient_type, recipient_id)` | `migrations/quotes_recipient_index_v1` | ✅ live (per inline comment ref) |

### Frontend
| Surface | File:Line | Status |
|---|---|---|
| `lead-detail-send-sms` button (manager+) | `pages/leads/LeadDetail.jsx:368-378` | ✅ live |
| `lead-detail-send-email` button (manager+) | `pages/leads/LeadDetail.jsx:379-390` | ✅ live |
| `lead-create-quote` button (admin only) | `pages/leads/LeadDetail.jsx:676-697` | ✅ live |
| Count badge `lead-create-quote-count` | `pages/leads/LeadDetail.jsx:688-695` | ✅ live |
| Navigate contract: `/quotes/new?recipient_type=lead&recipient_id=<id>` | `pages/leads/LeadDetail.jsx:679-681` | ✅ live |
| Linked-Quotes mini-list panel (admin, lazy, `View all`, reparented marker) | `pages/leads/LeadDetail.jsx:724-779` | ✅ live |
| `LeadComposeModal` (SMS + email, consent override, GSM-7 counter) | `pages/leads/LeadComposeModal.jsx` | ✅ live |
| Inline Communication Timeline + `View details` → shared Dialog | `pages/leads/LeadDetail.jsx:614-658, 807-866` | ✅ live |

### Tests (shipped)
- `pages/leads/__tests__/lead-create-quote-button.test.jsx` — 8 cases (role gate × 7, nav contract × 1, badge × 3)
- `pages/leads/__tests__/LeadDetailLinkedQuotes.test.jsx` — 5 cases (panel visibility, nav, view-all, non-admin, zero-count)
- `pages/leads/__tests__/LeadDetailCommRowClick.test.jsx` — 3 cases (view-details affordance, fetch wiring, status_change suppression)

---

## 3. Fifteen-question matrix

Each row: brief ask → current state (`✅ shipped` / `⚠️ gap` / `❓ needs-verify`).

| # | Question | State | Note |
|---|---|---|---|
| 1 | Lead profile UX: are SMS + Email + Create Quote buttons on the detail header? | ✅ | SMS/Email in top action row (manager+), Create Quote in right Actions column (admin). |
| 2 | Button placement follows customer-profile conventions? | ✅ | SMS/Email mirror customer-profile pattern (`CustomerDetail.jsx:2714+`). Create Quote lives in the Actions column, not the header — matches the Close Won / Close Lost cluster. |
| 3 | SMS/Email compose modal reuse customer-profile shape? | ⚠️ | A dedicated `LeadComposeModal.jsx` was built (consent override + GSM-7 counter). Customer side has its own `Send Email/SMS modal`. Two separate modals, not one shared component. Refactor opportunity — flag for TD-98/99 or a dedicated TD. |
| 4 | Create Quote → `/quotes/new?recipient_type=lead&recipient_id=<id>` URL contract? | ✅ | Exact match (`LeadDetail.jsx:679-681`); locked by vitest. |
| 5 | Quote schema delta — how is the lead attached? | ✅ | Polymorphic `recipient_type/recipient_id` + legacy `lead_id` pointer stamped on create. Not lean Option a. |
| 6 | Convert-to-customer transfer semantics (full reparent vs. pointer-flip)? | ✅ | **Full reparent**: `recipient_type → "customer"`, `recipient_id → <cid>`, `converted_from_lead_id → <lid>` stamp. Linked-quotes `$or` keeps lead-side visibility after. |
| 7 | Idempotency on reparent? | ✅ | Pipeline-level `converted_customer_id` short-circuit + scoped filter (`recipient_type="lead" + recipient_id=<lid>`) ensures a 2nd call writes zero docs. |
| 8 | Auth/role gating on each surface? | ✅ | SMS/Email: manager+ (`canCompose`). Create Quote: admin/super_admin/owner only. Linked-Quotes panel: admin only. Backend `POST /quotes` is `require_admin`. All gates aligned. |
| 9 | Telemetry on button clicks? | ❓ | No `client_telemetry` call fires from `lead-create-quote` / `lead-detail-send-*`. **Verify-needed**: is operator OK leaving these untelemetered given customer-side parity? |
| 10 | Empty states? | ✅ | Phone/email disabled with tooltip; `No address provided` empty-state for geo; Linked-Quotes panel only renders when `quotes_count > 0 AND fetch non-empty`. |
| 11 | Error paths? | ✅ | Compose modal shows provider status / raw error. Linked-Quotes fetch is fail-open (`.catch(() => setLinkedQuotes(null))`). Count-badge back-compat for legacy payloads tested. |
| 12 | Mobile parity note? | ⚠️ | `/app/mobile/` edits BANNED this phase. Flag: audit does not inspect mobile. Record as TD-96-mobile parity bookmark if operator wants it. |
| 13 | Linked-Quotes inline list (brief §13)? | ✅ | Shipped as `lead-linked-quotes-panel` (admin, lazy, status pills, reparented marker, View all → `/quotes?lead=<id>`). Mirrors customer-profile `Last N invoices`. |
| 14 | Migration / backfill needed? | ✅ | `quotes_recipient_index_v1` is live. No new backfill required. One structural question (§5) — verify-only. |
| 15 | Rollback story? | ✅ | `recipient_type/recipient_id` columns are additive (legacy `customer_id` still populated per `routers/quotes.py:748-749`). Reverting the FE buttons is a trivial surgical commit. Reparent writes are provenance-stamped (not destructive). |

---

## 4. Downstream touch-map

Default stance from brief: existing surfaces should **ignore lead-tied quotes until conversion**. Audit verifies:

| Surface | Behavior today | Exception needed? |
|---|---|---|
| Admin **InvoicesList** (TD-93/94/95 flow) | Filters on `doc_type == "invoice"`. Lead-recipient quotes are `doc_type == "quote"` and are excluded automatically. | ❌ none |
| **Payments-summary** (`/payments-summary`) | Aggregates `doc_type == "invoice"` with `recipient_type` scopes. Lead-recipient docs with `doc_type == "quote"` do not reach aging/collected tiles. | ❌ none |
| **Reports / revenue by service / close-ratio** | All scoped to converted-customer docs. Pre-conversion lead quotes contribute to pipeline reports (sales_pipeline) only. | ❌ none |
| **Portal (customer-facing)** | Customer-portal queries scope by `recipient_type="customer"`. Lead-recipient docs invisible until reparent flips the type. | ❌ none |
| **Mobile** | Not inspected this phase (guardrail). | ❓ flagged — see §3 Q12 |
| **Global search / dashboard** | Lead objects are indexed separately from customer/quote; search returns lead cards. Quote search returns only post-conversion customer-recipient docs. | ❌ none |

Verification task for the doc-only ship: add a one-shot pytest smoke that asserts the payments-summary + InvoicesList filters do NOT surface a `recipient_type="lead"` doc.

---

## 5. Email-button novel-scope question (operator ask)

Operator asked: *does customer profile have an Email button today, or is lead-side novel?*

**Answer**: Customer profile already has it. `pages/customers/CustomerDetail.jsx:2714` carries the `Feb-2026 Customer Detail Additions — Send Email/SMS modal` block. SMS + Email are both wired. The lead-side send-email button is **parity**, not novel scope. No operator decision required on adding customer-side Email.

Minor residual: the two modals are not a shared component (see §3 Q3). Deferred.

---

## 6. Forward-compat flags for TD-97 and TD-98/99

### TD-97 (auto-convert on quote accept)
**Finding**: Commit `3f153049b` subject reads `P2 #4 · backend · quote.created_from_lead audit + lead auto-convert on quote accept + closed-lead filter on /quote-recipients/search`. **TD-97 appears to already be shipped at the backend.** Audit does not re-verify quote-accept flow in this phase; recommend a dedicated TD-97 Phase-1 audit that confirms: (a) accept hook fires `_run_close_won_pipeline`, (b) idempotency works when accept lands twice, (c) reparent kicks in post-accept.

**Structural impact on TD-96**: zero. The shipped `recipient_type/recipient_id` + `converted_from_lead_id` schema already satisfies TD-97's needs — no breaking change required.

### TD-98/99 (combined timeline: shared `<CommunicationTimeline>`)
**Finding**: Lead-side timeline is **inline** in `LeadDetail.jsx` (`CommTimelineItem` local function, lines 807-866). Customer side has its own equivalent. No shared component exists today. The brief explicitly defers shared extraction to TD-98/99. Current implementation is forward-compatible — both surfaces consume the same `/communications-detail/<id>` shared Dialog modal (`CommunicationDetailModal`), so the data layer is already unified. Only the row-renderer is duplicated.

**Structural impact on TD-96**: zero. The deferred extraction will be a pure refactor, no schema or endpoint change.

### `lead_id` on invoice doc (operator's reminder)
Audit checked: **invoice docs inherit `recipient_type/recipient_id` from the parent quote at convert-to-invoice time** (per `routers/quotes.py` `invoice_builder` propagation referenced in prior commit `cea1a4890`). Pre-conversion payments against a lead-recipient quote would reference `lead_id` as the owner — this is correct and already live. **No invoice-schema delta needed.** TD-97 can rely on this without a schema change.

---

## 7. "What's actually left"

| Item | Severity | Ship candidate |
|---|---|---|
| `TECH_DEBT.md` doesn't record the Option-b-variant decision | P3 | `td96a-doc` reconciliation |
| No pytest smoke for the `recipient_type="lead"` exclusion in InvoicesList + payments-summary | P2 | `td96b-be` (optional) |
| Telemetry events on `lead-create-quote` / `lead-detail-send-*` clicks | P3 | `td96c-fe` (optional) |
| Shared `LeadComposeModal` ↔ customer compose modal refactor | P2 | **Deferred — not TD-96** |
| Shared `<CommunicationTimeline>` extraction | P2 | **Deferred — TD-98/99** |
| Mobile parity for the three lead-detail buttons | P2 | **Deferred — mobile ban** |

**None of the P2/P3 items is blocking**. The lead-profile expansion feature is end-user-complete.

---

## 8. Ship split proposal (LOC estimates)

Minimal verify-and-close path (recommended):

| Commit | Path(s) | LOC | Risk |
|---|---|---|---|
| `td96a-doc` | `/app/memory/td96_lead_profile_expansion_audit.md` (this file) + `/app/TECH_DEBT.md` (3-5 line Option-b-variant decision record) | ~15 | None (docs only) |

**Total LOC: ~15.** Single atomic ship.

Optional follow-up (not required for TD-96 close):

| Commit | Path(s) | LOC | Risk |
|---|---|---|---|
| `td96b-be` *(optional)* | `backend/tests/test_lead_recipient_exclusion.py` — pytest smoke on InvoicesList + payments-summary scope | ~80 | Low (read-only, uses existing seed) |
| `td96c-fe` *(optional)* | `pages/leads/LeadDetail.jsx` — add 3 `client_telemetry` calls | ~15 | Low (observability only) |

Operator may authorize `td96a-doc` alone, `td96a + td96b`, or the full three-ship set.

---

## 9. Rogue-cron (TD-61) checks

- **Pre-audit `git log`**: HEAD `e70dd9e1c` (td95b-fe). No author-mismatch commits between td95-audit and now. Chain remains at **14**.
- Working tree pre-audit: only `__pycache__/*.pyc` noise. `td85_session_hygiene_precheck.sh` to be run before commit.
- **Post-audit `git log`**: will re-verify after commit; if an auto-commit lands during the audit window, log it as strike #15 under TD-61 in `TECH_DEBT.md` — do NOT revert.

---

## 10. Recommended operator decisions

Before ship (operator reply needed):

1. **Disposition**: `verify-and-close` as a single doc-only ship (`td96a-doc`), OR expand to include `td96b-be` pytest smoke, OR include `td96c-fe` telemetry?
2. **Shared compose modal refactor**: park as a dedicated TD (e.g., TD-100-compose-shared), or fold into TD-98/99 scope?
3. **Mobile parity bookmark**: raise a TD-96-mobile ticket for the lead-detail buttons, or treat as covered by generic mobile parity backlog?

No code edits requested in audit phase. Awaiting operator approval before any further commit.

---

## 11. STOP for operator approval

**End of audit. No code changes. Awaiting operator "proceed" with chosen disposition from §10.1.**
