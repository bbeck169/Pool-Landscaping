## Iteration 64 — Phase K26: Portal Activation filter + Waitlist tab (Investigation)
- **Commit**: N/A — no code changes; parity already complete
- **Date**: 2026-09-02
- **Findings**:
  ### Mobile vs Web comparison — FULL PARITY CONFIRMED
  
  | Feature | Web param | Mobile param | Match? |
  |---|---|---|---|
  | Active/Inactive | `is_active=true/false` | `is_active=true/false` | ✅ |
  | Waitlist tab | `waitlisted=true` | `waitlisted=true` | ✅ |
  | Portal Activation | `portal_status=activated/not_activated` | `portal_status=activated/not_activated` | ✅ |
  
  ### UI controls already present on mobile:
  - **Status segmented control**: Active / Inactive / Waitlist / All (line 194, testID `customer-status-*`)
  - **Portal activation chips**: All / Activated / Not activated (line 220, testID `customer-portal-*`)
  - **AsyncStorage persistence**: `customerListFilter.status` + `customerListFilter.portalStatus` (lines 47-60)
  - **Pagination reset on filter change**: `setPage(1)` called on both filters
  
  ### Phase attribution:
  - Status filter: Phase F6b (Active/Inactive/All) + Phase H4 (Waitlist)
  - Portal activation filter: Phase G4b
  - All implemented prior to K26 investigation
  
  ### Conclusion: **Nothing needed to be shipped.** Mobile already at complete parity with web.
- **Files modified**: None
- **Tests added**: None (K25 already covered the filter logic + persistence tests)
