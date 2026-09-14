# Feb-2026 · Backend Chemistry-Gate Ship — Preserve-vs-Clear + Shared Pipeline + Multi-Body Fallback

Backend-only slice of the multi-body chemistry work. Mobile client
+ web client parity ships alongside this via the mobile team's
parallel dispatch. Three behavior changes; no route surface added
or removed; **OpenAPI paths unchanged at 1735**.

## Touched files

| File | Change | LOC |
| ---- | ------ | --- |
| `backend/services/water_bodies.py` | New `apply_water_bodies_payload(upd, rep)` — shared validate/flatten pipeline for every write path | +85 |
| `backend/services/chemistry_gate.py` | `gather_readings_for_job` now falls back to `iter_water_bodies + flatten_pool_readings` when neither the flat mirror nor legacy readings produced core values | +23 / −0 |
| `backend/routers/service_reports.py` | Web `PATCH /api/service-reports/{jid}` now funnels through `apply_water_bodies_payload` (no inline branch fork) | +14 / −41 |
| `backend/routers/mobile_sync.py` | `_handle_service_report_upsert` (both update AND insert branches) now funnels through the SAME shared helper | +30 / −2 |
| `backend/tests/test_chemistry_gate_backend.py` (NEW) | 10 pytest cases covering the 5 acceptance criteria + shared-import guard + validator regression | +285 |

## Preserve-vs-Clear semantics (Acceptance 1 + 2)

The shared `apply_water_bodies_payload(upd, rep)` helper is the
single choke-point that decides how a partial patch mutates the
persisted service_report doc. The presence check is **always**
`"water_bodies" in upd` — never `upd.get("water_bodies")` — because
`[]` is a legitimate customer/tech signal ("I deliberately cleared
everything") and must not conflate with "the client omitted the
key entirely".

Three states, three semantics:

| State of `upd` | Effect on `water_bodies` | Effect on flat `chemical_readings` |
|---|---|---|
| `water_bodies` key absent, no legacy mirror key present | **Preserved** (helper is a no-op; Mongo `$set` on the reduced `upd` naturally leaves untouched keys alone) | **Preserved** (same rule) |
| `water_bodies: []` (explicit clear) | **Set to `[]`** | **Set to `[]`** (flat mirror cleared in lockstep) |
| `water_bodies: [...]` (structured payload) | Validated via `validate_water_bodies`; each body's `sequence` stamped by index; unknown types coerced to `"pool"` (legacy compat) | Rebuilt via `flatten_pool_readings(bodies)` — mirror derived from the FIRST pool body's readings |
| `water_bodies` absent BUT legacy mirror key (`chemical_readings` / `chemicals_added` / `notes`) present | **Rebuilt from existing `water_bodies[0]` merged with the incoming legacy fields** (spawns default body if empty) | Left as-is on `upd` (caller wrote it explicitly) |

The `validate_water_bodies` empty-array rejection is intentionally
bypassed inside the helper — an explicit `[]` short-circuits to
the deliberate-clear branch without invoking the structured
validator.

## Shared validate/flatten pipeline (Acceptance 6)

Before this ship, the newer web PATCH path at
`routers/service_reports.py:590+` and the mobile-sync path at
`routers/mobile_sync.py:_handle_service_report_upsert` had DIFFERENT
write semantics — the mobile handler did a raw `$set(payload)` with
no validation, no mirror rebuild, and no legacy sync-back into
`water_bodies[0]`. Result: mobile clients that sent structured
`water_bodies` payloads via the offline sync queue never rebuilt
the flat mirror, and mobile clients that sent legacy top-level
readings never populated `water_bodies[0]`.

Both paths now funnel through the SAME `apply_water_bodies_payload`
helper — verified by the `test_bonus_shared_helper_is_imported_by_both_paths`
regression guard which asserts the helper name appears in both
handlers' `inspect.getsource` output. No fork.

Helper location: `backend/services/water_bodies.py` (module already
housed the validator + flatteners). Import path:

```py
from services.water_bodies import apply_water_bodies_payload
```

## Close-gate multi-body fallback (Acceptance 4 + 5)

`services.chemistry_gate.gather_readings_for_job(job, service_report)`
was pinned to `service_report.chemical_readings` (list-of-dicts flat
mirror) and `job.chemical_readings` (legacy dict fallback). If a
service_report carried structured `water_bodies` with a valid pool
body but the flat mirror was empty (stale mobile client, pending
migration, etc.), the close-gate falsely rejected the job.

Fix: when NEITHER source produced any core value, the gate now
falls through to:

```py
from services.water_bodies import (
    flatten_pool_readings, iter_water_bodies,
)
flat_rows = flatten_pool_readings(iter_water_bodies(service_report))
combined.update(normalize_readings(flat_rows))
```

`iter_water_bodies` materialises a default body from the legacy
top-level fields when the structured array is missing — so
existing single-body reports keep hitting the same fast path
they did before. The fallback is scoped inside a broad
`try/except` so an unusual `water_bodies` shape can never crash
the gate — worst case it degrades to the pre-ship behavior
(rejects with the same 422 detail).

Callers unchanged — every downstream (web close endpoint,
mobile-sync `job.close`, edit-window PATCH, service-report submit)
picks up the fallback automatically through the shared helper.

## Old-vs-new client interop matrix

The user's coordination note called out that mobile might land
before or after backend. Both orderings are safe:

| Mobile client state | Backend behavior |
|---|---|
| **Old (omits `water_bodies` on some PATCHes)** | Helper is a no-op on those keys → Mongo `$set` preserves the persisted `water_bodies`. Legacy top-level `chemical_readings` still routes through `water_bodies[0]` sync-back if present. |
| **New (always sends `water_bodies` when bodies exist)** | Helper validates + rebuilds the flat mirror on every write. Close-gate uses the flat mirror as its fast path — falls back to structured only when the mirror is empty. |
| **Sends `water_bodies: []`** | Helper clears BOTH surfaces in lockstep (deliberate customer/tech wipe). Close-gate rejects with the same 422 detail as an empty single-body report — that's the desired semantic. |

## Tester runbook (curl recipes)

The full acceptance matrix is covered by the pytest fixture at
`backend/tests/test_chemistry_gate_backend.py` (no HTTP round-trip
needed — tests run against the shared helpers directly). For an
interactive smoke against the live preview backend:

```bash
API=$(grep REACT_APP_BACKEND_URL /app/frontend/.env | cut -d '=' -f2)
TOK=$(curl -s -X POST "$API/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@aquaterra.com","password":"password123"}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

# 1. Pick a job with an existing service_report (any pool job).
JID=$(curl -s -H "Authorization: Bearer $TOK" \
  "$API/api/jobs?status=in_progress&limit=1" \
  | python3 -c 'import sys,json;d=json.load(sys.stdin)
items = d if isinstance(d, list) else d.get("items") or d.get("jobs") or []
print(items[0]["id"] if items else "")')

# 2. PATCH without water_bodies → persisted value preserved.
curl -s -X PATCH "$API/api/service-reports/$JID" \
  -H "Authorization: Bearer $TOK" \
  -H "Content-Type: application/json" \
  -d '{"notes":"tech visited"}'
# Confirm: GET the report and verify water_bodies unchanged.

# 3. PATCH with explicit water_bodies: [] → clears both surfaces.
curl -s -X PATCH "$API/api/service-reports/$JID" \
  -H "Authorization: Bearer $TOK" \
  -H "Content-Type: application/json" \
  -d '{"water_bodies":[]}'

# 4. PATCH with a structured multi-body payload → mirror rebuilt.
curl -s -X PATCH "$API/api/service-reports/$JID" \
  -H "Authorization: Bearer $TOK" \
  -H "Content-Type: application/json" \
  -d '{"water_bodies":[
        {"id":"b1","type":"pool","readings":[
          {"key":"free_chlorine","value":2.5,"unit":"ppm"},
          {"key":"total_chlorine","value":2.6,"unit":"ppm"},
          {"key":"ph","value":7.4},
          {"key":"alkalinity","value":90,"unit":"ppm"},
          {"key":"cyanuric_acid","value":40,"unit":"ppm"}
        ]}
      ]}'
# GET the report; verify chemical_readings is a 5-entry flat list.

# 5. Attempt to close the job via web PUT (structured readings only,
# empty flat mirror). Expect 200 — the multi-body fallback fires.
curl -s -X PUT "$API/api/jobs/$JID?status=completed" \
  -H "Authorization: Bearer $TOK"

# 6. Attempt to close with both surfaces empty → 422 with
# ``chemistry_core_readings_missing`` + 5 missing_fields.
```

## Test-suite status

* **Pytest** `test_chemistry_gate_backend.py`: **10 passed** in 0.5 s
  (all 5 acceptance criteria + shared-import guard + validator
  regression + no-op noop-path + explicit-empty-clear).
* Adjacent suites regressed: `test_service_report_multi_body.py`
  (16 + 1 skipped) + `test_chemical_usage_events_water_body.py`
  (8) + `test_job_edit_window.py` (many) +
  `test_gps_auto_start_p37a.py` + `test_public_quote_attachments.py`
  all still green — **34 passed** across those files in 10.9 s.
* Pre-existing failures in `test_chemistry_required_readings_gate.py`
  + `test_service_report_submit_hardening.py` (7 tests) are NOT
  caused by this dispatch — they fail on baseline too
  (`submit_service_report()` signature drift — `background_tasks`
  + `request` positional args added upstream). Flagging for a
  separate housekeeping pass.
* **Runtime**: `curl /api/openapi.json` → **paths = 1735**
  unchanged (no route surface added or removed — this ship is
  pure helper refactor + gate fallback).

## Out of scope

* Any mobile-side change — mobile team handles that.
* Any frontend/web change.
* The 7 pre-existing `submit_service_report` signature-drift test
  failures — separate housekeeping pass.
* Any unrelated job-endpoint refactor.
