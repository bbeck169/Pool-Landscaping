# TD-92 · Web portal auth doesn't honor sessionStorage impersonation token · Phase-1 audit

**Status:** audit only — NO code touched this phase.
**Priority:** P1 (blocks TD-91 operator-visible flow + deployment hold reason).
**Author:** web pod.
**Reported by:** mobile pod (TD-91 receipt, commit `682dcc90c`).
**Blocked downstream:** TD-91 end-to-end (`m-td91 · 037bcb1f0`).

---

## 1 · Symptom

Opening `/portal/home?impersonation_token=<token>` in a browser that has **no** admin web login in `localStorage` redirects to `/portal/login` instead of landing on the customer portal home signed-in as that customer.

Mobile pod's confirmed external signals:
- `POST /api/admin/impersonate/{id}` returns a valid customer-scoped JWT (TTL 30min, carries `act` claim with admin identity per TD-91 audit).
- `GET /api/auth/me` with that token as `Authorization: Bearer …` returns 200 and the customer identity.
- The portal URL strip-and-pin bootstrap in `frontend/src/index.js:23-66` runs synchronously, correctly moves the token to `sessionStorage.portal_token`, and seeds `localStorage.user` with a minimal customer shape decoded from the JWT.
- The web FE still redirects to `/portal/login`.

Reproduces 100% of the time when:
1. A device-local admin session is **absent** from `localStorage` (fresh browser, incognito, or external device like a mobile in-app browser).
2. The impersonation token is delivered via the designed `?impersonation_token=` querystring handoff.

Does **not** reproduce when the admin already has a staff session in the same `localStorage` (same browser profile as `/admin` login) — because then `_readCachedUserSync` can hydrate `user` from `localStorage.token`+`localStorage.user` and the subsequent `/auth/me` self-heal lands on the impersonation identity on its own. This is the existing web "View as customer" happy path.

---

## 2 · Current auth model — ground truth from the code

### 2.1 · The route gate

`frontend/src/layouts/AppLayout.jsx::ProtectedShell` (line 245-290) is the sole gate for every `/portal/*` route and every other authenticated staff route.

```jsx
function ProtectedShell() {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return /* spinner */;
  if (!user) {
    // magic-link estimate exception + customer-portal special case
    ...
    const isPortalPath = location.pathname.startsWith("/portal");
    return <Navigate to={isPortalPath ? "/portal/login" : "/login"} ... />;
  }
  // mount AppLayout + Outlet
}
```

The only signal consulted is `user` from `useAuth()`. When `user === null`, the shell navigates to `/portal/login`.

### 2.2 · How `user` lands in the context

`frontend/src/auth.jsx::AuthProvider` (line 27-221) sets `user` via two paths:

**Sync hydrate — `_readCachedUserSync` (line 15-25):**

```js
function _readCachedUserSync() {
  if (typeof window === "undefined") return null;
  try {
    const token  = window.localStorage.getItem(TOKEN_KEY);  // "token"
    const stored = window.localStorage.getItem(USER_KEY);   // "user"
    if (!token || !stored) return null;
    return JSON.parse(stored);
  } catch { return null; }
}
```

Returns `null` when EITHER key is missing. **Reads only `localStorage`. Never reads `sessionStorage.portal_token`.**

**Async self-heal — `useEffect` (line 34-107):**

```js
useEffect(() => {
  const token = localStorage.getItem(TOKEN_KEY);
  if (!token) return;        // ← early-bail
  (async () => {
    const fresh = await api.get("/auth/me");
    ...
  })();
}, []);
```

Early-bails when `localStorage.token` is empty. **`/auth/me` is never fired** on the no-admin-login path. The sessionStorage portal_token is ignored by the gate even though it exists and is valid.

### 2.3 · The storage keys in play

| Key | Scope | Written by | Read by |
|---|---|---|---|
| `localStorage.token` | per-browser-profile | `auth.jsx::persist`, `/auth/revert-impersonation` return | `_readCachedUserSync` (gate), `useEffect` (self-heal), `api.js::authHeaders` (fallback), `AppLayout.jsx` (banner JWT decode) |
| `localStorage.user` | per-browser-profile | `auth.jsx::persist`, `index.js:60` (K13 seed), `/auth/me` on refresh | `_readCachedUserSync` (gate) |
| `sessionStorage.portal_token` | per-tab | `index.js:28` (K13 bootstrap, strip from URL) | `api.js:160` (Authorization header on `/portal/*` paths), `AppLayout.jsx:363` (banner JWT decode), `PaymentMethodPromptModal.jsx:23`, `PaymentMethodPromptBanner.jsx:26` |

**The entire sessionStorage.portal_token path is unknown to `auth.jsx`.** Every other K13 consumer learned about it; the auth gate did not.

---

## 3 · Impersonation handoff path — ground truth

### 3.1 · Admin-tab side (writer)

`frontend/src/pages/customers/CustomerDetail.jsx:3017-3052`:
```js
const r = await api.post(`/admin/impersonate/${customer.id}`);
...
const portalUrl = `/portal/home?impersonation_token=${encodeURIComponent(token)}`;
window.open(portalUrl, "_blank");
```

Admin obtains a customer-scoped token and opens a new tab/window with the token in the querystring. In the mobile pod's TD-91 flow, the mobile app constructs the same URL and hands it to the device's in-app browser instead of calling `window.open`.

### 3.2 · Portal-tab side (reader)

`frontend/src/index.js:23-66` runs **synchronously before React mounts**:

1. Reads `impersonation_token` from `window.location.search`.
2. Writes it to `sessionStorage.portal_token`.
3. Scrubs it from the URL via `window.history.replaceState`.
4. Decodes the JWT payload (no verification — display-only); if `role === "customer"`, seeds `localStorage.user` with a minimal customer shape:
   ```js
   const seed = {
     id: payload.sub,
     role: "customer",
     customer_id: payload.customer_id || null,
     name: payload.name || "Customer",
     email: payload.email || "",
     tenant_id: payload.tenant_id || null,
     is_impersonated: true,
     impersonator_id: payload.act ? payload.act.sub : null,
   };
   window.localStorage.setItem("user", JSON.stringify(seed));
   ```
5. Does **not** write `localStorage.token`. This is intentional per the K13 commit comment ("prefer per-tab sessionStorage token so the admin's own session in another tab is not touched").

Then React mounts. `AuthProvider` initializer runs `_readCachedUserSync` which requires both `localStorage.token` AND `localStorage.user` to be present. The seed landed `user` but not `token` → `_readCachedUserSync` returns `null`. The useEffect bails on `!localStorage.token`. `user` stays `null`. `ProtectedShell` navigates to `/portal/login`.

---

## 4 · Why `/api/auth/me` works but the FE gate does not

Confirmed via `frontend/src/api.js:149-165` (K13 header pin):

```js
let token = "";
try {
  const path = window.location.pathname || "";
  const portalToken = sessionStorage.getItem("portal_token") || "";
  if (portalToken && path.startsWith("/portal")) {
    token = portalToken;
  }
} catch { /* SSR / test env */ }
if (!token) token = localStorage.getItem(TOKEN_KEY) || "";
```

The API client **already** prefers `sessionStorage.portal_token` over `localStorage.token` for every request issued while the pathname matches `/portal/*`. So any `/auth/me` call that fires from inside the portal tab lands with the correct Bearer header and the BE returns the customer identity.

**The bug is that no `/auth/me` call ever fires on the no-admin-login path, because `auth.jsx:38-39` gates the fetch on `localStorage.token`, which is empty.**

The mobile pod's `curl` test attached `Bearer` manually, which is why they saw 200. In-browser the request would succeed identically — if someone fired it.

---

## 5 · Scope of surfaces affected

Every `/portal/*` route under the top-level `<AppLayout>` (`frontend/src/App.js:950`+):

- `portal/home` ← operator-visible repro from TD-91
- `portal/services`, `portal/services/:id`
- `portal/service-reports`, `portal/service-reports/:id`
- `portal/invoices`, `portal/invoices/:id`
- `portal/estimates`, `portal/estimates/:id`
- `portal/payments`, `portal/payment-method`
- `portal/documents`, `portal/warranties`
- `portal/messages`, `portal/chats`
- `portal/photos`, `portal/videos`, `portal/profile`
- `portal/terms`
- `portal/request-service`
- Every other `portal/*` sub-route guarded by `ProtectedShell`.

Public token-authed portal routes are **not** affected (they live outside `<AppLayout>`):
- `portal/login`
- `portal/service/:uuid`
- `portal/sign/:token`
- `portal/add-card`, `portal/setup-success`, `portal/setup-cancelled`
- `portal/payment-method/return`
- `portal/review/submit`
- `/customer-portal/agreements/:id/renew`
- `/r/review`, `/r/preferences`

**Operator takeaway:** every portal-landing deep-link an admin generates for a mobile-held device bricks on the gate. `/portal/home` is the mobile pod's primary consumer today; every other portal route is equally dead under the same precondition.

---

## 6 · BE impersonation token lifecycle — unchanged

Confirmed via `backend/routers/auth.py:1737-1792` (same ground truth as the TD-91 audit):

- `POST /api/admin/impersonate/{customer_id}` issues `auth_response(cust_user, impersonator_id=admin["id"], ...)` → JWT with `act` claim.
- `POST /auth/revert-impersonation` validates the active impersonation session (requires `impersonator_id` on the current JWT), reads the admin user record, issues a fresh admin-scoped JWT.
- TTL per TD-91 audit: 30 minutes. No per-tab revoke-on-close; FE-only sessionStorage lifetime matches the tab.
- Audit log is emitted on both `impersonation_started` + `impersonation_ended`.

**Nothing on BE needs to change for TD-92.** The fix is a pure FE auth-guard patch.

---

## 7 · Fix strategy — options evaluated

### Option A · Minimal · teach `auth.jsx` about `sessionStorage.portal_token`

Narrow surgical widening of `_readCachedUserSync` + the useEffect self-heal to recognize the sessionStorage token as a valid signed-in signal, scoped to `/portal/*` paths.

**Changes (sketch):**
```jsx
function _readCachedToken() {
  if (typeof window === "undefined") return "";
  try {
    const path = window.location && window.location.pathname || "";
    if (path.startsWith("/portal")) {
      const sess = window.sessionStorage.getItem("portal_token");
      if (sess) return sess;
    }
    return window.localStorage.getItem(TOKEN_KEY) || "";
  } catch { return ""; }
}

function _readCachedUserSync() {
  const token  = _readCachedToken();
  const stored = window.localStorage.getItem(USER_KEY);
  if (!token || !stored) return null;
  try { return JSON.parse(stored); } catch { return null; }
}
```

And in the useEffect:
```jsx
useEffect(() => {
  const token = _readCachedToken();
  if (!token) return;
  // ...existing /auth/me body unchanged
}, []);
```

Everything else stays byte-identical. `persist()`, `logout()`, `token()`, `login()`, `me()` all keep operating against `localStorage.token` as the admin source of truth. The sessionStorage path is read-only — the auth gate honors it, no code writes it (that's K13's job in `index.js`).

**Pros:**
- Single file, ~15 LOC + comment block.
- Scoped to `/portal/*` — admin routes unchanged.
- Matches the pattern `api.js:149-165` already uses (prefer sessionStorage on portal paths).
- Preserves the admin-in-same-tab happy path (if `localStorage.token` and `sessionStorage.portal_token` both exist, the portal path still prefers sessionStorage — matches `api.js` and `AppLayout.jsx` banner path).
- No new context, no routing surgery, no storage migration.
- Compatible with the K13 seed in `index.js:60` — the seeded `localStorage.user` becomes consumable the moment the token read also considers sessionStorage.
- `logout()` still clears `localStorage` only. For the mobile case, `logout()` is never fired by the user; the tab closes, sessionStorage dies with it. Clean.

**Cons:**
- Slight coupling of `auth.jsx` to the K13 storage key name (`"portal_token"`). Centralise with a tiny shared const if the mobile pod picks up more consumers.

### Option B · Normalize storage · migrate sessionStorage token into localStorage

Rejected. Breaks K13's deliberate decoupling (admin's own session in another browser profile stays untouched). Also surprises `logout()`: a portal logout would then clear the admin session.

### Option C · Separate "portal impersonation mode" context branch

Rejected. Over-engineered for the fix. The core issue is one gate reading one storage key — the symptom is clean, don't refactor the whole auth surface.

### Recommendation: **Option A**

Smallest blast radius, matches the pattern every other K13 consumer already uses, preserves the admin-same-tab happy path, no new abstractions. Ship it tight.

---

## 8 · Risk map

### 8.1 · Admin-in-same-tab happy path

Current path: admin signs in → `localStorage.token` + `localStorage.user` land. Admin clicks "View as customer" in `CustomerDetail.jsx:3181` → new tab opens with `?impersonation_token=…`. Pre-mount K13 strips the token into sessionStorage + seeds `localStorage.user` with the customer shape. Admin tab's `localStorage.user` is overwritten but `localStorage.token` is intact.

Under Option A, in the new portal tab:
- `_readCachedToken` on `/portal/home` reads `sessionStorage.portal_token` first → returns the impersonation token.
- `_readCachedUserSync` returns the seeded customer identity.
- `/auth/me` self-heal fires with the impersonation token → returns the full customer identity (BE-authoritative overwrite of the seed).
- Banner renders via the existing `AppLayout.jsx:363` sessionStorage branch.

Byte-identical to the current working admin-in-same-tab flow.

### 8.2 · Admin tab vs portal tab in the same browser

Two tabs under one `localStorage`. Admin tab is on `/admin/customers/…` — pathname does NOT start with `/portal` → `_readCachedToken` returns `localStorage.token` (admin). Portal tab is on `/portal/home` → `_readCachedToken` returns `sessionStorage.portal_token` (impersonation). Zero cross-contamination.

### 8.3 · "Return to admin" affordance in the mobile use case

**Risk flagged — mitigation deferred to the ship.**

`AppLayout.jsx:376-388` has:
```jsx
const revertImpersonation = async () => {
  const r = await api.post("/auth/revert-impersonation");
  if (r?.access_token) {
    localStorage.setItem("token", r.access_token);  // ← writes admin JWT
    if (r.user) localStorage.setItem("user", JSON.stringify(r.user));
    window.location.href = "/";
  }
};
```

In the mobile use case, this would deposit an admin access_token into the mobile device's `localStorage` — an admin session the device-holder never explicitly signed into. BE already audits + validates (requires the current JWT's `act` claim to point at a live admin), but the UX is semantically wrong: there's no admin session to "return to" on this device.

**Mitigation options for the ship phase:**
1. **Hide "Return to admin" when `localStorage.token` was absent at mount.** Capture `_hadLocalAdminToken` once at mount; render the button only when truthy. If falsy, render "End session" instead that calls `logout()` + clears `sessionStorage.portal_token` + navigates to `/portal/login`.
2. Alternatively, on the hidden-case click handler, do NOT write to `localStorage.token`; just clear sessionStorage.portal_token and redirect.

**Recommendation:** mitigation is in-scope for the ship but can be a sibling atomic (`td92b-fe · scope revert affordance to admin-same-tab flows`) so the primary gate fix lands first and unblocks mobile verification, with the revert UX tightened in commit 2. One file touched twice, two commits, clean.

### 8.4 · Impersonation audit-log emission

- `impersonation_started` fires at `POST /api/admin/impersonate/{id}` call-site (admin's localStorage-signed-in context). Unchanged under TD-92.
- `impersonation_ended` fires at `POST /auth/revert-impersonation` call-site. Only fired if a user clicks "Return to admin". Under 8.3 mitigation (option 1), the mobile case suppresses the button, so `impersonation_ended` doesn't fire from the mobile device. **This is a telemetry gap worth logging** — operator may want "ended via session close" audit emission in a future ticket (not in TD-92 scope).

### 8.5 · TosGate / ProfileCompletionGate / PaymentMethodPromptModal interaction

- `TosGate` reads from `useAuth().user` — hydrates correctly under Option A.
- `ProfileCompletionGate.jsx:54` early-returns on `!user || !user.name` — hydrates correctly under Option A (the K13 seed emits `name: payload.name || "Customer"`).
- `PaymentMethodPromptModal` + `Banner` read `sessionStorage.portal_token` directly for their own JWT decode — unchanged.

No gate downstream of `auth.jsx` makes a storage-layer assumption that breaks under Option A.

---

## 9 · Pytest / vitest coverage plan

### 9.1 · Existing coverage to extend / reuse as pattern

- `frontend/src/test/auth-bootstrap-sync.test.jsx` — mounts `AuthProvider` with pre-seeded localStorage and asserts `user` on the FIRST render. **Use as the template.**
- `frontend/src/test/auth-self-heal-401.test.jsx` — self-heal error flow.
- `frontend/src/test/api-auth-headers-portal-gate.test.jsx` — API client's portal_token preference. Confirms the pattern for `window.location.pathname` mocking.

### 9.2 · New vitest — `frontend/src/test/auth-portal-impersonation-bootstrap.test.jsx`

Minimum 4 specs:
1. **Sync hydrate on `/portal/*` recognizes `sessionStorage.portal_token` + seeded `localStorage.user`** → `user` is non-null on first render (no `/portal/login` redirect).
2. **Sync hydrate on `/admin/*` ignores `sessionStorage.portal_token`** → `user` is null if `localStorage.token` is empty (admin-only routes still require localStorage).
3. **useEffect self-heal fires `/auth/me` when only sessionStorage.portal_token exists on `/portal/*`** → mocked `api.get("/auth/me")` is called, returned payload becomes `user`.
4. **localStorage.token present overrides sessionStorage.portal_token on non-portal paths** → regression guard for admin-same-tab path.

Optional 5th: `logout()` clears localStorage only (does not touch sessionStorage.portal_token) — preserves the per-tab lifetime semantics.

### 9.3 · No backend tests needed

The BE lifecycle is unchanged. The existing `test_impersonation_*` suite covers the token-issue + revert flow.

---

## 10 · Commit plan

**Scope: 1 FE commit + sibling test file. Optionally 1 follow-up commit for revert-UX mitigation.**

- `td92b-fe · auth.jsx honors sessionStorage.portal_token on /portal/* paths`
  - `frontend/src/auth.jsx` — introduce `_readCachedToken(path?)` helper, consume it from `_readCachedUserSync` + useEffect self-heal. No other call-site touched.
  - `frontend/src/test/auth-portal-impersonation-bootstrap.test.jsx` — new vitest with the 4-5 specs enumerated above.
  - Live reproducer: open preview browser incognito → paste `/portal/home?impersonation_token=<freshly-issued-token>` → lands on customer portal home signed-in as that customer. Previously 100% redirect to `/portal/login`.

- `td92c-fe · scope "Return to admin" affordance to admin-same-tab flows` (optional sibling, operator-approved)
  - `frontend/src/layouts/AppLayout.jsx` — capture `_hadLocalAdminTokenAtMount` once, gate the revert button on it; render an "End session" fallback that clears sessionStorage + bounces to `/portal/login` otherwise.
  - Vitest coverage for both branches of the gate.

**Pre-commit guardrails (unchanged):**
- Atomic `git commit --only -- <paths>` on each.
- `scripts/td85_session_hygiene_precheck.sh` green pre-commit.
- No `/app/mobile/` edits.
- No `/app/backend/` edits.
- No testing agent. Manual `yarn vitest run` only.
- English only. Rogue cron logged in-place (chain at 13).

**Operator ask:** approve `td92b-fe` for immediate ship. Approve or defer `td92c-fe` revert-UX mitigation to a later ticket. If deferred, add a one-line bookmark under `TD-61` neighborhood in `TECH_DEBT.md` so the audit-log telemetry gap in 8.3 doesn't fall off the stack.

---

## 11 · Rationale summary (one-liner)

Every K13 consumer learned about `sessionStorage.portal_token` when the admin-side impersonation bootstrap shipped — except `auth.jsx`. Teach it, and the mobile use case lights up end-to-end without any other code moving.
