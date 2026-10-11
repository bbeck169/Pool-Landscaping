# Deprecations ledger

Each entry lists an API/field/endpoint that is being renamed or removed, the
window during which both old and new coexist, and the planned removal date.
When you add a new deprecation to the codebase, ALWAYS add a row here so the
future removal pass has an unambiguous source of truth.

Format:
- **Scope** — endpoint / module / component affected.
- **Deprecated name** — the old identifier (still works for now).
- **Canonical name** — the new identifier to migrate to.
- **Deprecated in** — commit / phase that introduced the deprecation.
- **Remove after** — the trigger event (phase ship, consumer migration, …)
  AND the earliest removal date.
- **Known consumers** — list of callers that must be updated before removal.

---

## Merge-tag registry — `token` field → `key`

- **Scope**: `GET /api/merge-tags` (flat) AND `GET /api/marketing/merge-tags`
  (grouped). Both endpoints now emit items with BOTH `key` and `token`
  fields; the values are byte-identical.
- **Deprecated name**: `token` (per-item field on every catalog response).
- **Canonical name**: `key`.
- **Deprecated in**: M-TAG-FIX FOLLOWUP Fix 2 · Feb-2026
  (commit landing with this ledger entry).
- **Remove after**:
  1. The upcoming visual-email-builder phase ships and consumes `key`.
  2. The mobile port's merge-tag picker ships and consumes `key`.
  3. **Earliest removal date**: Aug 1, 2026 (6 months — one full release
     cycle after both consumers above have shipped and had time to drift
     to `key`).
- **Known consumers** (must migrate to `key` before removal):
  - `frontend/src/components/marketing/MergeTagPalette.jsx` — already
    reads `t.key` with a fallback to `t.token`; drop the fallback at
    removal time.
  - Upcoming visual-email-builder (not yet implemented) — consume `key`
    directly, no fallback needed.
  - Upcoming mobile-port merge-tag picker (not yet implemented) — same.
  - Any third-party integration consuming `/api/merge-tags`: communicated
    via release notes when removal lands.
- **Removal checklist**:
  - [ ] Remove the `"token": tok` line from `catalog_grouped()` + `catalog_flat()`
        in `backend/services/marketing/merge_tags.py`.
  - [ ] Drop the `t.token` fallback in `_tagKey()` in
        `frontend/src/components/marketing/MergeTagPalette.jsx`.
  - [ ] Delete the vitest/pytest assertions that verify the alias.
  - [ ] Remove this ledger entry.
