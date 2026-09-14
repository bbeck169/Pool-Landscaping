# Fix — Recurring-jobs backfill · broaden keyword matching in job titles

**Phase**: Feb-2026  
**Type**: Data-hygiene widening on the existing orphan-backfill admin endpoint.  
**Scope**: Backend only. No route surface change (OpenAPI paths remain **1744**).

## Summary

The orphan backfill previously classified recurring jobs from *structural
fields* only (`is_recurring`, `recurring`, `cadence`, `recurrence`,
`recurring_template_id`). Legacy rows created before the K4 mirror
landed often carry a cadence hint **only in the job title/description**
(e.g. `"Weekly Pool Service"`, `"Bi-weekly Landscape"`) and slip past
detection.

This fix widens both detection (`_is_recurring_row`) and frequency
inference (`_infer_frequency` fallback) to run a case-insensitive
word-boundary regex over `title` / `description` / `notes` when
structural signals are missing. Structural matches still win — the
keyword path is a strict fallback.

## Keyword → frequency mapping

| Keyword pattern (case-insensitive) | Canonical `frequency` |
|-----------------------------------|-----------------------|
| `\bbi[-\s]?weekly\b` | `biweekly` |
| `\bweekly\b` | `weekly` |
| `\bmonthly\b` | `monthly` |
| `\bquarterly\b` | `quarterly` |
| `\bsemi[-\s]?annual\b` | `semi_annual` |
| `\b(annual|yearly)\b` | `custom` * |

\* `annual` / `yearly` are not in the `VALID_FREQ` enum (see
`routers/recurring_jobs.py`), so they collapse into `custom` — same
downstream shape, notes carry the original word implicitly via the
job's title being preserved on the template.

## Priority order

Most-specific-first: **biweekly > weekly > monthly > quarterly > semi_annual > custom (annual/yearly)**. Enforced by the order of
`_KEYWORD_FREQ_PATTERNS`; the loop returns the first match so
"biweekly" never mis-classifies as "weekly".

## Structural-first fallback rule

Per cluster, the freq is picked in this priority order — the
`backfill_source` field on both the orphan preview and the created
template records which pathway won:

1. **`structural`** — at least one row in the cluster has a
   structural cadence field (`frequency`, `cadence`, `recurrence`,
   `recurring_type`) with a non-empty value.
2. **`keyword_match`** — no row has structural cadence, but at least
   one row's title/description/notes matches a `_KEYWORD_FREQ_PATTERNS`
   regex.
3. **`gap_inference`** — no structural, no keyword; ≥2 occurrences
   → gap between the first two determines the frequency.
4. **`default`** — nothing usable → `weekly` fallback (unchanged).

## Idempotency + audit trail

- The existing `exists` check in `backfill_orphans` (keyed on
  `tenant_id + customer_id + service_type (case-insensitive) + frequency`)
  is unchanged. Keyword-matched clusters flow through the same
  dedupe path, so a second run is a no-op.
- Every created template row now carries `backfill_source ∈
  {structural, keyword_match, gap_inference, default}` alongside the
  pre-existing `created_by_backfill=True` marker. Admins can audit
  via a direct Mongo query::

      db.recurring_job_templates.find({
        tenant_id: "...", backfill_source: "keyword_match"
      })

## Trigger

- Admin endpoint (unchanged):
  - `GET  /api/recurring-jobs/orphans` — dry-run preview (now
    includes `backfill_source` on each row).
  - `POST /api/recurring-jobs/backfill-orphans` — materializes
    templates. Safe to re-run.
- **Not auto-run on boot** — this is a manual admin action per the
  existing shape of the script.

## Testing

New: `backend/tests/test_recurring_backfill_keyword_broaden.py` —
**24 tests passing**:

- `TestKeywordFrequency` × 16: every keyword pattern hit, priority
  (biweekly beats weekly / semi_annual beats annual), word boundary
  guard, description-field coverage, ordering matches spec.
- `TestIsRecurringRowBroaden` × 4: keyword-only row now counts,
  structural still wins, no-hint returns False, structural freq
  survives when keyword disagrees.
- `TestBackfillKeywordEndToEnd` × 4: `"Weekly Pool Service"` +
  `"Bi-weekly Landscape"` mint templates with `backfill_source=
  'keyword_match'`, no-hint rows still produce zero templates,
  structural freq is NOT overridden.

Pre-existing suites — no regression:

- `tests/test_p0_recurring_orphan_backfill.py` — 4/4 still passing.
- `tests/test_recurring_is_active_and_hard_delete.py` — 7/7 still
  passing.

## Out of scope (unchanged)

- No new admin UI surface (existing preview + backfill endpoints
  are enough).
- No change to the recurring-jobs generator gate, `is_active`
  migration, or delete actions (already shipped in earlier phases).
- No frontend / mobile change.
- No A–F backlog items.
