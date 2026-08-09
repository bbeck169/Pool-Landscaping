# Phase 54f · Wholesale pricebook integration closeout

_Status: SHIPPED (Feb 2026)_

## Scope closed
- Web pricebook: supplier column + filter (client-side, additive).
- Mobile pricebook: supplier badge + chip-strip filter.
- Mobile Settings > Suppliers: read-only view screen.
- Super-admin **"Sync all suppliers"** sequential batch button.
- Docs: PRD.md + CHANGELOG.md prepended with a consolidated Phase 54 (a → f) section including the persistent-volume runbook.
- **Phase 54f addendum**: Playwright cache-path startup log line + `PLAYWRIGHT_BROWSERS_PATH` smoke-check pytests.

## Files touched

| File | Kind | Purpose |
| --- | --- | --- |
| `frontend/src/pages/ops/OpsHub.jsx` | edit | PriceBook: `SupplierBadge` component + supplier filter dropdown + `filteredRows` useMemo + import `SUPPLIER_METADATA`. Additive-only — `/items` contract unchanged. |
| `frontend/src/pages/settings/SupplierSettings.jsx` | edit | Super-admin **"Sync all suppliers"** button + sequential fire loop + progress state (`Syncing 2 of 5 · SiteOne…`). Rest of the page unchanged. |
| `frontend/src/test/phase54f-supplier-parity.test.jsx` | **new** | 5 vitest source-inspection tests: supplier-column wiring, filter presence, sync-all sequential-fire guardrail, badge testid parity across web + mobile, wired-slug parity across web + mobile. |
| `mobile/app/price-book.tsx` | edit | `SUPPLIER_LABELS` map + `SupplierFilterChips` component + supplier badge per row + `filteredItems` state. |
| `mobile/app/settings/suppliers.tsx` | **new** | Mobile Settings > Suppliers (read-only view): all 5 cards with connected pill, sync_frequency, last sync + status, active toggle status. No API mutations. |
| `mobile/__tests__/phase54f-mobile-supplier-parity.test.ts` | **new** | 4 mobile-jest source-inspection tests mirroring the vitest side. |
| `backend/services/suppliers/cron.py` | edit | Added `_report_playwright_cache_path()` — startup log line reporting the effective Playwright cache path + Chromium version (or `missing`). Honors `PLAYWRIGHT_BROWSERS_PATH`. |
| `backend/tests/test_phase54e_heritage_epoolsupply_cron.py` | edit | +3 addendum smoke-check pytests: default cache path, env-override, log-line contains `cache_path` + `chromium`. |
| `memory/PRD.md` | edit | Prepended a consolidated Phase 54 (a → f) section — feature scope, endpoints, data model, cron behavior, env gates, sync frequency enum, operator runbook, legal caveat, non-goals. |
| `CHANGELOG.md` | edit | Prepended a consolidated Phase 54 (a → f) entry with the same sections plus test invariants + runbook. |
| `memory/PHASE54F_CLOSEOUT.md` | **new** | This file. |

Both `OpsHub.jsx` and `mobile/app/price-book.tsx` were **extended in place** — no duplicate pricebook pages introduced.

## Pricebook page paths (confirmed extended, not duplicated)
- **Web**: `frontend/src/pages/ops/OpsHub.jsx` → `PriceBook` function (line ~1725).
- **Mobile**: `mobile/app/price-book.tsx` (Expo Router route `/price-book`).

## Sync-all button — behavior guarantees
- Renders only for `role === "super_admin"` (admin does NOT see it).
- Fires `POST /api/suppliers/{slug}/sync` **sequentially** — no `Promise.all`, no parallel launch (prevents rate-limit hits + memory spikes from five concurrent Chromium instances).
- Progress state: `{current, total, label}` where `label` is the wholesaler's `display_name`.
- 400 `no_credentials` errors count as `skipped` (expected for wholesalers the operator hasn't configured yet).
- Any other error surfaces via a `sonner` toast.
- Final summary toast: `Sync-all done — N launched, M skipped (no creds).`

## Phase 54f addendum — persistent-volume Chromium mount (Option B)

### Startup log line (verified against live preview backend)
```
INFO:pool_crm:supplier.playwright: cache_path=/root/.cache/ms-playwright chromium=1228
```

Captured from `/var/log/supervisor/backend.err.log` after a supervisor restart in this session. Confirms:
1. The cache path resolves to Playwright's default (no `PLAYWRIGHT_BROWSERS_PATH` set in the preview env).
2. Chromium 1228 is installed and detected.
3. Operators can grep `supplier.playwright:` to confirm the mount / path on every deploy.

### `PLAYWRIGHT_BROWSERS_PATH` behavior
- Native to Playwright — no code change needed to honor it.
- Set the env var in the container spec → Playwright reads it → downloads / launches from that path.
- Our reporter helper (`_report_playwright_cache_path`) inspects the same env var so the startup log line matches Playwright's actual behavior.

### Volume mount instructions (from PRD § Operator runbook)
- **Recommended mount path**: `/root/.cache/ms-playwright` (or the value of `PLAYWRIGHT_BROWSERS_PATH` if you override).
- **Docker example**: `docker run -v playwright_cache:/root/.cache/ms-playwright ...`
- **Kubernetes**: mount a `PersistentVolumeClaim` at that path. Use `ReadWriteMany` if you want the cache shared across fleet replicas.
- **First-boot behavior**: empty mount → the container's entrypoint (or a one-time bootstrap script) runs `python -m playwright install chromium`. Subsequent boots find the cache warmed and skip the download.
- **Verification**: `ls /root/.cache/ms-playwright/chromium-*` should list a `chromium-1228/` directory (version number moves with Playwright releases).

### Smoke-check pytests (Phase 54f addendum)
Three new tests in `test_phase54e_heritage_epoolsupply_cron.py`:
- `test_playwright_cache_path_defaults_to_default` — asserts the reporter falls back to `~/.cache/ms-playwright` when `PLAYWRIGHT_BROWSERS_PATH` is unset.
- `test_playwright_cache_path_honors_env_override` — asserts the reporter respects the env var when set (Playwright-native behavior).
- `test_playwright_cache_path_logs_chromium_version` — asserts the startup log line contains `supplier.playwright`, `cache_path=`, and `chromium=`.

## `SUPPLIER_SYNC_LIVE` — unchanged
Still **OFF by default** everywhere. Cron ticks fire hourly + at 03:00 UTC and log dry-run summaries; no real wholesaler traffic until the operator flips the env var and restarts supervisor.

## Test-count delta

### Backend (`pytest`)
| Suite | Before | After | Δ |
| --- | --- | --- | --- |
| `test_phase54e_heritage_epoolsupply_cron.py` | 26 | 29 | **+3** (Playwright-cache-path smoke checks) |

**Phase 54 curated total: 84 → 87** (still 100 % green in ~15 s).

### Frontend (`vitest`)
| Suite | Before | After | Δ |
| --- | --- | --- | --- |
| `phase54f-supplier-parity.test.jsx` | 0 | 5 | **+5** |

**Full vitest: 1425 → 1430** (still 100 % green).

### Mobile (`jest`)
| Suite | Before | After | Δ |
| --- | --- | --- | --- |
| `phase54f-mobile-supplier-parity.test.ts` | 0 | 4 | **+4** |

**Mobile jest: 236 → 240** (still 100 % green).

## Confirmation of invariants (post-ship)

| Gate | Result |
| --- | --- |
| `yarn vitest run` | **1430 / 1430 pass** in ~41 s |
| `yarn lint` | exit **0** |
| Mobile Jest | **240 / 240 pass** in ~20 s |
| Phase 54 curated backend suite | **87 / 87 pass** in ~15 s |
| Startup log confirms Chromium install | ✅ `cache_path=/root/.cache/ms-playwright chromium=1228` |
| `SUPPLIER_SYNC_LIVE` default | OFF everywhere ✅ |
| Cron log line at startup | ✅ `supplier.cron.registered hourly=@0min daily=@03:00UTC live=False` |

## Deviations from scope

**None.** All Phase 54f items shipped as spec'd, plus the 54f addendum folded in cleanly (2 file edits + 3 pytests + PRD/CHANGELOG runbook additions).
