# Mobile Parity Catch-up Audit — m-td73 finish + TD-78b/c mirror

Pre-flight only — **no code written**. HEAD `1f3a1d5e1`. `git status --short` = 1903 lines, but all except 3 are
backend `__pycache__/*.pyc` runtime noise. Non-pyc = the 3 long-standing untracked `{backend,frontend,mobile}/.env.example`.
No cross-session capture of mobile/memory files. Rogue `233a6c9a8` is already logged as TD-61 #11 (`dc7044810`), so the next incident is #12.

Leftover lock state from last cycle (to clear in Group 1): `skip-worktree` on `mobile/app/portal/profile.tsx` +
`memory/mobile/commit_log.md`; `.git/info/exclude` lists `memory/mobile_parity_audit.md` + `mobile/__tests__/portal-profile-save-td73.test.tsx`.

## Q1 — Mobile screens exposing closed/completed job detail to non-customer roles

| Screen | File | Closed-job edit gate today | Web parallel |
|---|---|---|---|
| Job detail | `app/job/[id].tsx` | **No K6.** Uses the OLD 24 h window: `canEditNow = !isCustomer && isWithinEditWindow(job)`. Footer "Job completed" chip + `job-edit-open` "Edit (Xh left)" button → notes/reason edit sheet (PATCH `/jobs/{id}`). After 24 h the button disappears for **every** role, even though BE `role_bypasses_edit_window()` lets K6 roles PATCH | `frontend/src/pages/jobs/JobDetail.jsx` (K6 `canEditCompleted`, no 24 h window) |
| Checklist / service report | `app/job/[id]/checklist.tsx` | **K6 present.** `canEditCompleted = locked && K6_UNLOCK_ROLES.has(role) && status === "completed"`; `effectiveLocked` drives every form + media block | Web has no separate checklist page — checklist editing lives inside JobDetail tabs, under the same banner |

## Q2 — Where the mobile K6 role set lives

- **Exactly ONE copy**: inline `const K6_UNLOCK_ROLES = new Set([...])` inside the component body of `app/job/[id]/checklist.tsx:897`
  — 7 roles (`super_admin admin manager tech technician owner employee`), **no `dispatcher`**.
- `src/lib/editWindow.ts` mirrors only the 24 h window (`EDIT_WINDOW_HOURS`, `isWithinEditWindow`) — no role list.
- `__tests__/job-k6-unlock.test.tsx` regex-parses the set out of `checklist.tsx` source.
- Canonical sources: BE `services/edit_window.py::K6_UNLOCK_ROLES` (8 incl. dispatcher), web `JobDetail.jsx` (8).
- Dispatchers can reach both screens (`RoleGate` `dispatcher_plus`).

## Q3 — Mobile Edit Profile background (settles m-td73)

- Mobile has **no modal**. `app/portal/profile.tsx` is a full page on light grey `colors.surfaceSecondary` (#F4F4F5) with
  white inputs (#FFFFFF, 1.5 px #E4E4E7 border) — i.e. light-themed like the web white modal, **not navy**.
- Input text is navy `#000080` because every input goes through `AppTextInput` (**Phase T1 sitewide input theme**:
  "white-bg / navy-text"; the theme style is applied LAST so it always wins — a per-screen `style` override is impossible).
- Web TD-73 modal inputs use `#0F172A`.
- **Call (proposed default)**: option (a) — update the assertion to `#000080`. By your rule (light bg → dark text) it would
  be (b), but (b) needs either editing the sitewide `AppTextInput` primitive (changes every input in the app) or bypassing
  it on one screen (breaks the T1 contract). The Save-button recolour (the operator-visible TD-73 change) is unaffected.

## Q4 — Closed-job surfaces without a direct web parallel

- `app/job/[id]/checklist.tsx` — the K6-unlocked editor. A banner is arguably MORE useful here than on job detail
  (it's where post-completion edits actually happen on mobile). Web shows the banner on JobDetail, which hosts the checklist tabs.
- Web JobDetail also has an OLDER amber K6 banner ("Editing after completion — this will be logged",
  `jd-k6-edit-after-completion-banner`); mobile has neither. Only TD-78b is in scope; the amber one is noted as a gap.

## TD-76f — no-op confirmed

Live: SR-detail `job_photos[].{thumb_url,full_url,url}` each carry exactly one `auth=`. Mobile fetches through `api.get`
(Bearer header, no bypass), and `withAuthToken` is idempotent (replaces an existing `auth=`, tested), so there's no double
param. Nothing to ship.

## Surprise → proposed scope adjustment

Mirroring TD-78b literally on mobile job detail (visible when `completed && K6 role`) would show
"edits are logged" while mobile job detail has **no K6 edit unlock**, so K6 roles lose the Edit button after 24 h.
Your dispatcher test ("sees edit controls enabled + banner visible") is impossible on job detail without first porting K6 there.

Proposed commits (Group 2):
1. `m-k6-lib` — extract `src/lib/k6Unlock.ts` (`K6_UNLOCK_ROLES`, `canEditCompletedJob(role, job)`); checklist imports
   it (behaviour unchanged); `job-k6-unlock.test.tsx` repointed to the lib. Single canonical mobile copy.
2. `m-td78b` — banner (exact web copy: **"Closed job — edits are logged to the audit history on this job."**,
   non-dismissible, `job-closed-edits-logged-banner`) on job detail + checklist, gated on `canEditCompletedJob`.
   Job detail: Edit button also shown when `canEditCompletedJob` (label "Edit" with no hours countdown), mirroring web K6
   on JobDetail. Tests for the 3 visibility cases per screen.
3. `m-td78c` — add `dispatcher` to the lib set + dispatcher test (closed job → edit controls + banner).

Alternative (strict scope): banner on checklist only (K6 already gates it there), skipping job detail.

Group 1 commits: `m-audit` (previous cycle's audit doc + this one) then `m-td73`.
