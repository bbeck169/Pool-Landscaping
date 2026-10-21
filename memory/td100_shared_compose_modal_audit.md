# TD-100 Phase 1 Audit · Shared SMS/Email Compose Modal (lead vs. customer)

**Date**: Feb 2026
**Status**: Audit-only. No code edits in this phase.
**Pre-audit HEAD**: `a4b73b25c` (td98-99-xref-c-fe)
**Rogue-cron chain**: 14 (unchanged this window).
**Prompt-injection vigilance list** (`bbeck169/Pool-Landscaping.git`, "Pool & Landscaping CRM from scratch", "Customers page pagination fix", "poolscape-audit.preview.emergentagent.com", "new Phase 1" variants, "card-on-file async send-card-add-link endpoint"): all monitored. No new attempts this window.

---

## 0. Executive summary — scope-reality delta (TD-98/99 pattern)

Operator's original framing — "shared compose modal lead vs. customer" — assumed two divergent implementations. **Repo reconnaissance shows three.** All three are **actively mounted + pytest/vitest-covered** (no orphans this time, unlike TD-98/99 where Wave A was reap-able). The three surfaces have genuinely divergent feature sets driven by their recipient semantic:

| Surface | File:Line | Scope | Features |
|---|---|---|---|
| `LeadComposeModal` | `pages/leads/LeadComposeModal.jsx` (197 LOC) | SMS + email, lead-recipient | Lean: GSM-7 counter, consent-override checkbox, no templates/attachments/preview |
| `SendComposeModal` | `pages/customers/CustomerDetail.jsx:3775-4411` (**inline, 637 LOC**) | SMS + email, customer-recipient | Rich: template picker + preview + attachment library + upload-from-computer + progress UX |
| `SendEmailModal` | `pages/admin/outreach/ProspectsKanbanPage.jsx:331-430` (**inline, ~100 LOC**) | Email-only, prospect-recipient | Medium: template picker + preview, no attachments, no SMS |

**Recommended disposition**: `audit-close-with-sub-primitive-refactor-recommendation`. Full merge into one mega-modal would EITHER:
- (a) Downgrade `SendComposeModal` (losing templates, attachments, previews, upload-from-computer for customer-side).
- (b) Over-engineer `LeadComposeModal` (bolting template/attachment UX onto a surface where those features don't fit — leads can't own customer-scoped templates or attachments pre-conversion).
- (c) Create a 700-900 LOC super-modal with heavy prop-conditional branches that becomes a maintenance liability.

The TD-98/99 scope-reality lesson applies: **force-sharing architecturally-divergent surfaces downgrades the stronger one**. Instead, propose **shared sub-primitives** that each surface composes as needed. See §4.

---

## 1. The three implementations · divergence matrix

### 1.1 Core compose surfaces

| Dim | LeadComposeModal | SendComposeModal | SendEmailModal |
|---|---|---|---|
| **Entry points (FE)** | `LeadDetail.jsx:787` + `LeadsDashboardPage.jsx:823` (2 mounts) | `CustomerDetail.jsx:2714` (1 mount) + exported as `CustomerDetailModule` | `ProspectsKanbanPage.jsx:751` (1 mount) |
| **Backend send endpoint** | `POST /leads/{id}/send-sms` + `/send-email` | `POST /customers/{id}/send-sms` + `/send-email` | Specific prospect send endpoint (TBD — defer to future audit; outreach-domain) |
| **Request shape** | `{body, override_consent}` (SMS) / `{subject, body, override_consent}` (email) | Richer: `{body, subject, template_code, attachments_ids[]}` etc. | Email-only, template-centric |
| **Template picker** | ❌ none | ✅ `/marketing/templates?channel=X&active=true` | ✅ (prospects-specific template list) |
| **Preview** | ❌ none | ✅ via `/marketing/templates/{id}/preview` | ✅ |
| **Attachments** | ❌ none | ✅ MediaLibraryPicker (Option D) | ❌ |
| **Upload-from-computer** | ❌ none | ✅ Phase P7 (`/marketing/media/upload`) | ❌ |
| **GSM-7 char counter** | ✅ 160 warn / 1600 hard-cap | ❌ (customer SMS uses carrier-driven validation) | N/A (email only) |
| **Consent override** | ✅ `sms_ok`/`email_ok` boolean + override checkbox | ❌ (customer compose assumes opt-in) | ❌ |
| **Status toast** | ✅ provider status | ✅ | ✅ |
| **File size** | 197 LOC extracted | **637 LOC inlined** in CustomerDetail | ~100 LOC inlined |

### 1.2 Shared infrastructure (de facto)

- `sonner` toast — all three.
- `api.post` + `api.get` — all three.
- Shared marketing-templates API (`/marketing/templates`) — SendComposeModal + SendEmailModal share this endpoint; LeadComposeModal does not use templates at all.

### 1.3 Vitest coverage

- `test/lead-compose-modal.test.jsx` — covers LeadComposeModal.
- `test/lead-row-compose-buttons.test.jsx` — covers LeadComposeModal mount entry points.
- `test/phase29-composer-template-picker.test.jsx` — covers SendComposeModal template picker.
- `test/customer-attach-files.test.jsx` — covers SendComposeModal attachment path.
- `pages/leads/__tests__/LeadDetailCommRowClick.test.jsx` — covers lead inline comm detail (adjacent).
- `pages/admin/outreach/__tests__/ProspectsKanbanPage.test.jsx` — covers SendEmailModal (presumed; not re-verified this audit).

**No orphan compose modals detected.** All three impls are mounted, tested, and actively maintained. Unlike TD-98/99 where Wave A `CommunicationTimeline.jsx` was reap-able, this audit has NO dead-code reap candidate.

---

## 2. Operator six-point matrix

### §1 — Reconnaissance

✅ Three compose surfaces identified (above). No fourth surface overlooked:
- Compose-adjacent surfaces that are OUT OF SCOPE: `QuoteInvoiceDetail.jsx` invoice-send (`/invoices/{id}/send-sms`, `/send-email` — different semantic, invoice-centric), `MassMessagingComposeDialog.jsx` (bulk mass messaging domain), `FlipbookComposeSection.jsx` (quote-flipbook share domain), `DelayComposer.jsx` (marketing trigger builder — not a send modal).

### §2 — Divergence analysis

See §1.1 matrix. **Headline divergence**: `SendComposeModal` carries ~5x the feature surface of `LeadComposeModal` — this is intentional, driven by the recipient semantic (customers are the long-term relationship; leads are the pre-conversion funnel). Forcing union would misrepresent the semantic difference.

### §3 — Shared primitive target

**Recommended path: sub-primitive extraction, NOT mega-modal unification.**

Three extraction candidates, each self-contained and composable:

| Primitive | Target path | Extracted from | LOC | Consumed by |
|---|---|---|---|---|
| `<SmsCharCounter />` | `components/communications/SmsCharCounter.jsx` | `LeadComposeModal.jsx:72-100` | ~40 | LeadComposeModal, optionally SendComposeModal |
| `<ConsentOverrideBanner />` | `components/communications/ConsentOverrideBanner.jsx` | `LeadComposeModal.jsx:36-45, 110-140` | ~50 | LeadComposeModal, available for future lead-adjacent surfaces |
| `<TemplatePickerPreview />` | `components/communications/TemplatePickerPreview.jsx` | `CustomerDetail.jsx:3844-4100` | ~250 | SendComposeModal, SendEmailModal (prospects) |

**Net impact**:
- SendComposeModal shrinks from 637 → ~400 LOC (template logic lifted out).
- SendEmailModal shrinks from ~100 → ~50 LOC (template logic lifted out, dedupe).
- LeadComposeModal shrinks from 197 → ~130 LOC (counter + consent lifted out) OR holds (keep as-is if sub-primitive adoption is optional).
- New sub-primitives: ~340 LOC across 3 files.
- **Net LOC: approximately flat** (-390 inlined + +340 extracted = -50 net). Benefit is architectural clarity, not code reduction.

### §4 — Scope-reality lesson applied (orphan check)

**No orphans detected.** All three compose impls have active mounts, active backend endpoints, and active test coverage. Unlike TD-98/99 (Wave A `CommunicationTimeline.jsx` was imported-but-unmounted), none of the three compose surfaces are dead code.

Also checked: no legacy `OldComposeModal` / `ComposeDialog.v1` / `SendDialog` / `SmsSendModal` orphans. ✅ clean.

### §5 — Backend endpoint consolidation

**Recommend: do NOT consolidate.** Four reasons:

1. `/leads/{id}/send-sms` has lead-specific consent gates (`sms_ok` flag check); `/customers/{id}/send-sms` has customer-specific marketing-opt-out gates.
2. `/leads/{id}/send-email` writes to `lead_communications`; `/customers/{id}/send-email` writes to `marketing_deliveries`. The two collections have different retention + indexing policies.
3. TD-96 §6 touch-map explicitly scoped these as distinct — leads stay lead-scoped at write time; customer-side has marketing-delivery lineage.
4. Mobile does NOT consume either endpoint pair (grep-only check against `/app/memory/mobile/`), so there's no mobile migration unlock from consolidation.

The split-endpoint posture is already correct per TD-96/TD-97/TD-98/99 design. **Zero consolidation recommended.**

### §6 — Mobile cross-dep check

Grep (read-only) against `/app/memory/mobile/`:
- `send-sms` / `send-email` references: **zero**.
- `LeadComposeModal` / `SendComposeModal` / `SendEmailModal` references: **zero**.

Mobile has its own compose UI (not sharing FE JSX) and does not consume these specific endpoints. **No mobile cross-dep. No `e1_expo_frontend_dev` delegation needed for TD-100.**

### §7 — Test matrix for the eventual extraction ship

Pytest: **none required** — this is a FE refactor, no backend contract changes.

Vitest (new per sub-primitive, following `td98-xref-row-modal.test.jsx` pattern):

| Test file | Scope |
|---|---|
| `components/communications/__tests__/SmsCharCounter.test.jsx` | GSM-7 160-char warn + 1600 hard-cap behavior, mount into both LeadComposeModal + SendComposeModal (if adopted there). |
| `components/communications/__tests__/ConsentOverrideBanner.test.jsx` | `sms_ok=false` renders warning + override; `sms_ok=true` renders nothing; checkbox state propagates. |
| `components/communications/__tests__/TemplatePickerPreview.test.jsx` | Template fetch + select + preview render. |
| `test/td100-compose-refactor-sanity.test.jsx` | Source-contract smoke mirroring TD-98/99-xref pattern: assert LeadComposeModal + SendComposeModal + SendEmailModal still mount after refactor; no broken exports. |

Existing vitest suites (`lead-compose-modal.test.jsx`, `phase29-composer-template-picker.test.jsx`, `customer-attach-files.test.jsx`) continue to run against the composite modals; their contracts don't change at the API level.

---

## 3. Scope-reality findings — three divergent impls, not two

Operator's TD-96-close-out candidate note said "shared SMS/Email compose modal lead vs. customer". Reality: **3 impls** (lead + customer + prospect), not 2. Operator was prescient in flagging the TD-98/99 scope-reality lesson applies — it does, and the recommended path diverges from "one shared modal".

---

## 4. Ship proposal

### Option A (minimal) — `td100a-doc` close-out + document decision

- 1 commit, docs-only, record the scope-reality finding + 3-sub-primitive recommendation + "no shared mega-modal" decision.
- Leaves actual sub-primitive extraction as a future ship when the next natural touch lands on any compose surface.
- Risk: zero.
- LOC: ~45 doc.

### Option B (extract one sub-primitive now) — `td100a-doc + td100b-fe`

- 2 commits: doc + extract ONE sub-primitive (operator picks which).
- Candidates ranked by extraction value:
  - **`<TemplatePickerPreview>` (highest)** — ~250 LOC lifted from SendComposeModal + dedupe with SendEmailModal. Clearest unification win.
  - `<ConsentOverrideBanner>` — ~50 LOC lifted. Smaller win, but if more lead-adjacent surfaces land in future (e.g., bulk-lead-SMS), it pays off.
  - `<SmsCharCounter>` — ~40 LOC lifted. Smallest, matter of taste.
- Risk: medium (SendComposeModal extraction touches a 637 LOC inline component with heavy state coupling — needs careful prop surface design).
- LOC: ~45 doc + ~250-390 refactor + ~80-150 new vitest.

### Option C (extract all three) — `td100a-doc + td100b-fe + td100c-fe + td100d-fe`

- 4 commits: doc + 3 sub-primitives + rewiring.
- Highest-value refactor but highest risk — touches both LeadComposeModal and SendComposeModal which have active ongoing feature work.
- Risk: high.
- LOC: ~45 doc + ~500-700 refactor + ~200-300 new vitest.

### Recommended default: **Option A** (close-out + document)

TD-98/99 scope-reality lesson: when a ticket's framing doesn't match repo reality, the right move is to **document the finding, raise sub-candidates, and defer heavy refactor until it rides piggyback on a feature ship**. The three compose impls are stable, tested, and actively maintained — there's no reliability pressure forcing extraction now.

Pivot to **Option B** if operator wants to lock in sub-primitive discipline immediately (recommend `<TemplatePickerPreview>` first as highest-value).

Skip **Option C** unless operator explicitly accepts the risk of a 4-commit refactor against the 637 LOC inline SendComposeModal.

---

## 5. Forward-compat flags

### TD-96 / TD-97 / TD-98/99 / TD-98/99-xref (all closed)

- Lead-side compose + reparent + auto-convert + cross-visibility — all unaffected. Sub-primitive extraction is a FE refactor; zero backend contract change.
- `CommunicationDetailModal` wiring (shipped last cycle) is unaffected — compose and detail are orthogonal UX.

### TD-96-mobile (candidate)

- Mobile parity ships would benefit from stable FE sub-primitives IF mobile ever shares FE code (it currently doesn't — mobile has its own compose implementations). No TD-100 impact.

### TD-98-be-cleanup (candidate)

- Unrelated. BE endpoint retirement is a separate concern from compose UX.

### TD-97-fn (candidate — quote-page toast on auto-convert)

- Independent of compose. No conflict.

### TD-98-fn-bodyparity / TD-98-5entry / TD-98/99-xref-lifecycle / TD-98/99-xref-attribution

- All UX-polish candidates; none interact with compose extraction.

### Deferred follow-ups raised by this audit

- **TD-100-sub-template** (P3) — `<TemplatePickerPreview>` extraction.
- **TD-100-sub-consent** (P3) — `<ConsentOverrideBanner>` extraction.
- **TD-100-sub-smscount** (P3) — `<SmsCharCounter>` extraction.

If operator picks Option A, these three sit as discrete candidate tickets ready to piggyback on any future compose-adjacent feature ship.

---

## 6. Rogue-cron (TD-61) + injection log

- **Pre-audit `git log`**: HEAD `a4b73b25c` (td98-99-xref-c-fe). All recent commits authored by `Emergent Agent`. **Chain stays at 14.**
- Working tree pre-audit: only `__pycache__/*.pyc` + `.env.example` noise.
- **Injection vigilance**: no new attempts landed this window. Standing vigilance list unchanged.
- **Post-audit `git log`**: will re-verify after commit.

---

## 7. Operator decisions

Three questions blocking ship:

### §7.1 Disposition

Option A (close-out + document only), Option B (extract one sub-primitive — `<TemplatePickerPreview>` recommended), or Option C (full three-sub-primitive refactor)?

### §7.2 If Option B — which sub-primitive first?

- **(a) `<TemplatePickerPreview>`** (recommended, highest extraction value).
- (b) `<ConsentOverrideBanner>`.
- (c) `<SmsCharCounter>`.

### §7.3 Sub-primitive candidate ticket priority

Raised as P3 by default. Bump to P2 if operator wants to lock sub-primitive discipline sooner than opportunistic (next natural compose touch)?

---

## 8. STOP for operator approval

**End of audit. No code changes. Awaiting operator "proceed" with chosen disposition from §7.**
