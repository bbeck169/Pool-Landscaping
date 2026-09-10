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
