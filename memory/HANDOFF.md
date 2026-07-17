# HANDOFF — most recent shipped phase

## Phase 56.13b · Training Web UI + "Tests" Nav (Feb 2026)

**Nav**
- New **"Tests"** chip in `layouts/AdminTopBar.jsx` QuickAccessRow with `GraduationCap` icon. Visible to `admin`, `super_admin`, and `technician` roles; hidden for `customer`.
- New "Training / Tests" entry in `nav/roleNav.js` `TECH_NAV.records` section (shows in the universal top-right menu for all techs including pool + landscape + both).
- Routes wired in `App.js`:
  - `/tests` → `TrainingList`
  - `/training` → redirects to `/tests` (backwards-compat alias)
  - `/tests/:code` → `TrainingModuleDetail`
  - `/tests/:code/quiz` → `TrainingQuiz`
  - `/admin/training` → `AdminTraining` (admin-only)

**Module list (`/tests`)**
- Fetches `GET /api/training/modules` (department-filtered server-side).
- Card grid — one card per module — with title, description, department badge (Pool / Landscape / Both), system badge, lesson + question counts, progress ring showing the tech's completed-lessons %, and a Start / Resume / Review CTA (Review is shown when 100 % complete).
- For `both` techs (rare), cards are grouped under Pool / Landscape / Cross-Department headers.
- Admin + super_admin see a **"Manage modules"** link (top-right of the header) → `/admin/training`.
- Empty state: "No training modules are available for your department yet." Uses `data-testid="training-list-empty"`.
- All cards carry `data-testid="training-module-card-{code}"`.

**Module detail (`/tests/{code}`)**
- Split panel:
  - Left: lesson list with green ✓ / grey ○ status per lesson (`data-testid="training-lesson-item-{lesson_id}"`).
  - Right: markdown-rendered lesson body via `react-markdown` (`data-testid="training-lesson-body"`).
- Footer with **Prev**, **Next**, and **Mark as complete** buttons (`training-lesson-prev`, `training-lesson-next`, `training-lesson-mark-complete`). Complete is disabled once done.
- When all lessons are complete, a green **"All lessons complete — ready to take the quiz"** banner appears with a prominent **Take Quiz** button (`training-take-quiz-banner`, `training-take-quiz-btn`).
- Persistent disclaimer callout at the top of the module (yellow) reads the module's `disclaimer` field verbatim — includes the "This is prep material only" language on the CPO module (`training-module-disclaimer`).

**Quiz runner (`/tests/{code}/quiz`)**
- One question at a time with a "Question N of M" counter (verified via screenshot: `Question 1 of 50` on CPO module).
- 4 pill-style radio choices (`training-quiz-choice-{qid}-{cid}`). Backend already redacts `correct_choice_ids` + `explanation` from the tech's payload (verified in 56.13a-commit `TestAnswerKeyRedaction`), so cheating from the API is impossible.
- Prev / Next between questions; local state until final submit.
- Final "Submit Quiz" button is disabled until every question has an answer, then styled green (`training-quiz-submit`).
- Submit posts `{ answers }` to `POST /api/training/modules/{code}/quiz` and returns score + certificate_id (if passing).

**Results screen**
- Big score display + PASS / FAIL banner (`training-quiz-passfail`, `training-quiz-score-value`). Colors: green pass, red fail.
- If passed AND `certificate_id` returned: shows the cert ID in a green award block + a `Download Certificate PDF` button (`training-quiz-cert-pdf-btn`) that links directly to `${REACT_APP_BACKEND_URL}/api/training/certificates/{cert_id}/pdf` (opens in new tab). The PDF byte-match assertions from 56.13a-commit (`test_pdf_endpoint_returns_pdf_with_disclaimer`) guarantee the disclaimer + "CPO Prep — Not Official Certification" subtitle are present.
- Per-question review below the banner: the tech's chosen answer is marked with `→` and "(your answer)". The other choices are dimmed. In line with the answer-key redaction policy from 56.13a-commit, we do NOT surface the correct answer to the tech — only their choice. Admins reviewing the audit trail can access the full attempt payload via `GET /api/training/modules/{code}/attempts?user_id=`.
- Retake Quiz + Back to Module buttons (`training-quiz-retake-btn`).
- No confetti in v1 — the PASS banner + cert block are the reward moment. (Deferred; a `canvas-confetti`-style flourish is a 20-minute follow-up.)

**Admin authoring (`/admin/training`)**
- Read-only table of every module the admin can see (`training-admin-table`). Columns: Title, Code, Dept, System badge, Lessons, Quiz, Actions.
- System modules (CPO Prep) render with a `Lock` icon + "System" pill.
- Row action = "View →" link into the same tech-facing module detail page (safe for read-only inspection).
- Full CRUD for tenant-custom modules + drag-reorder + leaderboard **DEFERRED to a follow-up ship** — called out on the page itself. V1 is intentionally minimal because the CPO seed is a system module and cannot be edited via the API anyway (immutable per 56.13a router).

**Certifications surface on user profile**
- **DEFERRED to Phase 56.13b-followup**. The `GET /api/training/certificates` endpoint is live from 56.13a-commit and returns the current user's certs — the tech can access their certs via the quiz results screen (immediately after passing). A dedicated section on the team-member detail page is a small UI additive and best landed after the mobile UI ships (Phase 56.13c) so both surfaces are wired in the same session.

**Non-goals (v1, locked)**
- No drag-reorder for lesson ordering.
- No rich-text editor (markdown source only).
- No discussion forum.
- No email delivery of the cert PDF (in-app download only).
- No AI tutoring / hints.
- No confetti or celebration animation (PASS banner suffices).
- No leaderboard (deferred).
- No forced-completion gate on the quiz — techs can technically take the quiz before finishing lessons; the "Take Quiz" banner only appears after all lessons are complete, but the URL is accessible manually. This is intentional — retakes are unlimited anyway.

**Preflight**: `bash /app/scripts/preflight.sh` → **exit 0**.

**Screenshot evidence (verified end-to-end)**
1. `/tests` list — logged in as pool tech (`test-pool-tech@aquaterra.com`), shows exactly one card under the **Pool** section: "Certified Pool Operator (CPO) — Prep Course", 9 lessons · 50 quiz questions, `POOL` + `SYSTEM` badges, Start button, 0% progress ring.
2. `/tests/cpo-prep` — module detail with 9 lessons in the sidebar (0 / 9 complete), Chapter 1 markdown body rendered in the main panel, prep-material disclaimer in a yellow callout above the split panel.
3. `/tests/cpo-prep/quiz` — quiz runner mid-quiz on Question 1 of 50 with 4 choices + Next button. Verified `Question 1 of 50` counter renders correctly.
4. Results screen — submitted 50 wrong answers (chose first choice on every question), got 6% score with a red FAIL banner + full per-question review. Cert block correctly HIDDEN because failed (verified separately by curl in Phase 56.13a-commit — passing score returns a valid `certificate_id`, the PDF endpoint returns a `%PDF-1.4` with the disclaimer byte-matched).
5. `/admin/training` route exists and is admin-gated at `App.js` via `<AdminOnly>` wrapper.

**Certificate PDF download**
Confirmed working end-to-end in Phase 56.13a-commit (backend byte-match assertion passing). The Results screen's `Download Certificate PDF` button links to the same endpoint that was byte-verified. No new backend changes in this ship — the certificate flow was already complete.

**Files touched**
- `frontend/src/pages/training/TrainingList.jsx` (new)
- `frontend/src/pages/training/TrainingModuleDetail.jsx` (new)
- `frontend/src/pages/training/TrainingQuiz.jsx` (new)
- `frontend/src/pages/training/AdminTraining.jsx` (new)
- `frontend/src/App.js` (imports + 4 new routes)
- `frontend/src/layouts/AdminTopBar.jsx` (Tests chip + `GraduationCap` icon)
- `frontend/src/nav/roleNav.js` (Training entry on TECH_NAV.records)
- `memory/HANDOFF.md`, `memory/PRD.md`

**Priority order**
1. ✅ Phase 56.13a — Training subsystem + CPO drafts.
2. ✅ Phase 56.13a-commit — CPO seed + PDF cert.
3. ✅ Phase 56.10 — Visible algae + AI remediation dosing.
4. ✅ Phase 56.11 — Customer Equipment Photo Library.
5. ✅ Phase 56.13b — Training Web UI + "Tests" Nav (THIS SHIP).
6. **NEXT: Phase 56.13c** — Training Mobile UI (parity with the web pages above).
7. Then: Phase 56.10-mobile (mobile algae toggle UI) + Phase 56.11-mobile (mobile equipment library).
8. Then: Phase 56.13b-followup — Certifications section on team member profile + admin tenant-custom module editor + leaderboard.
9. **PAUSED**: 56.9b Zillow, T1-T6 calculators, 56.13d supplemental modules, 56.14 landscaper training, 56.15 handbook.
