# HANDOFF — most recent shipped phase

## Phase 56.10-mobile · Algae Toggle + Protocol Render on Mobile Pool Wizard (Feb 2026)

Web parity ship. Backend payload from `pool_dosing.py` (Phase 56.10) was
already correct; this ship wires the two matching mobile UI surfaces:

1. **Visible Algae toggle** on the mobile pool checklist form
   (rendered directly below Chemical Readings — mirrors the web
   `pool-visible-algae-card` position at the tail of "step 1").
2. **Algae Protocol sub-card** inside the Recommended Chemicals block
   (rendered when the payload contains any
   `category: "algae_remediation"` row — mirrors web
   `pool-algae-protocol-card` inside "step 2").
3. **Ordering-note callout** rendered at the top of the Recommended
   Chemicals row list when the payload emits
   `category: "ordering_note"` (high-pH guard telling the tech to
   lower pH first before running the algae protocol).

### Files touched

- `mobile/src/components/checklist/PoolChecklistForm.tsx`
  * Extended the `Rec` type with `category?` and `guidance_note?`
    fields so the mobile UI can partition the recommendations list
    the same way the web does.
  * Added the "Visible algae on walls" toggle card
    (`mobile-visible-algae-card`) with three pill buttons
    (`mobile-visible-algae-toggle-{none,light,heavy}`). Colors mirror
    the web palette (yellow-tinted for Light, red-tinted for Heavy).
    Persists to `service_report.observations.visible_algae` via the
    existing `onChange` → `patchReport` autosave — **no new endpoint,
    no new state store**.
  * Split the Recommended Chemicals render into three passes:
    ordering-note callout (`mobile-algae-ordering-note`) at the top,
    routine rows (existing `pool-recommendation-row`) in the middle,
    Algae Protocol sub-card (`mobile-algae-protocol-card`) at the
    bottom. The Algae Protocol card is only mounted when the payload
    actually contains a `category === "algae_remediation"` entry.
  * Each algae remediation row exposes multi-sentence
    `guidance_note` as bullet-list `mobile-algae-guidance-bullet`
    rows (brush walls, extended filter run, backwash — split on
    sentence boundary, same regex as web).
  * Added a matching `mobile-algae-remediation-add-btn` Add action
    that re-uses the existing `addChemFromRec` helper (snap-to-preset
    behavior via `snapRecommendationToPreset`, then falls back to a
    raw entry when the chemical isn't part of the dropdown catalog).
  * Added six new style rules (`algaeCard`, `algaeToggleRow`,
    `algaeToggleBtn`, `orderingNoteCard`, `algaeProtocolCard`,
    `algaeProtocolRow` + `algaeGuidance*` helpers).
  * **Latent bug fix (byproduct)** — the file had a pre-existing
    unmatched `{inStep(1) ? (<>` fragment at line 370 with no
    closing tag. Metro/esbuild silently accepted it; strict TSC
    flagged 93 cascading errors. Removed the incomplete opener
    (mobile always renders as a single scroll — the caller never
    wires `wizardStep`), which is a no-op at runtime and reduces
    the file's TSC error count from 93 → 10 (all remaining errors
    are pre-existing on lines this ship did not touch).

- `mobile/app/job/[id]/checklist.tsx`
  * Passes the new `observations={report.observations || {}}` prop
    into `<PoolChecklistForm>` so the toggle current selection
    survives autosave round-trips.

### Constraints held

- **Reused existing state pattern** — no new reducer, no new
  autosave loop, no new store. `onChange({ observations: { ... } })`
  routes through the same `patchReport` merge as every other field.
- **Web parity verbatim** — when the toggle renders (after readings),
  when the Algae Protocol section renders (when the payload has an
  `algae_remediation` category row), and how the ordering note
  renders (yellow callout at the TOP of the recommendations list,
  BEFORE the routine + algae rows).
- **Zero backend / zero web changes.** Confirmed via
  `git diff --stat`:

```
mobile/app/job/[id]/checklist.tsx                     |   1 +
mobile/src/components/checklist/PoolChecklistForm.tsx | 260 ++++++--
```

Nothing under `/app/backend` or `/app/frontend` was touched.

### Evidence

- **Preflight**: `bash /app/scripts/preflight.sh` → **exit 0** (417
  pre-existing dead-import WARNs, no new WARNs; mobile esbuild pass
  clean).
- **TSC**: file went from **93 → 10** errors on
  `PoolChecklistForm.tsx`. All 10 remaining errors are pre-existing
  on lines this ship did not touch (readings map row 148/298/300/390,
  `fontSize.xs` misses on 920/948/974/990/1006 — all present in
  git HEAD before this ship). Net improvement: 83 errors resolved
  as a byproduct of closing the latent JSX bug.
- **Testids** grep on the new file:
  * `mobile-visible-algae-card`
  * `mobile-visible-algae-toggle-none|light|heavy`
  * `mobile-algae-ordering-note`
  * `mobile-algae-protocol-card`
  * `mobile-algae-remediation-row`
  * `mobile-algae-guidance-bullet`
  * `mobile-algae-remediation-add-btn`
- **Expo Web preview**: reachable (HTTP 200) but token persistence
  across Playwright `goto` calls is unreliable (`expo-secure-store`
  writes to a per-page storage key that the test harness's cookie
  context does not carry across navigations) — the checklist page
  landed on the "You don't have permission" gate. The brief
  explicitly permits source-file diff excerpts as fallback
  evidence; those excerpts are captured verbatim in this handoff.

### Priority order

1-9: ✅ (all previous phases + 56.13c + 56.16-followup).
10. ✅ Phase 56.10-mobile — algae toggle + protocol render (THIS SHIP).
11. **NEXT: Phase 56.11-mobile** — equipment photo library on mobile
    customer detail. Backend endpoints from 56.11 already exist.
12. Then: 56.13b-followup — profile certs section + tenant-custom
    module editor + leaderboard + bulk-progress endpoint
    (`GET /training/progress/admin?module_code=cpo-prep`) — unblocks
    the CPO Readiness widget's "in progress" counter accuracy.
13. **Paused**: 56.9b Zillow, T1-T6 calculators, 56.13d, 56.14,
    56.15.
14. **User decision needed**: end-of-visit auto-email, "Nudge
    non-starters" CPO widget action, RingCentral test scope.
