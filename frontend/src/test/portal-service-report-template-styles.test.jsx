/**
 * Phase 14B · Feb-2026 — Portal detail wire-up + checklist order
 * vitest coverage.
 *
 * Follow-ups 3 + 4 from the Phase 14 batch. Two scopes:
 *
 *   A. orderChecklistByTemplate (@/lib/checklistOrder) — unit
 *      tests on the label-match reordering helper.
 *   B. PortalServiceReports Section component — wraps with
 *      TemplateFieldProvider + applies template bg_color via
 *      useFieldStyle.
 *
 * Covers the 5 brief-pinned cases:
 *   1. Items render in template order when template has them
 *      reordered.
 *   2. Items unmatched by the template are appended at end.
 *   3. Template fields that don't match any item are skipped.
 *   4. Empty / missing template → source order unchanged.
 *   5. Section applies template style when provider wraps it.
 */
import React from "react";
import {
  describe, it, expect, vi, beforeEach, afterEach,
} from "vitest";
import { render, screen, cleanup } from "@testing-library/react";

import {
  orderChecklistByTemplate,
  checklistFormTypeFor,
} from "@/lib/checklistOrder";
import {
  TemplateFieldProvider,
  useFieldStyle,
} from "@/components/form-renderer/TemplateFieldContext";


afterEach(() => cleanup());


// ─── A. orderChecklistByTemplate ─────────────────────────────────
describe("orderChecklistByTemplate · unit", () => {
  const _ITEMS = [
    { id: "a", label: "Skim surface and empty baskets", checked: true },
    { id: "b", label: "Brush walls and steps", checked: false },
    { id: "c", label: "Vacuum floor", checked: true },
  ];

  it("1 · reorders items to match template field order", () => {
    // Template says: Vacuum floor FIRST, then Skim, then Brush.
    const tpl = [
      { field_id: "chk_vacuum_floor",   label: "Vacuum floor",                 order: 0 },
      { field_id: "chk_skim_surface",   label: "Skim surface and empty baskets", order: 1 },
      { field_id: "chk_brush_walls",    label: "Brush walls and steps",        order: 2 },
    ];
    const out = orderChecklistByTemplate(_ITEMS, tpl);
    expect(out.map((i) => i.id)).toEqual(["c", "a", "b"]);
  });

  it("2 · unmatched items appended in original relative order",
      () => {
        // Template only mentions Vacuum; Skim + Brush are not in
        // the template → they should land after Vacuum, in their
        // original order (Skim then Brush).
        const tpl = [
          { field_id: "chk_vacuum_floor", label: "Vacuum floor", order: 0 },
        ];
        const out = orderChecklistByTemplate(_ITEMS, tpl);
        expect(out.map((i) => i.id)).toEqual(["c", "a", "b"]);
      });

  it("3 · template fields with no matching item are skipped",
      () => {
        // Template mentions a Ghost item that doesn't exist in
        // service_report_templates → silent skip, no crash.
        const tpl = [
          { field_id: "chk_ghost",         label: "Not a real item", order: 0 },
          { field_id: "chk_vacuum_floor",  label: "Vacuum floor",    order: 1 },
          { field_id: "chk_skim_surface",  label: "Skim surface and empty baskets", order: 2 },
          { field_id: "chk_brush_walls",   label: "Brush walls and steps",        order: 3 },
        ];
        const out = orderChecklistByTemplate(_ITEMS, tpl);
        expect(out.map((i) => i.id)).toEqual(["c", "a", "b"]);
        expect(out.find((i) => i.label === "Not a real item"))
          .toBeUndefined();
      });

  it("4a · empty template → source order unchanged (same ref)",
      () => {
        expect(orderChecklistByTemplate(_ITEMS, []))
          .toBe(_ITEMS);
        expect(orderChecklistByTemplate(_ITEMS, null))
          .toBe(_ITEMS);
        expect(orderChecklistByTemplate(_ITEMS, undefined))
          .toBe(_ITEMS);
      });

  it("4b · template with only non-checklist fields → source order",
      () => {
        // The form_template may carry fields like ``notes`` or
        // ``signature``. They must NOT reorder checklist items.
        const tpl = [
          { field_id: "notes",     label: "Notes",     order: 0 },
          { field_id: "signature", label: "Signature", order: 1 },
        ];
        expect(orderChecklistByTemplate(_ITEMS, tpl))
          .toBe(_ITEMS);
      });

  it("4c · empty items array passes through", () => {
    expect(orderChecklistByTemplate([], [
      { field_id: "chk_x", label: "X", order: 0 },
    ])).toEqual([]);
  });

  it("4d · match is case-insensitive + whitespace-tolerant", () => {
    const items = [{ id: "a", label: "  Vacuum Floor  " }];
    const tpl = [
      { field_id: "chk_vacuum_floor", label: "vacuum floor", order: 0 },
    ];
    const out = orderChecklistByTemplate(items, tpl);
    expect(out.map((i) => i.id)).toEqual(["a"]);
  });
});


describe("checklistFormTypeFor · kind mapping", () => {
  it("maps the three kinds to the matching form_type", () => {
    expect(checklistFormTypeFor("pool")).toBe("job_checklist_pool");
    expect(checklistFormTypeFor("landscape"))
      .toBe("job_checklist_landscape");
    expect(checklistFormTypeFor("generic"))
      .toBe("job_checklist_generic");
    // Unknown kind defaults to pool.
    expect(checklistFormTypeFor("")).toBe("job_checklist_pool");
    expect(checklistFormTypeFor(undefined))
      .toBe("job_checklist_pool");
  });
});


// ─── B. Section + template style threading ──────────────────────
function _ConsumerProbe({ templateFieldId }) {
  const style = useFieldStyle(templateFieldId);
  return (
    <div
      data-testid="probe"
      data-bg={style?.backgroundColor || "fallback"}
      data-border={style?.borderColor || "fallback"}
    />
  );
}


describe("useFieldStyle · template style threading", () => {
  it("5a · returns null when no provider wraps (fallback branch)",
      () => {
        render(<_ConsumerProbe templateFieldId="checklist_section" />);
        const el = screen.getByTestId("probe");
        expect(el.dataset.bg).toBe("fallback");
        expect(el.dataset.border).toBe("fallback");
      });

  it("5b · applies the template bg + border when the provider "
      + "has a matching field", () => {
        const fieldsById = {
          checklist_section: {
            field_id: "checklist_section",
            style: {
              bg_color: "#FEF3C7",
              bg_alpha: 1.0,
              border_color: "#92400E",
              text_color: "#111827",
              width_cols: 12,
              padding_y: 4,
            },
          },
        };
        render(
          <TemplateFieldProvider fieldsById={fieldsById}>
            <_ConsumerProbe templateFieldId="checklist_section" />
          </TemplateFieldProvider>,
        );
        const el = screen.getByTestId("probe");
        // ``styleToCss`` composes rgba for ``backgroundColor``;
        // just assert something non-fallback came through.
        expect(el.dataset.bg).not.toBe("fallback");
        expect(el.dataset.border).toContain("#92400E");
      });

  it("5c · empty fieldsById → fallback branch", () => {
    render(
      <TemplateFieldProvider fieldsById={{}}>
        <_ConsumerProbe templateFieldId="checklist_section" />
      </TemplateFieldProvider>,
    );
    const el = screen.getByTestId("probe");
    expect(el.dataset.bg).toBe("fallback");
  });
});
