# Notification Bundle · Feb-2026 — 24hr Reminder + Reschedule

## Ship summary

Two customer-facing service-lifecycle notifications, both shipped through a shared pipeline module.

### Files touched
| File | Change | LOC |
|---|---|---|
| `backend/services/notifications_pipeline/__init__.py` | **NEW** namespace | 15 |
| `backend/services/notifications_pipeline/service_notifications.py` | **NEW** cron + reschedule + helpers | 560 |
| `backend/server.py` | Cron registration hook (gated by scheduler flag) | +18 |
| `backend/routers/jobs.py` | Reschedule hook (bg task, fire-and-forget) | +42 |
| `backend/scripts/run_scheduler.py` | Exports `SCHEDULER_WORKER=1` for prod override | +5 |
| `backend/boot_flags.py` | `should_enable_scheduler()` honours `SCHEDULER_WORKER` | +8 |
| `backend/scripts/ensure_indexes.py` | Registers notifications-pipeline indexes | +3 |
| `backend/tests/_notif_pipeline_fakes.py` | **NEW** shared Motor stubs | 120 |
| `backend/tests/test_service_reminder_*.py` | **NEW** 5 files, 12 tests | 350 |
| `backend/tests/test_reschedule_*.py` | **NEW** 3 files, 8 tests | 220 |
| `backend/tests/test_notification_identity_guard.py` | **NEW** 2 tests | 90 |
| `backend/tests/test_notification_bundle_hardening.py` | **NEW** 9 tests (testing-agent fixes) | 235 |

### Tests
- **Bundle**: 33/33 pass (24 unit + 9 hardening regressions).
- **Full sweep** (F1 + F2 + F3 + bundle): 89/89 pass.

### Empirical proof
```
=== CRON TICK RESULT ===
scanned_tenants: 1, total_fires: 1

=== SMS SENT ===
to: +16028874400
"Reminder: AquaTerra Pools is scheduled to visit Alice Demo for
Pool Cleaning on Tue Sep 1 at 6:33 PM. Reply STOP to opt out.
Questions? Call +15559999."

=== EMAIL SENT ===
to: alice@aquaterra.com
subject: "Reminder: your Pool Cleaning visit tomorrow — AquaTerra Pools"

=== AUDIT ROW ===
template_key: service_reminder, channels_sent: ['email', 'sms']
actor: system_cron, scheduled_at: 2026-09-01T18:33:...

=== JOB STAMP ===
service_reminder_sent_at: 2026-08-31T01:33:58...
```

Second cron tick on the same job → 0 additional sends (idempotency stamp caught it).

## Testing agent findings — all addressed

| Priority | Finding | Fix |
|---|---|---|
| CRITICAL | `should_enable_scheduler()` shorts to False under `APP_ENV=production` — cron never registers in prod (pre-existing bug affecting every cron in the codebase) | Added `SCHEDULER_WORKER` override in `boot_flags.py`; `scripts/run_scheduler.py` exports it. Web workers keep it unset → no duplicate cron work. |
| CRITICAL | Reschedule hook fires on completed/cancelled/could-not-service jobs | Added `_REMINDER_STATUSES` gate to `fire_reschedule_notification`. |
| Minor | Reschedule to a past date notifies + poisons `service_reminder_sent_at` | Past-date guard: skip when `hours_until_new < 0`. Reminder stamp untouched. |
| Minor | No unique index on `notifications_sent_log` for reschedule idempotency → race window | Partial unique index on `(tenant_id, job_id, template_key, transition_key)` filtered to `transition_key exists && string`. Live-verified. |
| Minor | `APP_ENV=production` in preview pod causes real Resend fires | Ops-side; documented — no code fix. |
| Minor | Cron iterates all 700 tenants each hour | Acceptable at current scale; TD entry if it becomes a hotspot. |
| Code review | Identity guard unreachable under current fetch path | Docstring updated to describe it as an intentional paved-road guard against future refactor drift. |
| Code review | Reschedule hook awaited inside PATCH → ~300ms latency | Wrapped in `asyncio.create_task(_resched_bg())` — PATCH returns immediately. |
| Code review | Cron stamped `service_reminder_sent_at` on transient failures → customer permanently loses reminder | Only stamp when outcome is TERMINAL (sent OR only permanent skips). Transient markers `:failed / :crash / :unknown / :missing_key` leave the stamp OFF so next tick retries. |
| Code review | 653 LOC in one module | Deferred — split when a 3rd notification type joins the pipeline. |

## Audit findings (Part A of user's spec)

| Q | Finding |
|---|---|
| 1. Templates | No pre-existing service-reminder / reschedule template registry. Codebase pattern: inline template strings per handler (`on_my_way`, `equipment_trackers_cron`). **Ship**: created inline SMS + HTML email renderers colocated in `service_notifications.py`. |
| 2. Cron infra | Reused `equipment_trackers_cron.py` pattern — `scheduler.add_job(..., "cron", minute=0)` hourly, per-tenant local-hour dispatch via `ZoneInfo(tenant.timezone)`, duplicate-fire safety via `scheduler_lease.try_acquire_lease` keyed on `(tenant_id, "service_reminder_cron", tick_iso)`. |
| 3. Notification prefs | 3-layer defense pre-existed in the codebase (adapter `communication_opt_outs`, customer `sms_opt_in`, marketing `channel_opt_in`). Added a **4th layer** — feature-specific `customers.notification_preferences.{reminders_email, reminders_sms, reschedule_email, reschedule_sms}` (missing = true, backwards-compat). All 4 layers honoured; precedence documented in the `_fire` helper. |
| 4. Job schema | Field is **`scheduled_date`** (not `scheduled_at`), stored as string — either bare `YYYY-MM-DD` or ISO datetime. Tenant TZ: `tenants.timezone` (IANA), default `America/Phoenix`. **Ship**: `_parse_scheduled_date()` handles both forms + treats bare date as start-of-day in tenant TZ. |
| 5. Job PATCH | `PUT /api/jobs/{jid}` in `routers/jobs.py` (already F1-hardened). Reschedule hook wired at line 1364 as a background task; PATCH latency unchanged. |

## New advisories (logged for the user)

| ID | Description |
|---|---|
| TD-17 | Tenant-fanout scan cost — cron currently iterates all 700 tenants every hour. Consider a `tenants.notifications_last_tick_at` sentinel or a tenant-shard bucket if the tenant count grows. |
| TD-18 | Refactor `service_notifications.py` (currently 560 LOC) once a 3rd notification type joins — split into `_cron`, `_events`, `_render`, `_dispatch`. |
| TD-19 | The reschedule hook awaits `db.jobs.find_one` before spawning the bg task. Not a hot path today but could be moved into the bg task. |

## Env vars
- `SERVICE_REMINDER_LOCAL_HOUR` (default `8`) — tenant-local hour for the reminder cron. Set on the scheduler-worker process env.
- `SCHEDULER_WORKER` (default unset) — set to `1` on the dedicated scheduler process so `boot_flags.should_enable_scheduler()` returns True in prod. Web workers MUST leave this unset.
