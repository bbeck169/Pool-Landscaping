# TD-91 · Mobile "View as customer" in Portal Access — Phase 1 audit

2026-10-20 · read-only · HEAD `3176cc81a` · English · no code

> **Headline:** mobile ALREADY has a "View as customer" action (`app/customer/[id].tsx:489`) that calls the same endpoint as web. But it **swaps the whole mobile app into an in-app customer session** (`src/auth.tsx:249` `startImpersonation`). It does **not** open the portal in the device browser, and it sits in the profile header action row, **not** in Portal Access. The ask is therefore "add a browser-based variant inside Portal Access", plus a decision on what happens to the existing in-app button (§5 G1).

## 1. Web ground truth
- **Button:** `frontend/src/pages/customers/CustomerDetail.jsx:3179-3187`. Label "View as customer", `testid="cd-impersonate"`, ghost variant.
  - Sits in the Portal Access action row, between Reset (`cd-portal-reset`, L3175) and Revoke (`cd-portal-revoke`, L3192). Siblings: `cd-portal-reset-link`, `cd-portal-reset-link-copy`, `cd-portal-manual-create`.
  - Disabled while busy, when the portal login isn't `active`, or when `!canImpersonate`.
- **Gate:** `canImpersonate = role === "super_admin" || role === "admin"` (L2962). The button is hidden otherwise.
- **Handler `impersonate()` (L3017-3080):**
  1. Synchronously opens a blank `about:blank` tab first (avoids the popup blocker).
  2. `POST /api/admin/impersonate/{customer.id}` (no body).
  3. Reads `r.access_token`; if it's missing → closes the tab and shows an error toast.
  4. Navigates the tab to `/portal/home?impersonation_token=<token>` (relative, so the web app's own origin) with `location.replace`.
  5. Success toast: `Opened portal as <name> in a new tab.`
  6. Popup blocked → error toast + copies the portal URL to the clipboard. Any other failure → closes the tab + error toast (e.g. the backend 400 detail).
- **Portal side:** the bootstrap in `frontend/src/index.js:16-60`, which runs before mount:
  - takes `impersonation_token` from the query, stores it in **sessionStorage** `portal_token`, and strips it from the URL with `history.replaceState`;
  - seeds `localStorage.user` from the JWT payload with `is_impersonated: true` and `impersonator_id = act.sub`.
  - There's **no cookie**; it's purely token-in-URL → sessionStorage, which a device browser handles fine.
- The admin's own tab is not re-tokened, so the admin session survives.

## 2. Backend — `POST /api/admin/impersonate/{customer_id}` (`backend/routers/auth.py:1737`)
- **Gate:** `require_admin` (`utils.py:219`) = **admin, super_admin or owner**. Regular admins are limited to their own tenant (`q.tenant_id = admin.tenant_id`); super_admin may pass `?tenant_id=`.
- **Errors:**
  - 404 "Customer not found"
  - **400 "This customer has no login yet. Create a login for them first."**
  - 403 "Admin access required" (live: tech `mike@` → 403)
- **Audit:** inserts `db.audit_logs` `{event:"impersonation_started", admin_id, admin_name, admin_role, target_customer_id, target_user_id, target_tenant_id, cross_tenant, created_at}`. It's surfaced in "Access History" on web `AiOpsPages.jsx:583` and on mobile `app/access-history.tsx:54`.
  - The server logs it automatically, so **no extra audit call is needed from mobile**.
- **Response (live, admin):** `{access_token, token_type, user{…customer…}, impersonating, impersonator_name:"Alex Admin"}`.
  - JWT claims: `sub` (customer user), `role:"customer"`, `act:{sub:<admin id>}`, `exp`.
- **Token lifecycle:** **30-minute expiry** for impersonation tokens (`utils.py:122` `exp_minutes = 30 if impersonator_id`).
  - No revoke-on-close; it simply expires.
  - `POST /auth/revert-impersonation` (`auth.py:1774`) exists only to swap back an *in-app* session; it isn't needed for the browser flow, since the admin's mobile session is never replaced.

## 3. Mobile today
- **Portal Access section:** `src/components/customers/PortalAccessPanel.tsx`.
  - Mounted at `app/customer/[id].tsx:856-866` inside a `LightPanel`, **admin / super_admin only** (`isAdmin`, L270).
  - Props: `customerId, customerEmail, customerName, hasLogin, userRole, onRefresh`. Status comes from the panel's own `/portal-status` fetch (`active`, `email`).
  - **Action row `portal-actions-row` (L330-376):**
    - `portal-send-invite-btn` "Re-send invite" / "Send invite"
    - `portal-send-reset-link-btn` "Send reset link"
    - `portal-copy-reset-link-btn` "Copy reset link" (super_admin)
    - `portal-reset-password-btn` "Reset password" (hasLogin)
    - `portal-revoke-btn` "Revoke access" (hasLogin, danger)
  - **Style tokens:** local `ActionButton` (L454-486). Pill with `colors.brandTertiary` background and `colors.brand` text/icon (danger: `#FEE2E2` / `#B91C1C`), Ionicons 16, `fontSize.xs` semibold, spinner when busy, opacity 0.4 when disabled. The row is wrap + gap `spacing.sm`.
- **Existing in-app impersonation:**
  - `app/customer/[id].tsx:488-493`: `impersonate-customer-button` "View as customer", steel action-row pill, shown when `isAdmin && c.has_login`.
  - Opens a confirm sheet (`impersonate-confirm-sheet`, L1034) → `startImpersonation` (`auth.tsx:249`) → stores the customer token as the app's token → `router.replace("/portal/home")`, with `ImpersonationBanner` and revert via `/auth/revert-impersonation`.
- **Opening a browser — two patterns in use:**
  - `WebBrowser.openBrowserAsync(url)` (expo-web-browser 15.0.11): `app/quote/[id].tsx:127` (Stripe pay), `app/payments/methods.tsx:107`, `app/gbp/index.tsx:120`, `app/reports/aeo-digest.tsx:66`. This is an in-app browser tab (SFSafariViewController / Chrome Custom Tab).
  - `Linking.openURL(url)` → external browser: `app/card.tsx:145`, `app/admin/seo/studio.tsx:104`.
- **Web origin:** mobile has no separate web-URL env var. Mobile web links derive from `EXPO_PUBLIC_BACKEND_URL` (e.g. `app/(app)/instaquote.tsx:64`), and in preview the same host serves the web app (`GET /portal/home` → 200).

## 4. Proposed mechanism (mobile, no backend change)
- **Flow:**
  1. `POST /admin/impersonate/{customerId}`
  2. `url = ${EXPO_PUBLIC_BACKEND_URL}/portal/home?impersonation_token=${encodeURIComponent(access_token)}`
  3. `WebBrowser.openBrowserAsync(url)`, the same pattern as Stripe pay. The admin's mobile session is untouched; the backend writes the audit row.
- **Failures:** the backend `detail` → existing panel error/toast pattern (400 no-login → web copy). On web preview (`Platform.OS === "web"`), use `window.open` semantics via `Linking.openURL` (expo-web-browser on web opens a new tab too).
- **Button:**
  - `ActionButton` testID `portal-view-as-customer-btn`, icon `eye-outline`, label "View as customer".
  - Placed after "Reset password" and before "Revoke" (web order).
  - Shown for admin / super_admin (web gate); disabled while busy or when `!active` (web parity).

## 5. Scope gaps / decisions
- **G1 · The existing in-app "View as customer"** (header, `impersonate-customer-button`) uses a different mechanism with the same label. Options:
  - **(a)** keep both, but relabel the header one "Switch to customer view" so they're distinguishable;
  - **(b)** keep both as is (two identical labels with different behaviour — not recommended);
  - **(c)** remove the header button so only the browser one remains (web parity; loses the in-app view).
  - **Recommend (a).**
- **G2 · Role drift:** the backend also allows **owner**; web and mobile UI show the button to admin / super_admin only. Recommend web parity (admin / super_admin). Note: the Portal Access panel itself is only mounted for `isAdmin`, so owners don't see the panel on mobile today anyway.
- **G3 · Web origin in prod:** relying on `EXPO_PUBLIC_BACKEND_URL` assumes the web app is served on the API host. That holds in preview; prod may differ (custom domains). Options: accept it (same assumption as existing mobile web links), or add `EXPO_PUBLIC_WEB_URL` with a fallback to the backend URL (needs an env addition — operator decision).
- **G4 · Token in URL:** the 30-minute customer-scoped token travels in the query string to the device browser. The portal strips it immediately, but it can linger in browser history or server access logs. This is the **same exposure as web** (accepted there).
- **G5 · No endpoint / audit gaps:** the endpoint is reusable as is and the audit is server-side. No backend work.
- **G6 · Session isolation:** an in-app browser tab (SFSafariViewController) doesn't share the admin's mobile token, and the portal session lives in that tab's sessionStorage. Closing the tab ends the view; the token expires on its own after 30 minutes.

## 6. Ship plan (mobile only, single atomic commit expected)
- `m-td91-view-as-customer` (~45 src LOC + ~90 test LOC):
  - `PortalAccessPanel.tsx`: `viewAsCustomer()` handler + the new `ActionButton` (gate, busy, disabled per §4).
  - Plus G1(a) relabel (1 line in `app/customer/[id].tsx`), if approved.
  - Jest: success opens the browser with the exact URL (token encoded) and **no** `startImpersonation` / token swap; 400 → error copy, browser not opened; hidden for manager / tech; disabled when the login is inactive.
- Live check (admin, preview): tap → the portal opens as that customer; Access History shows `impersonation_started`.
- Receipt + commit log as a docs commit.
- **Decisions to confirm:** G1 (a/b/c) · G2 (admin + super_admin only?) · G3 (accept the backend-URL origin, or add `EXPO_PUBLIC_WEB_URL`).
