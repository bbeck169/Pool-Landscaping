# HANDOFF — most recent shipped phase

## Phase 56.13b-followup · Training Profile Certs + Tenant Module Editor + Leaderboard + Bulk-Progress Endpoint (Feb 2026)

Four deliverables shipped **as a bundle** — all four (A, B, C, D)
landed in one ship. Closes the "in-progress counter approximation"
footnote from 56.13c and unlocks tenant-authored training content
end-to-end.

### A. Bulk-progress endpoint (backend, small)

New endpoint powers the widget's accurate "in progress" counter and
future admin dashboards:

```
GET /api/training/progress/admin?module_code=cpo-prep
Response: [{
  user_id, module_code, lessons_completed: [...],
  has_started: bool, started_at, last_activity_at
}, ...]
```

- Admin / super_admin only (403 for techs).
- Strictly tenant-scoped (`tenant_id` from the get_current_tenant
  dependency; no cross-tenant leakage possible).
- `has_started` is derived server-side from the length of the
  `lessons_completed` array so the widget never needs to compute
  it.

Team CPO Readiness widget updated to call this endpoint and now
renders the correct three-state breakdown:
- **Certified**: has a cert row with `passed=true`.
- **In progress**: has a progress doc with
  `lessons_completed.length > 0` AND no cert.
- **Not started**: neither.

Live confirmation on preview: widget summary reads
`"0 of 1 pool techs certified · 1 in progress · 0 not started"` for
the seeded P19092-Pool tech, with a row showing `In progress
(1 lessons)`. The "v1 approximation" italic footnote from 56.13c
has been replaced with "In-progress counter accurate as of last
widget load."

### B. Profile certs section

New `frontend/src/pages/training/TrainingCertsPanel.jsx` component
mounted on `TechnicianProfile` (`/technician/:id`) via a new
**"Certifications"** tab that sits alongside the existing 6 tabs.
Visible to:
- The tech themselves (`isSelf` — subset tab filter updated).
- Admins / super_admins viewing anyone's profile.

Per row: module title, `certificate_id`, quiz-score %, awarded
date, and a **Download PDF** button that fetches
`/api/training/certificates/{id}/pdf` via a JWT-authenticated
`fetch` (auth header) → blob → hidden anchor → click →
`URL.revokeObjectURL()`. Empty state renders "No certifications
earned yet. Take a training module to earn one."

Testids: `profile-certs-section`, `profile-cert-row-{cert_id}`,
`profile-cert-download-{cert_id}`, `profile-certs-empty`,
`tech-tab-certs`.

Note: the technician profile route param may be either a
`technician_id` or a `user_id` depending on how the caller
navigated in. `TrainingCertsPanel` matches both when filtering the
admin cert list (`r.user_id === id || r.technician_id === id`).

**Mobile profile:** the mobile app has no "user profile" screen
today — the equivalent lives on the customer-detail impersonation
flow. Explicitly deferred to a future ship; not blocking the CPO
tech workflow.

### C. Tenant-custom module editor (web)

`AdminTraining.jsx` was rewritten from a 109-line read-only table
into an 812-line admin console with:

- **Segmented tabs** — "Modules" and "Leaderboard".
- **Modules table** — shows every module (system + tenant-custom).
  System rows keep the Lock badge and only expose "View →". Tenant
  rows expose Edit + Delete actions inline.
- **New tenant module** button — opens a full slide-over editor.
- **Editor sheet** (`training-admin-editor-sheet`) — form
  layout:
  * **Basics**: `code` (URL slug, editable only on create,
    validated against the same regex as `TrainingModuleIn._check_code`
    server-side: `^[a-z0-9][a-z0-9_\-]{1,60}$`), `title`,
    `description`, `department` (dropdown pool / landscaping /
    both), `passing_score` (0.0–1.0 with the 0.75 default).
  * **Lessons list** — up/down arrow reorder (no drag-drop v1),
    add/remove buttons, plain-markdown textarea for `body_md` (no
    rich text editor), minutes + optional video URL field.
  * **Quiz list** — up/down arrow reorder, add/remove, per
    question: prompt, N choices, single-select radio for
    `correct_choice_ids` (backend invariant enforces exactly one
    correct), explanation textarea.
- Client-side validation guards submit: unique correct choice per
  question, non-empty prompt, at least 2 choices, valid code
  on create.
- Backend endpoints (from 56.13a) are unchanged:
  `POST /training/modules`, `PATCH /training/modules/{code}`,
  `DELETE /training/modules/{code}`. All three enforce admin RBAC
  and refuse writes to `is_system=true` modules (409 conflict).

**Non-goals** (called out here, matching the brief):
- No rich text editor for lesson bodies (markdown-in-textarea).
- No drag-drop reorder — up/down arrows only.
- No per-lesson video embedding beyond a plain URL field.
- No AI-assisted authoring.

### D. Leaderboard (web)

New backend endpoint + new UI section under the same admin console:

```
GET /api/training/leaderboard?days=90
Response: [{
  user_id, name, email, department, role,
  modules_completed, quizzes_passed, quiz_attempts,
  certificates_earned, avg_score
}, ...]
```

- Admin-only (403 for techs).
- Rolling window bounded by the `days` query param (default 90,
  hard-clamped 1–365).
- Aggregates from `training_quiz_attempts`, `training_certificates`,
  and `training_progress` in a single admin request (avoids the
  N+1 fan-out the widget originally worried about).
- Sorted server-side by `certificates_earned desc, modules_completed desc,
  quizzes_passed desc`.

UI renders a sortable table (click any column header to bump
sort direction). "Export CSV" button generates a client-side blob
download with today's date in the filename. Testids:
`training-leaderboard-table`, `training-leaderboard-col-{key}`,
`training-leaderboard-row-{user_id}`, `training-leaderboard-csv`.

### Files touched

- **Backend**
  - `backend/routers/training.py` — two new admin-only endpoints
    (`/training/progress/admin`, `/training/leaderboard`); +143
    lines, no changes to existing endpoints.
  - `backend/tests/test_phase56_13b_followup.py` (**new**) —
    4 backend tests covering both new endpoints + system-module
    immutability + tenant-custom CRUD with RBAC on every mutation.
- **Web frontend**
  - `frontend/src/components/admin/TeamCpoReadinessWidget.jsx` —
    rewrite (65-line delta) to consume the new bulk-progress
    endpoint and render the accurate three-state breakdown.
  - `frontend/src/pages/training/AdminTraining.jsx` — full
    rewrite (109 → 812 lines) implementing the tenant-custom
    module editor + leaderboard.
  - `frontend/src/pages/training/TrainingCertsPanel.jsx`
    (**new**) — profile certs panel.
  - `frontend/src/pages/phase14/Phase14Pages.jsx` — 12-line
    delta: add "Certifications" tab + wire `<TrainingCertsPanel>`.
- **Mobile**: intentionally unchanged this ship. No `mobile/`
  paths were touched.

### Evidence

**Preflight**: `bash /app/scripts/preflight.sh` → **exit 0** (418
pre-existing dead-import WARNs; the +1 vs 56.11-mobile is
`mobile/app/d2d/report.tsx:3 dead-import Ionicons`, which is a
mobile file not touched this ship — carried over from a prior
phase, flagged for a future cleanup pass).

**Backend tests**: `pytest
backend/tests/test_phase56_13b_followup.py` → **4 passed** in
27.97s.

**Live curl verification** (against the preview API):

```
GET /api/training/progress/admin?module_code=cpo-prep
  as admin  → 200, rows: [{user_id: 785626e8..., module_code:
                            cpo-prep, lessons_completed: ['cpo-prep-l1'],
                            has_started: true, ...}]
  as tech   → HTTP 403

GET /api/training/leaderboard
  as admin  → 200, 9 rows (Alex Admin + 6 techs + 2 test users);
              per-user shape includes all 9 documented keys.
  as tech   → HTTP 403

PATCH /api/training/modules/cpo-prep    (system module immutability)
  as admin  → HTTP 409  ("System modules are immutable; create a
                          custom module with the same code to override")

DELETE /api/training/modules/cpo-prep
  as admin  → HTTP 409

POST /api/training/modules                (tenant-custom CRUD)
  as tech   → HTTP 403
  as admin  → 200, doc.is_system=false, doc.tenant_id set.

PATCH /api/training/modules/{custom_code}
  as tech   → HTTP 403
  as admin  → 200, title updated.

DELETE /api/training/modules/{custom_code}
  as tech   → HTTP 403
  as admin  → 200, {"ok": true, "deleted": <code>}
```

All eight assertions verified live.

**Screenshots**:
- `/tmp/56_13b_fu_widget.png` — Admin dashboard, Team CPO
  Readiness widget expanded, summary reads
  `"0 of 1 pool techs certified · 1 in progress · 0 not started"`.
- `/tmp/56_13b_fu_modules.png` — `/admin/training` Modules tab
  showing the cpo-prep row with a `SYSTEM` badge, the "New tenant
  module" CTA, and the Modules / Leaderboard segmented control.
- `/tmp/56_13b_fu_editor.png` — Slide-over editor with pre-filled
  code `56-13b-demo`, title, description, department dropdown,
  passing score 0.75, one lesson block with markdown body area,
  and one quiz question block. Create / Cancel footer sticky.
- `/tmp/56_13b_fu_leaderboard.png` — Leaderboard table (8 techs +
  admin), sortable columns, "Export CSV" button top-right.
- `/tmp/56_13b_fu_profile_certs.png` — Mike Rivera profile,
  Certifications tab active, one cert row:
  `Certified Pool Operator (CPO) — Prep Course ·
  CPO-PREP-2026-000101 · 92% · Awarded 2026-07-17` with a green
  "Download PDF" button.

**Ship scope**:
```
$ git diff --stat HEAD
 backend/routers/training.py                        | 143 +++
 frontend/src/components/admin/TeamCpoReadinessWidget.jsx | 65 +-
 frontend/src/pages/phase14/Phase14Pages.jsx        |  12 +-
 frontend/src/pages/training/AdminTraining.jsx      | 812 ++++++++--
 4 files changed, 976 insertions(+), 56 deletions(-)
```

Plus two untracked new files: `backend/tests/test_phase56_13b_followup.py`
and `frontend/src/pages/training/TrainingCertsPanel.jsx`.

### Deferrals called out

- **Mobile profile certs section** — the mobile app has no
  "user profile" screen today (technician detail exists only on
  the web `/technician/:id` route). Adding one is a discrete
  ship; recommend bundling with a broader mobile technician-detail
  effort in a future phase.
- **Mobile tenant module editor** — not shipped and not
  requested. Admin authoring stays on web.
- The pre-existing `mobile/app/d2d/report.tsx` dead-import
  warning that first appeared in a prior 5x.x phase is inherited
  in the preflight WARN count and remains flagged for a future
  cleanup pass (unrelated to training).

### Priority order

1-11: ✅ (all previous phases + 56.16-followup + 56.10-mobile +
       56.11-mobile).
12. ✅ Phase 56.13b-followup — Training Profile Certs + Tenant
    Module Editor + Leaderboard + Bulk-Progress Endpoint
    (**THIS SHIP** — A+B+C+D bundled).
13. **Paused**: 56.9b Zillow, T1-T6 calculators, 56.13d
    (supplemental pool modules), 56.14 (landscape training),
    56.15 (handbook + onboarding).
14. **User decision needed**: end-of-visit auto-email, "Nudge
    non-starters" widget action, RingCentral test scope.

After this ship, the **active training + service-report + equipment
triangle** is fully feature-complete for the pool tech workflow, as
called out in the brief.
