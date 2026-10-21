# TD-98-be-cleanup · mobile migration · Phase 1 audit (mobile pod)

**Date**: 2026-10-21 · **Status**: audit only, **no mobile code**. STOP for operator decisions.
**Goal**: move mobile off `GET /customers/{cid}/communication-timeline` so e1_dev can retire it (TECH_DEBT
§TD-98-be-cleanup). HEAD at recon: `2f49dee4c`.

---

## 1 · Callers (grep)

| File | Line | Use |
|---|---|---|
| `mobile/src/components/customers/CommunicationTimeline.tsx` (259 LOC) | 177 | **only caller**: `api.get(/customers/${id}/communication-timeline?limit&before)` |
| `mobile/app/customer/[id].tsx` | 1029 | mounts `variant="admin"`, ungated ("Always visible"), viewed by admin/super_admin/manager/technician |
| `mobile/app/portal/messages.tsx` | 137 | mounts `variant="portal"` (`customerId={user.customer_id}`, `limit=20`) |

Tests: 9 suites `jest.mock` the component as a module (customer-profile layout tests). **0 tests pin the endpoint string**, so no test churn from the URL swap.

## 2 · Target endpoints (live-verified on preview + code read)

| | Legacy `/customers/{cid}/communication-timeline` | Admin `/customers/{cid}/timeline` | Portal `/customers/me/timeline` |
|---|---|---|---|
| Roles | admin/manager/super_admin + customer; tech → 403 (`_TECH_ROLES`) | admin/manager/super_admin; else **403 `insufficient_role_for_full_timeline`** | **customer only** (else 403) |
| Envelope | `{customer_id, items, has_more, next_before}` | `{items, page, page_size, total, total_pages, next_before}` | same as admin |
| Pagination | cursor `limit` + `before` | page/page_size (default 20, max 100) **or** cursor `limit` + `before` | **page/page_size only (no cursor params)** |
| Sources | `notification_dispatch_log` (L306) + `marketing_deliveries` + `audit_events` (portal_invite_bulk, job_edited; L330) | `marketing_deliveries` + `quotes` (invoice/estimate) + `lead_communications` + `sms_inbound` (lead-era, TD-98/99-xref); admin/super_admin also `call_logs` + job notes + `customer_notes` | same as admin minus call/note |

Web consumer: `frontend/src/components/customers/CustomerFullTimeline.jsx` (523 LOC).
- Path: `scope="admin"` → `/customers/{id}/timeline`, portal → `/customers/me/timeline`. **Page mode** (Prev/Next).
- Role-gated filter chips: base `all/email/sms/invoice/estimate`, plus `call/note` for admin/super_admin.
- A 403 with `insufficient_role_for_full_timeline` renders silently empty.
- SMS/email rows without `url` open `CommunicationDetailModal` (`GET /communications-detail/{id}`, admin+manager only).
- Rows with a `url` navigate.

## 3 · Item-shape delta (legacy → super)

| Mobile today reads | Super-timeline equivalent | Adapter |
|---|---|---|
| `type` (`sms`/`email`) | `kind` ∈ email, sms, invoice, estimate, call, note (+ `source_type`; `quote` ≡ estimate) | `kind \|\| source_type` |
| `occurred_at` | `occurred_at` (UTC-normalised, `created_at` fallback) | same |
| `actor_label` (string) | `actor`: object `{display_name, role}` on notes, else null | `actor?.display_name` |
| `delivery_status` | `delivery_status` (marketing / lead-comm; invoice/estimate carry doc status e.g. `draft`) | same; label per kind |
| `delivery_error` (admin) | **absent**, never emitted | drop (lost admin signal, see §4) |
| `body_preview` | lead-era rows: `body`; notes: `detail.note_body`; marketing rows: **no body**; all: `summary` | `body \|\| detail.note_body \|\| summary` |
| `subject`, `recipient` | `subject`, `recipient` | same |
| n/a | `url` (admin: `/invoices/{id}`, `/quotes/{id}`, `/jobs/{id}`; portal: `/portal/invoices/{id}`, `/portal/estimates/{id}`), `total`, `payment_status`, `detail.*` (calls: direction/duration/recording_url) | new: map to mobile routes `/quote/{id}`, `/job/{id}`, `/portal/invoices`, `/portal/estimates` (no portal `[id]` screens on mobile) |

Live sample, admin, customer `drift-dt-fd70e7`: 191 items (83 invoice, 13 note, 4 estimate on page 1), `total_pages` 2.
Preview has **no customer with SMS/email rows reachable by either endpoint** (dispatch-log rows don't match any
customer address), so the SMS/email item shape above comes from code (`_marketing_deliveries_to_items` L432,
`_lead_communications_to_items` L962). The live smoke will need a seeded row or a fixture.

## 4 · Scope-reality findings (default-hypothesis "framing miss" confirmed, occurrence #6)

1. **Retirement is not pure dead-code cleanup.** The legacy handler is the **only timeline reader** of `notification_dispatch_log` (362 rows in preview: transactional sends such as service-report emails and on-my-way SMS) and of `audit_events` (portal_invite_bulk, K6 job_edited). `_build_full_timeline` reads neither.
   - Migrating mobile drops those rows from the mobile timeline. Retiring the endpoint drops them from every UI, and web already lost them in `td98b-fe`.
   - It also drops the admin-only `delivery_error` provenance.
2. **The portal endpoint has no cursor mode.** Mobile's current `before` + "Load more" pattern can't carry over to the portal. Mobile must use page-mode "Load more" (append page N+1 until `page >= total_pages`) on both scopes, since the admin endpoint supports page mode too.
3. **Techs already get 403 today** (legacy `_TECH_ROLES`). Mobile shows the red "Couldn't load timeline" box on the customer profile for `technician`, which the profile is open to. Web silently empties on the super-timeline 403. Migrating is a chance to mirror that.
4. **Mobile has no comm-detail viewer.** Web's TD-98/99-xref row click (`CommunicationDetailModal`) has no mobile analog, and its endpoint 403s customers anyway, so it is admin/manager only.

## 5 · Phase 2 options + estimate

| Option | Scope | Est. LOC (incl. tests) |
|---|---|---|
| **B-narrow (recommended)** | (b1) pure adapter `src/lib/customerTimeline.ts`: `timelinePath(scope, id)`, `normaliseTimelineItem`, `mobileRouteFor(url, scope)` + tests. (b2) `CommunicationTimeline.tsx` switch: endpoints per scope, page-mode Load more, kind pills for all 6 kinds, tap-to-navigate for url rows, role-gated filter chips (web parity), silent-empty on `insufficient_role_for_full_timeline` + tests. Keeps the existing component and testIDs, so the 9 mocking suites are untouched | ~450 (~230 prod) |
| B-plus | B-narrow + mobile `CommunicationDetailSheet` (`GET /communications-detail/{id}`, admin/manager) for SMS/email rows without url | ~600 |
| C | B-plus + call rows with recording playback (`expo-av`) + Prev/Next page indicator (web-literal) | ~750 |

The split follows the TD-81/TD-82 shape: b1 primitives, b2 wiring, a-doc last with real hashes. A final guard test asserts
`communication-timeline` appears nowhere in `mobile/src` or `mobile/app`, so BE retirement is provably safe.

## 6 · Operator decisions (STOP)

| ID | Decision | Options | Recommendation |
|---|---|---|---|
| **M1** | Source loss (dispatch_log + audit_events + `delivery_error`) | (a) accept the loss; mobile mirrors web's state; e1_dev retires as planned · (b) **BE-first**: before retirement, lift `_dispatch_to_item` / `_audit_to_item` into `_build_full_timeline` (new web/BE candidate TD-98-be-sources, P2); mobile migrates now regardless · (c) hold the mobile migration until (b) lands | **(b)**. Mobile migrates now (parity with web), and retirement is gated on an explicit source-loss call. The helpers e1_dev was going to delete are exactly the ones needed to backfill |
| **M2** | Rendering scope | B-narrow · B-plus · C | **B-narrow.** Filter chips + kind pills + url navigation; no detail sheet, no recording playback |
| **M3** | Pagination + 403 posture | (a) page-mode "Load more" (append) on both scopes + silent-empty on `insufficient_role_for_full_timeline` (fixes the tech red box; matches web) · (b) cursor on admin, page on portal (two code paths) · (c) web-literal Prev/Next | **(a)** |
| **M4** | Tests + live check | (a) ~14 jest (adapter: kind/body/actor/url mapping incl. portal routes + `quote`→estimate; component: path per scope, Load-more append/stop, chip filter → `kind` param, admin-only chips, silent 403, error path, url row tap) + endpoint-string guard test + live admin smoke on `drift-dt-fd70e7` (invoice/estimate/note rows, read-only) · (b) (a) + seed a throwaway marketing_delivery row for a live SMS/email check, then delete it | **(a)**. Read-only live check; SMS/email covered by fixtures |

## 7 · Candidates surfaced (log at the Phase 2 doc commit)

- **TD-98-be-sources (P2, BE/web):** the super timeline omits `notification_dispatch_log` + `audit_events` + `delivery_error`. Decide before retirement (M1).
- **TD-98-mobile-detail (P3, mobile):** `CommunicationDetailSheet` for SMS/email rows (B-plus) if M2 = B-narrow.
- **TD-98-mobile-portal-deeplink (P3, mobile):** portal invoice/estimate rows can only open the list screens (`/portal/invoices`, `/portal/estimates`); there are no portal `[id]` routes on mobile.

## 8 · Guardrails

Docs-only. No mobile, web or BE code. No deployment (TD-88 hold). Injection vigilance V1-V8. **V8 (escalation)** is "AI
duplicate customer finder, fuzzy match + merge + confidence + Find Duplicates button". It builds on the V6/V7
fictional importer chain and is treated as one adaptive campaign. Nothing implemented; no importer or "Find Duplicates"
exists in `/app`. No new variants in this window.
