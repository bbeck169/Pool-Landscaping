# SPEC: MARCO Analytics & Reporting Suite (queued brief)

**Status:** QUEUED — position 7. **DO NOT START.**
Saved at: Feb-2026 (post-PS-A landing).

## Scope
End-to-end marketing analytics: KPI aggregation, attribution linking, Growth Hub dashboard, NOVA-generated executive summaries.

## Sub-phases (5)

### MAS-A — `marketing_intelligence` collection + aggregators
- New collection `marketing_intelligence`:
  - `{tenant_id, date, department, source, kpi_name, kpi_value, unit, meta}`
  - Departments: `ads`, `seo`, `local`, `outreach`, `content`, `social`
  - KPIs: `ad_spend`, `cpc`, `rank_position`, `backlink_count`, `citation_score`, `impressions`, `clicks`, `ctr`, `conversions`, etc.
- Indexes: `(tenant_id, date desc)`, `(tenant_id, department, date desc)`, `(tenant_id, kpi_name, date desc)`
- Aggregator service `backend/services/marketing_intelligence.py`:
  - `record_kpi(tenant_id, department, source, kpi_name, kpi_value, unit, meta)` — write helper
  - `roll_up_daily(tenant_id, date)` — daily aggregation from raw sources
  - `roll_up_weekly(tenant_id, week_start)` — weekly aggregation
- Wire into existing marketing tools (RANK, GEO, LOCAL, SCRIBE, SOCIAL, ADAM, PULSE, REPUTE, CREATIVE, INTEL, CONVERT, ATTRIB) — each specialist writes KPIs on completion of their runs. Depends on 18-employee workforce landing.
- Idempotent migration `marketing_intelligence_v1.py` — creates indexes, sentinel-gated.
- Router `backend/routers/marketing_intelligence.py`: `GET /api/marketing-intelligence/kpis?department=&date_from=&date_to=` — tenant-scoped, JWT-derived.
- Tests: KPI write, roll-up correctness, tenant isolation, index presence.

### MAS-B — Attribution Tool for ATTRIB agent
- New tool `attribute_revenue_to_source(source: str, date_from: date, date_to: date)` in `services/ai_employee_tools.py`:
  - Queries `leads` (filter `source == input`), joins to `quotes` and `payments` via lead_id / customer_id.
  - Returns `{source, leads_count, quotes_count, quotes_value, payments_count, payments_value, conversion_rate, avg_deal_size, revenue_attributed}`.
  - Scope: available to all personas but primarily called by ATTRIB. Not orchestrator-restricted.
- Extend to multi-source: `attribute_revenue_by_all_sources(date_from, date_to)` returns array of the above per source.
- Tests: mock lead/quote/payment fixtures, verify attribution math, tenant isolation, multi-source aggregation.

### MAS-C — Growth Hub dashboard (frontend)
- New page `frontend/src/pages/marketing/GrowthHub.jsx`.
- Add route in `App.jsx` under admin surface: `/marketing/growth-hub` (or place under `/marketing/` group if it exists).
- Sidebar: add "Growth Hub" entry under existing Marketing group in `adminNav.js`.
- Charts (Recharts):
  - (a) **Marketing ROI** — line chart, `revenue_attributed / total_spend` over 30/90/YTD toggle
  - (b) **Keyword Ranking Trends** — line chart, top 10 tracked keywords' rank position over time (data source: RANK persona's KPIs)
  - (c) **Citation Health** — gauge or bar chart, citation_score aggregate + per-directory breakdown (data source: LOCAL persona)
- Department KPI cards (4): Ads (spend, CPC, ROAS), SEO (avg rank, clicks, impressions), Local (citation score, GMB views), Outreach (backlinks acquired, DA delta).
- Date range picker at top: 7d / 30d / 90d / YTD / Custom
- Palette: Navy `#1B1F5C` card backgrounds, Blue `#3B82F6` accents, chart line colors from existing chart palette. Reuse shared `Card`, `KPIStat`, `DateRangePicker` components if present.
- Data-testids: `growth-hub`, `growth-hub-kpi-{department}`, `chart-roi`, `chart-rank-trends`, `chart-citation-health`, `growth-hub-date-picker`.
- Recharts: grep `package.json` — if not present, add. Match version used elsewhere in the codebase.
- Vitest: chart renders with mocked KPI data, date range change triggers refetch, empty state renders "No data yet — connect your marketing tools" CTA.

### MAS-D — NOVA weekly executive summaries
- New endpoint `POST /api/nova/weekly-summary` — triggers NOVA to generate a plain-English summary of the past week's marketing performance.
- Flow:
  1. Endpoint pulls the past 7 days of aggregated KPIs from `marketing_intelligence`
  2. Invokes NOVA via the tool loop from MARCO Sub-phase B with a summarization prompt (structured input: KPI dict → structured output: markdown summary)
  3. Uses `delegate_task` to pull specialist input (RANK for ranking narrative, ADAM for ads narrative, ATTRIB for revenue narrative)
  4. Writes final summary to new `executive_reports` collection: `{tenant_id, generated_at, generated_by="nova", period_start, period_end, summary_md, kpi_snapshot}`
- Schedule: weekly cron (Sunday 6am tenant-local time) auto-generates and delivers via:
  - Insert into notification bell (`type=nova_weekly_summary`) targeting admin + super_admin roles
  - Optional email delivery (reuse existing email service if present)
- Grep for existing weekly-summary or scheduled-report patterns and reuse.
- Tests: mocked KPI data → NOVA-generated markdown includes all department sections, tool-loop delegation chain fires, notification inserted.

### MAS-E — UI polish + integration
- Add "Marketing" section to admin dashboard homepage: 3-week trend spark-lines + link to Growth Hub.
- Wire notification bell click for `nova_weekly_summary` type → navigate to `/marketing/executive-reports/{id}` (new detail route).
- Ensure all new surfaces respect Tenant Configuration Hub's `enabled_ai_employees` toggle — if NOVA disabled, hide the "Generate Summary" button.
- Palette: consistent Navy/Blue theme across all new surfaces.

## Dependencies (must land before MAS starts)
1. **18-employee hierarchical workforce** — NOVA, ATTRIB, RANK, LOCAL, GEO, ADAM, all Marketing specialists must exist for KPI writes and delegation to work.
2. **Lead-Sense LS-C** — source tagging must persist verbatim so attribution links leads → payments correctly.
3. **Tenant Config Hub TCH-B** — `enabled_ai_employees` filter drives MAS-E gating.
4. **Web Builder WB-B** — nice-to-have; page-view analytics from generated sites feed into MAS.

## Design forks to resolve inline
- **Recharts already in package.json?** — grep first. If not, adding it is a dependency install decision; note in commit.
- **Executive reports collection vs. reuse `marketing_intelligence`?** — separate collection is cleaner (they're generated artifacts, not raw KPI rows).
- **NOVA weekly cron timing** — Sunday 6am local vs. Monday 8am? Pick and note.
- **Attribution tool: point-in-time vs. rolling?** — Start with rolling (query at call-time). Materialization comes later.
