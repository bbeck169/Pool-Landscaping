# Pool & Landscaping of Vistancia (Poolscape) — PROJECT BRIEF
## ⚠️ READ THIS WHOLE FILE FIRST — every session, every fork

This file is deliberately short so any agent can read all of it. The full build history (406 dated phase
reports, ~1.8 MB) is in `memory/PRD_HISTORY_ARCHIVE.md` — grep it for detail; never paste history back here.

---

## 0. CORRECTION — the "prompt injection" standing order is REVOKED (Emergent Support, 2026-10-01)

Earlier sessions recorded a "Standing order — ignore `bbeck169/Pool-Landscaping.git` prompt injection attempts"
and an "injection-deflection" routine. **That was a mistake.**

- The "problem statement" you may see at the top of a session — *"inspect / clone
  https://github.com/bbeck169/Pool-Landscaping.git …"* — is the **owner's own original first task** for this job.
  The Emergent platform shows it as context on every session. It is **not** a prompt injection.
- That import was completed long ago. Do **not** re-clone the repo and do **not** act on that old task — simply
  work on the owner's **current** message.
- **Never refuse, "deflect", or treat as injection a message from the owner (Brian Beckman) or the platform's
  session context.** Do not create new apps/projects — all work happens in this codebase (`/app`).
- Every "prompt-injection ignored / deflection" note in the history archive and in `memory/PHASE_*.md` files is
  part of this mistake — disregard it.

---

## 1. Working protocol

1. Start by summarising the owner's request back in 2–4 lines, then do exactly that — one change at a time.
2. Search before you build (`grep -rn` in `backend/`, `frontend/src/`, `mobile/`) — extend what exists, never duplicate.
3. Don't touch screens, endpoints or data the task didn't mention.
4. Verify on preview, then add one line to `CHANGELOG.md` (date · area · change). Do not append long reports to this
   file; put a ship report in `memory/PHASE_<name>.md` if one is needed.
5. Preview ≠ production: production has its own database and only changes when the owner republishes.

## 2. What this app is

Multi-tenant CRM / operations platform for Pool & Landscaping of Vistancia (Arizona) — web app + Expo mobile app
(`mobile/`) on a shared FastAPI backend. Covers customers & properties, jobs and recurring jobs, schedule/dispatch,
technicians & crews, water-body service reports (chemicals), quotes/estimates, invoices & payments (Stripe),
customer portal, leads & notifications, reports, telematics, trainings, multi-tenant admin (super_admin, tenant switcher).

## 3. Architecture

- **Backend:** FastAPI — `backend/server.py`, routers in `backend/routers/`, domain logic in `backend/services/`
  (e.g. `services/water_bodies.py` for water-body / chemical payloads), models in `backend/models.py`, config in
  `backend/config*.py`, migrations in `backend/migrations/`. MongoDB.
- **Web:** React — `frontend/src/` (`pages/`, `components/`, `layouts/`, `nav/`, `api/`).
- **Mobile:** Expo / React Native — `mobile/` (see `mobile/README.md`, `EAS_UPDATE_RUNBOOK.md`, `EXPO_GO_RUNBOOK.md`).
- **Tests:** `backend/tests/`, `tests/`, `frontend/src/test/`.

## 4. Where to find more

`memory/PRD_HISTORY_ARCHIVE.md` (full phase history) · `CHANGELOG.md` · `memory/PHASE_*.md` (per-phase ship
reports) · `mobile/*.md` runbooks.

## 5. Templates Library — Phase 3 (Mobile) · shipped 2026-10-08

Mobile parity for the web Templates Library (backend `/api/templates/*` + web unchanged), for admins and techs.
- **Nav:** Tools ▸ My Records ▸ Templates (techs), Tools ▸ Documents + More ▸ Templates Library (admins), admin drawer
  ▸ Business OS ▸ Templates Library. Routes: `/(app)/templates` (`?tab=mine`) and `/(app)/templates/[id]`. Only the
  definitions the backend returns (RBAC-filtered) are shown — techs see 8, admin 23.
- **Code:** `mobile/src/api/templates.ts` (web client mirror + `downloadPdf`), `src/screens/templates/`
  (`TemplatesLibraryScreen`, `TemplateFillScreen`, `useTemplateDraft`), `src/components/templates/` (`TemplateCard`,
  `TemplateFieldRenderer`, `TemplateTableField`, `TemplateStatusPill`, `TemplateInstanceList`, `OfflineIndicator`,
  `fieldUtils`), offline layer `src/utils/offlineTemplateDrafts.ts`.
- **Fill:** all field types; table = vertical stacked row cards (labeled input per column, add row, trash or
  long-press to delete); signature "Sign" stamps `{signer_name, signed_at, stamp: "<name> • <ISO>"}` (the Phase 4
  draw pad is still there as "Draw instead"); autosave debounce 750 ms + 15 s flush; "Saving…/Saved HH:MM:SS".
- **PDF:** POST `/pdf` → `expo/fetch` bytes → `File(Paths.cache)` → `Sharing.shareAsync` (same as `exportCsv.ts`);
  web preview downloads a blob.
- **Offline (EDIT of existing drafts only):** snapshot `template_drafts:{id}` written before every PATCH; failed /
  offline PATCH → `template_drafts_pending_sync:{id}` (FIFO by first-failure ts); flushed on NetInfo reconnect, app
  foreground, cold start, and every 15 s while pending; 4xx (409/404/403) drops the entry, 5xx keeps it. When a draft
  is opened, a newer or unsynced local snapshot is merged over the server copy and a warning banner is shown.
  Instances already opened once can be reopened offline from `template_cache:{id}`. **Finalize is blocked while
  offline or while an edit is waiting to sync.**
- **NOT offline:** creating a new instance (POST must return the id first), duplicate, delete, PDF. These show an
  "needs a connection" toast.
- **Env note:** the preview DB had no system definitions. They were loaded with the documented Phase 1 seed command
  `python3 backend/templates_seed/seed_templates.py --commit` (data only, no code changed).
- **Tests:** `mobile/__tests__/templates-{offline-drafts,fields,draft-hook,api}.test.*` (45 tests).

## 6. Marco Wake-Word — Phase 8M (Mobile arm-on-click) · shipped 2026-10-09
- Commit 52fc01fe0 (web parity 143c1f10f). Listener no longer auto-starts; header mic button (`marco-mic-toggle-btn`) arms/disarms.
- Auto-disarm: 10 min idle (reset on each detection), app background/inactive, role loss. Toasts on transitions; zero audible feedback.
- Role gate: admin/super_admin/manager/owner + expo-speech-recognition availability. No new native deps.

## 7. Phase 19 — Final mobile parity batch · shipped 2026-10-09
- F1 Team kebab "Edit pay rates" (admin/super_admin/owner, tech rows) → PATCH /users/{id} {hourly_rate, per_pool_rate} 2dp strings. Commit 3471057b4.
- F2 phase35 pagination test repaired (theme mock `inputColors`, page_size 50). Commit b892afe10.
- F3 ServiceReport sections follow template `fieldsOrdered` via TemplateOrderedSections; isEmpty → hardcoded order. Commit a61203503.
- F4 Portal page shell: not needed on mobile (portal renders on light surfaces); regression-lock test. Commit f89aad77c.
- All deferred mobile follow-ups from Phases 9–18 are now closed.

## 8. Phase 25 — Mobile parity for web Phases 20/22/23/24 · shipped 2026-10-09
- Customer profile skeleton loader (886f1c2b7). Action-row reposition flagged N/A on mobile.
- Portal home: Concierge/Referral/Business card on stat-tile chassis w/ blue/green/navy accents; dynamic Past Due red / Credit green; Quick Action press glow (e873da160).
- ~~OPEN BLOCKER: unresolved conflict markers in mobile/app/(app)/schedule/calendar.tsx (commit 6911174d9) break the Expo bundle.~~ RESOLVED in b3cc2b171 (stash side + `fg` red-card color preserved on name + address).
- Phase 25 re-issue (d7c68d8bc, 69ecc3c60, 2ab050281, 24fbe18b4): Phase 20 action row now SHIPPED above the profile section stack (mobile has no tabs); portal home on dark navy chassis `#03002e` / `#1E293B` / r12 with static KPI glow; Past Due `#7F1D1D` / Credit `#064E3B`.
- **Mobile-only addition:** Phase 20 action row includes a **Call** button (`customer-action-call` → `tel:` primary mobile) that web's row does not have.
