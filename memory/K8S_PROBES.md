# Phase F4 · Feb-2026 — k8s Liveness/Readiness Probe Split

## What each probe does

| Probe        | Path                | Checks                                  | Latency |
| ------------ | ------------------- | --------------------------------------- | ------- |
| Liveness     | `GET /health/live`  | Nothing — proves the Python process is alive. Returns 200 unconditionally. | < 5ms |
| Readiness    | `GET /health/ready` | Mongo ping (<500ms), F3 integrity state, critical migrations applied. Returns 503 with per-check `failures` list on any gate failure. | < 600ms typical |
| Legacy alias | `GET /health`       | Alias for liveness. Emits a deprecation warning once per process on first hit. Kept for anything still pointing at the old path. | < 5ms |
| `/api` mirrors | `GET /api/health`, `GET /api/health/live`, `GET /api/health/ready` | Same as the un-prefixed versions — for ingress paths that always inject `/api`. | matches |

All probe endpoints are **unauthenticated**, **rate-limit-exempt**, and reachable **before** the F3 boot integrity scan finishes (the scan sets a module-level `_F4_BOOT_INTEGRITY_STATE` flag that `/health/ready` reads; until it flips, readiness returns 503 with reason `boot_integrity_pending`).

## Recommended k8s config

```yaml
containers:
- name: backend
  livenessProbe:
    httpGet:
      path: /health/live
      port: 8001
    initialDelaySeconds: 5
    periodSeconds: 30
    timeoutSeconds: 3
    failureThreshold: 3
  readinessProbe:
    httpGet:
      path: /health/ready
      port: 8001
    initialDelaySeconds: 10
    periodSeconds: 15
    timeoutSeconds: 5
    failureThreshold: 6      # ~90s grace for F3 scan
  startupProbe:
    httpGet:
      path: /health/ready
      port: 8001
    initialDelaySeconds: 10
    periodSeconds: 10
    failureThreshold: 30     # 5-minute cold-start grace on big prod DBs
```

## Response shapes

### `GET /health/live` → 200
```json
{"status": "alive", "uptime_seconds": 42, "version": "dev"}
```

### `GET /health/ready` → 200 (all gates OK)
```json
{
  "status": "ready",
  "checks": {"mongo": "ok", "integrity": "ok", "migrations": "ok"},
  "uptime_seconds": 42,
  "dangling_refs_total": 0
}
```

### `GET /health/ready` → 503 (any gate failing)
```json
{
  "status": "not_ready",
  "checks": {"mongo": "ok", "integrity": "fail", "migrations": "ok"},
  "uptime_seconds": 42,
  "dangling_refs_total": 5215,
  "failures": [
    {"check": "integrity",
     "reason": "dangling_refs_present",
     "dangling_refs_total": 5215}
  ]
}
```

Other failure reasons ops will see:
- `boot_integrity_pending` — F3 scan hasn't stamped yet (normal for the first ~30-90s of cold boot on big prod DBs).
- `scan_error` — F3 scanner crashed. Ops should investigate; readiness stays 503 until fixed.
- `missing` (migrations) — a required migration marker hasn't completed. Current gate: `perf_customers_v1`. Add more to `_REQUIRED_MIGRATIONS` in `server.py` as they land.
- `mongo: fail` — Mongo `ping` did not return within 500ms. Usually a networking or credential issue.

## Interaction with the prod F3 recovery playbook

The prod F3 outage today has ~5215 dangling refs. With this probe split:

- **Liveness** stays 200 the entire time — pods will NOT crash-loop.
- **Readiness** stays 503 with `reason: "dangling_refs_present"` and `dangling_refs_total: 5215` in the payload — pods are correctly held out of the load balancer while the refs remain.
- Ops runs the F5 sentinel reset + Phase A test-tenant purge to zero the refs.
- Readiness flips to 200 as soon as the next scan completes or a manual `POST /api/admin/migrations/f5-leads-backfill/reset` refreshes the state.

Net: **no more crash-loops on integrity failures**. Pods sit healthy-but-out-of-rotation while ops does the correct manual work.

## Kill switch

`HEALTH_READY_INTEGRITY_CHECK=false` in the pod env → `/health/ready` bypasses ONLY the F3 gate (still requires Mongo pingable + migrations applied). Use this **only** during an emergency where:
- integrity refs are known-recoverable but a partial-degradation service must accept traffic first, AND
- ops has an active recovery window open.

Undo: set `HEALTH_READY_INTEGRITY_CHECK=true` (or delete the var) and restart the pod. The scan state is still tracked so `dangling_refs_total` in the response stays accurate — the switch only controls whether that count triggers 503.

## Rollback

- To revert to the single-endpoint model: remove the `/health/live` and `/health/ready` handlers in `backend/server.py` and the `_F4_BOOT_INTEGRITY_STATE` stamping in the F3 boot block. The legacy `/health` endpoint is untouched and will keep working.
- No schema changes to roll back.
- The probe manifest can be reverted to `path: /health` on both probes without any redeploy of the app (same 200 response as before).
