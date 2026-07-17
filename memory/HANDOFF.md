# HANDOFF — most recent shipped phase

## Phase 56.10 · Visible algae field + AI remediation dosing (Feb 2026)

**Backend (`services/pool_dosing.py` + `config_chlorine_targets.py` + `routers/service_reports.py`)**
- New constants: `CAL_HYPO_AVAILABLE_CHLORINE_PCT=73`, `ALGAE_LIGHT_SHOCK_PPM=10`, `ALGAE_HEAVY_SHOCK_PPM=30`, `POLYQUAT_OZ_PER_10K_GAL=4.0`, `ALGAE_HIGH_PH_THRESHOLD=7.6`.
- `compute(...)` accepts a new `visible_algae: str = "none"` kwarg with states `none | light | heavy`.
- **Light** → 1 cal-hypo shock entry at 10 ppm boost, unit=`lbs`, `category="algae_remediation"`, `severity="light"`, `guidance_note="Brush walls thoroughly and run filter 24h continuous."`.
- **Heavy** → 2 entries: triple-shock cal-hypo at 30 ppm boost + Polyquat 60 at 4 oz per 10k gal (unit=`oz`). Both `category="algae_remediation"`. Extended guidance including "Backwash / clean filter after 24h. Recheck FC before allowing swimmers."
- **High-pH ordering guard** — when pH > 7.6 AND algae is light/heavy, a `category="ordering_note"` entry is prepended: *"Lower pH to 7.2 with muriatic acid FIRST, then shock. Shocking at high pH reduces effectiveness."*
- **Algae entries are exempt from the 6-item cap** — they always ship even when the routine list is full.
- `RecommendChemicalsBody` gains `visible_algae: Optional[str] = "none"`; `ServiceReportPatch` gains `observations: Optional[Dict[str, Any]] = None` (persists `observations.visible_algae` on the report doc).

**Preferred-form reasons** (per spec)
- Cal-hypo: *"Rapid FC boost required for algae remediation. Cal-hypo delivers ~73% available chlorine per lb."*
- Polyquat: *"Non-metallic algaecide safe for salt cells and vinyl liners. Chlorine alone is insufficient for heavy algae blooms."*

**Web frontend (`components/checklist/PoolChecklistForm.jsx` + `PoolChecklistWizard.jsx`)**
- **Step 1** — new pill-style toggle group (None / Light / Heavy) rendered below the readings analysis card, with test-ids `pool-visible-algae-card`, `pool-visible-algae-toggles`, `pool-visible-algae-{state}`. Persists via `observations.visible_algae` through the existing PATCH pipeline.
- **Step 2** — refactored recommendation renderer:
  - Ordering-note entry (`category="ordering_note"`) renders as a top warning callout (`pool-recommendation-ordering-note`).
  - Routine entries render as before.
  - Algae-remediation entries render in a distinct red-tinted **"Algae Protocol"** sub-section (`pool-algae-protocol-card`) with warning icon, per-entry guidance-note bullets (`pool-algae-guidance`), and an Add button (`pool-recommendation-algae-add-btn`).
- Wizard shell passes `observations={report?.observations || {}}` to the form.

**Mobile (`mobile/src/components/checklist/PoolChecklistForm.tsx`)**
- Backend plumbing wired: `PoolChecklistFormProps.observations` accepted; `fetchRecommendations` now sends `visible_algae: props.observations?.visible_algae || "none"` to the recommender.
- **Mobile UI toggle group NOT shipped this phase** — the mobile pool wizard shell (56.7 revised port) is still pending, and the current mobile form has all sections in a single step-1 block. Adding the toggle without the wizard boundary would clutter the screen. **Deferred to the next mobile pool-wizard ship (58.x).** When the mobile wizard lands, follow the web pattern: toggle group at bottom of readings, algae protocol callout in step-2 recommendations.

**Tests**
- New `tests/test_phase56_10_algae.py` — **13 tests, all passing**:
  - `TestVisibleAlgaeStates` (3): none/light/heavy states.
  - `TestHighPhOrderingGuard` (4): high-pH prepend on light + heavy; normal pH no note; high pH without algae no note.
  - `TestDoseScaling` (3): linear with gallons, magnitude ~1.67 lbs at 20k gal / 10 ppm / 73% cal-hypo, inverse scaling with `CAL_HYPO_AVAILABLE_CHLORINE_PCT` via monkeypatch.
  - `TestAlgaeExemptFromSixCap` (1): algae entries ship even when routine list is full.
  - `TestNoRegressionOnBaseline` (2): default kwarg matches "none"; existing recommendations unchanged.
- Existing Phase 56.5 dosing tests — **20/20 still passing**.
- Existing Phase 34e stale tests — 3 pre-existing failures NOT caused by this ship (they pre-date the seasonal chlorine targets + tabs-default from Phase 56.5). Marked for future cleanup, not blocking.

**Sample recommender payloads** (verified via curl against live API)
```
visible_algae="none" ph=7.4 → 0 algae_remediation entries, 0 ordering_note entries.

visible_algae="light" ph=7.4 pool_gallons=20000 →
  Calcium hypochlorite shock (73%) | 1.67 lbs | algae_remediation
  guidance_note: "Brush walls thoroughly and run filter 24h continuous."

visible_algae="heavy" ph=8.0 pool_gallons=20000 →
  Ordering guidance | 0 | ordering_note
    "Lower pH to 7.2 with muriatic acid FIRST, then shock…"
  Calcium hypochlorite triple shock (73%) | 5.0 lbs | algae_remediation
    guidance_note: "Brush walls thoroughly. Run filter 24h continuous. Backwash / clean filter after 24h. Recheck FC…"
  Polyquat 60 algaecide | 8.0 oz | algae_remediation
    guidance_note: "Add slowly around the perimeter…"
```

**Screenshot / DOM evidence**
Programmatic click flow to open the wizard modal from the schedule row was blocked by intermediate route-guard selectors in the Playwright script (not by the toggle UI itself). The wizard modal, toggle group, and Algae Protocol card are wired into the JSX with stable `data-testid` attributes and match the payload rendering path already tested at `pool-recommendation-row` (Phase 56.6). The backend curl evidence above confirms the wire-level payload the UI renders from is correct across all three states + the high-pH guard.

**Preflight**: `bash /app/scripts/preflight.sh` → **exit 0**.

**Files touched**
- `backend/config_chlorine_targets.py` — 5 new constants.
- `backend/services/pool_dosing.py` — `compute()` kwarg + `_algae_remediation_entries` helper.
- `backend/routers/service_reports.py` — `RecommendChemicalsBody.visible_algae` + `ServiceReportPatch.observations` + pass-through.
- `backend/tests/test_phase56_10_algae.py` — new, 13 tests.
- `frontend/src/components/checklist/PoolChecklistForm.jsx` — observations prop, toggle group, step-2 renderer refactor.
- `frontend/src/components/checklist/PoolChecklistWizard.jsx` — passes observations to form.
- `mobile/src/components/checklist/PoolChecklistForm.tsx` — observations prop + fetch payload plumbing (UI toggle deferred).
- `memory/HANDOFF.md`, `memory/PRD.md`.

**Updated priority order**
1. ✅ Phase 56.13a (subsystem + drafts).
2. ✅ Phase 56.13a-commit (CPO seed + PDF cert).
3. ✅ Phase 56.10 · Visible algae + AI remediation dosing (THIS SHIP).
4. **NEXT: Phase 56.11** — Customer Equipment Photo Library (11 types, ≤4 photos each, admin-only delete, strict tenant isolation).
5. **PAUSED**: 56.9b Zillow, T1-T6 calculators, 56.13b/c Training UI, 56.13d supplemental pool modules, 56.14 landscaper training, 56.15 handbook.
6. **DEFERRED**: mobile pool-wizard toggle UI for algae (waiting on the mobile wizard port).
