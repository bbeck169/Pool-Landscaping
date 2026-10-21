# TD-96-g1-mobile — Phase 1 recon + Phase 2 proposal

Status: **STOP — awaiting operator decisions D1–D5.**
Recon date: 2026-10-21, at HEAD after `e6654ca0d` (BE) + `00888d0af` (FE) + `d9f4912b2` (lessons-doc-4).
Mobile-only. Read-only recon: no mobile UI code written.

## 1. Step 1 — memory grep (`TD-96-g1-mobile|LeadLinkedQuotesPanel|lead-linked-quotes`)

| Hit | Content |
|---|---|
| `TECH_DEBT.md:994` | TD-96-g1-mobile candidate (P3). Estimated ~30–50 LOC + 1 spec + TODO cleanup. "Mobile Lead badge rendering is optional parity." |
| `TECH_DEBT.md:965-982` | TD-96-mobile b2 ship record: the panel is admin-gated and its follow-up is TD-96-g1-mobile. |
| `mobile/iteration_160.md:11-12` | Panel mapping: "View all → `/quotes?lead=`" was replaced by the non-link `lead-linked-quotes-more`. |
| `mobile/td96_mobile_audit.md:75,146-163` | Original P4 spec plus the role matrix: the panel is absent for managers (A1). |
| `mobile/commit_log.md:2105` | Iteration 160: "+N more" instead of a dead View all. |

No separate TD-96-g1-mobile audit doc exists, so this file is the first one.

## 2. Step 2 — file-inventory recon

| # | Question | Finding |
|---|---|---|
| R1 | Is "+N more" still what ships? | **Yes.** `src/components/leads/LeadLinkedQuotesPanel.tsx` is untouched since `1e722bd10`. L84-86 render the non-link `<Text testID="lead-linked-quotes-more">+N more</Text>` when `total > items.length` (limit 10). No drift deep-link exists. |
| R2 | Mobile Quotes list screen | `app/(app)/quotes.tsx` (414 LOC, tab screen). **It reads no route params at all** (no `useLocalSearchParams`). **Scope delta:** param consumption is new work. |
| R3 | List fetch | `load(v, dtf)`: admin → `GET /quotes?view=<v>` (default **`open`**); non-admin → `GET /quotes[?doc_type=]`. Response is an array. |
| R4 | Offline cache | `writeCache/readCache("quotes:<view or doc_type>")`. A lead-filtered fetch **must not** write to or read from that key, or the unfiltered offline cache gets poisoned. |
| R5 | Routing convention | Object form, `router.push({ pathname: "/(app)/customers", params })` (TD-84 b1). No string-query pushes into `(app)` tabs. A clearable chip uses `router.setParams({ x: undefined })` (customers.tsx precedent). |
| R6 | Backend contract | `list_quotes` now takes `lead_id` (`e6654ca0d`): `$or` on (recipient_type=lead AND recipient_id) or `converted_from_lead_id`, combined with `view`, `status` and `customer_id`. |
| R7 | Web consumer (`00888d0af`) | `?lead=` → `qs.set("lead_id")`. Badge `quotes-filter-lead-badge` shows the name from `GET /leads/{lid}`, with a fallback of `Lead <id[:8]>`. Clear button: `quotes-filter-lead-clear`. Web **keeps `view`** (default `open`). |
| R8 | Web View all | `LeadDetail.jsx:776-784`: shown when `total > items.length`; label "View all {total} →"; navigates to `/quotes?lead=${lead.id}` with **no `view`**. |
| R9 | Tests touching the list | `QuoteDeclineReopen.test.tsx` and `quotes-bulk-actions.test.tsx`. Both must stay green. |
| R10 | Who sees the panel | Admin and super_admin only (caller gate in `app/leads/[id].tsx`). Managers never reach the link. |

### Live data (preview tenant, admin)

110 quotes in total. Only 3 leads have linked quotes, each with 1–2.

| Lead | Panel `total` | `/quotes?lead_id=…&view=open` | `view=all` | `view=accepted` |
|---|---|---|---|---|
| `8721ff57` | 2 | **0** | 1 | 1 |
| `3a0933b2` | 1 | 1 | 1 | 0 |
| `1f1eefb2` | 2 | **0** | 1 | 1 |

Two findings:
- **F1 · the "open" default hides linked quotes.** On 2 of the 3 leads, web's View all URL (no `view`, so `open`) lands on an **empty** list, because the linked quote was converted (accepted).
- **F2 · count mismatch.** The panel endpoint `/leads/{id}/quotes` includes **invoices**. For `8721ff57` that is the converted invoice `eb541e58` plus quote `cdc8cd49`. The lifecycle `view` scopes to quotes, and even `&doc_type=invoice` is overridden by `view`. So "View all 2 →" can show at most 1 row, on web too.

No lead has more than 10 linked quotes, so View all never renders on live data (it needs `total > 10`). The live check needs a fixture (see D5).

## 3. Divergence table (web as of `00888d0af` → proposed mobile)

| Surface | Web | Mobile today | Proposed mobile |
|---|---|---|---|
| Panel affordance | `View all {total} →` button when total > shown | Non-link `+N more` text | `Pressable` "View all {total} →", `testID="lead-linked-quotes-view-all"`, same condition |
| Link target | `/quotes?lead=<id>` (`view` defaults to open) | — | `{pathname:"/(app)/quotes", params:{lead:id, view:"all"}}` (**D1**) |
| List param | `?lead` → `lead_id` | none | `lead` route param → `&lead_id=` on both role branches (**D4**) |
| View handling | URL `view` kept | local state, default `open` | `view` route param seeds the state once when present (**D1**) |
| Lead badge | name via `GET /leads/{lid}`, fallback `Lead <id8>` | — | **D2** |
| Clear | removes `?lead`, refetches | — | `testID="quotes-filter-lead-clear"` → `router.setParams({lead: undefined})` |
| Offline cache | n/a | `quotes:<view>` | skip cache read/write while `lead` is set (R4) |
| Count semantics | panel counts invoices; list doesn't | same panel | unchanged (**D3**) |
| TD-96-g2 TODO (fetch gate) | gates on `linked_quotes_count` | always fetch (TODO) | **out of scope** (scope guard); see D5 note |

## 4. Proposed ship — 1 commit `td96-g1-mobile-fe` (~70–90 LOC + ~8 tests)

1. **`LeadLinkedQuotesPanel.tsx` (~15 LOC):**
   - Replace L84-86 with the View all `Pressable` (44pt min height) and the D1 target.
   - Rewrite the header comment's "No View all link" deviation and drop the TD-96-g1 part of the TODO.
2. **`app/(app)/quotes.tsx` (~55–70 LOC):**
   - `useLocalSearchParams<{lead?: string; view?: string}>()`.
   - `leadFilter` is appended as `lead_id` on both branches.
   - The `view` param seeds `setView` once (validated against `VIEW_FILTERS`).
   - Cache skipped while `leadFilter` is set.
   - `useFocusEffect` deps include `leadFilter`.
   - Badge row (D2) with Clear.
3. **New test `__tests__/td96-g1-mobile-view-all.test.tsx` (~8 cases):**
   - View all hidden when total ≤ shown; shown with "View all N →" when total > shown; push target exact.
   - List sends `lead_id` (admin `view=all` combined; non-admin `doc_type` combined); no `lead_id` without the param.
   - Badge shows the fetched name; falls back to `Lead <id8>` on a 404.
   - Clear calls `setParams({lead: undefined})`.
   - Cache not written while filtered.
   - Re-run `QuoteDeclineReopen` and `quotes-bulk-actions`.
4. **Doc:** TECH_DEBT close-out plus commit_log, either inline in the same commit or as a 2nd docs commit (operator's preference; default is a 2nd commit, `td96-g1-mobile-doc`).

Estimate: ~70–90 LOC versus the candidate's 30–50. The difference is R2 (the list reads no params today), R4 (the cache guard) and the badge.

## 5. Operator decisions

| # | Decision | Options | Recommendation |
|---|---|---|---|
| **D1** | View on the deep-link (F1) | (a) mirror web exactly: no `view`, so `open`, and can land empty; (b) mobile passes `view:"all"`, and log **TD-96-g1-web-view** (P3 web) so web's View all appends `&view=all` | **(b)**. Mirroring a link that lands empty is parity with a bug. The `view` chips stay usable to narrow. |
| **D2** | Lead name display | (a) web parity: `GET /leads/{lid}` badge plus `Lead <id8>` fallback (~12 LOC); (b) pass `lead_name` as a route param from the panel (no fetch, but stale and deep-link-fragile); (c) generic "Filtered by lead" chip, no name | **(a)**. Same contract as web, cheap, and survives deep-links. |
| **D3** | Panel/list count mismatch (F2) | (a) keep "View all {total} →" (web parity) and log **TD-96-g1-invoices** (P3 BE/web: should `lead_id` + `view` include converted invoices, or should the panel count exclude them?); (b) label "View all →" with no count on mobile | **(a)**. Keep the label identical to web and fix the semantics once, server-side. |
| **D4** | Role branches | (a) honour `lead` on both admin and non-admin fetches; (b) admin only (the only role that reaches the link) | **(a)**. A one-line difference, and it keeps a shared deep-link from silently ignoring the filter for managers. |
| **D5** | Live-check fixture (no lead has more than 10 linked quotes) | (a) a throwaway lead plus 11 draft quotes via `POST /quotes` (recipient_type=lead), hard/soft-deleted afterwards; (b) jest only, plus an Expo-web check of the list with a `lead` param via the panel on a ≤10 lead (View all hidden, which proves the gate) | **(a)**. Same throwaway discipline as TD-81-adj and TD-84. Drafts send nothing. |

Explicitly **not** in this ship (scope guard):
- **TD-96-g2 fetch gate.** Leads now return `linked_quotes_count`, so the panel's "always fetch" TODO could be resolved. Suggest a separate candidate, `TD-96-g2-mobile` (P3, ~5 LOC).
- Showing the total anywhere beyond the View all label.
- Web's existing `converted` vs `accepted` view-label difference.

## 6. Risks

- **Tab param persistence.** `lead` stays on the Quotes tab until cleared; this is the same behaviour as TD-84 b1's customers chip. The Clear chip is the exit.
- **TD-61.** The ship is about 3 files, written, tested and committed in one short cycle (under 5 minutes) per the strike #17 guidance. Precheck drift rows are compared against the expected count of 3–4.
