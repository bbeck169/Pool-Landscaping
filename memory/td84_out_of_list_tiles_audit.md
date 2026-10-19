# TD-84 · Out-of-list web tiles · mobile port scope audit

**Date:** 2026-02-18
**Scope:** scope the mobile port for the three admin dashboard surfaces operator previously flagged as "out of list" for TD-dashboard-parity: `Customers by Service Category` row, `Uncategorized line-items` banner, `Data Integrity` tile.
**Verdict:** **STOP · operator confirmation required before any port lands.** Previous dispatch excluded these intentionally; this audit scopes the work in case operator wants to revisit.

---

## 1 · Surfaces in scope

### 1.a · Customers by Service Category row
- `frontend/src/components/dashboard/ServiceCategoryTileRow.jsx` — 178 LOC. 4-tile row (Pool / Landscaping / Both / Uncategorized) with deep-link drill-downs.
- Consumed by `frontend/src/pages/admin/Dashboard.jsx:704` ("P2 #6 · Feb-2026 — Customers by Service Category").
- Data source: existing `GET /api/dashboard` fields (`active_accounts_count`, `pool_customers_count`, `landscaping_customers_count`, `both_customers_count`). No new BE needed.

### 1.b · Uncategorized line-items banner
- Rendered inline on `pages/admin/Dashboard.jsx:469-473` from `GET /api/reports/uncategorized-summary` (not actually a dedicated banner component — a conditional div).
- Deep-link target: `frontend/src/pages/reports/UncategorizedItemsReport.jsx` — **987 LOC**. Full report with bulk-reclassify, CSV export, K48 confirmation flow, A2 role gate.

### 1.c · Data Integrity tile
- `frontend/src/components/admin/DataIntegrityTile.jsx` — 375 LOC. Composite tile aggregating 6-8 drift signals (null geocode, orphan line items, dangling photo refs, missing service_category, etc.) with per-signal fix links.

---

## 2 · Mobile port sizing

### Partial / minimum port (read-only tiles only, no actions)

| Surface | Mobile scope | Est LOC |
|---|---|---|
| Customers by Service Category row | 4 read-only tiles with deep-link navigation to a mobile Customers list filtered by category | ~180 |
| Uncategorized banner | Read-only banner + navigation to a NEW mobile report screen (summary only, no bulk-reclassify) | ~120 |
| Data Integrity tile | Composite read-only tile with per-signal count + "View on web" deep-link | ~200 |
| Jest + detox regression | ~100 |
| **Minimum total** | | **~600 LOC** |

### Full parity (web feature set)

| Surface | Mobile scope | Est LOC |
|---|---|---|
| Service Category row + drill-down | Full parity including filter composition on Customers list | ~250 |
| Uncategorized full report | Port of UncategorizedItemsReport.jsx (987 LOC) incl. bulk-reclassify + K48 + A2 + CSV export | ~1200 |
| Data Integrity tile + per-signal fix flows | 375 LOC web = ~500 LOC mobile with per-signal drill-ins | ~500 |
| Shared primitives (K48 bottom sheet, A2 auth shim) | ~200 (overlaps with TD-81 if that ships first) |
| Test coverage | ~400 |
| **Full total** | | **~2550 LOC** |

Both estimates exceed the 300-LOC roll-through ceiling. Minimum is 2× over; full is 8.5× over.

---

## 3 · Previous operator stance (restated for context)

From the dispatch spec:
> _"operator previously said these were out-of-list for TD-dashboard-parity."_

The audit cannot infer whether this stance has changed. The three surfaces each serve a distinct admin workflow (data hygiene, revenue classification, fleet audit) that is naturally desk-top centric — field techs typically neither trigger nor consume these signals from mobile. The web experience owns the primary workflow.

---

## 4 · Options

- **A) Keep out-of-list.** Zero LOC. Matches the prior operator position. No further action.
- **B) Minimum read-only port.** ~600 LOC Expo-specialist dispatch. Mobile shows the three tiles at-a-glance but drills to web for any action. Lowest-friction way to surface the signals on mobile.
- **C) Full web parity.** ~2550 LOC multi-week Expo dispatch. Not recommended without a clear workflow motivation; the admin desk is where these signals operationally land.

---

## 5 · Guardrail status

- Audit-only. Zero code written. Zero `/app/mobile/` edits.
- Single doc commit.
- STOP triggered per operator dispatch spec ("CONFIRM with operator before shipping — operator previously said these were out-of-list").

**Awaiting operator decision between A / B / C.**
