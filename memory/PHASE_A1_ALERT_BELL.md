# Phase A1 · Feb-2026 — Proactive Intelligence: Alert Bell + Missed-Service Scan

## Scope shipped
- Backend `intelligence_alerts` MongoDB collection with unique
  `(tenant_id, alert_key)` compound index for idempotent inserts.
- Backend routes:
  - `GET  /api/intelligence/alerts`
  - `POST /api/intelligence/alerts/{alert_id}/read`
  - `POST /api/intelligence/alerts/{alert_id}/dismiss`
  - `POST /api/intelligence/alerts/mark-all-read`
  - `POST /api/intelligence/scans/missed-service/run-now`
- APScheduler `missed_service_scan` cron: detects recurring
  jobs missed the previous day and emits `missed_service` alerts
  via the shared `emit_alert()` helper (dedup-safe).
- Frontend `AlertBell` component — polls every **60 s** with an
  extra fetch on window `focus`. Role-gated to `admin` and
  `super_admin` only.
- Frontend `IntelligenceAlerts` page mounted at
  `/admin/intelligence/alerts` (wrapped in `<AdminOnly>` — which
  resolves to admin + super_admin, matching the backend
  `insufficient_role_for_alerts` gate exactly).
- Navigation surfaces:
  - Top nav: `<AlertBell />` mounted in the AdminTopBar right
    cluster on both narrow (<768 px) and wide branches, between
    `SettingsSprocket` and `LanguageSelector`.
  - Sidebar / Category dropdowns: new **Intelligence** category in
    `ADMIN_NAV_V2` (icon `Bell`) with a single **Alerts** entry.
    Uses the new `hard_rule: "admin_or_super_admin"` value —
    filter added to both `useVisibleGroups` (AdminTopBar) and
    `visible` (AdminSidebar).
- Small typo fix: Phase B timeline chip label renamed **Call →
  Calls** in `CustomerFullTimeline.jsx`.

## Tests
- Backend: `backend/tests/test_intelligence_alerts_a1.py`
  → **12 / 12 passed** (`pytest -q`, 6.4 s wall).
- Frontend: `frontend/src/components/nav/__tests__/AlertBell.test.jsx`
  → **18 / 18 passed** (`vitest`, 1.6 s wall).
- Regression sweep — 60/60 passed across:
  `header-cleanup-bell-cluster`, `admin-topbar-add-job-button`,
  `admin-top-bar-mobile-role-preview-switcher`, `k75-top-nav`,
  `admin-sidebar-pinned-nav`, `customer-full-timeline`.

## Next steps
- Phase A2 — Chemistry Upsell Alerts.
- Phase A3 — Churn Risk Alerts.
- Phase A4 — Renewal Due Alerts.
