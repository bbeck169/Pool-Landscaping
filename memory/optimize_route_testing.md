# Optimize Route — Preview-Pod Test Fixture

**Script:** `backend/scripts/seed_optimize_route_fixture.py` (idempotent).
**Endpoint under test:** `POST /api/schedule/optimize-route`

## Current fixture (auto-recomputed on every run)

| Field | Value |
|-------|-------|
| Date (yyyy-mm-dd) | **2026-09-09** — always `today + 14 days` (outside the 1–10 day window used by `test_route_optimization_approval.py` fixtures, so we never pollute CI). |
| Tenant | Pool & Landscaping of Vistancia (`affdfbfa-88b9-4baa-ae45-2ef78531b6e4`, slug `aquaterra`) |
| Technician user id | `0b8784ff-6204-47bb-8049-23338d19b631` (`mike@aquaterra.com` — Mike Rivera) |
| Job ids | `seed-opt-1`, `seed-opt-2`, `seed-opt-3`, `seed-opt-4` |
| Customer id | `seed-optimize-route-customer` (auto-upserted) |

### Stops

| Job id | Local start | Address | (lat, lng) |
|--------|-------------|---------|------------|
| `seed-opt-1` | 08:00 MST | 1234 W Vistancia Blvd, Peoria, AZ 85383 | (33.7734, −112.2378) |
| `seed-opt-2` | 09:30 MST | 6825 W Bell Rd, Glendale, AZ 85308 | (33.6389, −112.2016) |
| `seed-opt-3` | 11:00 MST | 2800 N 15th Ave, Phoenix, AZ 85021 | (33.4823, −112.0916) |
| `seed-opt-4` | 13:00 MST | 4155 N 44th St, Phoenix, AZ 85018 | (33.4948, −111.9840) |

The Peoria → Glendale → Phoenix → Scottsdale-adjacent spread was picked
so that a pure-Haversine ordering and a real Google Directions ordering
diverge meaningfully (differing right-turn / freeway routing on the
final Phoenix pair).

## How to run

```bash
# Live seed:
python3 backend/scripts/seed_optimize_route_fixture.py

# Dry-run — logs what would change without touching Mongo:
python3 backend/scripts/seed_optimize_route_fixture.py --dry-run
```

Behaviour:

* **Tenant discovery** — `slug=aquaterra`, falling back to the pod's only
  tenant when there is exactly one (fresh dev container). Bails with a
  helpful message on any other pod so it never writes to the wrong org.
* **Technician** — pinned via `email=mike@aquaterra.com`, falling back
  to any user with `role="technician"` in the resolved tenant.
* **Idempotent** — 2nd+ runs `$set` on the same doc ids (never
  duplicate rows). Re-running rotates `scheduled_date` /
  `scheduled_start` to today+2 so the fixture never rots.

## How to exercise the endpoint

```bash
API=$(grep REACT_APP_BACKEND_URL frontend/.env | cut -d= -f2)
TOKEN=$(curl -s -X POST "$API/api/auth/login" \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@aquaterra.com","password":"password123"}' \
  | python3 -c "import sys, json; print(json.load(sys.stdin)['access_token'])")

curl -s -X POST "$API/api/schedule/optimize-route?user_id=0b8784ff-6204-47bb-8049-23338d19b631" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"date":"2026-09-09"}' | python3 -m json.tool
```

### Expected response contract

Locked by:

* `routers/route_optimization.py` — docstring on `optimize_route`.
* `backend/tests/test_route_optimizer_response_contract.py`.
* `backend/tests/test_route_optimization_google_directions.py`.

```jsonc
{
  "ordered_job_ids": ["seed-opt-1", "seed-opt-2", "seed-opt-3", "seed-opt-4"],
  "total_distance_m": 96234.5,
  "total_duration_s": 8102,
  "legs": [ /* pairwise legs (from_job_id, to_job_id, distance_m, duration_s, polyline) */ ],
  "cached": false,
  "algorithm": "directions_v2+orion_bias" /* or "haversine_fallback" */,
  "warnings": [ /* ORION notes on Google path; fallback banner text on failure */ ],
  "date": "2026-09-09",
  "waypoints_hash": "…",
  "tenant_id": "affdfbfa-…",
  "user_id": "0b8784ff-…",
  "computed_at": "…"
}
```

### Algorithm-string branches to verify

| `algorithm` | When |
|-------------|------|
| `"google_directions"` | Google returned a route AND ORION added no warnings (rare — the ZIP pass usually emits at least an informational warning). |
| `"directions_v2+orion_bias"` | Google returned a route AND ORION appended ≥1 warning (applied a swap or skipped for missing ZIP data). **Default on this fixture.** |
| `"haversine_fallback"` | Google unavailable / errored — `warnings` contains "Directions unavailable — using Haversine fallback. Review order manually." Reproduce locally by unsetting `GOOGLE_MAPS_API_KEY` in `backend/.env` and restarting supervisor. |
| `"trivial"` | <2 geocoded stops (not reachable with this fixture). |
