# DEPRECATED (K55 · Feb-2026)
#
# The Homeworks (home.works / Copilot CRM) BYO-MCP integration was
# retired in Phase K55.  This document is preserved as historical
# context for future engineers investigating legacy
# ``homeworks_byo_integrations`` / ``homeworks_byo_oauth_states`` /
# ``homeworks_import_runs`` rows (kept intact for audit) and the
# ``homeworks_integration_models.py`` typed-access module.
#
# For the actual removal record, see:
#   * /app/memory/PHASE_K55_INTEGRATION_REMOVAL_DIAGNOSIS.md
#   * /app/memory/PHASE_K55_a_FRONTEND_REMOVAL.md   (frontend rip)
#   * /app/memory/PHASE_K55_b_BACKEND_REMOVAL.md    (backend rip)
#   * /app/memory/PHASE_K55_c_ENV_DOCS.md           (env + docs cleanup)
#
# Do NOT resurrect any wiring described below without a fresh design
# doc — the surrounding code paths (routers/services/frontend pages)
# no longer exist.
#
# ─────────────────────────────────────────────────────────────────────


# Homeworks (home.works) MCP · Phase 0 POC

**Status:** Shell + shell tests complete. **Not yet validated against real
Homeworks OAuth server.** Real credentials required from user before we
can prove any of this end-to-end (see "What still needs user-provided
creds to fully validate" below).

## What this is

Per-tenant bring-your-own-credentials scaffold for the Homeworks
(formerly Copilot CRM) MCP integration. Deliberately **separate** from
the existing global env-var-driven Homeworks integration under
`/api/integrations/homeworks/*` — this new surface lives at
`/api/admin/integrations/homeworks/*` and is:

* Per-tenant (secrets stored in `db.homeworks_byo_integrations`, one
  doc per tenant)
* Super_admin only (all mutating routes gated)
* User-editable authorize_url + token_url (no hardcoded guesses, no
  `.well-known/oauth-authorization-server` discovery — the docs live
  behind home.works's connect page so we let the operator paste)
* Read-only smoke test only (`tools/list` + best-effort
  `list_customers`) — **NO writes to the CRM DB in Phase 0**

## Files shipped

**Backend**
- `backend/homeworks_integration_models.py` — Pydantic models. (⚠️
  deviation from spec: was requested as `backend/models/homeworks_integration.py`
  but `backend/models.py` already exists as a flat module. Creating a
  `models/` package would shadow that module. Renamed to avoid
  breakage.)
- `backend/services/homeworks_mcp_client.py` — Fernet helpers + Mongo
  layer + `HomeworksMCPClient` (OAuth + MCP JSON-RPC 2.0 over HTTP).
- `backend/routers/homeworks_integration.py` — Router at
  `/api/admin/integrations/homeworks`.

**Frontend**
- `frontend/src/pages/admin/integrations/HomeworksIntegrationPage.jsx`
  — Route `/admin/integrations/homeworks`.
- `frontend/src/pages/admin/integrations/HomeworksOAuthCallback.jsx`
  — Route `/admin/integrations/homeworks/oauth/callback`.

**Tests**
- `backend/tests/test_homeworks_mcp_client.py` — 10 tests: authorize
  URL construction, token exchange + refresh, MCP JSON-RPC, 401 →
  refresh → retry, fetch_sample_customer fallback.
- `backend/tests/test_homeworks_router.py` — 10 tests: super_admin
  gate, secret encryption at rest, redaction on GET, connect flow,
  smoke-test gating, disconnect keeps creds.
- `frontend/src/test/homeworks-integration-page.test.jsx` — 8 tests:
  testids, form pre-fill, save payload shape, connect opens new tab,
  smoke-test render, error banner.

**Nav / routes**
- Registered as `_hw_byo_router` in `backend/server.py` inline with
  the other integration routers.
- Wired in `frontend/src/App.js` for both routes above.
- Nav entry in `frontend/src/nav/adminNav.js` under Operations →
  Settings.

**Env**
- `FERNET_KEY` added to `backend/.env` (fresh key generated per Phase
  0 spec). **Rotating this invalidates every stored refresh token —
  preserve across deploys.** Also: it is NOT the same key as the
  existing `MCP_TOKEN_ENCRYPTION_KEY` (Supercool) or the HKDF-derived
  keys used by the older env-var-driven Homeworks integration.

## Setup instructions the user needs to follow

Once `home.works/connect` grants access to their OAuth dashboard:

1. Log in to your CRM as the **super_admin**. This surface is gated
   there and nowhere else.
2. Navigate to **Operations → Settings → Homeworks Integration (POC)**
   (path: `/admin/integrations/homeworks`).
3. On the Credentials card, paste from your home.works dashboard:
   - **Client ID** — issued when you register this app.
   - **Client Secret** — never displayed back to you after save (it is
     Fernet-encrypted at rest); leave the field blank to keep the
     stored value on subsequent saves, or paste a new value to rotate.
   - **Authorize URL** — the OAuth `/authorize` endpoint URL. If
     home.works has published this in your connect dashboard, copy it
     verbatim; otherwise ask their support.
   - **Token URL** — the OAuth `/token` endpoint URL. Same source.
   - **Redirect URI** — pre-filled with
     `https://<your-crm-host>/admin/integrations/homeworks/oauth/callback`.
     Register this exact URL in your home.works dashboard.
   - **MCP Server URL** — defaults to
     `https://www.home.works/connect/mcp`. Update only if home.works
     ships a distinct MCP endpoint.
   - **Scopes** — one per line. Ask home.works which scopes their MCP
     needs; common candidates include `read:customers`, `read:jobs`.
4. Hit **Save credentials**.
5. Hit **Connect Homeworks** — a new browser tab opens on the
   home.works authorize URL. Approve the connection.
6. You'll land on the OAuth callback page which POSTs to the backend
   and bounces you back to the integration page with status
   `connected`.
7. Run the smoke test. The tools list + a sample customer probe run
   read-only. If the sample-customer probe misses (e.g. home.works
   uses a tool name other than `list_customers`), the tools list is
   still surfaced along with a "no matching tool" hint.

## Rollback / disconnect

* Hit **Disconnect** on the integration page → clears access + refresh
  tokens, keeps client credentials. Confirmed via
  `test_homeworks_router.py::TestDisconnect`.
* Manual purge from Mongo (super_admin only, off-band):
  ```
  db.homeworks_byo_integrations.deleteOne({ tenant_id: "<your-tenant-id>" })
  db.homeworks_byo_oauth_states.deleteMany({ tenant_id: "<your-tenant-id>" })
  ```

## Known unknowns — need user-provided creds to validate

Phase 0 ships the shell honestly. These items **cannot** be verified
until the user pastes real credentials and completes an actual OAuth
handshake against home.works:

1. **Actual OAuth URLs.** We don't hard-code `authorize_url` or
   `token_url`. If home.works uses a non-standard grant type or
   requires PKCE, the current implementation may need to be extended.
2. **Scope naming.** We list scopes as a form field. If home.works
   requires a specific set (e.g. `openid company` per the existing
   env-var flow, or something else), the user provides them.
3. **MCP tool name for "list customers".** Our smoke test tries
   `list_customers` first, then any tool matching `/customer/i` from
   `tools/list`. If home.works exposes only a `graphql` tool (like
   the existing global integration uses), Phase 1 will need to swap
   the probe to hit `query-graphql` with a Homeworks-native query
   instead.
4. **Refresh token rotation.** Backend refresh flow persists any
   rotated refresh token. Verified with a mock but not against a real
   AS.
5. **SSE vs plain-JSON MCP responses.** The existing home.works client
   at `backend/services/homeworks_mcp/client.py` handles both. This
   Phase 0 shell only accepts `application/json` per the user spec;
   if home.works's MCP endpoint returns SSE, we'll need to port that
   parser over.

## Test posture

* Backend tests are offline (`httpx.MockTransport`).
* Frontend tests mock `@/api` and `window.open`.
* No live Homeworks endpoint touched. All tests pass with the shipped
  FERNET_KEY.

## What Phase 1 will need to promote off POC

* Merge the two Homeworks surfaces — the env-var-driven one at
  `/api/integrations/homeworks/*` and this per-tenant one — into a
  single admin console.
* Replace the best-effort `list_customers` probe with an actual
  Homeworks-native tool call (probably `query-graphql`, per the
  existing importer package under `backend/services/homeworks_mcp/`).
* Add a Homeworks → AquaTerra sync layer that writes to
  `db.customers` (destructive-ish; needs a dry-run flag).
* Backfill the frontend nav under Admin → Integrations with both
  Homeworks surfaces + Supercool.

## Contact

Anything under this surface is Phase 0 POC. **Do not enable
production data flows against it.** Ping the ops channel once the
user has completed a first successful handshake so we can promote to
Phase 1.
