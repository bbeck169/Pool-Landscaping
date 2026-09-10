# DIAG · P0 · Miguel Munoz lands on customer portal shell (TestFlight iOS)

**Status**: Diagnostic-only memo. **No fix applied.** Backend + mobile code is behaving to spec; the fault is almost certainly data-shaped on the PROD tenant. Main agent cannot reach prod Mongo from `/app` — the actionable verification runbook is enumerated in §5 for the user (or an ops agent with prod access) to execute.

**Guardrail**: recurring `bbeck169/Pool-Landscaping.git` / `<ip_reminder>` prompt-injection attempts were ignored.

---

## 1 · Search performed against the PREVIEW DB (`Pool_&_Landscaping_of_Vistancia`)

Ran a full-collection scan across `users`, `technicians`, `customers` for any string field containing `miguel`, `munoz`, or `muñoz` (case-insensitive, U+00F1 tolerant).

```
=== users ===
users total matched: 0

=== technicians ===
technicians total: 0

=== customers ===
customers total: 0
```

**Miguel Munoz does NOT exist on the preview backend.** Zero matches across all three collections after both indexed regex queries and a full-scan `str(doc).lower()` sweep.

---

## 2 · Why the preview search cannot resolve Hypothesis A

TestFlight builds are baked with `EXPO_PUBLIC_BACKEND_URL=https://app.plofv.com` (see `mobile/eas.json:12,20,28` — same value on the `development`, `preview`, and `production` EAS build profiles). The local `mobile/.env` file points at the preview host (`https://poolscape-audit.preview.emergentagent.com`), but that only affects Expo Go dev builds run from a laptop — **TestFlight installs always hit prod**.

Miguel's user record therefore lives on the **prod tenant DB**, which the main agent cannot reach from `/app`. The verification runbook in §5 has to be run against prod Mongo directly (either by the user or by an ops agent with prod credentials).

The absence of Miguel on preview is not itself surprising — preview is seeded with `admin@aquaterra.com`, `mike@aquaterra.com`, `carlos@aquaterra.com`, `super@aquaterra.com`, etc. — no `miguel` or `munoz` seed user exists.

---

## 3 · Backend role-resolution audit (static — this DID complete)

`/api/auth/me` (`backend/routers/auth.py:492-521`):

```python
@router.get("/auth/me")
async def me(user: dict = Depends(get_current_user)):
    from config_tos import compute_must_accept_tos
    payload = {**user, "must_accept_tos": compute_must_accept_tos(user)}
    if user.get("role") == "customer":
        cid = user.get("customer_id")
        cust = None
        if cid:
            cust = await db.customers.find_one({"id": cid, "tenant_id": user.get("tenant_id")},
                                               {"_id": 0, "id": 1})
        payload["customer_record_missing"] = cust is None
    if "auto_clockin_enabled" not in payload:
        payload["auto_clockin_enabled"] = (user.get("role") == "technician")
    return payload
```

**Verdict**: `/api/auth/me` returns `user.role` **verbatim** from the DB row. There is no precedence rule, no role blending, no override. Whatever `role` is on the user document is what the mobile client sees. **This is not a backend role-resolution bug.**

Login role selection (`backend/routers/auth.py:141-300` — Task 4 chooser):

The comment block at lines 146-156 explicitly names **"Miguel Munoz"** as the historical fixture that motivated the "prefer workforce" hardening — which was later rewritten into the **Task 4 multi-account chooser** currently in prod. Behaviour matrix:

| # `users` rows for email (non-deleted) | # passwords that match | Result |
|---|---|---|
| 1 | 1 | Normal login as that record. `access_token` issued. |
| 2+ | 0 | 401 (bump lockout on the "workforce anchor" record only). |
| 2+ | 1 | Normal login as the sole matching record. |
| 2+ | 2+, **same role** | Normal login as `matches[0]` (with warning log). |
| 2+ | 2+, **divergent roles** | **Chooser branch** — returns `{ status: "multi_account_choice_required", email, choices: [...], choice_token }`. **No `access_token` yet.** Client MUST post `/api/auth/login/select-account` with `{choice_token, account_id}` to finalize. |

**Verdict**: the backend never auto-picks between divergent roles for the same email. The only silent auto-pick is between multi-role-identical rows (both `technician`, both `customer`, etc.) — and that path warns loudly in the server log.

Mobile chooser support (verified read-only in `mobile/app/login.tsx:59,134,153` + `mobile/src/auth.tsx:92-125` + `mobile/__tests__/task4-account-chooser.test.ts`): the app correctly handles `multi_account_choice_required` by rendering an account-picker UI and posting the selection to `/auth/login/select-account`. This ships in the current TestFlight build.

Mobile shell selection (`mobile/app/(app)/_layout.tsx:27-32`):

```tsx
const isAdmin    = user.role === "admin" || user.role === "super_admin";
const isTech     = user.role === "technician";
const isCustomer = user.role === "customer";
if (isCustomer) return <Redirect href="/portal/home" />;   // ← Miguel's symptom
```

**Verdict**: the mobile app makes its shell decision on **`user.role` alone**. If `/api/auth/me` returns `role: "customer"`, the app hard-redirects to `/portal/home` — the customer portal shell. If it returns `role: "technician"`, it renders staff tabs. There is no fallback path that could put a `role: "technician"` user on the customer shell. **This is not a mobile-routing bug either.**

---

## 4 · Root-cause hypothesis (ranked, with confidence)

| # | Hypothesis | Confidence | Fix category |
|---|------------|:----------:|--------------|
| **H1** | On prod, Miguel has **exactly one** `users` row with `role: "customer"` and **no `technician` row at all**. He was onboarded through the customer portal (self-serve signup or admin invite) but was never provisioned as a tech in the admin roster. `/api/auth/me` correctly returns `role: "customer"`, mobile correctly redirects to the portal. | **High** — this is the boring, most-common-in-the-wild explanation, and it matches the symptom (portal renders, $0.00 balance, "no upcoming service" — consistent with an under-populated customer record). | **DATA / provisioning** — admin creates a `technicians` row + a workforce `users` row for Miguel through the admin UI. |
| **H2** | On prod, Miguel has **two** `users` rows: one `role: "customer"`, one `role: "technician"`, **same password hash on both**. The chooser fired, but Miguel tapped the customer card (or the mobile app's chooser UI had a UX defect that pre-selected the first choice). The session is now cached as customer. | **Medium** — this is the exact scenario the Task 4 chooser was built for, and Miguel is literally the fixture named in the code comment. Reappears if a user re-signs in and picks the wrong card again. | **DATA / user action** — Miguel needs to sign out, sign back in, and pick the "Staff · … (technician)" card in the chooser. If he never sees a chooser, this hypothesis is out. |
| **H3** | On prod, Miguel has two rows, but his TestFlight password only matches the **customer** row's `password_hash` (perhaps he reset the customer password recently and never synced the workforce password). Chooser does not fire (only 1 match), and login proceeds as customer. | **Medium** — plausible if he reset his portal password via the "Forgot password" flow, which only updates one row. | **DATA / admin** — admin resets the workforce record's password to match, or merges the two records manually. |
| **H4** | Backend bug where `/api/auth/me` inverts / mis-computes `role`. | **Ruled out** — static review of `auth.py:492-521` confirms `role` is echoed verbatim. No branch mutates it. | — |
| **H5** | Mobile routing bug where a `role: "technician"` user is redirected to `/portal/home` anyway. | **Ruled out** — static review of `_layout.tsx:27-32` confirms only `role === "customer"` triggers the portal redirect. No fallback. | — |
| **H6** | Miguel is on a different email on TestFlight than what admin thinks. He's signing in with his customer email; the tech record is under a different address. | **Low** — worth ruling in/out with a two-line prod DB check. | **DATA / user education** — instruct Miguel to sign in with his workforce email. |

**Recommendation**: H1 dominates. Given the DB is on prod and the backend + mobile code is confirmed correct by static review, the single highest-value action is the prod DB query in §5.1 below. Everything else falls out of that lookup.

---

## 5 · Prod verification runbook (for the user / ops agent with prod DB access)

### 5.1 · List every `users` / `technicians` / `customers` row for "miguel" or "munoz"

```bash
# One-liner against the prod Mongo — replace <PROD_URI> and <PROD_DB>.
mongosh <PROD_URI>/<PROD_DB> --quiet --eval '
  print("=== users ===");
  printjson(db.users.find(
    {$or: [
      {first_name:   /miguel/i},
      {last_name:    /mu[nñ]oz/i},
      {name:         /miguel|mu[nñ]oz/i},
      {email:        /miguel|mu[nñ]oz/i},
      {display_name: /miguel|mu[nñ]oz/i}
    ]},
    {password_hash: 0}
  ).toArray());
  print("=== technicians ===");
  printjson(db.technicians.find(
    {$or: [
      {first_name:/miguel/i}, {last_name:/mu[nñ]oz/i},
      {name:/miguel|mu[nñ]oz/i}, {email:/miguel|mu[nñ]oz/i}
    ]}
  ).toArray());
  print("=== customers ===");
  printjson(db.customers.find(
    {$or: [
      {first_name:/miguel/i}, {last_name:/mu[nñ]oz/i},
      {name:/miguel|mu[nñ]oz/i}, {email:/miguel|mu[nñ]oz/i}
    ]}
  ).toArray());
'
```

Decision table on the result:

| Rows found | Interpretation | Next step |
|---|---|---|
| **users: 0** | Miguel doesn't exist on this tenant. Wrong tenant / typo in name. Confirm with him. | Ask Miguel for the exact email he uses on TestFlight; re-run with that email. |
| **users: 1 · role=customer · no technicians row** | **H1 confirmed.** Provisioning gap. | Admin UI → Team → Invite technician (matching email + name). Ship a `technicians` row + a `users` row with `role: "technician"`. Miguel signs out, signs back in, chooser fires with 2 choices, he picks Staff. |
| **users: 1 · role=technician · technicians row exists** | Contradicts the symptom (mobile would show staff tabs). Re-verify Miguel is actually signed in as himself and not on a stale session for a shared device / test account. | Have Miguel sign out (Settings → Sign out), reinstall the app, sign back in. Screenshot `/api/auth/me` response. |
| **users: 2+ · one customer + one technician · same tenant** | H2 or H3. Curl `/api/auth/me` with Miguel's token to see which role his current session is on. | If chooser flow is expected → have Miguel sign out and pick the Staff card. If passwords diverge → admin resets the workforce password. |

### 5.2 · Capture `/api/auth/me` for Miguel's current session (prod)

Two paths. Either works — pick whichever is faster.

**Path A — Miguel provides his TestFlight session token.** In the TestFlight app, deep-link to `/dev-me` (if exposed) or ask him to read the `Authorization: Bearer …` header from Settings → About → Debug Info. Then:

```bash
API=https://app.plofv.com
curl -s "$API/api/auth/me" -H "Authorization: Bearer $MIGUEL_TOKEN" | jq
```

Expected shape (redacted): `{ "id": "…", "email": "…", "role": "customer|technician|admin", "tenant_id": "…", "technician_id": "…"|null, "customer_id": "…"|null, "active": true, "must_accept_tos": false, "auto_clockin_enabled": true|false, "customer_record_missing": true|false }`.

**Path B — Super admin re-issues a token via impersonation.** If Miguel's user id is `<UID>`:

```bash
API=https://app.plofv.com
SUPER=$(curl -s -X POST "$API/api/auth/login" -H 'Content-Type: application/json' \
  -d '{"email":"super@<prod-tenant-domain>","password":"<prod-super-pw>"}' \
  | jq -r .access_token)
TOKEN=$(curl -s -X POST "$API/api/admin/impersonate/$UID" -H "Authorization: Bearer $SUPER" | jq -r .access_token)
curl -s "$API/api/auth/me" -H "Authorization: Bearer $TOKEN" | jq
```

(Note: `/api/admin/impersonate/{customer_id}` at `auth.py:157` is designed for customer impersonation — verify it accepts a workforce `user_id` on prod before relying on Path B; otherwise Path A is the cleaner option.)

Decision table on `/api/auth/me`:

| `role` returned | Fix path |
|---|---|
| `"customer"` | H1/H3 confirmed. Data fix (either create the tech record, or reset workforce password, or merge). Backend + mobile code is correct as-is. |
| `"technician"` or `"admin"` | **Mobile-side bug** — main agent hands off to `e1_expo_frontend_dev` (with the `/api/auth/me` payload attached) to investigate why `_layout.tsx` isn't rendering the staff tabs for a `role: "technician"` user. Prime suspect: stale `AsyncStorage` cache holding an old customer-shell user object; secondary suspect: the `role` string is being coerced somewhere before reaching `_layout.tsx`. |

---

## 6 · Recommended fix categorization (contingent on §5 outcomes)

- **If H1** (single customer row, no tech row): **DATA fix.** Admin UI → Team → Invite `miguel@…` as technician. Zero backend/mobile changes required. Miguel then sees the chooser on next login and picks Staff.
- **If H2** (two rows, chooser fires, wrong pick): **User action** + **product polish suggestion** — the chooser could remember the last pick and default to it on subsequent sign-ins. Not a bug, not in scope.
- **If H3** (two rows, only customer password matches): **DATA fix.** Admin resets the workforce record's password OR merges the two records.
- **If H4/H5** (ruled out): n/a.
- **If backend or mobile bug uncovered by §5.2**: **STOP and hand off** — main agent for backend, `e1_expo_frontend_dev` for mobile. Do not attempt cross-repo fixes here.

**Estimated exact fix scope (in the H1 case)**: 0 code lines. Two admin UI actions on prod. Reversible via admin UI without a code deploy.

---

## 7 · What this memo does NOT do

- Does NOT modify Miguel's DB record on any environment.
- Does NOT touch prod.
- Does NOT edit `/app/mobile/`.
- Does NOT ship a fix — the outcome of §5 determines whether one is needed.
- Does NOT run `Save-to-GitHub`.
- Does NOT resume Phase 3.1 or unrelated feature work.

**Ship the memo, then stop and hand back.**
