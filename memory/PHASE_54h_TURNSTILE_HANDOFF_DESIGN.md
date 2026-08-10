# Phase 54h — Cloudflare Turnstile / Anti-Bot Human-Handoff · Design Doc

**Status:** DESIGN ONLY. No code, no shim edits, no new deps.
**Owner:** e1 (Emergent main agent) drafting; awaiting user approval before Phase 54h-a starts.
**Companion tickets:** shipped Fix B-1 (timeout cap 15→45s), Fix B-2 (SiteOne HTTP/2 fallback), Wholesale Suppliers nav (Task A). Blocked B-4 (Pool360/SiteOne selector refresh — URL drift, see separate report). Enabled by all of them.

---

## 1. Problem statement

Heritage Pool Supply (and any future Cloudflare-protected wholesale supplier) fronts its `pro`-portal login with a **Cloudflare Turnstile** interactive challenge. Post Fix B-1 + B-2 the connector reaches the login page, locates the correct `<input>` selector, and begins to `page.fill(…)` — but the challenge widget renders an overlay that keeps the form fields in the DOM while marking them `not visible / not editable`. Playwright retries visibility 60× and returns a timeout envelope. Headless automation cannot solve Turnstile (that's Turnstile's entire product spec) so a bot-side workaround like `stealth`-mode Playwright + realistic Chrome UA does not help either. Per the user's product decision we are NOT going to buy a captcha-solver (Option 1) or a residential proxy pool (Option 4). We ARE going to implement a **human-handoff** flow where an operator (admin / manager / super_admin) solves the challenge once, we cache the resulting supplier session cookies encrypted, and subsequent syncs re-use the cookies until they expire.

---

## 2. UX flow — narrative walkthrough

1. Admin / manager / super_admin opens `/settings/suppliers`, clicks **"Test connection"** on the Heritage row (or any other Turnstile-guarded supplier once they're wired up).
2. Backend fires the existing `/api/suppliers/{slug}/test-connection` handler → the connector calls `authenticate(credentials)`. Playwright launches, navigates to the login URL, waits for a login-form input.
3. Connector detects a **challenge state** (§3 below). Instead of throwing a `TimeoutError`, it:
   - Preserves the Playwright `Browser` + `BrowserContext` + `Page` in a **live-session registry** keyed by `challenge_id = uuid4()`.
   - Registers a 5-minute idle TTL on the entry (auto-cleanup via a background task).
   - Returns a NEW response envelope `{ok: false, challenge_required: true, challenge_id, supplier_slug, expires_at, message: "This supplier needs a one-time human solve."}`.
4. Frontend `SupplierSettings.jsx` sees `challenge_required: true` — instead of the red-toast error path, it opens a **Challenge Handoff modal** with:
   - Supplier display name + slug hint (matches the existing UX pattern).
   - Copy-to-clipboard button for the supplier's login URL (from the connector's `SEL["login_url"]`).
   - Copy-to-clipboard button for the operator's stored credentials (username + password revealed via a "Reveal" click — same paranoia gate we already use on the credentials page).
   - A single **"I've solved it — import cookies"** primary CTA.
   - Small link "Cancel & release the browser session" (fires `DELETE /api/suppliers/{slug}/challenges/{challenge_id}`).
5. Operator opens the supplier in their OWN browser tab (they can copy-paste the URL from step 4), logs in manually — solves Turnstile the same way any human does. Once logged in, they use one of the two cookie-import paths (§3d).
6. Operator clicks **"I've solved it — import cookies"** → frontend either (a) shells out to a browser bookmarklet that exports the supplier's cookies as JSON, or (b) prompts the operator to paste a JSON blob copied from their DevTools (guided screenshot in the modal). Choice locked in §3d.
7. Frontend `POST /api/suppliers/{slug}/challenges/{challenge_id}/cookies` with `{cookies: [{name, value, domain, path, secure, sameSite, expires}, ...]}`.
8. Backend loads the cookies into the still-open Playwright `BrowserContext`, re-navigates to the supplier's authenticated landing page (e.g. `catalog_url` for Pool360-like connectors), and verifies the `logged_in_marker` selector resolves. If it does → success:
   - Stores the cookies **encrypted with Fernet** (same key/pattern as `supplier_credentials`) in a new collection `supplier_sessions` keyed by `(tenant_id, supplier_slug)`.
   - Session TTL: whatever the supplier's session cookie says (`expires` on the primary session cookie); defaults to 30 minutes if the supplier only issues session-only cookies.
   - Closes the Playwright browser.
   - Returns `{ok: true, session_cached_until, supplier_slug}` to the frontend.
9. Frontend flips the challenge modal to a green success state, shows the TTL ("Heritage session cached until 2:15 PM"), and closes.
10. On subsequent syncs / test-connections for the same supplier, the connector reads `supplier_sessions`, decrypts + hydrates the cookies into a fresh `BrowserContext`, skips the login flow entirely, and proceeds to the catalog walk. **No Turnstile prompt.**
11. When the cached session expires (either the TTL elapses OR the supplier invalidates the cookie server-side), the next connector run falls back to the challenge flow — same UX as step 3.

---

## 3. Detection + option weighing

### 3a. Challenge-state detection (mandatory regardless of option)

Three signals, cheapest first — connector short-circuits on the first match:

1. **URL heuristic** — after `page.goto(login_url)`, if `page.url` ends up on `challenges.cloudflare.com` OR contains `/cdn-cgi/challenge-platform/`, we are in a full-page Turnstile challenge.
2. **DOM heuristic** — `page.query_selector("iframe[src*='challenges.cloudflare.com'], .cf-turnstile, [data-sitekey]")` returns non-null. Covers embedded Turnstile widgets that don't full-page-redirect.
3. **Fill-invisibility heuristic** — the existing `Page.fill: element is not visible` behaviour Heritage exhibits. If the selector RESOLVES but the input is `not visible` after 2s (much shorter than the current 30s wait), we treat it as a challenge state.

Signal #3 is our current de-facto detection; #1 + #2 make it fast + explicit + logged with the correct classification.

### 3b. Option 3a — Playwright CDP live-view via websocket (RULED OUT for this phase)

Backend exposes the browser's Chrome DevTools Protocol endpoint over a WebSocket, frontend renders a live `<canvas>` of the page using `chrome-remote-interface`-style client + streams pointer/keyboard events back through the WS. Beautiful UX (operator sees the exact page in-app and clicks the Turnstile checkbox in place), but:

- CDP endpoints run on the backend container's loopback — exposing them through the Kubernetes ingress requires a new WS route + tenancy isolation + auth-token propagation on every frame. ~600-1000 LOC + infra.
- Rendering CDP frames in the frontend needs a WebGL / canvas painter (or an iframe with `src=blob:` populated from raw `Page.captureScreenshot` diffs). Non-trivial. Likely a new dep (`chrome-remote-interface` or a rolled equivalent).
- Bandwidth: 30-60 KB/s per active session at 5 FPS. Fine for one operator, painful if we ever concurrent multiple challenges.
- If the operator's browser network to the container is flaky, the "click" event may lose ordering with respect to the visual frames — misses on the Turnstile widget.

**Rule out for Phase 54h.** Revisit if the manual-cookie-import flow proves too painful.

### 3c. Option 3b — Screenshot + step-by-step click replay (RULED OUT)

Backend captures serial screenshots of the login page + Turnstile widget; frontend shows them in a modal; operator taps coordinates in the frontend; backend replays clicks via `page.mouse.click(x, y)`. Fundamentally cannot solve Turnstile: Turnstile validates via **JS-in-context** (invisible token minted after the user interacts with a real widget in a real user-agent). A backend-side "replayed click" produces a click event whose provenance Turnstile's JS explicitly detects as automated (that's the entire point of Turnstile). **Rule out on technical grounds.**

### 3d. Option 3c — Manual cookie import via bookmarklet or DevTools paste (RECOMMENDED)

Operator solves the challenge in their **own browser** (native, no CDP bridge), then exports cookies back to our app. Two sub-flavours; the design picks 3c-bookmarklet for the primary path with 3c-paste as a fallback:

- **3c-bookmarklet (primary).** We ship a small JavaScript bookmarklet the operator drags into their bookmarks bar once. When on the supplier's post-login page, clicking the bookmarklet reads `document.cookie` (plus first-party cookies via `chrome.cookies` if the operator has our tiny helper extension installed — optional Phase 54h-c), formats them as JSON, and POSTs them to our backend using the `challenge_id` + a short-lived, single-use HMAC token minted in step 3 of the flow. No paste, no copy-paste of secrets in plain text.
- **3c-paste (fallback).** If the bookmarklet's third-party POST is blocked by the supplier's CSP (some enterprise portals set strict `connect-src` that reject cross-origin XHR to our domain), fall back to the operator opening DevTools → Application → Cookies → copy-as-JSON, then pasting into our modal. Backend accepts the paste at `POST /api/suppliers/{slug}/challenges/{challenge_id}/cookies` with the same envelope.

**Why 3c wins for now:**
- Zero infra additions. No new deps. No WebSocket routes. No CDP bridge.
- Backend stays synchronous — the existing `test-connection` handler just gains a challenge-state branch and a live-session registry.
- Bookmarklet is one file, ~40 LOC, hosted from our own domain so an operator can drag it into their bookmarks bar exactly once.
- Failure modes are inspectable: if the operator's cookies don't unlock the supplier, we get a legible `logged_in_marker not found` in the backend log; we can prompt them to retry.
- Composable with Fix B-4 down the road — once we know the correct login URL for Pool360 / SiteOne, the same challenge-handoff flow works for them too (Pool360 doesn't necessarily use Turnstile, but the modal-driven login flow benefits from the same "solve once, cache cookies" pattern).

---

## 4. Recommendation

**Ship Option 3c (manual cookie import) with the bookmarklet as primary and paste as fallback.** Rationale — the sole product benefit of Option 3a's live-view UX is "operator never leaves our app"; the operator only does this once per session TTL (~30 min – 24h depending on supplier), so the friction of "open supplier in new tab, log in, click bookmarklet" is minimal. Option 3a's infra cost is disproportionate. Option 3b is technically impossible against Turnstile.

---

## 5. Phasing plan

Each phase is atomic and independently revertible.

### Phase 54h-a — Backend session storage + challenge-state detection (est. ~250 LOC)

- New MongoDB collection `supplier_sessions` — `{tenant_id, supplier_slug, encrypted_cookies_ciphertext, cached_until, created_at, created_by_user_id}`. Fernet-encrypted with the existing `SUPPLIER_ENCRYPTION_KEY`.
- New helper `services/suppliers/session_store.py` — `save_session()`, `load_session()`, `expire_session()`, `_encrypt`/`_decrypt` mirror of the credentials store.
- New in-process live-challenge registry `services/suppliers/challenge_registry.py` — dict of `challenge_id → {browser, context, page, supplier_slug, created_at, tenant_id, user_id}`. 5-minute idle TTL enforced by an `asyncio.create_task` sweeper in the router's lifespan hook.
- Extend `services/suppliers/heritage.py` (only) — add the three-signal challenge detection; return a `ChallengeRequiredError` sentinel that the router catches and translates to the new `{challenge_required: true}` envelope. **Only Heritage in this phase** — Pool360 / SiteOne will opt in in a later mini-phase once B-4's URL question is resolved.
- Pytest: 5-6 unit tests. Mock the Playwright layer entirely; assert challenge_id minted, registry stores it, TTL enforced, `POST /cookies` unlocks the session.

**Files touched:** `backend/services/suppliers/{session_store,challenge_registry,heritage}.py`, `backend/routers/suppliers.py`, one new pytest file.

**Rollback:** revert `heritage.py` + revert the new `challenge_required` branch in `routers/suppliers.py` — the existing non-challenge path is untouched.

### Phase 54h-b — Frontend Challenge Handoff modal + bookmarklet host (est. ~180 LOC)

- New modal `frontend/src/components/settings/ChallengeHandoffModal.jsx` — copy-URL, copy-creds, primary "I've solved it — import cookies" CTA + fallback paste box.
- Wire it into `SupplierSettings.jsx` — on `response.challenge_required === true`, open the modal instead of firing the red toast.
- New static route `frontend/public/bookmarklets/supplier-cookie-export.js` served from the app's own domain. Ships the minimal JS that reads `document.cookie` + POSTs to our `/challenges/{id}/cookies` endpoint with the short-lived HMAC token embedded at registry-creation time.
- Vitest: 3-4 tests. Modal opens on `challenge_required`, copy buttons write to clipboard, "solved" CTA POSTs the expected envelope, fallback paste accepts JSON.

**Files touched:** `frontend/src/components/settings/ChallengeHandoffModal.jsx`, `frontend/src/pages/settings/SupplierSettings.jsx`, `frontend/public/bookmarklets/supplier-cookie-export.js`, one new vitest.

**Rollback:** delete the new modal file + revert the two-line hook in `SupplierSettings.jsx`.

### Phase 54h-c (OPTIONAL, defer) — Bookmarklet cross-origin fallback + browser extension

Only if Heritage's supplier CSP blocks the bookmarklet's cross-origin POST. Ship a tiny Chrome/Firefox extension that reads first-party cookies (`chrome.cookies` API) and messages them back to us via `chrome.runtime.sendMessage` + a same-origin bridge page. This is the belt-and-suspenders path; ~120 LOC + a Chrome Web Store submission. **Defer until we have observational evidence of blocked bookmarklets.**

**Files touched:** N/A in this design — a Phase 54h-c doc would be written separately if needed.

**Rollback:** deleting the extension repo folder has no impact on the running app.

### Phase 54h-d (post-launch, small) — Auto-refresh + expire-warning UX

- Background task: 5 minutes before a cached session expires, log a WARNING + surface a small yellow banner on `/settings/suppliers` that "Heritage session expiring soon — click to re-solve".
- Optional: opt-in "always keep signed in" toggle that fires the challenge flow proactively 3 minutes before expiry so the operator is never surprised mid-sync.
- ~60 LOC total across router + frontend.

**Rollback:** revert the banner + the pre-expiry task.

---

## 6. Non-goals (locked)

- **No paid captcha-solver integration** (2Captcha, Anti-Captcha, DeathByCaptcha). Turnstile is designed to reject them anyway.
- **No residential proxy pool.** Cloudflare identifies datacenter egress; a residential pool would help avoid IP-blocklist bans but doesn't solve Turnstile itself. Deferred as a separate infra ticket if user ever wants it.
- **No changes to the four non-Heritage connectors** in Phase 54h-a. Pool360 / SiteOne / Ewing / ePoolSupply keep their current code paths. Once B-4 lands (or we merge B-4 into the challenge flow via a "let a human log in once and cache cookies" pattern), the same session-store from Phase 54h-a is reusable — but that opt-in is a separate mini-phase.
- **No CDP bridge / live-view UX** (Option 3a). Explicit reject.
- **No cross-tenant session sharing.** Each tenant's cached cookies are scoped to `(tenant_id, supplier_slug)`. Operators from tenant A can never re-use tenant B's Heritage cookies.
- **No hard-delete of expired sessions** (defer to a separate purge task with an audit trail).

---

## 7. Rollback plan (per phase)

| Phase | Minimum revertible unit | Blast radius if rolled back |
|---|---|---|
| 54h-a | Revert `heritage.py` + the challenge branch in `routers/suppliers.py`. Drop the `supplier_sessions` collection (empty on first ship). | Heritage `/test-connection` returns the pre-54h `element is not visible` timeout envelope. Other suppliers untouched. |
| 54h-b | Delete `ChallengeHandoffModal.jsx` + revert the two-line hook in `SupplierSettings.jsx`. Remove `frontend/public/bookmarklets/supplier-cookie-export.js`. | Backend still returns `challenge_required: true`; frontend just shows the raw error text — same UX as pre-launch. |
| 54h-c | N/A in this design (defer decision). | N/A. |
| 54h-d | Revert the banner + the pre-expiry task. | Operators still have to re-solve when the session actually expires; the WARNING logs still trip. |

Each phase is safe to revert independently. No phase depends on the next; 54h-b works with or without 54h-c/d shipped.

---

## 8. Open questions for user review

1. **Session TTL default when the supplier only issues session-only cookies?** Proposal: 30 minutes. Configurable per-supplier via a small dict in `session_store.py`.
2. **Which roles can complete the challenge handoff?** Proposal: admin / super_admin / manager — same three-role gate as the credentials edit page. Technician / customer never see the modal.
3. **Bookmarklet or paste as PRIMARY?** Design picks bookmarklet as primary. User may prefer paste-first if their operators are DevTools-fluent already.
4. **After 54h-a lands for Heritage, do we opt Pool360 / SiteOne INTO the same challenge flow?** Recommendation: **yes**, once B-4's URL drift is resolved. The challenge flow doubles as a "cache the session cookies so subsequent syncs are 10x faster" optimization even for non-Turnstile suppliers.
5. **Extension (54h-c) — should we start the Chrome Web Store submission in parallel?** Recommendation: **no**, wait until we have data that the bookmarklet is genuinely blocked by supplier CSPs.
