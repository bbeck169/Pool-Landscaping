# Phase K75 · Web Nav Revert · Step B — SHIPPED (Feb 2026)

## Scope shipped in Step B

Pin management on top of Step A's shell. Every authenticated staff role (admin / super_admin / manager / technician) can now:

- **Add pins** from a role-appropriate registry (search + tree grouped by category).
- **Remove pins** with a typed confirm dialog.
- **Reorder pins** via drag-and-drop (`@dnd-kit`).
- **Persist** the pin list per-user in `users.preferences.quickPins`, cap 15, iconKey-whitelisted, role-registry-gated.

Customer portal untouched. Mobile bottom-nav / drawer untouched.

## Endpoint contract

| Endpoint | Purpose | Notes |
| --- | --- | --- |
| `GET /api/users/me/quick-pins` | Return `{ pins: [{to, label, iconKey}] }` — `[]` for first-run users. | Read-only; the endpoint never auto-writes a default seed. The rail renders defaults client-side (see `defaultQuickPinsForRole`). |
| `PUT /api/users/me/quick-pins` | Replace the full pin array. Body: `{ pins: [{to, label, iconKey}] }`. Returns `{ ok: true, pins: [...] }`. | Tenant/user scoped — writes into the caller's own doc only, never accepts a `uid` arg. |

**Validation matrix** (PUT). Every failure surfaces `400` with a `detail.code`:

| Failure | Code |
| --- | --- |
| More than 15 pins | `pin_cap_exceeded` |
| Duplicate `to` inside the same PUT | `duplicate_pin` |
| Route missing leading `/`, containing `..`, > 200 chars, or an embedded protocol (`http:` / `javascript:` / `data:`) | `foreign_route` |
| Tech / customer pinning a route outside their role allow-list | `wrong_role_route` |
| `iconKey` not in `ICON_WHITELIST` | `icon_not_whitelisted` |
| Empty label or label > 40 chars | `label_invalid` |

Admins / super_admins / managers get a permissive route gate (any well-formed path) so they can pin any of the ~130 admin routes; techs are constrained to their existing IA (`/schedule`, `/d2d`, `/tech/*`, `/customers`, `/estimates`, `/invoices`, `/tests`, `/portal/profile`, `/landscape/time-clock`, `/job-timers`); customers to `/portal/*` and `/customer/*` (the customer portal doesn't currently render the K75 rail, but the guard is in place for future).

## Deliverables

### Backend

- **NEW** `backend/routers/quick_pins.py` — GET + PUT + all validators + `ICON_WHITELIST` frozenset (mirror of the JS side).
- **NEW** `backend/tests/test_k75_quick_pins_endpoint.py` — **17 assertions**, all green:
  1. GET returns `[]` for a fresh user + no auto-write.
  2. PUT roundtrip persists into `users.preferences.quickPins`.
  3. Cap enforcement — 16 pins → 400 `pin_cap_exceeded`; exactly 15 → 200.
  4. Foreign route rejection (missing leading `/`, path traversal, embedded URL).
  5. Wrong-role route rejection — technician pinning `/admin/impersonate` → 400 `wrong_role_route`.
  6. Icon whitelist — stale `iconKey` → 400 `icon_not_whitelisted`.
  7. Duplicate `to` → 400 `duplicate_pin`.
  8. Label empty / over max → 400 `label_invalid`.
  9. Unauthenticated GET + PUT → 401.
  10. Cross-user isolation — user A's PUT doesn't surface on user B's GET.
  11. **Icon whitelist source parity** — the Python frozenset and the JS `ICON_MAP` share the identical key set (regex-verified so they can't drift silently).
- **MODIFIED** `backend/server.py` — one-line router registration (`api_router.include_router(quick_pins.router)`).

### Frontend

- **NEW** `frontend/src/nav/lucideIcons.js` — the 35-key `ICON_MAP` (iconKey → lucide component) + `resolveIcon()` fallback to `ExternalLink` so a stale pin never crashes the rail.
- **NEW** `frontend/src/nav/defaultQuickPins.js` — seed defaults per role (mirrors the retired pre-K75 hard-coded rail array byte-for-byte for admin+, dashboard + schedule for tech, empty for customer).
- **NEW** `frontend/src/nav/pinRegistry.js` — searchable picker source (ADMIN_TOP_NAV as "Primary" group + all 6 `ADMIN_NAV_V2` categories for admin; TECH_TOP_NAV + curated extras for tech). Dedupes across groups so every route surfaces exactly once with a unique testid.
- **NEW** `frontend/src/hooks/useQuickPins.js` — CRUD hook (`pins`, `addPin`, `removePin`, `reorderPins`, `atCap`, `cap`, `pinnedRoutes`, `loading`, `saving`, `error`). Optimistic update with rollback on PUT failure.
- **NEW** `frontend/src/components/nav/QuickPinsRail.jsx` — the 88 px navy rail. K64 canonical active/hover, `@dnd-kit/sortable` reorder, grip handle + `×` remove appearing on hover, "+" trigger at the bottom (disabled at cap with N/N label). Preserves `data-testid="quick-nav-rail"` + `rail-nav-{key}` naming so pre-K75 tests keep locking the shape.
- **NEW** `frontend/src/components/nav/AddPinModal.jsx` — searchable tree modal, pinned-row disable + "Pinned" badge, at-cap notice banner, error surface for failed PUTs (`pin_cap_exceeded`, `duplicate_pin`, `wrong_role_route`, `icon_not_whitelisted`, generic).
- **NEW** `frontend/src/components/nav/RemovePinConfirm.jsx` — shadcn AlertDialog wrapper for the unpin confirm.
- **MODIFIED** `frontend/src/layouts/AppLayout.jsx` — deleted the pre-K75 inline `QUICK_NAV_RAIL` array + `QuickNavRail` function (dead code after Step B); import `<QuickPinsRail>` and render it in place. Removed the unused `Timer` / `UserPlus` lucide imports.
- **NEW** `frontend/src/test/k75-quick-pin-rail.test.jsx` — **12 assertions**, all green:
  1. First-run rendering — GET `[]` → rail shows seeded defaults.
  2. Persisted rendering — GET non-empty → rail shows persisted pins (not defaults).
  3. "+" opens the modal with searchable groups.
  4. Search filters rows by label or route.
  5. Clicking an unpinned row PUTs the new pin with correct payload shape.
  6. Already-pinned rows are disabled + wear the "Pinned" badge.
  7. At-cap: "+" is disabled + shows `15/15` label.
  8. At-cap modal source-lint — cap notice testid + `disabled = isPinned || atCap` predicate present.
  9. Remove-pin flow opens the confirm modal.
  10. Confirm remove PUTs the pin list minus the removed pin.
  11. `useQuickPins.reorderPins` source-lint — `arrayMove` in `onDragEnd`, `reorderPins(next.map(p => p.to))`, `SortableContext` + `verticalListSortingStrategy` present.
  12. **Icon whitelist source parity** — JS `ICON_MAP` and Python `ICON_WHITELIST` share the same key set (mirror of the pytest assertion).

### Test updates from Step A

- `test/rail-nav-leads.test.jsx` — rewritten to source-lint the new `defaultQuickPins.js` (P20 gating semantics preserved via `defaultQuickPinsForRole(role)`).
- `test/phase20-quick-nav-rail-managerial-links.test.jsx` — source-lint path moved from `AppLayout.jsx` → `defaultQuickPins.js`.
- `test/k50-theming.test.js` — the Slice A rail source-body assertion re-scoped to `QuickPinsRail.jsx::SortableRailPin` (K64 canonical preserved).
- `test/k52-theming.test.js` — the Slice D rail source-body assertion re-scoped to `QuickPinsRail.jsx` (K64 canonical preserved).
- `test/k64-nav-active-hover-unify.test.jsx` — the rail source-body describe moved from `AppLayout.jsx::QuickNavRail` → `QuickPinsRail.jsx::SortableRailPin` (K64 canonical preserved).
- `test/nav-hover-polish.test.jsx` — motion polish assertion re-scoped to `QuickPinsRail.jsx`.

## Non-negotiables · verified

- Right cluster on the top nav preserved verbatim (Add Customer · Credits · Sprocket · Sign Out · UniversalMenu bell+hamburger).
- K64 canonical (`colors.nav.bgActiveNavy`) on active + hover for every rail pin and every top-nav chip. No `brandGradient` reintroduction on nav surfaces.
- Mobile drawer (`AdminSidebar`) untouched.
- No cross-tenant / cross-user reads or writes; every PUT is scoped to the caller's own user doc.

## Tests · results

**K75 Step B + adjacent surface: 152 / 152 PASS** across the frontend (12 files) + **17 / 17 PASS** on the backend contract test (`test_k75_quick_pins_endpoint.py`).

Frontend full-suite: **438 passed / 30 failed** (same 30 pre-existing failures as the pre-K75-Step-A baseline — verified via prior `git stash` diff). Zero K75-B-introduced regressions.

## Screenshots (super@aquaterra.com preview)

- `/tmp/k75b-1-rail-at-rest.png` — post-login shell with the horizontal top nav (Dashboard active), left rail with all 11 seeded pins ("QUICK ACCESS" header, "+ Add pin" trigger at the bottom).
- `/tmp/k75b-2-rail-hover-controls.png` — hover state revealing grip handle (top-left) + `×` remove (top-right) on the Schedule pin.
- `/tmp/k75b-3-add-pin-modal.png` — Add-pin modal open, "Primary" and Finance / Ops / Marketing / AI Tools / D2D / Directory groups listed.
- `/tmp/k75b-4-add-pin-search.png` — search "marketing" filters the picker down to the Marketing group.
- `/tmp/k75b-5-remove-confirm.png` — Remove-pin AlertDialog for the Workstream pin ("Remove 'Workstream' from Quick Access?" + Cancel / Remove-pin CTA).

## Queue after K75 Step B

1. e1_tester backend contract sweep + UI CRUD smoke on Step B (matches user's stated post-ship plan).
2. K74.1 — Schedule job-tile bg lighten (~`#EAF7F0`), web + mobile parity.
3. R2 Operations Reporting Suite.
4. R3 → R7 sequential.
5. K75.1 (usage-frequency hint on the pin picker) — reconsider post-R7 per user.
6. K73.6 legacy `user_id`-in-`technician_id` normalization (P3, behind R7).
