# TD-96-mobile · Phase 1 Audit · Lead-detail action buttons (mobile parity)

**Date**: 2026-10-21
**Status**: Audit only. **No mobile code shipped.** STOP for operator decisions (§8).
**Pre-audit HEAD**: `45fd07e8b` (off-task Templates re-verify, doc-only, acknowledged, no rollback).
**Rogue-cron chain**: 14 (unchanged). **Deployment hold**: in effect (TD-88 device verification pending).
**Injection vigilance**: monitored list (`bbeck169/Pool-Landscaping.git`, "CRM from scratch" / "new Phase 1 build",
"Customers page pagination fix", "poolscape-audit.preview.emergentagent.com", "card-on-file async
send-card-add-link endpoint"). No new variants this window. No repo cloned.

---

## 0. Executive summary

- **Mobile lead detail screen**: `mobile/app/leads/[id].tsx` (412 LOC). Reached from `app/leads/index.tsx:191`
  (row press) and global search (`src/lib/globalSearchRoutes.ts:28`).
- **All 4 web primitives are ABSENT** on the mobile lead detail screen. Nothing is half-built on that screen.
- **Scope-reality check (3rd occurrence of the pattern)**: mobile has **3 lead-adjacent impls**, not 1 (§3).
  1. `app/leads/[id].tsx`: the target screen, with no SMS/Email/Quote primitives.
  2. `app/leads/index.tsx:242-330`: an **orphan** `lead-detail-sheet` + `convert-sheet`. You cannot reach it,
     because `sel` is only ever set to `null`. It contains a legacy `POST /leads/{id}/convert-to-quote` path.
  3. `app/quote/new.tsx:22-40`: **already accepts** `?recipient_type=lead&recipient_id=<id>` (Phase 2 B2). Nothing
     on mobile links to it with a lead yet. It shows the raw UUID as the recipient name (no lead-name hydration;
     web hydrates via `GET /leads/{id}`).
- **Two web-side latent gaps found, which mobile would inherit if it copied web literally**:
  - **G1 · "View all" is a dead filter.** Web navigates to `/quotes?lead=<id>`, but neither web
    `QuotesList.jsx` (reads `q,status,customer_id,has_declined,view` only) nor BE `list_quotes`
    (`routers/quotes.py:262-325`, no `lead`/`recipient_id` param) honours `lead`. The user lands on the
    **unfiltered** quotes list.
  - **G2 · The reparented marker can't show after a full conversion.** `quotes_count` (`routers/leads.py:300`)
    counts only `recipient_type="lead"`. After close-won reparent, the count drops to 0. The web lazy-fetch gate
    (`quotes_count > 0`, `LeadDetail.jsx:282`) then skips `GET /leads/{id}/quotes`, so the panel and its
    `· reparented` marker never render. Preview DB has 0 reparented docs today, so there is no live repro.
- **Backend is ready**: all 4 endpoints are live and RBAC-verified (§4). The mobile effort is **UI-only**. No BE/web
  edits are needed for parity; G1/G2 fixes would be web/BE tickets, outside this delegation.

---

## 1. Recon · current mobile lead detail (`app/leads/[id].tsx`)

| Lines | Element | testID | Notes |
|---|---|---|---|
| 92-93 | Screen role gate `allowed = admin/super_admin/manager` | — | Hand-rolled. Same set as `isAdminPlus()` in `src/components/RoleGate.tsx:25` |
| 104-113 | `load()` → `GET /leads/{id}` | — | `quotes_count` arrives in the payload but is **unused** |
| 115 | `useFocusEffect(load)` | — | Refetches on focus, so the count badge refreshes after returning from `quote/new` |
| 171-182 | Not-authorized state | `lead-detail-role-gate` | |
| 206-212 | Nav bar: back / title / refresh | `lead-detail-back` | Refresh icon has **no testID** (pre-existing) |
| 219-231 | Conversion banner → `/customer/{cid}` | `conversion-banner` | |
| 234-261 | Contact card: `PhoneLink` (tel:), `mailto:` row, `AddressLink` | `lead-phone`, `lead-email`, `lead-address` | **Native OS handoff only**. Doesn't write to `lead_communications`; not the web primitive |
| 202 | `canAct` = status not closed/archived | — | Hides the whole Actions card on closed leads |
| 263-280 | Actions card, `ActionBtn` grid (88-wide icon tiles) | `lead-actions`, `lead-action-*` | Contacted / Quoted / On Hold / Close Won / Close Lost / Archive |
| 283-303 | Add-note card | `lead-note-input`, `lead-note-submit` | |
| 306-313 | Timeline (from `lead.timeline`) | `timeline-<kind>` | No `GET /leads/{id}/communications` timeline (web has one) |
| 316-346 | Close-Lost `Modal` + `KeyboardAvoidingView` | `close-lost-modal/-reason/-cancel/-confirm` | **The in-file modal pattern a compose sheet should copy** |
| 351-360 | `ActionBtn` local component | — | Reusable for SMS/Email/Quote tiles |

**Modal patterns in use on mobile**: RN `Modal` (this file), the shared `Sheet` (`src/components/ui.tsx:116`, used
by `leads/index.tsx`), `showConfirm` (`src/components/ConfirmModal.tsx`), and full-screen route compose
(`app/customer/[id]/compose.tsx`).

**Pre-existing, out of scope (logged as candidates, not fixed)**: the `ActionBtn` row checks title-case statuses
(`lead.status === "New"`, L268/271) and PATCHes `"Contacted"/"Quoted"/"On Hold"/"Archived"`. Preview DB statuses are
all snake_case (`new, contacted, quoted, closed_won, closed_lost`). So the **Contacted/Quoted tiles never render**,
and the strings sent are legacy. See TD-96-mobile-status in §9.

---

## 2. Divergence table · 4 web primitives vs. mobile

| # | Web primitive (`frontend/src/pages/leads/LeadDetail.jsx`) | Web gate | Mobile | Evidence |
|---|---|---|---|---|
| P1 | `lead-detail-send-sms` (L368-378). Disabled when no `phone`. Opens `LeadComposeModal channel="sms"` (L786-793) | `canCompose` = admin/super_admin/owner/manager (L211) | **absent** | No `send-sms` reference anywhere in `mobile/src` or `mobile/app` except the customer `SendCreateSheet`. Only `tel:` via `PhoneLink` (L248) |
| P2 | `lead-detail-send-email` (L379-389). Disabled when no `email`. Opens `LeadComposeModal channel="email"` | same as P1 | **absent** | Only a `mailto:` handoff (L251) |
| P3 | `lead-create-quote` (L676-697) → `/quotes/new?recipient_type=lead&recipient_id=<id>`, plus `lead-create-quote-count` badge when `quotes_count > 0`. **Not** status-gated | `isAdmin` = admin/super_admin/owner (L210) | **absent** (button) / **present** (landing route) | `app/quote/new.tsx:22-40` already parses the URL contract. Gap: lead-name hydration missing (`QuoteRecipientPicker.tsx:126` falls back to `value.id`) |
| P4 | `lead-linked-quotes-panel` (L729-779). Lazy `GET /leads/{id}/quotes?limit=10` gated on `quotes_count > 0` (L280-289). Rows: title, `$total`, `· reparented`, `QuoteStatusPill` → `/quotes/{qid}`. `lead-linked-quotes-count`. `lead-linked-quotes-view-all` when `total > items.length` → `/quotes?lead=<id>` | `isAdmin` | **absent** | Mobile has no linked-quotes list. Existing analog to copy: `src/components/customers/CustomerInvoiceList.tsx` (TD-79: cap 10, `statusMeta` badge, row → `/quote/<id>`, View all) |

Supporting web piece: `LeadComposeModal.jsx` (196 LOC) has a GSM counter (warn > 160, hard cap 1600), subject ≤ 200,
consent override (`sms_ok`/`email_ok === false` → checkbox `override_consent`), and status toast
(`row.status === "sent"` → success, otherwise error with `row.error`). On error it uses `e.data.detail`, which may be
the `{code:"consent_required", message}` dict. `onSent` refreshes the web comm timeline. **Mobile has no lead comm
timeline, so `onSent` would only toast** (§9 candidate).

---

## 3. Scope-reality lesson (TD-98/99, TD-100 pattern) · mobile analog

| Impl | File | State | Disposition proposal |
|---|---|---|---|
| A · target screen | `app/leads/[id].tsx` | Mounted, active | Ship P1-P4 here |
| B · orphan list sheets | `app/leads/index.tsx:242-262` (`lead-detail-sheet`), `:263-330` (`convert-sheet`, legacy `POST /leads/{id}/convert-to-job` + `/convert-to-quote`), state at L57-62, handlers L115-169 | **Unreachable**. `setSel` is only called with `null` (L117/123/132). Row press routes to `/leads/[id]` (L191) | Leave as-is in TD-96-mobile, or reap (decision D4). Must **not** be "reused" for Create Quote: it is the legacy convert-first path, not the Phase-2 lead-recipient contract |
| C · quote landing | `app/quote/new.tsx:22-40, 104-105` | Mounted. Lead branch already wired but **no caller** passes `recipient_type=lead` | Reuse as-is for P3. Optional +~8 LOC lead-name hydration (`GET /leads/{id}`) to match web `QuoteInvoiceNew.jsx:147-160` (decision D3) |
| D · customer compose route | `app/customer/[id]/compose.tsx` (296 LOC) + `SendCreateSheet.tsx:48-53` launcher | Mounted, customer-only. Template-driven (`/marketing/templates`), sends via `POST /communications/send` with `customer_id` | **Do not reuse** for leads (§6). Mirrors the TD-100 Option-A verdict on web |

There is no legacy mobile compose modal already doing lead-side send. `TemplatePickerPreview`-style components are
customer/marketing-template scoped. Leads have no templates on web either.

---

## 4. API client plumbing check

Mobile has **no per-domain lead API module**. Every lead call goes through the generic `api` wrapper
(`src/api.ts:265`, `api.get/post/patch`, `ApiError{status, detail}` at L71-82) with inline paths. That matches
`leads/[id].tsx`, so no new `src/api/leads.ts` is required (and per house rules, don't add one for 3 one-off calls).

| Endpoint | Mobile reference today | Live check (preview, 2026-10-21) |
|---|---|---|
| `POST /leads/{lid}/send-sms` `{body, override_consent}` | **miss** | BE `routers/lead_communications.py:202`. Roles `_ALLOWED_ROLES={admin,super_admin,manager,owner}` (L73). Mike (pool_tech) → **403** |
| `POST /leads/{lid}/send-email` `{subject, body, override_consent}` | **miss** | BE `lead_communications.py:258`. Same roles. 400 `consent_required` / "no email on file" branches |
| `GET /leads/{lid}/quotes?limit=N` | **miss** | BE `routers/leads.py:317`. Roles `_INBOUND_MANAGER_ROLES={admin,super_admin,manager}` (L87). Admin: lead `1f1eefb2…` → `{items:[2], total:2, limit:10}`. Items carry `doc_type` **quote AND invoice**, `reparented`, `converted_invoice_id`. Mike → **403** |
| `GET /leads/{lid}` → `quotes_count` | **hit (fetched, field unused)** (`leads/[id].tsx:107`) | `quotes_count=2` on `1f1eefb2…` and `8721ff57…`. Mike → **403** |
| `POST /quotes` (`recipient_type=lead`) | **hit** (`app/quote/new.tsx:104-111`) | `require_admin` = admin/super_admin/owner (`backend/utils.py:226`) |

Row tap target: `/quote/<id>` handles both doc types on mobile (`app/quote/[id].tsx`, same as `CustomerInvoiceList`).

---

## 5. Role gates · web vs. backend vs. mobile helper

| Primitive | Web gate | BE gate | Mobile helper to use | Delta |
|---|---|---|---|---|
| Screen | (route-level) | `GET /leads/{id}` = admin/super_admin/manager | `allowed` L93 (= `isAdminPlus`) | — |
| P1/P2 SMS/Email | admin/super_admin/**owner**/manager | +owner | `isAdminPlus(user)` (admin/super_admin/manager) | Owner is excluded on mobile. **Moot**: owner already 403s on `GET /leads/{id}` and never reaches the buttons. Same as web in practice |
| P3/P4 Quote + panel | admin/super_admin/**owner** | `POST /quotes` +owner. `GET /leads/{id}/quotes` **excludes** owner | `isStrictAdmin(user)` (admin/super_admin) | Owner is moot for the same reason. **Manager**: web hides P3/P4, BE `POST /quotes` 403s. Mobile must hide them too |

So, inside the already-authorised screen: **manager sees P1+P2 only; admin/super_admin see P1-P4.** Gates come from
`src/components/RoleGate.tsx` helpers (no new string lists). Preview has 6 `manager` users
(`manager@aquaterra.com`), but no manager password is in the test-creds set, so manager checks will be **unit-test
only** unless the operator supplies creds.

---

## 6. Compose modal · reuse vs. new (LOC estimates)

| Path | What | Est. LOC | Pros | Cons |
|---|---|---|---|---|
| **R1 (recommended)** · new `src/components/leads/LeadComposeSheet.tsx` | 1:1 RN port of `LeadComposeModal.jsx`: RN `Modal` + `KeyboardAvoidingView` (copy the L316-346 pattern), GSM counter 160/1600, subject ≤ 200, consent-override toggle, toast mapping, `ApiError.detail` string/dict handling | ~170 + ~40 mount/wiring in `[id].tsx` | Exact BE contract, small, isolated, testable. Matches the web 3-impl separation (TD-100 Option A) | New file. Some styling overlap with customer compose |
| R2 · generalise `app/customer/[id]/compose.tsx` with a `recipient=lead` branch | Add a lead mode: skip templates, swap the endpoint | ~120 diff into a 296-LOC route | One compose surface | Template/preview/`/communications/send` flow is customer-only. Branch-heavy. Reverses the TD-100 verdict. Full-screen route vs. web modal |
| R3 · split into two components (`LeadSmsSheet` + `LeadEmailSheet`) | Same as R1, split per channel | ~2×110 | Simpler per-file | Duplicated consent/toast logic. Web is a single component |
| R4 · native handoff only (`sms:`/`mailto:`) | Already present | 0 | Zero work | **Not parity**: no `lead_communications` row, no consent enforcement, no provider status |

Placement proposal (P1/P2): a "Message" row of two `ActionBtn` tiles **outside** the `canAct` gate. Web shows them
regardless of status. Disabled state + opacity when phone/email is missing (web `disabled` + title). Testids are
`lead-detail-send-sms` / `lead-detail-send-email`, identical to web.
P3: `ActionBtn`-width primary button with a count pill, also **outside** `canAct` (web: not status-gated).
Testids are `lead-create-quote` / `lead-create-quote-count`.
P4: new `src/components/leads/LeadLinkedQuotesPanel.tsx` (~110 LOC), modelled on `CustomerInvoiceList.tsx`, with
`statusMeta` (`src/theme.ts:48`) for the pill. Testids are `lead-linked-quotes-panel`, `-count`,
`lead-linked-quote-row-<id>`, `-view-all`.

Total estimated Phase-2 diff (R1 + P3 + P4, no D3/D4 extras): **~330-380 LOC** across 3 files plus tests.

---

## 7. Test matrix proposal (jest + @testing-library/react-native, existing `__tests__/` conventions)

Mocks follow `td91-view-as-customer.test.tsx`: `jest.mock("@/src/api")`, `ToastProvider`, `@/src/auth`
`useAuth`. Also expo-router `useLocalSearchParams` / `useRouter` / `useFocusEffect`.

**File A · `__tests__/td96-mobile-lead-actions.test.tsx` (screen-level, ~12 cases)**

| # | Role | Lead fixture | Assert |
|---|---|---|---|
| A1 | manager | phone + email | `lead-detail-send-sms` + `-send-email` render. `lead-create-quote` + `lead-linked-quotes-panel` absent |
| A2 | admin | phone + email, `quotes_count:2` | all 4 render. `lead-create-quote-count` text `2` |
| A3 | super_admin | same | same as A2 |
| A4 | admin | `quotes_count:0` | Create Quote renders, **no** count badge, panel absent, `/leads/{id}/quotes` **not** called (if D2 = mirror) |
| A5 | admin | no phone | SMS button disabled (press → no modal). Email enabled |
| A6 | admin | no email | Email disabled |
| A7 | admin | `status:closed_won` | P1-P3 still render (not `canAct`-gated) |
| A8 | admin | — | press `lead-create-quote` → `router.push("/quote/new?recipient_type=lead&recipient_id=<id>")` |
| A9 | pool_tech / landscape_tech | — | `lead-detail-role-gate`. None of the 4 testids render (regression lock) |
| A10 | admin | quotes fetch rejects | panel absent, no crash (fail-open like web) |
| A11 | admin | `total:12, items:10` | `-view-all` renders. Press → target per D2 |
| A12 | admin | item `reparented:true` | row subtitle contains `· reparented` |

**File B · `__tests__/td96-mobile-lead-compose.test.tsx` (component-level, ~9 cases)**

| # | Case | Assert |
|---|---|---|
| B1 | SMS empty body | send disabled |
| B2 | SMS 161 chars | counter shows multi-segment warn |
| B3 | SMS 1601 chars | over-cap text, send disabled |
| B4 | SMS send OK | `api.post("/leads/L/send-sms", {body, override_consent:false})`, success toast, `onClose` |
| B5 | Email requires subject + body | disabled until both are filled. Payload `{subject, body, override_consent}` |
| B6 | `sms_ok:false` | consent warning renders. Send disabled until override is toggled. Payload `override_consent:true` |
| B7 | `row.status:"failed"` | error toast with `row.error` |
| B8 | `ApiError` with dict detail `{code:"consent_required", message}` | toast shows `message` |
| B9 | cancel / close | no API call |

**Regression guards**: re-run the adjacent suites `QuoteInvoiceLeadBadge.test.tsx` plus any `leads-*` suites. Full jest
must stay at the **42 failing-suite baseline**. tsc must stay at the **651 baseline** (0 errors today in
`leads/[id].tsx` and `quote/new.tsx`). Live smoke: admin on lead `1f1eefb2…` (2 linked: 1 quote + 1 invoice).
Mike → screen role gate.

---

## 8. Operator decisions (STOP)

| ID | Decision | Options | Recommendation |
|---|---|---|---|
| **D1** | Compose modal strategy | R1 new `LeadComposeSheet` · R2 generalise customer compose route · R3 split per channel · R4 native handoff only | **R1**. Exact BE contract, TD-100 Option-A precedent, ~170 LOC |
| **D2** | Linked-quotes panel inclusion + web-gap handling (G1 dead "View all", G2 reparented hidden after conversion) | (a) **Faithful mirror**: gate on `quotes_count > 0`, View all → unfiltered `/(app)/quotes` (inherits G1+G2). (b) **Mirror + mitigate**: always lazy-fetch for admin (fixes G2 on mobile, +1 GET per open). Replace "View all" with a non-link "+N more" hint, because the list can't be filtered by lead (avoids G1). (c) Defer P4 entirely to a later cycle | **(b)**, and log G1/G2 as web/BE TD candidates. (a) if strict web-identical behaviour is preferred |
| **D3** | Scope extras in adjacent files | (a) P1-P4 only in `leads/[id].tsx` + 2 new components. (b) + lead-name hydration in `app/quote/new.tsx` (~8 LOC, matches web `QuoteInvoiceNew.jsx:147`) | **(b)**. Otherwise the P3 landing shows a raw UUID as the recipient |
| **D4** | Test depth + orphan handling + TD-98-be-cleanup intersection | (a) Files A+B (~21 cases), leave orphan sheets. (b) (a) + reap orphan `lead-detail-sheet`/`convert-sheet` in `leads/index.tsx` (~-90 LOC, separate atomic commit). (c) A only (screen-level, ~12) | **(a)**. Reap as its own later ticket. **TD-98-be-cleanup does not intersect**: it targets the customer `/customers/{cid}/communication-timeline` consumer (`src/components/customers/CommunicationTimeline.tsx`). TD-96-mobile touches no customer timeline or lead comm-timeline code |

Proposed ship sequence after approval (atomic, `--only`, `td96-mobile-*` prefix):
`td96a-mobile-compose` (LeadComposeSheet + File B) → `td96b-mobile-actions` (P1-P3 wiring + D3 + File A part) →
`td96c-mobile-linked-quotes` (P4 panel + rest of File A) → `td96d-mobile-doc` (commit_log, iteration memo, TECH_DEBT
reconcile).

---

## 9. TD candidates surfaced (to log at reconcile commit; not logged in this docs-only ship)

- **TD-96-viewall (web+BE, P3)**: `/quotes?lead=<id>` is a dead filter (G1). Needs a BE `list_quotes` lead/recipient
  filter plus `QuotesList.jsx` param read. Mobile would then wire View all → filtered list.
- **TD-96-reparent-count (BE, P3)**: `quotes_count` excludes `converted_from_lead_id` docs (G2). Align it with the
  `/leads/{id}/quotes` `$or` filter so the web panel shows reparented quotes after conversion.
- **TD-96-mobile-status (mobile, P3)**: `leads/[id].tsx` status tiles use title-case statuses (L268-277). Contacted
  and Quoted never render against snake_case data.
- **TD-96-mobile-timeline (mobile, P3)**: no lead communication timeline (`GET /leads/{id}/communications`) on
  mobile, so compose `onSent` can only toast.
- **TD-96-mobile-orphan (mobile, P3)**: reap the unreachable `lead-detail-sheet` / `convert-sheet` in
  `app/leads/index.tsx` (if D4 ≠ b).

---

## 10. Ambiguities surfaced

- The delegation says "mirror web's gating". Web includes `owner`, but BE `GET /leads/{id}` excludes owner, so owner
  can't open the screen on either platform. Mobile uses the existing `isAdminPlus`/`isStrictAdmin` helpers, with no
  owner special-case. Flag if owner support on lead detail is wanted; that is a BE change.
- No manager password is in the provided creds, so manager-role verification will be jest-only unless creds are supplied.
- Commit `45fd07e8b` (off-task Templates doc) stays as acknowledged. This ship touches no Templates files.
