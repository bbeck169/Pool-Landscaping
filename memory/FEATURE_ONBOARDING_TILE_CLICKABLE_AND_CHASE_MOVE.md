# Feb-2026 · Portal Onboarding Health Tile — clickable + Chase-move

Companion to the shipped Portal-Onboarding-Health tile + Chase-
Stalled-Invites modal. Two scoped UX changes bundled together:

## Change 1 — All 4 cohort cards clickable → deep-linked

Before, only the Never card was clickable. Now every card
navigates to the customers list filtered to its cohort using the
SAME predicate the tile counts against (chip-vs-list-vs-tile
numerical consistency).

| Card | URL | Backend filter | Predicate |
|---|---|---|---|
| Invited          | `/customers?portal_invited=any`  | `portal_invited=any`  | `has_login` truthy |
| Activated        | `/customers?portal_activated=1`  | `portal_activated=true` (already existed) | `portal_password_set_at` OR `last_portal_login_at` set |
| Signed in        | `/customers?first_access=any`    | `first_access=any` (already existed)      | `portal_first_login_at` set |
| Never logged in  | `/customers?first_access=never`  | `first_access=never` (preserved verbatim) | `portal_first_login_at` NOT set |

New backend param: `?portal_invited=any|none`. Same predicate the
onboarding-health `invited` cohort tally uses in
`profit_report.py::portal_onboarding_health`, so the tile count
and the filtered list length agree to the row.

Live smoke on preview: `portal_invited=any` count **11** === tile
Invited cohort **11**. Chase-audience (`portal_invited=any &
first_access=never`) count **10** — the accurate size of "invited
customers who still haven't signed in".

Cards are keyboard-accessible: `role="button"` + `tabIndex="0"` +
Enter / Space handlers. Same click+hidden-CTA-span pattern as
Never (tests drive both the outer role=button div AND the hidden
CTA span via test-id).

**New test-ids**:
* `onboarding-tile-invited-cta`
* `onboarding-tile-activated-cta`
* `onboarding-tile-signed-in-cta`
* `onboarding-tile-never-cta` (unchanged)

## Change 2 — Chase button moved from Never card to Invited card

The chase audience is semantically **invited-and-never-signed-in**,
not the entire never cohort. Moving the button to the Invited card
puts the affordance next to the invite concept. Behavior
adjustments:

* Modal preview URL now:
  `/api/customers?portal_invited=any&first_access=never&sort=stalest_first&limit=N`
  (added `portal_invited=any` intersect — same predicate as the
  Invited cohort, so we never chase a customer who was never
  invited).
* Enable-state on the Chase button uses
  `min(invited_count, never_count)` as an upper-bound approximation
  for the chase audience — disables when either cohort is 0.
* Rest of the modal flow (batch selector 5/10/25 → confirm → bulk
  endpoint → summary state → refetch tile+list) unchanged.

**Test-id renamed** — old `onboarding-tile-never-chase-cta` is
retired in favor of `onboarding-tile-invited-chase-cta`. This is a
breaking test-id change; the two frontend test files that
referenced it were updated in this diff. Callers outside the repo
should search-and-replace. Rationale for the rename: the
placement changed, the semantics changed, and stale test-ids on
old locations are more dangerous than a one-time rename.

## Chip layout on the customers page

Added two sibling chips in the "First-time sign-in" group,
mirroring the existing "Never logged in" chip pattern:

* **Invited** (test-id `filter-chip-portal-invited`) →
  `?portal_invited=any`
* **Signed in** (test-id `filter-chip-signed-in`) →
  `?first_access=any`  — mutually exclusive with "Never logged in"
  on the shared `first_access` param (activating one turns the
  other off).
* **Never logged in** (existing, unchanged UX beyond the mutual
  exclusion with "Signed in").

Both new chips hydrate from and persist back to the URL on the
same effect that Never uses — refresh + share links preserve
state.

The Activated card deep-links to `?portal_activated=1`, which the
existing "Portal activation" tri-state selector on the page
already hydrates — no new chip needed.

## Files touched

**Backend**
* `routers/customers.py`
  * new `portal_invited: Optional[str]` query param + predicate
    body (matches onboarding-health `invited` cohort predicate).
  * `count_only=true` variant supported for free.

**Frontend**
* `components/customers/PortalOnboardingHealthTile.jsx` — full
  rewrite of `COHORT_ORDER` (each card carries its own
  `ctaHref` / `ctaTestid`) + Chase button moved to Invited card.
* `components/customers/ChaseStalledInvitesModal.jsx` — preview
  URL prefix changed to include `portal_invited=any`.
* `pages/customers/CustomersList.jsx` — two new sidebar chips
  (Invited, Signed in), URL hydration + persistence, mutual
  exclusion between Never and Signed in on `first_access`,
  filter-count summary bar wiring.

**Tests**
* `tests/test_customers_portal_invited_filter.py` (new) — 5 cases:
  * `portal_invited=any` returns only invited rows.
  * `portal_invited=none` returns only uninvited rows.
  * Bad value → 400 `invalid_portal_invited`.
  * `count_only=true` returns the count of matched rows.
  * Intersection with `first_access=never` isolates the chase
    audience.
* `src/test/portal-onboarding-health-tile.test.jsx` (rewritten) —
  table-driven navigation coverage per cohort card + keyboard
  activation (Enter + Space) for all four cards.
* `src/test/chase-stalled-invites.test.jsx` (updated) — Chase
  button now under Invited card, retired testid asserted absent,
  preview URL asserts new `portal_invited=any` prefix.

**Memo**
* `/app/memory/FEATURE_ONBOARDING_TILE_CLICKABLE_AND_CHASE_MOVE.md` (this file)

## Test tally

| Suite | Result |
|---|---|
| `test_customers_portal_invited_filter.py` | **5/5** ✅ |
| `test_chase_stalled_invites.py` (regression) | **5/5** ✅ |
| `portal-onboarding-health-tile.test.jsx` | **8/8** ✅ (up from 4) |
| `chase-stalled-invites.test.jsx` | **4/4** ✅ (behavior updated) |
| `bulk-portal-invite-from-customers-list.test.jsx` (regression) | **6/6** ✅ |

Pre-existing failures in `test_customers_portal_status_filter.py`
(4 tests) confirmed to be pre-existing (verified via `git stash`
pop) — the tests seed `has_login=True` alone and expect the row
to be counted as "activated", but the P43c-corrected predicate
requires `portal_password_set_at` OR `last_portal_login_at`.
Not caused by this ship; not touched per the small-diff constraint.

## Live smoke-test evidence (preview)

```
$ curl /api/customers?count_only=true&portal_invited=any
  {"count": 11}
$ curl /api/customers?count_only=true&portal_invited=none
  {"count": 17}
$ curl /api/customers?count_only=true&portal_invited=any&first_access=never
  {"count": 10}                               ← Chase audience
$ curl /api/reports/portal-onboarding-health?window_days=30
  cohorts.invited.count = 11                   ← matches list count above
$ curl /api/customers?portal_invited=bogus
  HTTP 400 (invalid_portal_invited)
```

## Follow-up

* Mobile parity — separate handoff to `e1_expo_frontend_dev`.
  Mobile does not currently render the onboarding health tile.
* Optional: add historical trend arrows on the three new
  deep-linked cohort counts (only Activated and Signed in expose
  a 30d delta today; Invited + Never explicitly emit `null` per
  backend assumption). Out of scope for this ship.
* Optional: Activated deep-link could be swapped from
  `?portal_activated=1` to `?portal_status=activated` if the
  operator prefers the semantic URL over the shorthand; both
  server params accept the identical predicate today. Current
  choice mirrors the URL hydration the CustomersList sidebar
  writes for its "Portal activation" filter (`portal_activated=1|0`)
  so refresh preserves state without cross-param translation.

**Guardrails honored:** no prod touched, no Save-to-GitHub, no
`/app/mobile/`, chip/list/tile numerical consistency preserved
(same predicate helpers everywhere), reused existing filter chip
infrastructure, small reviewable diff (1 new backend param, 3
frontend files, 2 test files + 1 new suite).
