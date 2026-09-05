# Phase K54.1 · Feb-2026 — Legacy outlined-red Delete buttons → solid destructive

**Status**: Shipped to preview. 21/21 vitest passing on the K54 +
K54.1 assertions.

**Trigger**: Tester on K54 flagged Marketing Templates admin's
"Delete" button as rendering with `background-color: rgba(0,0,0,0)`
(transparent) + red text — off spec. Root cause: it was a legacy
inline `<button>` with an outlined-red class list
(`text-red-600 border border-red-200 hover:bg-red-50`) that the K54
sweep didn't touch because the K54 audit only covered Sign-out
entry points + shadcn `variant="destructive"` consumers.

## Audit result

Found three legacy inline outlined-red destructive buttons the K54
sweep missed:

| File | data-testid | Old spec | New spec |
|---|---|---|---|
| `frontend/src/pages/marketing/MarketingTemplatesAdmin.jsx` | `template-detail-delete` | `text-red-600 + border-red-200 + hover:bg-red-50` (outlined) | Solid K54 destructive |
| `frontend/src/pages/marketing/MarketingMediaAdmin.jsx` | `media-admin-bulk-delete-btn` | Same outlined variant | Solid K54 destructive |
| `frontend/src/pages/marketing/InstaScheduleAdmin.jsx` | `insta-service-row-remove-btn` | Icon-only `text-red-500 p-1` (foreground only) | Solid K54 destructive (icon size) |

## Design tension flagged (user asked me to surface these)

The **InstaScheduleAdmin ServiceRow trash icon** is a row-level remove
inside a table row of services. Promoted to solid red per user's
"consistency over emphasis" ask. This makes each row a bit more
visually loud — if the user later adjudicates that row-level removes
should stay low-emphasis, revert this one and codify the exception in
the K54 principles doc. Everything else in the promotion sweep is a
top-level destructive action that clearly benefits from the solid spec.

## shadcn `<Button variant="destructive">` consumers — already on spec

Verified that the 2 shadcn-primitive destructive consumers still route
through the shadcn primitive and thus automatically inherit the K54
spec via `components/ui/button.jsx`:

- `pages/dispatch/RouteOptimizationApprovalModal.jsx` (`route-optimization-approval-reject-confirm`)
- `components/dashboard/DashboardDrillDownModal.jsx` (row-level `di-row-*-delete-btn` matcher)

Both use `<Button variant="destructive">` and paint the K54 spec
(`bg-[#DC2626] hover:bg-[#B91C1C] focus-visible:ring-[#EF4444]`).
Locked in by the new `K54.1 · shadcn Button variant='destructive'
consumers still use the primitive` describe block.

**Walkie**: the earlier grep hit was on `<Badge variant="destructive">`
(a status badge, not a button). Badges are non-interactive; K54 spec
applies only to buttons. No action needed on Walkie.

## Not touched in this pass

Roughly 25 more legacy inline `text-red-*` / `colors.error` custom
buttons across the app (SEO / onboarding / portal preferences /
some settings surfaces). Each has a bespoke class list. The
Marketing + Insta trio was the tester-flagged batch; the rest live
outside the current tester's smoke path and can be swept in a
follow-up K54.2 audit if you want a formal per-page checklist.

## Tests

New assertions in `frontend/src/test/k54-destructive-buttons.test.js`:

* `K54.1 · legacy outlined-red Delete → solid destructive` — 3
  parametrized assertions locking each of the 3 promoted surfaces
  to `bg-[#DC2626] + hover:bg-[#B91C1C] + focus-visible:ring-[#EF4444] + text-white`.
* Two guard assertions confirming the pre-K54.1 outlined-red class
  tuple (`text-red-600 + border-red-*`) is gone from the two
  outlined-red surfaces.
* `K54.1 · shadcn Button variant='destructive' consumers still use
  the primitive` — 2 parametrized assertions locking the shadcn
  consumers to `<Button variant="destructive">` so a future refactor
  can't silently drop off the primitive.

## Files changed

* `frontend/src/pages/marketing/MarketingTemplatesAdmin.jsx`
* `frontend/src/pages/marketing/MarketingMediaAdmin.jsx`
* `frontend/src/pages/marketing/InstaScheduleAdmin.jsx`
* `frontend/src/test/k54-destructive-buttons.test.js` (extended, not
  overwritten — original 14 K54 assertions still pass).
