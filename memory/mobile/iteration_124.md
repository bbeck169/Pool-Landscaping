# Iteration 124 — Time Clock Gate hotfix

## Root causes
1. Gate punch payload `source: "mobile_gate"` rejected by backend `PunchIn` (Literal mobile|web) → 422. Test file had locked the bad value.
2. Gate discriminator is `role` + `department`. Preview `mike@` = `pool_tech`, which was already non-gated; hardened with explicit `isPoolTech()` priority + normalisation so pool variants ("Pool Tech", "pool", "pool-tech") can never be gated, and pool techs no longer hit `/timeclock/mine-status`.

## Deliberate non-changes
- `department: "both"` → still gated (web parity; brief: default gate-ON when ambiguous).
- Missing/unknown department (47 preview techs = null, also north/south) → NOT gated (unchanged; backend `_require_landscaping` would 403 their punch → gating them = unrecoverable lockout).
- Known drift (not fixed, backend/web scope): backend `_require_landscaping` only allows landscaping|both, while web+mobile gate also covers landscape_tech|landscaper. mine-status 403 → fail-open, so no lockout.

## Deps: none added.
