# FEATURE — Bulk Portal Invite from customers top-menu

**Date**: 2026-02-10 (wall clock 2026-09-10)
**Author**: e1_dev
**Scope**: Thin admin affordance — top-toolbar "Portal Invite" button on the customers list page that reuses the pre-existing Phase H1 confirm modal + bulk endpoint. No new endpoint, no new confirm shell, no bulk-select scaffolding (all already present).

---

## TL;DR

Everything the spec asked for was already scaffolded EXCEPT the top-toolbar button:

| Spec item | Reality before this ship | Action |
|---|---|---|
| Bulk-select checkboxes on rows + select-all header | ALREADY exists (`selected` Set state @ L247, row + header checkboxes @ L2039-2091) | REUSED |
| Confirm modal with preview + Send CTA + summary | ALREADY exists as the Phase H1 modal (test-id `h1-modal-portal-invite`) — mature superset of Chase modal (adds already-activated pre-warning, filter-state pill, failure-details side-panel) | REUSED verbatim |
| Bulk endpoint | ALREADY exists at `POST /admin/customers/portal-invite/bulk` | REUSED |
| Refetch onboarding tile after send | Missing plumbing | ADDED — `externalRefetchToken` prop on the tile |
| **Top-toolbar button** (spec test-id `customers-toolbar-portal-invite-btn`) | Missing | **NEW — this ship** |

## Modal reuse decision (STOP-and-flag context)

The spec offered three paths:
1. Reuse `ChaseStalledInvitesModal` if the shape fits.
2. Extract a common component if it doesn't.
3. (Implicit) Reuse the existing H1 modal.

**Chose (3): reuse the existing H1 modal in place.**

Rationale:
- H1 modal is a mature **superset** of ChaseStalledInvitesModal — has all of Chase's features (confirm→summary two-phase, preview list, spec response-shape parsing) PLUS three things Chase lacks: filter-state pill, already-activated pre-warning, and failure-details side-panel.
- Extracting a common shell would touch BOTH callers (Chase tile + CustomersList) plus require the extracted shell to superset the H1 features, resulting in a diff that violates the "small, reviewable" constraint.
- Swapping CustomersList to use Chase would DOWNGRADE the UX (lose the already-activated warning users rely on).

Trade-off flagged in memo: two similarly-shaped modals now coexist (Chase for the tile CTA, H1 for the list bulk actions). A future consolidation ticket could extract a shared shell once the two flows have stabilized.

## Files touched

| File | Delta |
|---|---|
| `frontend/src/pages/customers/CustomersList.jsx` | +1 icon import (`Mail`) + ~30 LOC button JSX in the PageHeader `right` prop + `externalRefetchToken={h1Result}` prop pass-through on the tile |
| `frontend/src/components/customers/PortalOnboardingHealthTile.jsx` | Added `externalRefetchToken` prop param + wired into the `useEffect` dep array. ~4 LOC delta |
| `frontend/src/test/bulk-portal-invite-from-customers-list.test.jsx` | NEW — 5 source-body contract tests mirroring the Phase H1 test pattern |

Zero backend changes. Zero DB / migration / schema impact.

## Behavior

- Rendered inside `isAdmin ? (...) : null` (admin + super_admin ONLY — manager and tech do NOT see it). Matches the underlying `POST /admin/customers/portal-invite/bulk` RBAC gate.
- `selected.size === 0` → button disabled, tooltip: `Select one or more customers to invite`.
- `selected.size >= 1` → button enabled, label: `Portal Invite (N)`, tooltip: `Send portal invite to N selected customer(s)`, click → `setH1ConfirmOpen(true)`.
- On modal confirm → existing `doBulkPortalInvite()` handler fires, posts to bulk endpoint, sets `h1Result` state.
- `h1Result` identity change flows into `PortalOnboardingHealthTile` via `externalRefetchToken` → tile useEffect fires → cohort counts refetch (60s server cache preserved).

## Tests

| Suite | Cases | Pass |
|---|---|---|
| `bulk-portal-invite-from-customers-list.test.jsx` (NEW) | Emits spec test-id · admin gate · onClick routes to `setH1ConfirmOpen(true)` · disabled-when-no-selection + spec tooltip · tile receives `externalRefetchToken={h1Result}` | **5/5** |
| `customers-bulk-portal-invite.test.jsx` (regression) | Existing 11 Phase H1 contract tests | **11/11** |
| `portal-onboarding-health-tile.test.jsx` (regression) | 4 tile tests | **4/4** |
| `chase-stalled-invites.test.jsx` (regression) | 4 Chase-CTA tests | **4/4** |
| **Total** | | **24/24** |

Runtime: 2.10s.

## Screenshots

- `/app/screenshots/top-menu-portal-invite-disabled.png` — top-menu button in disabled state (no selection) + tooltip.
- `/app/screenshots/top-menu-portal-invite-enabled.png` — enabled state after 3 rows ticked (label reads `Portal Invite (3)`, tooltip `Send portal invite to 3 selected customers`).
- `/app/screenshots/top-menu-portal-invite-modal.png` — H1 modal opened from the top-menu click: "Send portal invite to 3 customers?" + filter-state pill + `1 of your selected customers already have portal access — they'll be skipped.` warning + Cancel/Send 3 invites CTAs.

## Rollback

Delete the button JSX block in the PageHeader `right` prop (~30 LOC), revert the `externalRefetchToken` prop plumbing on both CustomersList + PortalOnboardingHealthTile (~5 LOC), remove the `Mail` icon import, delete the new test file. No prod, no DB, no dependency changes.
