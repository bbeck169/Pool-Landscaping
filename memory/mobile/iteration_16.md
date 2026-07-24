# Iteration 16 — Breadcrumb Navigation

## Architecture
- `useBreadcrumbs(currentTitle?)` hook: parses `usePathname()`, maps segments to labels via 150+ entry LABELS map, builds route paths, handles dynamic segments (UUIDs), deduplicates adjacent items, returns empty for root screens.
- `<Breadcrumbs items={...}>` component: renders tappable breadcrumb strip with `›` separators. Collapses to `Home › … › Current` when > 3 items on screens < 420px wide. Ellipsis opens a popover modal listing intermediate items.
- `<BreadcrumbBar title={...}>` wrapper: self-contained component for screens with custom headers.
- Shared `<Header>` component automatically renders breadcrumbs via the hook.

## Coverage
- **Shared Header** integration covers 120+ screens automatically
- **BreadcrumbBar** added to 6 key custom-header screens
- Remaining ~14 custom-header screens could be enhanced later

## Role behavior
- Admin root: "Dashboard" at `/(app)`
- Tech root: "Schedule" at `/(app)/schedule/calendar`
- Customer root: "Home" at `/portal/home`
- Root screens: empty breadcrumbs (no strip rendered)

## Web agent notes
- No web-side changes needed for breadcrumbs — this is mobile-only
- No new backend endpoints needed — breadcrumbs are derived from routes + existing user role

## Files
- Created: `src/components/nav/Breadcrumbs.tsx`, `src/components/nav/BreadcrumbBar.tsx`, `src/hooks/useBreadcrumbs.ts`
- Modified: `src/components/widgets.tsx`, `app/time-clock.tsx`, `app/marketing/index.tsx`, `app/marketing/templates.tsx`, `app/settings/widgets.tsx`, `app/settings/tenant.tsx`, `app/settings/promo-codes.tsx`
