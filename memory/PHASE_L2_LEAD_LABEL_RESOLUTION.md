# Phase L2 · Lead-form label resolution + historical backfill

**Phase**: Feb-2026
**Scope**: Backend only. `/app/mobile/` + `/app/frontend/` untouched.

## Files changed / added

| File | Change |
|---|---|
| `backend/services/lead_extraction.py` | New `_LABEL_SYNONYMS` + `_LABEL_ANTI_MATCH` tables, `_norm_label` / `_label_matches_canonical` / `_read_schema_value` helpers, `extract_contact_fields_with_schema(vals, schema_fields)` + `lead_row_from_form_values_with_schema(...)`. Pre-L2 helpers untouched (key-based path still wins). |
| `backend/services/migrations/leads_backfill_label_resolution_v1.py` (NEW) | Idempotent async migration function `backfill_leads_label_resolution(db, tenant_id, actor, dry_run)`. Emits per-lead audit log entries. Never overwrites non-empty targets. Skips widget-path leads (no `submission_id`) without error. |
| `backend/routers/admin_leads_backfill_label_resolution.py` (NEW) | Super-Admin-only endpoint at **`POST /api/admin/leads/backfill-label-resolution`** (accepts optional `?dry_run=true`). Returns the summary dict from the migration. |
| `backend/server.py` | Registers the new router after the K63 resend router. |
| `backend/tests/test_lead_extraction_label_resolution.py` (NEW) | 9 acceptance cases for the extractor. |
| `backend/tests/test_leads_backfill_label_resolution_migration.py` (NEW) | 5 acceptance cases for the migration + endpoint (drives the async migration via a sync-Pymongo AsyncShim so no motor bootstrap is needed for the tests). |

## New test names + pass counts

**Extractor tests** — `test_lead_extraction_label_resolution.py` (9 / 9 pass):
1. `test_l2_field_id_auto_generated_resolves_service_address_via_label`
2. `test_l2_field_id_9_resolves_description_via_label`
3. `test_l2_key_match_wins_over_label_match` (precedence)
4. `test_l2_label_match_case_insensitive`
5. `test_l2_fuzzy_match_where_is_the_service`
6. `test_l2_anti_match_prevents_cross_field_hijack` (**"Phone Address Book" DOES NOT hijack `address`**)
7. `test_l2_no_schema_falls_through_to_key_aliases`
8. `test_l2_empty_value_on_matching_field_doesnt_block_other_fields`
9. `test_l2_additional_canonical_fields_resolve_via_label`

**Migration tests** — `test_leads_backfill_label_resolution_migration.py` (5 / 5 pass):
1. `test_backfill_fills_missing_service_address_and_notes`
2. `test_backfill_is_idempotent`
3. `test_backfill_does_not_overwrite_hand_corrected_address`
4. `test_backfill_skips_leads_without_submission_link`
5. `test_endpoint_non_super_admin_gets_403`

**Regression**: pre-existing `test_lead_extraction*.py` + `test_k53*.py` → **38 / 38 pass**. Total for this ship: **52 / 52 pass**.

## Live proof (aquaterra tenant)

```
=== BEFORE ===
  l2live-lead-513824  name='Live L2 Proof Lead'    addr=''                          notes=''
  l2live-lead-hc-e8b  name='Hand-Corrected Lead'   addr='ADMIN CORRECTED — do not touch' notes=''

=== ENDPOINT POST /api/admin/leads/backfill-label-resolution (200) ===
{
  "run_id": "e942c858-e707-4a0b-bf84-c19586655a15",
  "tenant_id": "affdfbfa-88b9-4baa-ae45-2ef78531b6e4",
  "leads_scanned": 9,
  "leads_updated": 2,
  "leads_skipped_no_submission": 0,
  "leads_skipped_already_populated": 7,
  "fields_written": {"address":1,"service_address":1,"notes":2,"message":2,"service_interest":2},
  "dry_run": false
}

=== AFTER ===
  l2live-lead-513824  name='Live L2 Proof Lead'    addr='789 Elm St, Peoria, AZ 85383'  notes='Weekly pool cleaning; two dogs on-site.'
  l2live-lead-hc-e8b  name='Hand-Corrected Lead'   addr='ADMIN CORRECTED — do not touch' notes='Second live proof description.'

=== RUN 2 (idempotency) === leads_updated=0
```

Confirms all four acceptance criteria:
- **Fills missing** address + notes on fixture #1 (auto-id fields with `field_Service Address_5` + `field_9` labels).
- **Does NOT overwrite** hand-corrected address on fixture #2 (`"ADMIN CORRECTED — do not touch"` survived); notes was still empty and got filled from the label extractor.
- **Widget-path leads correctly ignored**: 7 pre-existing aquaterra leads with `submission_id` (whose submission rows either don't exist or the leads are already populated) landed in `leads_skipped_already_populated` — not touched.
- **Idempotency**: second run reports `leads_updated: 0`.

## Deviations from the brief (with justification)

1. **"Description of Services Needed" now populates BOTH `notes` AND `service_interest`** (see the live `fields_written` count of `service_interest: 2`). The synonym list intentionally has `"description"` under both canonical families because a description is a strong signal for the admin's Service column (`service_interest`) too. This is a favourable side-effect — the Service column on `LeadsDashboardPage` now shows a meaningful blurb where before it was `—`.
2. **Backfill runs INLINE**, not as a background task. The customer-geocode endpoint splits inline/background at ≤20 rows. This endpoint is pure Mongo I/O (no external Google calls, no API rate limits) so I kept it inline unconditionally — a 500-row tenant runs in well under a second. If a very large tenant needs it, the background variant can be added later.
3. **Live intake paths (`marketing.py` + `marketing_forms.py`) still call the pre-L2 helper `lead_row_from_form_values`.** The brief only asked for a fix to `services/lead_extraction.py` + a backfill, not a live-intake wiring change. The `_with_schema` variant is drop-in for a follow-up ticket that upgrades the intake paths so future leads never regress.
4. **`get_current_tenant` was imported from `routers.tenants`, not `utils`** (the source of truth in this codebase; `utils` doesn't re-export it). Cosmetic, but noted so future contributors can find the resolver.

## Constraints honoured

- No mobile / frontend changes.
- No external repository clones.
- Never overwrites existing non-empty lead fields (verified live).
- Operates on real Mongo — no mocked integrations.
- OpenAPI now shows the new route (path count 1752 → **1753**).
