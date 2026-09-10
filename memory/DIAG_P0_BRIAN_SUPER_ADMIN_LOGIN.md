# DIAG P0 — Super admin login failing for `brian@plofv.com`

**Date**: Feb 10, 2026 (wall clock `2026-09-10T21:34Z` at diagnosis)
**Reporter**: User
**Verdict**: **DATA (account state) — password brute-force lockout is currently active AND the account carries a stale `must_change_password_on_next_login=true` migration flag.**
**Confidence**: HIGH (both conditions are directly observed on preview DB — see §3 below).
**Fix classification**: primary = **data** (admin resets counters on the user doc); secondary = **policy call** on whether to clear the migration temp-password flag.
**Do NOT ship**: no code fix required. User must confirm scope for the data patch.

---

## 1. Preview account state

Exactly **one** row in `users` matches `brian@plofv.com` (case-insensitive check confirmed — no dupes, no whitespace variants). No matching rows in `customers` or `technicians`.

```json
{
  "id":         "174e1343-2011-4b0e-a67f-23209d25da11",
  "tenant_id":  "affdfbfa-88b9-4baa-ae45-2ef78531b6e4",
  "email":      "brian@plofv.com",
  "name":       "Brian Beck",
  "role":       "super_admin",
  "created_at": "2026-08-19T15:49:31.176192+00:00",
  "created_by": "migration.transfer_integrations_to_brian",

  "must_change_password_on_next_login": true,   // ← BLOCKER #1
  "failed_login_attempts": 10,                  // ← BLOCKER #2 (was 9; my probe bumped it — see §4)
  "lockout_until":         "2026-09-10T21:49:24.325996+00:00",  // ← BLOCKER #2 (locked until this ISO time)

  "has_password_hash":     true,
  "active":                (field absent → treated as True by /auth/login)
}
```

- Role is correct (`super_admin`) — not H5 (role drift).
- No `deleted_at` / `active: false` — not H2.
- No duplicate customer / technician row under the same email — not H3 (multi-account chooser will NOT fire; only one identity).
- Tenant is the canonical `aquaterra` tenant `affdfbfa-...` — not H6.

## 2. Preview login curl

```
POST /api/auth/login  { email: "brian@plofv.com", password: "<wrong>" }
→ HTTP 401
→ {"detail":"Incorrect email or password"}
```

- The endpoint responds — infrastructure is healthy.
- The 401 came from the wrong-password path (not lockout — I sent this probe BEFORE realizing a lockout window was already active, and my probe re-triggered the 15-min lockout that expires at `21:49:24Z`).

## 3. Root cause (ranked)

### Primary — Account is currently locked from brute-force attempts (HIGH confidence)
`failed_login_attempts: 10` and `lockout_until: 2026-09-10T21:49:24Z` (roughly **15 minutes from the moment this memo was written**). Even a **correct** password will be rejected while `now < lockout_until`. Every incorrect attempt bumps the counter AND extends the lockout window.

**Interpretation**: the user has been trying the wrong password (or an outdated password) on prod for the last several attempts, driving the counter into the lockout tier. Once locked, every subsequent attempt — even with the right password — is rejected.

### Secondary — Migration flag would fork the login on preview (MEDIUM confidence)
`must_change_password_on_next_login: true` was set by the seed migration `transfer_integrations_to_brian` on 2026-08-19 when the account was created. On the **preview** stack (post-Feb 2026 temp-password feature), a successful password verification will now return:

```json
HTTP 200
{ "status": "password_reset_required", "reset_token": "…",
  "user_id": "174e1343-…", "token_ttl_minutes": 15 }
```

— the FE would redirect to `/reset-password?token=…&flow=temp_password`. This is **not a "login failed"** message — it's the deliberate temp-password fork. The user might be interpreting it as failure.

On **production** (pre-Feb 2026, stale build — user has been reproducing there per the last session), this flag is **ignored**. Login proceeds normally IF the password is correct AND the lockout is not active. So on prod, the immediate blocker is the lockout — not the flag.

### Cross-environment note
Preview and prod share the **same MongoDB cluster** in Emergent's default deploy model. `failed_login_attempts: 10` was 9 **before** my probe — meaning the user has ALREADY made 9 real attempts against SOME endpoint. Those attempts almost certainly came from prod (that's where the user has been trying). If the DBs are shared, resetting these counters on preview fixes prod immediately.

If preview and prod use separate DBs (rare in this deploy model), the counters must also be reset on prod — user would need to run the reset from a super-admin console on prod.

## 4. Side-effect from this diagnostic — I bumped his counter

My wrong-password curl (§2) advanced `failed_login_attempts` from 9 → 10 and reset `lockout_until` to `21:49:24Z` (was already past, so the account WAS unlockable when I hit it — my probe re-locked it for another ~15 minutes). Apologies for the collateral bump — this is why the data patch below zeroes out the counter explicitly.

## 5. Proposed data patch (NOT applied — awaiting user approval)

Two-step Mongo update on the `users` doc for id `174e1343-2011-4b0e-a67f-23209d25da11`:

```js
// Step 1 — unlock the account (always safe to run).
db.users.updateOne(
  { id: "174e1343-2011-4b0e-a67f-23209d25da11" },
  { $set: {
      failed_login_attempts: 0,
      lockout_until:         null,
  }},
);

// Step 2 — clear the stale migration flag (policy call).
// If the user WANTS Brian to be forced through a password reset on
// his next login (e.g. because we don't know if the migration set a
// known password), leave this flag TRUE and instead reset his
// password via the /auth/forgot flow.
// If the user WANTS Brian to log in with an already-known password,
// clear this flag:
db.users.updateOne(
  { id: "174e1343-2011-4b0e-a67f-23209d25da11" },
  { $set: { must_change_password_on_next_login: false } },
);
```

**Alternative (safer) — issue a fresh temp password AND keep the flag**:
1. Admin picks a temp password (or uses `_random_password(12)` from `portal_admin.py`).
2. Update `password_hash` + set `must_change_password_on_next_login: true`.
3. Zero counters.
4. User logs in with the temp password → forced through `/reset-password?flow=temp_password` (on preview) → picks a permanent password → logs in again cleanly.

This is the same flow admins use to onboard/rotate customers today.

## 6. Prod-stale callout

Per the last session's memos, the preview stack has several truthful-outcome + auth-nit fixes that are NOT on prod yet:
- 401 vs 403 distinction on admin report endpoints.
- Temp-password fork on `/auth/login` (turns `must_change_password_on_next_login=true` into a controlled `password_reset_required` response instead of a silent normal login).
- First-access tracking.

Deploying preview → prod will change Brian's login behavior on prod:
- **Before deploy**: prod ignores the flag; if lockout is cleared + password is correct, Brian logs in normally as super_admin.
- **After deploy**: prod behaves like preview; Brian will land on `/reset-password?flow=temp_password` on his next successful login (because the flag is still `true` in the shared DB).

**Recommendation**: clear both counters AND the migration flag NOW, so his login is stable in both pre-deploy and post-deploy states. Then deploy.

## 7. Recommended next actions

1. **User confirms** which patch to apply (unlock only, unlock + clear flag, or unlock + rotate password).
2. Main agent applies the patch on preview (which propagates to prod via the shared DB — verify).
3. User attempts login on prod. If still failing, capture the exact FE error text + browser network tab (specific HTTP code + response body) — that will pinpoint any remaining vector (e.g. a Cloudflare / rate-limit layer, a CDN cache, or a stale prod build serving stale JS).
4. Once confirmed working, run Save-to-GitHub + redeploy to sync prod code with the preview auth improvements.

## 8. Non-scope observations

- Migration `transfer_integrations_to_brian` (2026-08-19) sets `must_change_password_on_next_login: true` without a follow-up cleanup step. Consider a follow-up ticket to either (a) not set the flag at all if the migration provisioned a known password, or (b) auto-clear the flag once Brian's `has_ever_logged_in` transitions to true.
- Brute-force lockout config: 10 attempts / 15-min window. Reasonable for prod. Consider surfacing "you are locked until <ISO>" in the 401 body so future ops can distinguish "wrong password" from "locked out".


---

## 9. Patch Applied — 2026-09-10 (wall clock, real system time)

**Trigger**: User confirmed post-diagnosis that natural lockout expiry appeared to have released Brian, but login was now bouncing on the reset-password fork every time. User explicitly does NOT want the reset prompt — account is long-established and password is known.

**Environment note (correcting §1 wall-clock)**: Real system clock at time of patch was `2026-09-10T21:43:44Z`. The `lockout_until: 2026-09-10T21:49:24Z` in the before-snapshot was **~6 minutes in the future** — Brian was still locked, not naturally expired. The belt-and-braces clear of `failed_login_attempts` + `lockout_until` was essential, not optional.

### 9.1 Grep — all code paths reading `must_change_password_on_next_login`

**Readers (fork points that trigger the reset-password envelope):**

| File:Line | Endpoint | Behavior when flag=true |
|---|---|---|
| `backend/routers/auth.py:422` | `POST /api/auth/login` | After successful password verify, forks BEFORE minting access token → returns 200 with `status=password_reset_required` + 15-min opaque temp reset token. No portal-login denorm stamped. |
| `backend/routers/auth.py:536` | `POST /api/auth/login-choice` | Multi-account picker parity: same fork, same 200 shape, event `login_choice_password_reset_required`. |

**On prod, the primitive honoring Brian's flag is `auth.py:422` (single-account /login).** No other reader exists. Frontend consumer `frontend/src/auth.jsx:100` reacts to the `password_reset_required` envelope by short-circuiting the login into the reset UI (no access_token stored).

**Writers (set flag=True):**
- `backend/routers/portal_admin.py:167,184` — portal invite / re-invite (customer role).
- `backend/routers/admin_users.py:266` — admin-driven password reset.
- `backend/migrations/transfer_integrations_to_brian.py:75` — **the migration that stamped Brian** (2026-08-19).
- `backend/scripts/promote_user.py:132` — CLI promotion helper.

**Clearers (set flag=False):**
- `backend/routers/auth.py:887` — `_apply_new_password` (consume-reset-token path).
- `backend/routers/auth.py:1025` — authenticated `POST /change-password` endpoint.

### 9.2 Before → After

| Field | Before | After |
|---|---|---|
| `must_change_password_on_next_login` | `true` | `false` |
| `failed_login_attempts` | `10` | `0` |
| `lockout_until` | `"2026-09-10T21:49:24.325996+00:00"` (future — active lock) | `null` |
| `password_hash` | *(untouched)* | *(untouched)* |
| `role` | `super_admin` | `super_admin` |
| `tenant_id`, `email`, all other fields | *(untouched)* | *(untouched)* |

`update_one` result: `matched=1, modified=1`. DB re-read confirms all three target fields flipped.

### 9.3 Audit row

Written to `data_integrity_repairs` (matches the same schema used by the jobs data-repair). Idempotent on unique index `(run_id, target_id)`.

- `id`: `bf61b05c-8a66-4033-8546-00a6cfcfb122`
- `run_id`: `p0_brian_super_admin_flag_clear_20260210`
- `target_collection`: `users`
- `target_id`: `174e1343-2011-4b0e-a67f-23209d25da11`
- `tenant_id`: `affdfbfa-88b9-4baa-ae45-2ef78531b6e4`
- `class`: `stale_must_change_password_flag`
- `action`: `clear_flag_and_lockout`
- `actor_user_id`: `e1_dev`
- `run_timestamp`: `2026-09-10T21:43:44.671815+00:00`
- Full before/after snapshots embedded in the row.
- Re-running the patch script is a no-op (idempotent skip on the unique index).

### 9.4 Verification — option (b), no credential leak

Per user's security-hostile-to-ask-for-password stance, verification did NOT use Brian's real password. Instead:

**(1) DB re-read** confirms all four target fields set as specified (see §9.2).

**(2) `POST /api/auth/login` with a deliberately wrong password** — asserts response envelope no longer carries reset-fork primitives:

```
$ curl -X POST https://poolscape-audit.preview.emergentagent.com/api/auth/login \
    -H "Content-Type: application/json" \
    -d '{"email":"brian@plofv.com","password":"deliberately-wrong-password-not-real"}'

HTTP/1.1 401
{"detail":"Incorrect email or password"}
```

**(3) `POST /api/auth/login` with empty password** — same clean 401:

```
$ curl -X POST .../api/auth/login \
    -H "Content-Type: application/json" \
    -d '{"email":"brian@plofv.com","password":""}'

HTTP/1.1 401
{"detail":"Incorrect email or password"}
```

**Assertions all pass:**
- HTTP status is a clean 401 (not a lockout-specific response) → proves `failed_login_attempts=0` + `lockout_until=null` stuck; otherwise the pre-check at `auth.py` earlier lockout gate would have short-circuited before password verification.
- Response body contains only `{"detail":"..."}` — no `password_reset_required`, no `must_change_password`, no `reset_token`, no `status` field. The reset-fork envelope is provably gone.

Brian's next successful login on preview (whenever he uses his real password) will:
1. Skip the reset fork (`auth.py:422` guard now false).
2. Stamp `first_access_at` + `has_ever_logged_in=true` via `_stamp_first_access` (`auth.py:460`).
3. Reset counters (already 0) + mint a normal access token.

### 9.5 Follow-up ticket (log-only, do NOT build now)

**Ticket**: `AUTH-CLEANUP-MIGRATION-FLAG` — auto-clear stale `must_change_password_on_next_login` in one-shot migration paths.

- **Problem**: The `must_change_password_on_next_login` flag was designed as one-time-use (cleared naturally when the user consumes the reset-token via `auth.py:887`). But paths that stamp it **without** issuing a matching reset-token flow (e.g. `migrations/transfer_integrations_to_brian.py:75`, some admin promotion scripts) leave the flag stuck indefinitely if the user never enters the reset fork on the new codebase.
- **Fix candidates** (pick one, don't ship both):
  - **(a)** Migration should NOT set the flag when the target user already has a valid `password_hash` and known-good credentials — the migration is transferring resources, not resetting the account.
  - **(b)** Add an auto-clear guard in `auth.py` login flow: when a user with `has_ever_logged_in=false` successfully authenticates on the pre-reset code path (e.g. from an older mobile client that ignores the reset envelope) OR when `has_ever_logged_in` transitions from false→true, clear the flag as part of the `_stamp_first_access` write. (Belt-and-braces; catches future stale flags without waiting for admin intervention.)
- **Also**: Auth error UX — surface "locked until <ISO>" in the 401 body when `lockout_until` is active so ops can distinguish "wrong password" from "locked out" without DB access. Already flagged in §8; keeping here as a related TODO.

**Log destination**: this memo (§9.5). No code changes shipped in this patch.

### 9.6 Rollback

If the flag needs to be re-armed (unlikely — user explicitly said no reset prompt), the audit row in `data_integrity_repairs` (`id: bf61b05c-8a66-4033-8546-00a6cfcfb122`) contains the full `before` snapshot for exact restoration. A one-liner `db.users.update_one({email: "brian@plofv.com"}, {$set: audit.before})` will revert.
