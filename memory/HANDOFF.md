# HANDOFF — most recent shipped phase

## Phase 56.13a · CPO Prep Training subsystem + chapter drafts (Feb 2026)

**What shipped:**
1. **Training backend subsystem** — `training_modules`, `training_progress`,
   `training_quiz_attempts` MongoDB collections; three Pydantic model
   families (`TrainingModuleIn/Update`, `TrainingProgressIn`, `TrainingQuizSubmit`);
   `/app/backend/routers/training.py` with 8 endpoints; registered on
   `api_router` in `server.py`.
2. **RBAC + tenant isolation**:
   - `customer` role → 403 on every endpoint.
   - `technician` w/ `department: pool` → sees `pool` + `both`.
   - `technician` w/ `department: landscaping` → sees `landscaping` + `both`.
   - `admin` / `super_admin` → sees all + can CRUD custom modules.
   - System modules (`is_system=True`, no `tenant_id`) are cross-tenant
     read-only. Custom modules are strictly tenant-scoped (verified by
     cross-tenant leak test using sunbelt admin).
3. **CPO prep chapter drafts (9 files)** — all authored in-house, 100%
   original, external standards cited by name + link only. Word counts:
   ```
   01_water_chemistry_fundamentals.md      734
   02_sanitization_and_oxidation.md        706
   03_filtration.md                        778
   04_circulation_and_hydraulics.md        810
   05_disinfection_and_rwi_prevention.md   731
   06_chemical_feed_and_automation.md      825
   07_facility_safety.md                   854
   08_regulations_and_code.md              856
   09_math_and_calculations.md             918
   ```
   All within the 400-1200 word guard band.
4. **CPO quiz drafts (`quiz.json`)** — 50 original multiple-choice
   questions across the 9 chapters. Every question has exactly 4 choices
   and exactly 1 correct answer. Passing score = 0.75.
5. **Seed script** — `/app/backend/training_seed/training_cpo.py`.
   Default is `dry_run=True`; the module ships a `--commit` CLI flag
   which was NOT invoked in this session. The DB is unchanged
   (`training_modules` count = 0, `is_system` count = 0).
6. **Backend subsystem tests** — 16 tests in `tests/test_training.py`
   covering:
   - RBAC matrix on `GET /api/training/modules` across all 5 roles.
   - Department filtering (pool tech blocked from landscaping module;
     `both`-department modules visible to all techs).
   - Admin-only writes (tech gets 403; admin can CRUD).
   - Tenant isolation (sunbelt admin cannot see aquaterra custom module).
   - Progress tracking (upsert, idempotent `$addToSet`, invalid lesson id).
   - Quiz scoring (perfect pass, partial fail below threshold).
   - Attempts list scoping (tech sees only own; admin can filter).
   - System-module immutability (PATCH + DELETE both return 409).
7. **Seed integrity tests** — 11 tests in `tests/test_training_cpo_seed.py`:
   - Every quiz question has exactly 1 `correct_choice_ids`.
   - ≥ 50 questions, passing score = 0.75.
   - Badge label = "CPO Prep — Completed" (never "CPO Certified").
   - Disclaimer string present verbatim on the module doc.
   - All 9 chapters within 400-1200 word bounds.
   - Chapter sha256 map logged for spot-check (no duplicate shas).
   - Dry-run reports `committed=False`, `is_system=True`.

**IP-safety commitments (locked):**
- No verbatim text from PHTA, NSPF, or any commercial CPO course.
- External standards (ANSI/APSP-11, ANSI/APSP-16, ANSI/APSP-7,
  CDC MAHC, VGB Act, ISPSC, ADA, OSHA, NEC 680, NFPA 704, NSF/ANSI 50,
  IAPMO) cited by name and canonical link only.
- Badge label enforced by test to never say "CPO Certified".
- Persistent disclaimer on the module doc: *"This is prep material only.
  Official CPO certification requires enrollment with an authorized
  provider (PHTA / NSPF)."*

**Verification:**
- 16/16 backend subsystem tests passing (`test_training.py`).
- 11/11 seed integrity tests passing (`test_training_cpo_seed.py`).
- `python -m training_seed.training_cpo` (dry-run) prints the payload
  summary with `committed=false`.
- `GET /api/training/modules` returns `[]` for admin (no seed committed).
- `GET /api/training/modules` returns HTTP 403 for customer role.
- `db.training_modules.count_documents({}) == 0` (verified).
- `bash /app/scripts/preflight.sh` → exit 0.

**What is deferred:**
- **Phase 56.13a-commit** — the small mechanical ship that runs
  `python -m training_seed.training_cpo --commit` after user reviews
  and approves the 9 chapter `.md` files + `quiz.json`.
- **Phase 56.10** — Visible algae field + AI remediation dosing.
- **Phase 56.11** — Customer Equipment Photo Library (11 equipment
  types, ≤4 photos each, admin-only delete, tenant isolation).
- **Phase 56.13b / 56.13c** — Web + mobile Training UI (including
  top-level "Tests" nav).

**Updated priority order (confirmed with user):**
1. ✅ Phase 56.13a — Training backend + subsystem + CPO chapter drafts
   (DONE — this ship).
2. **Next: Phase 56.13a-commit** — after user reviews `.md` chapters
   + quiz, run `python -m training_seed.training_cpo --commit`.
3. Then: Phase 56.10 — Visible algae field + AI remediation dosing.
4. Then: Phase 56.11 — Customer Equipment Photo Library.
5. **PAUSED**: 56.9b Zillow, T1–T6 calculators, 56.13b/c UI, 56.13d
   supplemental pool modules, 56.14 landscaper training, 56.15 handbook.

**Deviation from spec (noted for record):**
- User's spec named the seed package `backend/seed/`. That path
  collides with the existing `/app/backend/seed.py` (611-line startup
  seeder consumed by `server.py`). The seed script and chapter folder
  were placed at `/app/backend/training_seed/` instead. Invocation
  becomes `python -m training_seed.training_cpo --commit` (from
  `/app/backend`) or `python -m backend.training_seed.training_cpo`
  (from `/app`). All spec requirements (dry-run default, `--commit`
  flag, no DB write this session) are honored.

**Files touched:**
- `backend/models.py` — added Training* Pydantic models.
- `backend/routers/training.py` — 8-endpoint router (new).
- `backend/server.py` — registered `training_router`.
- `backend/tests/conftest.py` — added `training_*` cleanup queries
  + `test-pool-tech@aquaterra.com` cleanup.
- `backend/tests/test_training.py` — 16 subsystem tests (new).
- `backend/tests/test_training_cpo_seed.py` — 11 integrity tests (new).
- `backend/training_seed/__init__.py` — package marker (new).
- `backend/training_seed/training_cpo.py` — seed script, dry-run default (new).
- `backend/training_seed/training_cpo_chapters/01…09_*.md` — 9 chapter
  drafts (new).
- `backend/training_seed/training_cpo_chapters/quiz.json` — 50-question
  quiz (new).
