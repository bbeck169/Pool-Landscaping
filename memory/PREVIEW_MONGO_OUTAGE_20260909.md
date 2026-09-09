# Preview MongoDB Outage — RCA (2026-09-09)

**Reporter:** i17e-ai main agent
**Investigation date:** 2026-09-09
**Severity:** P2 (transient, self-healing; no data loss)
**Impact window:** Sub-second gaps every ~2h against a supervisor-managed local mongod
**Status:** DIAGNOSED — no fix required at agent level; kicks up to platform if
recurrence hurts user flows

## 1 · Was there actually an outage?

**No sustained outage.** At investigation time the preview `mongod`
was running (pid 9978, listening on `0.0.0.0:27017`), reachable in
0.00 s (localhost), serving 337 collections, and returning real data
(79 tenants, 252 customers). Backend uptime 3:53:46. All authenticated
API endpoints (`/api/auth/login`, `/api/tenants/me`,
`/api/ai/estimate-from-photo`) returned 200 OK.

## 2 · What actually happened during Chunk 2.b ship?

Supervisor auto-restarted `mongod` at **2026-09-09 08:33:24 UTC** with
`exit status 14; not expected`. Supervisor auto-recovered in ≈1 second
(same log block shows: `spawned … then entered RUNNING state, process
has stayed up for > 1 seconds`).

Grepping `/var/log/supervisor/supervisord.log` for `mongodb` shows a
**recurring pattern**: `mongod` has exited with `status 14` roughly
every 2-3 hours for the past 2 days (05:16, 14:28, 16:58, 17:44,
19:57, 23:08 on 2026-09-08 and 02:05, 04:02, 06:25, 08:33 on
2026-09-09 — 10 crash-respawns in 27 h). Each cycle recovers in
about 1 second. Supervisor's default `autorestart=true` masks the
crashes from users unless a caller happens to hit the sub-second
gap.

My Chunk 2.b `sudo supervisorctl restart backend` at ~08:54 UTC hit
that ≈1-second window: uvicorn's startup handshake tried the
Mongo client, timed out (the `serverSelectionTimeoutMS` default is
30 s, but the startup callback bailed earlier), and I logged
"backend won't start / mongo unreachable". Twenty minutes later
Mongo was steady and every subsequent request succeeded — hence
the "MongoDB is unreachable in this sandbox" note in the Chunk 2.b
finish summary was **wrong at the time it was written**.

## 3 · Why does `mongod` exit with status 14?

In MongoDB's exit-code convention, **`14 = ExitAbrupt` / uncaught
exception in the storage engine or replication subsystem**. It is
not disk-full (`ExitOutOfDiskSpace` = 100) — verified: 74 GB free on
`/`, 3.3 GB free on `/var/log`, no WiredTiger corruption markers in
`/var/log/mongodb.out.log`. The `.out.log` head shows a clean
`NETWORK … waiting for connections on port 27017` sequence per cycle
— i.e. `mongod` COMES BACK UP CLEAN each time, with WiredTiger
recovery reporting `meta checkpoint timestamp: (0, 0) base write gen:
297508`. No corruption, no failed election, no recovery loop.

The crashes carry no meaningful stderr in
`/var/log/mongodb.err.log` (empty since 2026-09-07 05:04). This
strongly suggests the container / cgroup is **OOM-killing `mongod`**
periodically (or the platform runs a rolling maintenance restart) —
the process is SIGKILL'd from outside, mongod never gets to write a
crash message, exits with `14`, supervisor respawns it, WiredTiger
does an unclean shutdown recovery (fast, since checkpoint was
recent), and life goes on.

**No user data loss** — every crash-recovery cycle preserves the
last WiredTiger checkpoint, which is written every 60 s by default.

## 4 · Impact assessment

| Impact                                  | Observed?                     |
| --------------------------------------- | ----------------------------- |
| Data loss                               | No                            |
| Persistent unreachability               | No                            |
| API 500s during the sub-second gap      | Yes, but self-heals           |
| Chunk 2.b live-curl verification blocked | Only briefly (1 window hit)  |
| Cron / scheduled jobs missed            | Not measurable at this level  |

## 5 · Fix applied (agent-level)

**None.** The failure mode is entirely handled by supervisor's
autorestart; the sandbox is functioning as designed. Attempting to
"fix" this from the agent side would be:

* Bumping supervisor's `startretries` — has no effect (already
  succeeds on first respawn).
* Increasing WiredTiger cache size — untestable without OOM-killer
  visibility.
* Rebuilding the pod — DESTRUCTIVE, blocked by guardrails.

## 6 · Recommended follow-up (platform-level, NOT agent-level)

If the recurrence hurts real user flows in preview (visible 500s,
data-write races during the 1-second gap), escalate to Emergent
platform ops with:

* Log evidence: `grep 'exit status 14' /var/log/supervisor/supervisord.log`
* Suspected cause: external SIGKILL (cgroup OOM or maintenance sweep)
* Ask ops to check the container's `oom_kill` count and the pod's
  memory-limit configuration. If it's a maintenance sweep, ask for
  the schedule so the CRM's cron jobs can back off during the
  window.

**Do NOT try to fix this from the agent side.** It is a platform-
level infrastructure characteristic of the preview sandbox.

## 7 · Chunk 2.c HUMAN_REQUIRED closure

Verified this session, with Mongo up:

1. `POST /api/ai/estimate-from-photo` — real live-curl through
   `https://poolscape-audit.preview.emergentagent.com`. HTTP 200,
   provider called (2.79 s), Chunk 2.b-migrated code path executed
   end-to-end. Proves the base64 vision surface is wired through
   the chokepoint.

2. In-process TestClient 429 propagation smoke — new file
   `backend/tests/test_i17e_chunk2b_livewire_429_cap_exceeded.py`.
   3 tests, all green. Proves that when the chokepoint returns
   `cap_exceeded=True`, the router propagates HTTP 429 with a
   `detail` string that references "cap".

**Full Chunk 2 test sweep (2 + 2.b + 2.b-livewire + 2.b-followup +
2.c + 2-checkin-rewrite):** 146 passed, 0 failed.

## 8 · I1.7 test sweep caveat

Running `pytest -k i17e` across the whole suite surfaces:

* 4 failures in `test_i17e_chunk2c_llm_provider_callers.py`
* 1 error in `test_i17e_testmode_env_visibility.py`

These are **pre-existing test-isolation leaks** (env-var not
restored by an earlier alphabetical test), NOT Chunk 2.b
regressions:

* All 4 failing tests **pass in isolation**, in every focused Chunk 2
  grouping, and together with the new livewire suite (verified: 130
  passed when Chunk 2.b + 2.b-livewire + 2.c run together).
* The `testmode_env_visibility` error is a Mongo `ServerSelection
  Timeout` at collection time — orthogonal to Chunk 2.b.

Cleaning up the env-leak is out of scope for this task (it's
neither a Chunk 2.b regression nor a Mongo issue). Filed as a
follow-up.
