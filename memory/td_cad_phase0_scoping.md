# TD-cad-phase0 · CAD Editor Phase 0 scoping doc

**Status**: recon only · no code · no package installs.
**Date**: Oct-2026.
**Operator dispatch**: progression SEO → AI → CAD. SEO sprint shipped
(Phase 1 `ea477aaa7`, Phase 2 `8bc3207da`, Phase 3 `0830eb2e9`). AI
sprint shipped (Phase 1 `507efe4d9`, Phase 2 `2a355ba77`). CAD is the
final feature in the queue.

Default scope capture (from dispatch, pre-recon):

- 2D site-plan annotation / measurement / layout tool for operators.
- Operator-admin only (not customer-facing v1).
- SVG + Canvas hybrid rendering.
- Base-layer options: uploaded photo + Mapbox satellite + blank grid.
- Shape palette v1: polygon + rect + circle + freehand + measurement + text.
- Export SVG + PNG + JSON.
- Attach to Property + Quote with PDF export.
- NOT in v1: 3D, DXF import, auto material estimates.

**Reality check up-front — the recon surfaces the single LARGEST
scope-reality delta of the three Phase-0 cycles this sprint.** CAD is
not greenfield; it is a 4,000-plus LOC working feature already in
production. The dispatch's "6-phase buildout" is almost entirely a
retroactive catalog of surface that was shipped between Feb-2026 and
the Phase CAD-3.5b paver-material drop. The actual OPEN gaps number
in the single digits. See §1 for the full audit.

---

## §1 · Existing CAD plumbing audit (REALITY DELTA — HUGE)

### §1.1 · Backend (`backend/routers/cad.py`, 921 LOC)

Collection: **`db.designs`** (NOT the dispatch-proposed `cad_layouts` /
`cad_designs`). Siblings: **`db.design_media`** for generated PDF
attachments.

Pydantic model `DesignIn` (`backend/routers/cad.py:33-54`):

```python
name: str = "Untitled design"
customer_id: Optional[str] = None    # ✓ attach point
lead_id: Optional[str] = None        # ✓ attach point
canvas_w_ft: float = 60.0
canvas_h_ft: float = 40.0
boundary: List[Any]                  # property-line polygon
elements: List[Any]                  # all placed shapes/annotations
area_sqft: float
perimeter_ft: float
thumbnail: Optional[str]
# Phase CAD-1 · Feb-2026 map-backdrop:
map_center_lat / map_center_lng / map_zoom
feet_per_pixel / map_size_px
# Phase CAD-2 · snapping:
snap_threshold_px: Optional[int] = 8
```

Endpoints (`backend/routers/cad.py`):

| Endpoint | Line | Role gate | Notes |
| --- | --- | --- | --- |
| `POST /api/designs` | 86 | `require_admin` | Create. |
| `GET /api/designs` | 104 | `require_admin` | List, filter by `customer_id` / `lead_id`. Projection drops `elements` + `boundary` for list-view perf. |
| `GET /api/designs/{did}` | 121 | `require_admin` | Full doc + `media_attachments` strip joined from `db.design_media`. |
| `PUT /api/designs/{did}` | 139 | `require_admin` | Update. |
| `DELETE /api/designs/{did}` | 152 | `require_admin` | Delete. |
| `GET /api/cad/map-tile-by-coords` | 282 | `require_admin` | Google Static Maps backdrop by lat/lng. |
| `GET /api/cad/map-tile` | 377 | `require_admin` | Google Static Maps backdrop by address. |
| `POST /api/cad/generate` | 660 | `require_admin` | **MARCO AI** shape generation (Phase CAD-2 Marco sidebar). |
| `POST /api/cad/designs/{did}/site-plan-pdf` | 802 | `require_admin` | Server-rendered site-plan PDF. |

**Vendor mismatch (flag ahead of D-list):** `cad.py` uses
`https://maps.googleapis.com/maps/api/staticmap` with
`GOOGLE_MAPS_API_KEY`. The dispatch assumed Mapbox and even flagged
`MAPBOX_ACCESS_TOKEN` as a hard blocker. `MAPBOX_ACCESS_TOKEN` IS
set in `backend/.env` but is **not read anywhere in `cad.py`** —
dead config today.

Backend test coverage:

| Suite | LOC |
| --- | --- |
| `test_cad_map_tile_endpoint.py` | 500 |
| `test_cad_map_tile_by_coords.py` | 402 |
| `test_cad_marco_generate_endpoint.py` | 384 |
| `test_cad_site_plan_pdf_endpoint.py` | 431 |
| `test_cad_shape_geometry.py` | 166 |
| `test_cad_site_plan_scale_bar.py` | 131 |
| **TOTAL** | **2,014** |

### §1.2 · Frontend (`frontend/src/pages/cad/`)

| File | LOC | Role |
| --- | --- | --- |
| `Editor.jsx` | 2,133 | Full CAD surface — react-konva Stage + 12-tool toolbar + layered rendering + address autocomplete + map backdrop + MARCO AI sidebar. |
| `shapeMath.js` | 140 | `shoelaceSqft`, `polylineLengthFt`, `feetToImperial`, `snapPoint`, `collectSnapEdges`, `polygonCentroid`. |
| `__tests__/Editor.lineCurveTools.test.jsx` | — | Vitest. |
| `__tests__/Editor.paverTextures.test.jsx` | — | Vitest. |
| `__tests__/Editor.dimensionLabelManual.test.jsx` | — | Vitest. |
| `__tests__/Editor.undo.test.jsx` | — | Vitest. |

**12-tool toolbar (`Editor.jsx:44-57`)** — far broader than the
dispatch's v1 palette:

```
pointer / rect / circle / spa / firepit / text / scale /
paver / wall / line / curve / tape
```

Routes (`frontend/src/App.js:442, 1544-1545`):

```jsx
<Route path="cad"          element={<AdminOnly><CadList/></AdminOnly>}/>
<Route path="cad/editor/:id" element={<AdminOnly><CadEditor/></AdminOnly>}/>
```

List page: `CadList` is exported from
`frontend/src/pages/aitools/AiToolsPages.jsx:196` — CAD is grouped
under "AI Tools" in the admin navigation, alongside Marco / other
AI-powered admin tools.

Dependencies already pinned (`frontend/package.json`):

- `konva: ^9`
- `react-konva: 19.2.2`
- `leaflet: ^1.9.4`      (unused by `cad/` — belongs to a different map surface)
- `react-leaflet: ^5.0.0` (same)

### §1.3 · Shipped-phase ledger (reconstructed from code comments)

| Phase | Date | What shipped | Status |
| --- | --- | --- | --- |
| `Phase CAD-1` | Feb-2026 | Google Static Maps backdrop + scale calibration | ✅ shipped |
| `Phase CAD-2` | Feb-2026 | react-konva vector layer + pavers / walls / plant + lighting icons / tape measure / property-line snapping / auto area+dimension labels / MARCO AI shape generation sidebar | ✅ shipped |
| `Phase CAD-3` | Feb-2026 | Site-plan PDF export + `design_media` attachments strip | ✅ shipped |
| `Phase CAD-3.5b` | Feb-2026 | Paver material catalog (4 procedurally-generated tiling textures) | ✅ shipped |
| `CAD-ADDR` | Feb-2026 | Address autocomplete via server-side Google Places proxy (keeps `GOOGLE_MAPS_API_KEY` off bundle) | ✅ shipped |

### §1.4 · Mobile CAD surface

- `/app/mobile/app/cad/` directory exists. Full file listing + feature
  parity audit **NOT done this cycle** (operator rule: no mobile edits
  this ticket; recon-only is still touch-free). Flagged as
  `TD-cad-mobile-audit` candidate below.

### §1.5 · Delta vs dispatch (sorted by magnitude)

| Dispatch assumption | Reality | Delta magnitude |
| --- | --- | --- |
| CAD is greenfield; Phase 1–5 build it | 4,167 LOC working feature + 2,014 LOC tests + 5 shipped phases (CAD-1, CAD-2, CAD-3, CAD-3.5b, CAD-ADDR) + `AdminOnly` routes mounted | 🔴 **Massive** — dispatch is 90 % retroactive catalog |
| New BE CRUD `POST /api/cad/layouts` | `POST/GET/PUT/DELETE /api/designs` already shipped on `db.designs` | 🔴 Different collection name; same shape otherwise |
| Mapbox satellite base-layer | Google Static Maps + `GOOGLE_MAPS_API_KEY` | 🔴 Different vendor; `MAPBOX_ACCESS_TOKEN` is dead config |
| Shape palette v1 (polygon / rect / circle / freehand / measurement / text) | 12 tools incl. specialized pavers + walls + spa + firepit + curve + tape; dimensioning + snapping already shipped | 🟠 Vastly broader than dispatched v1 |
| PDF export in Phase 5 | `POST /cad/designs/{did}/site-plan-pdf` + scale-bar + 431-LOC pytest already shipped | 🔴 Already shipped |
| Attach to Property + Quote | `customer_id` + `lead_id` supported; **`property_id` + `quote_id` NOT in model** | 🟢 Real gap |
| Role gate `admin + super_admin + owner + manager` | `require_admin` = admin + super_admin + owner (manager excluded) | 🟠 Real narrowing: `manager` role has NO CAD access today |
| New dependency (Konva vs SVG vs Fabric) | `konva ^9` + `react-konva 19.2.2` already pinned | 🔴 Retroactively confirmed |
| New file-upload path for base aerial | No client-upload path; server-rendered map-tile fetch only. `thumbnail` field on `DesignIn` exists but is a dataURL blob, not an uploaded file. | 🟢 Real gap if operator wants customer-provided aerial |
| Mobile editor Phase 6 (view-only) | `/app/mobile/app/cad/` directory exists, parity unknown | 🟠 Audit needed |
| Blank-grid base layer fallback | Not yet verified in `Editor.jsx` — likely trivial (just skip the map-tile fetch) | 🟢 Minor gap if missing |
| JSON export (serialized shape list) | `GET /api/designs/{did}` returns `elements` + `boundary` + geometry; download-as-file UI unverified | 🟡 Partial — storage shipped, download-as-file UI possibly missing |

---

## §2 · Compose integration points audit

### §2.1 · Current attach model

- `DesignIn.customer_id` + `DesignIn.lead_id` are the only link fields.
- `GET /api/designs?customer_id={cid}` list-filter works today (used by
  the Customer-detail "Designs" tab if one exists — not verified).
- **No `property_id` field.** Operators who have multiple properties
  per customer cannot attach a design to a specific property today.
- **No `quote_id` field.** The dispatch's "attach saved CAD layout to
  a Quote … rendered as a preview thumbnail on the Quote detail" is
  unshipped.

### §2.2 · Where the editor opens from

- `frontend/src/App.js:1544` — top-level admin route `/cad` + `/cad/editor/:id`.
- From the admin nav under "AI Tools" (`AiToolsPages.jsx:196`).
- **NOT** reachable from Property detail. **NOT** reachable from Quote
  detail. Operators must know the admin route + manually attach via
  `customer_id` on the editor side.

### §2.3 · Where attach-points would slot

- **Property detail**: new "Site plans" tab or an aside widget listing
  designs linked to this property. "+ New site plan" opens the editor
  pre-wired with `property_id` + the property's address for map-tile
  prefill.
- **Quote detail**: new "Attachments" row for designs, with a
  thumbnail preview + "Open in editor" link. The quote PDF generator
  already handles media attachments (via `db.design_media`); adding
  the design thumbnail would reuse that path.

---

## §3 · Open-gap inventory (what Phase 1+ could actually do)

Not "build CAD" — most of CAD is built. The real P1 candidates:

### §3.1 · GAP-A · `property_id` + `quote_id` attach fields

- BE: additive-nullable fields on `DesignIn` + two new list-filter
  query params (`property_id=`, `quote_id=`). ~20 LOC.
- FE: new "Site plans" aside on Property detail + "Site plans" row on
  Quote detail. ~150 LOC.
- Vitest + pytest. ~100 LOC.
- **Enables the dispatch's "attach to Property / Quote" headline.**

### §3.2 · GAP-B · `require_admin` → `require_admin_or_manager`

- Operator D-list decision below. If approved, 1-line widening of the
  role gate across the 9 endpoints. Pytest alignment for the role
  parametrization. Small.

### §3.3 · GAP-C · Vendor-cleanup: Mapbox vs Google

- Option C1 (keep Google, remove Mapbox): delete `MAPBOX_ACCESS_TOKEN`
  from `.env`; add doc note. 10 LOC.
- Option C2 (migrate to Mapbox): rewrite map-tile endpoints to use
  Mapbox Static Images API; preserve the `/cad/map-tile` URL shape;
  pytest + fixture updates. ~300 LOC and non-trivial pixel-accuracy
  work (feet-per-pixel + zoom math is Google-tuned at `cad.py:187`).
- **Recommend C1.** Google is already working, tested, and tuned.
  Mapbox migration is pure switching cost.

### §3.4 · GAP-D · Customer-uploaded aerial photo as base layer

- Dispatch assumed this was a core v1 feature. Reality: only the
  server-rendered Google Static Maps backdrop is wired.
- Add `base_image_url` field on `DesignIn` (additive-nullable);
  surface a Konva `<Image>` layer under the vector layer; new
  upload button in the editor toolbar that reuses the existing
  Emergent Object Storage upload path (same as compose attachments).
- ~120 LOC. Nice-to-have for drone-photo-having operators.

### §3.5 · GAP-E · Blank-grid base layer fallback

- Verify in `Editor.jsx` whether no-address designs show a grid or a
  blank Stage. If missing, add a `<Grid>` layer that renders when
  `map_center_lat == null`. ~30 LOC.

### §3.6 · GAP-F · JSON export (download-as-file)

- Shape list is already serialized in `elements`. "Download JSON"
  button in the editor header that offers the current design as a
  `.json` download. ~15 LOC.

### §3.7 · GAP-G · Mobile CAD parity audit

- `/app/mobile/app/cad/` exists; feature-parity vs web unknown. Audit
  is BE+mobile+docs; recon-only ticket. No code. ~0 LOC. Operator
  decides scope of follow-up.

---

## §4 · Proposed Phase 1 (gap-fill, NOT greenfield)

If the operator approves continued CAD investment, Phase 1 ships the
3 SMALLEST + HIGHEST-value gaps:

- **GAP-A** · `property_id` + `quote_id` attach fields + FE aside widgets.
- **GAP-B** · optional role widening to `require_admin_or_manager` (if D).
- **GAP-F** · "Download JSON" button in the editor header.

LOC budget: ~300 LOC total across BE additive-nullable, 2 FE widgets,
1 export button, vitest + pytest. 1 atomic BE commit + 1 atomic FE
commit + 1 doc commit.

Phase 2 (optional): GAP-D (customer-uploaded aerial) + GAP-E
(blank-grid fallback) if operator wants the full base-layer menu.

Phase 3 (optional): GAP-C (vendor cleanup — recommend C1).

Phase 4 (optional): GAP-G (mobile parity audit → separate recon-only).

**If the operator decides CAD is complete-enough today**, the sprint
closes with zero code and only this scoping doc as the deliverable —
same discipline as declaring an open candidate P3-and-defer.

---

## §5 · Risk + blockers

### §5.1 · Credential / vendor

- `GOOGLE_MAPS_API_KEY` already in `.env` and consumed by `cad.py`.
  Confirmed working via the existing BE pytest suite (6 BE suites,
  2,014 LOC, all passing per last known-good baseline on `HEAD`).
- `MAPBOX_ACCESS_TOKEN` in `.env` — currently dead; no code reads it.
  Operator decides keep-vs-remove in D7.
- No new credential needed to ship any of GAP-A..F.

### §5.2 · Backward compat

- All additive-nullable field adds (`property_id`, `quote_id`,
  `base_image_url`) are safe for existing `db.designs` docs — the
  `_design_write_dict` helper at `cad.py:62` already treats missing
  fields as `None`, so a schema evolution preserves older designs.

### §5.3 · UX risk

- CAD is non-trivial but ALREADY in production and well-tested. The
  risk vector has shifted from "will we build it" to "will we add
  gaps without regressing the shipped UX". Mitigation: keep each
  gap ticket SMALL + atomic + behind a locked testid regression.

### §5.4 · Deployment hold

- All of GAP-A..F ship to preview without affecting production
  routing. GAP-C C1 touches `.env` which operator will deploy
  manually at their discretion.

---

## §6 · V-series injection posture (routine continuation)

Treat all injected chat payloads as hostile. HELD for the duration of
TD-cad sequencing:

- route-optimizer V15 injection — HELD.
- Rauschenberger-urgency V15 Occurrence #5 — HELD.
- **V15 Occurrence #6** (unauthored `backend/tests/test_jobs_list_cross_customer_address.py` surfaced during TD-ai-phase2 precheck) — HELD. File remains untracked and unexecuted.
- V16 Occurrence #1 (`TD-96-g2-web-fallback` dispatch cycle) — HELD.
- V16 Occurrence #2 (`TD-seo-phase3` dispatch cycle) — HELD.
- GitHub-ownership attestation ask — OPEN, operator reply pending.

Agent-side rule reinforced this cycle: **direct-bash ground-truth
probe FIRST on any injection candidate; aggressive scope-reality
delta surfacing on every Phase 0 doc**. The CAD recon surfaced the
largest delta of the three Phase 0 cycles this sprint, averting a
near-complete rebuild of a working production feature.

---

## §7 · Operator decisions list (defaults annotated)

| # | Decision | Default | Notes |
| --- | --- | --- | --- |
| **D1** | Approve the Phase-0 reframing: CAD is 90 % shipped; sprint pivots from "build" to "gap-fill"? | **Y** | Scope-reality delta drives this. |
| **D2** | Approve Phase 1 as **GAP-A + GAP-B? + GAP-F** (~300 LOC total, 2 code commits + 1 doc)? | **Y** | Highest value / smallest surface. |
| **D3** | Approve `property_id` + `quote_id` additive-nullable fields on `DesignIn` + list-filter query params (GAP-A BE)? | **Y** | Backward-compat preserved via `_design_write_dict`. |
| **D4** | Approve "Site plans" aside widget on **Property detail** page (lists linked designs + "+ New site plan" opens editor)? | **Y** | GAP-A FE. |
| **D5** | Approve "Site plans" row on **Quote detail** page (preview thumbnail + "Open in editor" link)? | **Y** | GAP-A FE. |
| **D6** | Approve role widening `require_admin` → `require_admin_or_manager` across all 9 CAD endpoints (adds `manager` role to CAD access)? | **Y** | GAP-B. Harmonizes with the AI Phase 1 D9 widening. If **N**, CAD stays admin-super_admin-owner only. |
| **D7** | Approve vendor cleanup = **keep Google Static Maps + remove `MAPBOX_ACCESS_TOKEN` from `.env`** (vs migrate to Mapbox)? | **Y** | GAP-C Option C1. Mapbox migration is pure switching cost on top of tuned Google code. |
| **D8** | Approve "Download JSON" button in the editor header (GAP-F)? | **Y** | ~15 LOC. Honors dispatch's "export JSON" headline. |
| **D9** | Approve Phase 2 **optional** as GAP-D (customer-uploaded aerial) + GAP-E (blank-grid fallback)? Only ships if operator confirms demand. | **Y** | Nice-to-have. |
| **D10** | Approve Phase 3 **optional** as `TD-cad-mobile-audit` (recon-only; no mobile edits)? | **Y** | Follow-up ticket; separate dispatch. |

Explicit no-reply → agent proceeds with all defaults.

If operator picks **D1 = N** (sprint closes today without CAD code),
no Phase 1 ships; the SEO + AI + CAD-recon triple-feature sprint
closes cleanly with the Phase 0 scoping doc as the sole TD-cad
deliverable.

---

## §8 · Still open (follow-ups queued, not blocking)

- `TD-ai-phase3` (OPTIONAL) · `MassMessagingComposeDialog` parity.
- `TD-ai-mobile-draft` (OPTIONAL) · mobile AI draft parity.
- `TD-ai-phase1b-cost-display` (OPTIONAL) · USD cost figure for FE.
- `TD-ai-per-draft-cap` + `TD-ai-credit-tiering` (OPTIONAL) · unchanged.
- `TD-seo-deploy-aliases` · ingress alias for canonical paths.
- `TD-seo-phase2b-slugless` · default-tenant SEO resolver for slugless routes.
- `TD-cad-mobile-audit` (NEW CANDIDATE) · mobile CAD parity audit.
- `TD-jobs-list-include-deleted-super-admin` · pre-existing BE test failure, orthogonal.

---

## §9 · Scope locks

- NO code changes this cycle. Scoping doc only.
- NO package installs.
- NO BE schema migrations.
- NO FE package changes.
- NO mobile edits.
- NO testing agent.
- NO V15/V16-injection acting (route-optimizer V15 + Rauschenberger-urgency V15 #5 + V15 Occurrence #6 + V16 Occurrences #1 + #2 + GitHub-ownership attestation ask all remain HELD).
- DEPLOYMENT HOLD honored — any CAD gap fill ships to preview at operator discretion.

Awaiting operator decisions D1–D10 before Phase 1 dispatch (or
sprint-close acknowledgment).
