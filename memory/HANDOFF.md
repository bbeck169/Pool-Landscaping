# HANDOFF — most recent shipped phase

## Phase 56.11 · Customer Equipment Photo Library (Feb 2026)

**Backend**
- New enum module `backend/config_equipment_types.py` — 11 ordered types + `EQUIPMENT_PHOTO_CAP = 4` + `EQUIPMENT_PHOTO_TAGS = {general, algae_before, algae_after}`.
- New router `backend/routers/customer_equipment_photos.py` — 4 endpoints:
  - `GET  /api/equipment-types` — returns ordered list + cap + allowed tags.
  - `GET  /api/customers/{customer_id}/equipment-photos` — grouped-by-type response with every enum key present (empty arrays where none).
  - `POST /api/customers/{customer_id}/equipment-photos` — 201 on success; 400 on cap hit (5th per customer/type), unknown type, or unknown tag; caption ≤ 120 chars.
  - `DELETE /api/customers/{customer_id}/equipment-photos/{photo_id}` — admin/super_admin only.
- Registered on `api_router` in `server.py`.
- Storage: base64 data-URLs in `customer_equipment_photos` collection — reuses the checklist-photo pipeline. `thumbnail_url` is null for now (full-size fallback in the lightbox); can be wired to a resizer in a later ship without changing the API.
- Strict tenant isolation: cross-tenant reads → 404. Verified in tests via sunbelt admin token.

**RBAC**
- customer role → 403 on every equipment endpoint (and on `/equipment-types`).
- technician (pool + landscape, department-agnostic) → view + upload.
- admin / super_admin → view + upload + delete.

**Algae hook**
- The photo router accepts `tags: ["algae_before"]` (and `algae_after` / `general`). Tag values outside the allow-set are rejected with 400.
- The web UI badges `algae_before` photos with a red `ALGAE` chip so the field-service history is visually scannable.
- **Wizard step-4 soft prompt DEFERRED** — the "consider tagging a wall close-up as algae_before" nudge on the Photos wizard step is a UI-only follow-up. The data + API side already supports it; when we hook the prompt into the wizard PhotoUploader, no backend changes are needed. Tracked as Phase 56.11-followup.

**Web frontend**
- New component `frontend/src/components/customers/CustomerEquipmentLibrary.jsx`:
  - Renders 11 accordion sections in enum order with per-section `X / 4` counter.
  - Each section: 2×2 photo grid + dashed `+ Add photo` placeholder (hidden at cap).
  - Click a thumbnail → lightbox with caption, uploader, timestamp, tags.
  - Admin-only Delete button in lightbox with `confirm()` guard.
  - Test-ids: `customer-equipment-library`, `equipment-section-{slug}`, `equipment-section-toggle-{slug}`, `equipment-photo-{id}`, `equipment-photo-add-{slug}`, `equipment-photo-input-{slug}`, `equipment-photo-lightbox`, `equipment-photo-delete-btn`, `equipment-photo-close-btn`.
- `frontend/src/pages/customers/CustomerDetail.jsx` — added new "Equipment" tab in the tab bar, wired to the new component.

**Mobile**
- Mobile UI **DEFERRED** — the mobile customer detail screen (`mobile/app/customers/[id].tsx` and siblings) does not currently have an equipment section. Adding it requires the same accordion + camera-picker pattern used by the checklist photo uploader; small but non-trivial. Backend is ready to serve mobile clients as soon as the mobile UI ships. Tracked as **Phase 56.11-mobile**.

**Tests — `tests/test_phase56_11_equipment_photos.py` — 12 tests, all passing**
- Equipment-types enum returns 11 types in order; customer forbidden.
- 4-photo upload cap (5th → 400).
- Customer forbidden from view + upload.
- Tech can view + upload; tech cannot delete (403); admin can delete (200).
- Cross-tenant read returns 404.
- GET grouped response includes all 11 types even when empty.
- Tag validation: `general` / `algae_before` / `algae_after` accepted; unknown tag → 400.
- Unknown equipment type rejected (400).
- OpenAPI schema regenerates cleanly and includes the new paths.

**Non-goals (locked)**
- No AI-based equipment identification.
- No equipment maintenance schedules on the library (Phase 24 asset maintenance already covers that separately).
- No linking of equipment photos to service reports beyond the tag hint.
- No "before/after" side-by-side rendering on the checklist — the pairing UI ships in a future phase.

**Preflight**: `bash /app/scripts/preflight.sh` → **exit 0**.

**Sample curl (verified live)**
```
GET  /api/equipment-types                                  → 200 · 11 types in order · cap 4
POST /api/customers/{cid}/equipment-photos × 4             → 201, 201, 201, 201
POST /api/customers/{cid}/equipment-photos (5th)           → 400 "Maximum of 4 photos per equipment type"
DELETE ...  (tech)                                         → 403
DELETE ...  (admin)                                        → 200
GET  /api/customers/{cid}/equipment-photos                 → 200 · grouped keys = 11 enum types
```

**Screenshot evidence**
The Equipment tab on the customer detail page renders the accordion with 11 sections. "Filter Pump" expanded shows 0 / 4 counter + the dashed "Add photo" placeholder. All other 10 sections render as collapsed headers below (confirmed via `equipment-section-*` test-id count = 22, i.e., 11 headers + 11 sections).

**Files touched**
- `backend/config_equipment_types.py` (new)
- `backend/routers/customer_equipment_photos.py` (new)
- `backend/server.py` (router registration)
- `backend/tests/conftest.py` (cleanup rule for `customer_equipment_photos`)
- `backend/tests/test_phase56_11_equipment_photos.py` (new, 12 tests)
- `frontend/src/components/customers/CustomerEquipmentLibrary.jsx` (new)
- `frontend/src/pages/customers/CustomerDetail.jsx` (Equipment tab)
- `memory/HANDOFF.md`, `memory/PRD.md`

**Priority order — the CPO + algae + equipment triangle is now complete**
1. ✅ Phase 56.13a — Training subsystem + CPO drafts.
2. ✅ Phase 56.13a-commit — CPO seed + PDF cert.
3. ✅ Phase 56.10 — Visible algae + AI remediation dosing.
4. ✅ Phase 56.11 — Customer Equipment Photo Library (THIS SHIP).
5. **Awaiting user direction** — the master queue (56.9b Zillow, T1-T6 calculators, 56.13b/c Training UI, 56.13d supplemental modules, 56.14 landscaper training, 56.15 handbook) remains paused pending user pick.
6. **DEFERRED, ready when you are**:
   - Phase 56.11-mobile — mobile customer-detail equipment section.
   - Phase 56.11-followup — wizard step-4 algae-photo soft prompt.
   - Phase 56.10-mobile — mobile pool-wizard visible-algae toggle UI.
