# Fix — Feb 2026 · Polish Bundle (3 items)

**Phase**: Feb-2026 · Polish  
**Scope**: 3 small backend + frontend surface additions bundled
per user dispatch. All strictly admin-side; no mobile parity in
scope (all three are admin desktop features).

## Item 1 — `GET /api/recurring-jobs/orphans?source=` filter

### Contract

Optional `?source=` query param on the pre-existing orphans preview
endpoint (`routers/recurring_jobs_backfill.py`). Accepts one of:

- `structural`
- `keyword_match`
- `gap_inference`
- `default`

Behaviour:

- **Omitted** — return the full unfiltered set (pre-polish behaviour).
- **Valid value** — filter clusters where `backfill_source == source`.
- **Unknown value (including empty string `""`)** — `422` with
  `detail = "recurring_jobs.orphans.invalid_source: source must be one of (…)"`.

Response gains a `source_filter` echo so callers can confirm which
pathway the server applied.

### Auth

Unchanged — `require_admin_or_manager` (admin / super_admin / owner
/ manager).

## Item 2 — `GET /api/ai/kb/citations/top` (AI RAG telemetry tile)

### Endpoint

`GET /api/ai/kb/citations/top?days=7&limit=10` (admin+/super_admin).

### Query shape

Aggregates the `sources[]` array persisted on every
`ai_employee_messages` assistant row by the KB RAG retrieval pass
(see `FEATURE_AI_EMPLOYEES_KB_RAG.md § Response payload delta`).

Pipeline:

```
match  {tenant_id, role:"assistant", created_at >= since, sources ≠ []}
unwind sources
match  {sources.doc_id ≠ null}
group  by sources.doc_id → count, max(created_at), last(title)
sort   citations desc, last_cited_at desc
limit  ${limit}
```

**No dedicated `ai_kb_citations` collection exists in this phase** —
the RAG memo only emits `logger.info` telemetry. Follow-up: if a
future phase adds a write-side collection, this handler flips its
source without changing the response shape.

### Response

```json
{
  "items": [
    { "doc_id": "…", "doc_title": "…",
      "citations": 12,
      "last_cited_at": "2026-02-06T10:00:00+00:00" }
  ],
  "days": 7,
  "since": "2026-02-01T00:00:00+00:00",
  "until": "2026-02-08T00:00:00+00:00"
}
```

Empty telemetry → `{ items: [], … }`. `days ∈ [1, 365]`,
`limit ∈ [1, 50]`; out-of-range → 422 (FastAPI query validation).

### Frontend tile

Location: **AI Brain admin page** (`pages/settings/AIBrainPage.jsx`),
inserted directly beneath `WeeklyAIEmployeesSummary` and above
`TopQuestionsWidget` so citation observability sits with the other
weekly-rollup blocks.

Component: `components/admin/TopKBCitationsTile.jsx`.

- Header: `Top KB docs cited (7d)`.
- Renders the top **5** rows client-side (endpoint returns up to
  `limit=10`, tile slices to 5).
- Empty state: `No citations yet. Ask questions in the AI Dock to populate.`
- Per row: title + citation count + last-cited date chip.

### Testids

| Testid                            | Element                    |
|-----------------------------------|----------------------------|
| `ai-kb-citations-tile`            | Tile wrapper               |
| `ai-kb-citations-loading`         | Loading state              |
| `ai-kb-citations-empty`           | Empty state                |
| `ai-kb-citations-error`           | Error state                |
| `ai-kb-citation-row-<i>`          | Row 0–4                    |

## Item 3 — `GET /api/warranties/expiring-soon` (admin tile)

### Endpoint

`GET /api/warranties/expiring-soon?days=30` (admin+/super_admin).

### Filter

```
tenant_id  == caller
status     == "active"
is_deleted != True
today  <= end_date <= today + days
```

Sorted by `end_date` ASC. `days ∈ [1, 365]`; out-of-range → 422.

### Response

```json
{
  "items": [
    { "id": "…",
      "contract_name": "Extended Pool Warranty",
      "customer_id": "…",
      "customer_name": "Alice Adams",
      "provider": "warranty",           // plan_kind_snapshot
      "coverage_end": "2026-02-13",
      "days_remaining": 5,
      "linked_summary": "Install job #a1b2"   // OMITTED when unlinked
    }
  ],
  "days": 30
}
```

### `linked_summary` shapes

- `linked_type == "install"` → `"Install job #<short_id>"`
  (short_id = last 4 chars of `linked_id`, or the raw id when
  shorter than 8 chars).
- `linked_type == "equipment"` → `"Equipment: <type> <brand> <model>"`,
  skipping any missing pieces cleanly.
- Unlinked / `linked_type == "none"` / referenced entity missing →
  **field omitted entirely** (never emitted as `"—"` or `null`)
  so the UI can hide the chip with a plain truthy check.

### Frontend tile

Location: **Main admin dashboard** (`pages/admin/Dashboard.jsx`),
directly beneath `RoutingCostTile`. Role gate: same as the
neighbouring `RoutingCostTile` (super_admin / admin / owner) —
the endpoint itself enforces admin+ regardless.

Component: `components/admin/WarrantiesExpiringTile.jsx`.

- Header: `Warranties nearing expiration`.
- Renders top **5** client-side.
- Empty state: `No warranties expiring in the next 30 days.`
- Per row: contract name + customer + `linked_summary` chip
  (when present) + `days_remaining` badge (colour-coded ≤7d red,
  ≤14d amber, else brand) + per-row `Renew` shortcut.
- Both the row click and the Renew button navigate to
  `/customers/{customer_id}?tab=warranties`. `stopPropagation` on
  the Renew click keeps navigation single-fire.
- v1 has no auto-renewal flow — Renew is a semantic shortcut.

### Testids

| Testid                                 | Element                          |
|----------------------------------------|----------------------------------|
| `warranties-expiring-tile`             | Tile wrapper                     |
| `warranties-expiring-loading`          | Loading state                    |
| `warranties-expiring-empty`            | Empty state                      |
| `warranties-expiring-error`            | Error state                      |
| `warranties-expiring-row-<i>`          | Row 0–4 (click-through)          |
| `warranties-expiring-row-<i>-renew`    | Renew shortcut per row           |

## API surface delta

- OpenAPI paths: **1747 → 1749** (+2). Item 1 is a query-param
  extension on an existing path.

## Test coverage added

Backend (`backend/tests/`):

- `test_polish_bundle_feb_2026.py` — 6 tests (Item 1 `?source=`
  filter matrix + 422 guard).
- `test_polish_bundle_kb_citations.py` — 6 tests (Item 2 aggregate,
  ordering, limit, auth, defaults, 422 guard).
- `test_polish_bundle_warranties_expiring.py` — 7 tests (Item 3
  filter window, sort, `linked_summary` shapes, `days_remaining`,
  auth, narrowing).

**All 19 new tests pass** + adjacent regression suites
(`test_recurring_backfill_keyword_broaden.py`,
`test_p0_recurring_orphan_backfill.py`,
`test_warranty_contracts_linked.py`,
`test_phase28_warranties.py`,
`test_ai_employees_kb_rag.py`) also green — combined **90 passed**.

Frontend (`frontend/src/test/`):

- `polish-bundle-top-kb-citations-tile.test.jsx` — 5 tests.
- `polish-bundle-warranties-expiring-tile.test.jsx` — 7 tests.

**All 12 new tests pass.** Full Vitest suite: **4412 passed,
34 skipped** across 591 test files (no regressions).

## Out of scope

- Mobile parity for either tile (both are admin desktop features).
- Any auto-renewal / renew-in-place flow (Renew is a shortcut).
- Backfilling a `ai_kb_citations` write-side collection — deferred
  until embedding-based RAG lands.
- A–F backlog items.
