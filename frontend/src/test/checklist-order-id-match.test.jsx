/**
 * Phase 17 · Feb-2026 — Checklist ordering id-match swap +
 * backwards-compat fallback.
 *
 * Pins the 4 behaviors from the Phase 17 brief:
 *
 *   1. Items with field_id are ordered via id-match (new primary
 *      match path).
 *   2. Items WITHOUT field_id fall back to label-match (backwards
 *      compat for pre-migration tenants + Phase 7A curated seed
 *      ids).
 *   3. Mixed template: some items have field_id, some don't →
 *      both match paths work correctly in one pass.
 *   4. Public API unchanged — Phase 14 FU4 callers continue to
 *      receive identical ``items`` reference when no reorder is
 *      needed.
 */
import { describe, it, expect } from "vitest";

import {
  orderChecklistByTemplate,
  checklistFormTypeFor,
} from "@/lib/checklistOrder";


describe("Phase 17 · orderChecklistByTemplate id-match", () => {
  // ─── Case 1 — id-match preferred when field_id is present ────
  it("1 · items with field_id are reordered via id-match",
      () => {
        // Template references ``chk_vac`` first (even though its
        // label is 'Vacuum different label' which does NOT match
        // any item's label). The id-match MUST win over label.
        const items = [
          { id: "a", field_id: "chk_skim",  label: "Skim pool", checked: false },
          { id: "b", field_id: "chk_brush", label: "Brush walls", checked: false },
          { id: "c", field_id: "chk_vac",   label: "Vacuum", checked: false },
        ];
        const tpl = [
          { field_id: "chk_vac",   label: "Vacuum different label", order: 0 },
          { field_id: "chk_skim",  label: "Skim different label",   order: 1 },
          { field_id: "chk_brush", label: "Brush different label",  order: 2 },
        ];
        const out = orderChecklistByTemplate(items, tpl);
        expect(out.map((i) => i.id)).toEqual(["c", "a", "b"]);
      });

  // ─── Case 2 — label-match fallback for items w/o field_id ────
  it("2 · items without field_id fall back to label-match",
      () => {
        // No item has a field_id — exercises the pre-migration
        // tenant path. Must behave identically to Phase 14 FU4.
        const items = [
          { id: "a", label: "Skim surface and empty baskets" },
          { id: "b", label: "Brush walls and steps" },
          { id: "c", label: "Vacuum floor" },
        ];
        const tpl = [
          { field_id: "chk_vacuum_floor",   label: "Vacuum floor",                     order: 0 },
          { field_id: "chk_skim_surface",   label: "Skim surface and empty baskets",   order: 1 },
          { field_id: "chk_brush_walls",    label: "Brush walls and steps",            order: 2 },
        ];
        const out = orderChecklistByTemplate(items, tpl);
        expect(out.map((i) => i.id)).toEqual(["c", "a", "b"]);
      });

  // ─── Case 2b — hand-curated Phase 7A ids + migrated items ────
  it("2b · migrated item field_ids that don't id-match the Phase "
      + "7A curated seed fall back to label-match", () => {
        // The Phase 7A seed uses ``chk_skim_surface`` (curated
        // keyword) while a migrated item slugged mechanically
        // from the full label carries
        // ``chk_skim_surface_and_empty_baskets``. The id-match
        // misses — label-match MUST bridge the gap.
        const items = [
          { id: "a", field_id: "chk_skim_surface_and_empty_baskets",
            label: "Skim surface and empty baskets" },
          { id: "b", field_id: "chk_brush_walls_and_steps",
            label: "Brush walls and steps" },
        ];
        const tpl = [
          { field_id: "chk_brush_walls",   label: "Brush walls and steps",            order: 0 },
          { field_id: "chk_skim_surface",  label: "Skim surface and empty baskets",   order: 1 },
        ];
        const out = orderChecklistByTemplate(items, tpl);
        expect(out.map((i) => i.id)).toEqual(["b", "a"]);
      });

  // ─── Case 3 — mixed template ─────────────────────────────────
  it("3 · mixed template: id-match wins + label-match covers the "
      + "rest", () => {
        const items = [
          // Has field_id → id-match path.
          { id: "a", field_id: "chk_mow", label: "Mow lawn" },
          // No field_id → label-match path.
          { id: "b",                     label: "Edge grass" },
          { id: "c", field_id: "chk_blow", label: "Blow property" },
        ];
        const tpl = [
          { field_id: "chk_blow", label: "Blow property",          order: 0 },
          { field_id: "chk_edge", label: "Edge grass",             order: 1 }, // match by label
          { field_id: "chk_mow",  label: "Different mow label",    order: 2 }, // match by id
        ];
        const out = orderChecklistByTemplate(items, tpl);
        expect(out.map((i) => i.id)).toEqual(["c", "b", "a"]);
      });

  // ─── Case 4 — public API unchanged (same-ref short-circuit) ──
  it("4 · same reference returned when no reorder is needed",
      () => {
        const items = [
          { id: "a", field_id: "chk_a", label: "A" },
          { id: "b", field_id: "chk_b", label: "B" },
        ];
        const tpl = [
          { field_id: "chk_a", label: "A", order: 0 },
          { field_id: "chk_b", label: "B", order: 1 },
        ];
        const out = orderChecklistByTemplate(items, tpl);
        // Already in-order → same array reference (React key
        // churn avoidance). Phase 14 contract preserved.
        expect(out).toBe(items);
      });

  it("4b · empty / null / undefined template → same ref", () => {
    const items = [{ id: "a", label: "A" }];
    expect(orderChecklistByTemplate(items, [])).toBe(items);
    expect(orderChecklistByTemplate(items, null)).toBe(items);
    expect(orderChecklistByTemplate(items, undefined)).toBe(items);
  });

  it("4c · checklistFormTypeFor still maps kinds correctly",
      () => {
        expect(checklistFormTypeFor("pool"))
          .toBe("job_checklist_pool");
        expect(checklistFormTypeFor("landscape"))
          .toBe("job_checklist_landscape");
        expect(checklistFormTypeFor("generic"))
          .toBe("job_checklist_generic");
      });

  // ─── Extra guard — unmatched items appended at end ──────────
  it("items unmatched by both id and label are appended at end",
      () => {
        const items = [
          { id: "a", field_id: "chk_a",   label: "A" },
          { id: "b", field_id: "chk_ghost", label: "Ghost" },
          { id: "c",                      label: "C" },
        ];
        const tpl = [
          { field_id: "chk_a", label: "A", order: 0 },
          { field_id: "chk_c", label: "C", order: 1 },  // matches 'c' by label
        ];
        const out = orderChecklistByTemplate(items, tpl);
        // a (id-match) + c (label-match) first; b unmatched →
        // appended at end.
        expect(out.map((i) => i.id)).toEqual(["a", "c", "b"]);
      });
});
