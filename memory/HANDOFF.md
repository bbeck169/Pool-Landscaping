# HANDOFF — session close

**Fresh session opens on Phase 56.9b Steps 1–10.** First action:
mobile canvassing survey (Step 0 continuation), then Step 1
rate-limit service.

## Session recap (7 shipped items, in order)

1. Phase 56.16-followup — Customer portal service reports UI.
2. Phase 56.10-mobile — Algae toggle + protocol on mobile pool
   wizard.
3. Phase 56.11-mobile — Equipment photo library on mobile
   customer detail.
4. Phase 56.13b-followup — Bulk-progress endpoint + profile
   certs + tenant module editor + leaderboard.
5. Phase 56.17 + P0 Master Invoices 404 fix — Autobilling
   schedule anchors (5 options inc. `fourth_friday`) + daily
   auto-run + `/master-invoices` → `/invoices/master` nav fix.
6. Phase 56.17-followup — Autobilling runs audit UI page at
   `/admin/autobilling-runs`.
7. Phase 56.9b Step 0 (exploration only) — **deferred**.

Preflight: **exit 0** at every ship boundary. `/app` is source of
truth.

## Fresh-session brief — Phase 56.9b (guardrail-first Zillow)

**Do NOT compress the 10 guardrail steps under budget pressure.**
Step 0 was executed as a read-only survey in the closing session;
no code was mutated. Full findings below.

### RBAC endpoints to swap on Step 8 (LAST — after Steps 1–5 green)

Currently `Depends(require_admin)` — must become
`Depends(require_zillow_access)`:

- `backend/routers/property.py`:
  - `/property/lookup`
  - `/property/save`
  - `/property/saved`
  - `/property/saved/{pid}`
- `backend/routers/d2d.py`:
  - `/d2d/sold-leads`

**Stays admin-only** (aggregate reporting, not a lookup):
`backend/routers/d2d.py::/d2d/report`.

**Already tech-accessible** (no change needed) — 5 endpoints on
`property.py`: `/search`, `/search-by-coords`, `/history`,
`/save-note`, `/saved-notes`.

### Clean-slate Mongo collections (Steps 1 + 3)

- `zillow_usage` — does NOT exist. TTL indexes on
  `{ts: 1}` (day/month rollups) and per-user counts.
- `zillow_cache` — does NOT exist. Key = `address_hash =
  sha256(normalized_address)`, 30-day TTL on `cached_at`.

### Widget endpoint home (Step 4)

`backend/routers/zillow_admin.py` is a 523-byte stub with only
`/health`. Extend it for the "Zillow Usage This Month" admin
widget endpoint. No refactor of existing code.

### Web frontend surfaces (Step 6)

- `frontend/src/pages/property-lookup/PropertyLookupPage.jsx`
  line 164 (banner + usage chip).
- `frontend/src/pages/d2d/D2dPages.jsx` lines 175, 248, 515
  (3 spots).
- `frontend/src/pages/aitools/AiToolsPages.jsx` line 572
  (virtual-bid — same Zillow lookup, add chip).
- `frontend/src/pages/tech/ToolsHub.jsx` line 35 (tile becomes
  accessible; no banner change needed).

### Mobile canvassing surface — CONFIRMED PRESENT (Step 0.5 done in prior session)

Step 7 is a **real deliverable**, not a no-op. Surfaces to touch:

- `mobile/app/(app)/d2d.tsx` — D2D screen tab
- `mobile/app/(app)/property-lookup.tsx` — Property Lookup screen
- `mobile/app/virtual-bid.tsx` — Virtual Bid (same Zillow lookup)
- `mobile/app/d2d/index.tsx`
- `mobile/app/d2d/leaderboard.tsx`
- `mobile/app/d2d/report.tsx`
- `mobile/src/components/d2d/*` — MapCanvas variants + dispo
  helpers (chip likely wires at screen-header level, not here)
- `mobile/src/components/tools/sections.ts` — nav registry;
  verify whether tile visibility needs updating

Chip + rate-limited banner must ship on `d2d.tsx`,
`property-lookup.tsx`, and `virtual-bid.tsx` at minimum.
D2D sub-screens should share the same usage state via a
component-local subscription to the widget endpoint.

### Configuration

- `OPENWEB_NINJA_API_KEY` env in `backend/config.py`.
- Base URL: `https://api.openwebninja.com/realtime-zillow-data`.

### Rate-limit caps (from brief, restated)

- Techs: **20 / day + 200 / month**.
- Admins: uncapped.
- Super_admin: uncapped; may pass `?override_budget=true`
  past a 100 %-consumed tenant budget (writes a
  `zillow_budget_override` audit event).
- Tenant monthly budget default: **1000 / month**.
- ≥ 90 % → 200 + `X-Zillow-Budget-Warning: 1` header +
  JSON banner field.
- ≥ 100 % → **HTTP 429** `{error: "tenant_budget_exhausted", ...}`
  except for the super_admin override.
- Cache hits do NOT decrement rate-limit counters.

### Fresh-session opening actions (in strict order)

1. ~~Step 0 continuation — grep `/app/mobile` for canvassing UI;
   confirm Step 7 scope~~ **DONE** (see above — Step 7 is real).
2. Step 1 — `backend/services/zillow_rate_limit.py` +
   `zillow_usage` collection w/ TTL indexes.
3. Step 2 — Tenant monthly budget guard w/ 90 % header + 100 %
   429 + super_admin override + audit event.
4. Step 3 — `zillow_cache` collection + address-hash key +
   30-day TTL. Cache hits DO NOT decrement counters.
5. Step 4 — `zillow_admin.py` widget endpoint.
6. Step 5 — `backend/tests/test_zillow_rbac.py` — tech access,
   tech 429 at daily cap, tenant budget at 1000, cache-hit no
   decrement, super_admin override + audit event.
7. Step 6 — Web frontend chips + banners on the 4 pages above.
8. Step 7 — Mobile parity or explicit "web-only" HANDOFF note.
9. **Step 8 — RBAC SWAP LAST**, only after Steps 1–5 tests are
   green. Add `require_zillow_access` to `backend/utils.py`
   (allow super_admin + admin + technician of either
   department; block customer + anonymous). Swap on the 5
   endpoints listed above.
10. Step 9 — HANDOFF.md + PRD.md 56.9b entry (incl. deferrals).
11. Step 10 — `bash /app/scripts/preflight.sh` → exit 0.

## Parallel user decisions (do NOT touch until greenlit)

- End-of-visit auto-email.
- "Nudge non-starters" CPO Readiness widget action.
- RingCentral test scope.

Being handled by the user in a separate track. Not blocking 56.9b.

## T-phases (T1–T6)

**Explicitly on hold** until the user reviews 56.9b evidence AND
delivers the design-system audit reply. Do NOT auto-start them.

## Paused (unchanged, informational)

- 56.9b (this brief — resumes next session)
- T1–T6 calculators
- 56.13d supplemental pool modules
- 56.14 landscape training
- 56.15 handbook + onboarding
