/**
 * Phase 7C · Feb-2026 — Form Template runtime wiring contract.
 *
 * Covers all 10 brief cases:
 *
 *   1  ServiceReport renders fields in template-ordered sequence
 *      (via useFormTemplateOrder helper — source-grep assertion
 *      that the Provider wraps the page)
 *   2  ServiceReport fields pick up template bg_color + alpha
 *      composed via styleToCss (Section component applies template
 *      style when templateFieldId provided; test the Section
 *      component in isolation)
 *   3  ServiceReport falls back to hardcoded layout when hook
 *      returns empty-template sentinel
 *   4  ServiceReport switches form_type between pool / landscape
 *      jobs (source-grep assertion that ``report.template``
 *      resolves the right form_type)
 *   5  EstimateView line-items Price/Unit/Total columns honor
 *      template styles (source-grep: the ``line_items_table`` style
 *      is applied inline to ``<thead>`` and body rows)
 *   6  InvoiceView line-items same billable unlock
 *   7  Checklist container renders with template-ordered seed
 *      (via styleToCss on the Section wrapper — individual
 *      checklist items stay in backend-template order, which is
 *      the live data path; container styling is the Phase 7C
 *      wire-up)
 *   8  styleToCss pure helper (alpha composition, grid span,
 *      padding scaling)
 *   9  404 from template endpoint → fallback mode, no crash
 *  10  form_type without a saved template → fallback mode
 *
 * Design: the hook + helpers are tested in isolation; the real-
 * page integrations are source-level grep locks (same pattern as
 * ``invoice-view-column-alignment.test.jsx``) because mounting the
 * full ServiceReport / EstimateView / InvoiceView page under
 * vitest hangs the collection phase per the config comments.
 */
import React from "react";
import {
  describe, it, expect, vi, beforeEach, afterEach,
} from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import fs from "node:fs";
import path from "node:path";

import {
  useFormTemplateRuntime,
  invalidateFormTemplateRuntime,
} from "@/hooks/useFormTemplateRuntime";


// ─── mocks shared across every test ───────────────────────────────

const { apiGetMock } = vi.hoisted(() => ({ apiGetMock: vi.fn() }));

vi.mock("@/api", () => ({
  api:       { get: apiGetMock, post: vi.fn(), put: vi.fn(),
               patch: vi.fn(), del: vi.fn(), delete: vi.fn() },
  api_base:  () => "http://test.example/api",
  TOKEN_KEY: "token",
}));


afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});


// ══════════════════════════════════════════════════════════════════
//  Case 8  —  styleToCss pure helper
// ══════════════════════════════════════════════════════════════════

describe("Case 8 · styleToCss pure helper", () => {
  it("composes bg_color + bg_alpha into rgba", async () => {
    const { styleToCss } = await import("@/lib/formStyle");
    const css = styleToCss({
      bg_color: "#FF0000", bg_alpha: 0.5,
      text_color: "#000000", border_color: "#FFFFFF",
      width_cols: 6, padding_y: 2,
    });
    expect(css.backgroundColor).toBe("rgba(255, 0, 0, 0.5)");
    expect(css.color).toBe("#000000");
    expect(css.borderColor).toBe("#FFFFFF");
  });

  it("maps width_cols to a span N / span N", async () => {
    const { styleToCss } = await import("@/lib/formStyle");
    expect(styleToCss({ width_cols: 4 }).gridColumn)
      .toBe("span 4 / span 4");
    expect(styleToCss({ width_cols: 12 }).gridColumn)
      .toBe("span 12 / span 12");
  });

  it("scales padding_y to padding_y * 4 px top and bottom", async () => {
    const { styleToCss, PADDING_Y_MULTIPLIER_PX } =
      await import("@/lib/formStyle");
    expect(PADDING_Y_MULTIPLIER_PX).toBe(4);
    const css = styleToCss({ padding_y: 3 });
    expect(css.paddingTop).toBe("12px");
    expect(css.paddingBottom).toBe("12px");
  });

  it("clamps out-of-range values + falls back to defaults", async () => {
    const { styleToCss } = await import("@/lib/formStyle");
    const css = styleToCss({
      bg_color: "nothex", bg_alpha: 2, text_color: "garbage",
      border_color: "", width_cols: 999, padding_y: 999,
    });
    // Falls back to the Phase 7A seed defaults.
    expect(css.backgroundColor).toBe("rgba(255, 255, 255, 1)");
    expect(css.color).toBe("#111827");
    expect(css.borderColor).toBe("#E5E7EB");
    expect(css.gridColumn).toBe("span 12 / span 12");
    expect(css.paddingTop).toBe("32px");  // 8 * 4
  });

  it("handles null / undefined input without throwing", async () => {
    const { styleToCss } = await import("@/lib/formStyle");
    expect(() => styleToCss(null)).not.toThrow();
    expect(() => styleToCss(undefined)).not.toThrow();
    const css = styleToCss(null);
    expect(css.backgroundColor).toBe("rgba(255, 255, 255, 1)");
  });
});


// ══════════════════════════════════════════════════════════════════
//  Case 9+10  —  useFormTemplateRuntime fallback behavior
// ══════════════════════════════════════════════════════════════════

describe("Case 9+10 · runtime loader fallback contract", () => {
  beforeEach(() => {
    invalidateFormTemplateRuntime();
  });

  function HookHost({ formType, onReady }) {
    const state = useFormTemplateRuntime(formType);
    React.useEffect(() => { onReady(state); }, [state, onReady]);
    return <div data-testid="hook-host" />;
  }

  it("Case 10 · null form_type returns the empty sentinel", async () => {
    const states = [];
    render(<HookHost formType={null} onReady={(s) => states.push(s)} />);
    await new Promise((r) => setTimeout(r, 0));
    const last = states[states.length - 1];
    expect(last.isEmpty).toBe(true);
    expect(last.fieldsOrdered).toEqual([]);
    expect(last.isLoading).toBe(false);
    expect(apiGetMock).not.toHaveBeenCalled();
  });

  it("Case 9 · fetch rejection returns the empty sentinel + sets error",
    async () => {
      apiGetMock.mockRejectedValueOnce(new Error("boom"));
      const states = [];
      render(
        <HookHost formType="estimate" onReady={(s) => states.push(s)} />,
      );
      await new Promise((r) => setTimeout(r, 0));
      await new Promise((r) => setTimeout(r, 0));
      await new Promise((r) => setTimeout(r, 0));
      const last = states[states.length - 1];
      expect(last.isEmpty).toBe(true);
      expect(last.error).toBeTruthy();
    });

  it("normal fetch populates fieldsById + fieldsOrdered", async () => {
    apiGetMock.mockResolvedValueOnce({
      id: "tpl-x", tenant_id: "t-A", form_type: "estimate",
      version: 3, is_current: true,
      fields: [
        { field_id: "b", label: "B", field_type: "text",
          order: 1, locked_reorder: false, style: {} },
        { field_id: "a", label: "A", field_type: "text",
          order: 0, locked_reorder: false, style: {} },
      ],
    });
    const states = [];
    render(
      <HookHost formType="estimate" onReady={(s) => states.push(s)} />,
    );
    await new Promise((r) => setTimeout(r, 0));
    await new Promise((r) => setTimeout(r, 0));
    const last = states[states.length - 1];
    expect(last.isEmpty).toBe(false);
    expect(last.version).toBe(3);
    expect(last.fieldsOrdered.map((f) => f.field_id)).toEqual(["a", "b"]);
    expect(last.fieldsById.a.field_id).toBe("a");
  });
});


// ══════════════════════════════════════════════════════════════════
//  Case 2+3+7  —  Section-level style application + fallback
// ══════════════════════════════════════════════════════════════════

describe("Case 2+3+7 · TemplateFieldProvider + useFieldStyle", () => {
  it("Case 2 · provider surfaces a template style under useFieldStyle",
    async () => {
      const { TemplateFieldProvider, useFieldStyle } = await import(
        "@/components/form-renderer/TemplateFieldContext");

      function Probe() {
        const css = useFieldStyle("photos");
        return (
          <div data-testid="probe"
                data-bg={css?.backgroundColor || ""}
                data-pad={css?.paddingTop || ""} />
        );
      }

      render(
        <TemplateFieldProvider fieldsById={{
          photos: {
            field_id: "photos", label: "Photos", field_type: "photo",
            order: 0, locked_reorder: false,
            style: {
              bg_color: "#00FF00", bg_alpha: 0.4,
              text_color: "#111827", border_color: "#E5E7EB",
              width_cols: 12, padding_y: 3,
            },
          },
        }}>
          <Probe />
        </TemplateFieldProvider>,
      );
      const probe = screen.getByTestId("probe");
      expect(probe.getAttribute("data-bg"))
        .toBe("rgba(0, 255, 0, 0.4)");
      expect(probe.getAttribute("data-pad")).toBe("12px");
    });

  it("Case 3 · no provider → useFieldStyle returns null (fallback)",
    async () => {
      const { useFieldStyle } = await import(
        "@/components/form-renderer/TemplateFieldContext");

      function Probe() {
        const css = useFieldStyle("photos");
        return (
          <div data-testid="probe"
                data-has-tpl={css ? "yes" : "no"} />
        );
      }
      render(<Probe />);
      expect(screen.getByTestId("probe").getAttribute("data-has-tpl"))
        .toBe("no");
    });

  it("Case 3 · empty fieldsById → useFieldStyle returns null",
    async () => {
      const { TemplateFieldProvider, useFieldStyle } = await import(
        "@/components/form-renderer/TemplateFieldContext");

      function Probe() {
        const css = useFieldStyle("photos");
        return (
          <div data-testid="probe"
                data-has-tpl={css ? "yes" : "no"} />
        );
      }
      render(
        <TemplateFieldProvider fieldsById={{}}>
          <Probe />
        </TemplateFieldProvider>,
      );
      expect(screen.getByTestId("probe").getAttribute("data-has-tpl"))
        .toBe("no");
    });

  it("Case 7 · useFormTemplateOrder returns ordered field_ids",
    async () => {
      const { TemplateFieldProvider, useFormTemplateOrder } = await import(
        "@/components/form-renderer/TemplateFieldContext");

      function Probe() {
        const order = useFormTemplateOrder();
        return (
          <div data-testid="probe"
                data-order={(order || []).join(",")} />
        );
      }
      render(
        <TemplateFieldProvider fieldsById={{
          notes: { field_id: "notes",     order: 2, style: {} },
          chk:   { field_id: "checklist_section", order: 0, style: {} },
          chems: { field_id: "chemicals_added_section", order: 1, style: {} },
        }}>
          <Probe />
        </TemplateFieldProvider>,
      );
      expect(screen.getByTestId("probe").getAttribute("data-order"))
        .toBe("checklist_section,chemicals_added_section,notes");
    });
});


// ══════════════════════════════════════════════════════════════════
//  Case 1+4  —  ServiceReport wires template loader with the right
//                form_type derivation (source-level)
// ══════════════════════════════════════════════════════════════════

describe("Case 1+4 · ServiceReport wire-up (source-level)", () => {
  const SRC = fs.readFileSync(
    path.resolve(__dirname, "../pages/tech/ServiceReport.jsx"),
    "utf8",
  );

  it("imports the runtime loader + the provider + useFieldStyle", () => {
    expect(SRC).toMatch(/useFormTemplateRuntime/);
    expect(SRC).toMatch(/TemplateFieldProvider/);
    expect(SRC).toMatch(/useFieldStyle/);
  });

  it("Case 4 · form_type derivation branches on report.template", () => {
    expect(SRC).toMatch(
      /report\.template\s*===\s*"landscape"[\s\S]{0,120}"landscape_service_report"/);
    expect(SRC).toMatch(/"pool_service_report"/);
  });

  it("Case 1 · provider wraps the main render tree", () => {
    expect(SRC).toMatch(
      /<TemplateFieldProvider[\s\S]{0,120}fieldsById=\{_tpl\.fieldsById\}>/);
    expect(SRC).toMatch(/<\/TemplateFieldProvider>/);
  });

  it("every top-level Section passes a templateFieldId", () => {
    // The Phase 7A seed field_ids used on the pool_service_report
    // seed:  photos, chemistry_readings, chemicals_added_section,
    // checklist_section, notes.  Each must be present on at least
    // one Section call site.
    const required = [
      "photos",
      "chemistry_readings",
      "chemicals_added_section",
      "checklist_section",
      "notes",
    ];
    for (const fid of required) {
      expect(SRC).toMatch(new RegExp(`templateFieldId="${fid}"`));
    }
  });
});


// ══════════════════════════════════════════════════════════════════
//  Case 5  —  EstimateView billable unlock
// ══════════════════════════════════════════════════════════════════

describe("Case 5 · EstimateView billable unlock (source-level)", () => {
  const SRC = fs.readFileSync(
    path.resolve(__dirname, "../components/EstimateView.jsx"),
    "utf8",
  );

  it("imports the runtime loader + style helper", () => {
    expect(SRC).toMatch(/useFormTemplateRuntime/);
    expect(SRC).toMatch(/styleToCss/);
  });

  it("loads the ``estimate`` template at the component level", () => {
    expect(SRC).toMatch(
      /useFormTemplateRuntime\(["']estimate["']\)/);
  });

  it("reads the ``line_items_table`` field style off the template", () => {
    expect(SRC).toMatch(
      /fieldsById\?\.line_items_table/);
  });

  it("applies template bg/text/border to the thead row", () => {
    // thead inline-style refers to _liStyle for backgroundColor
    // + color + borderColor so the Price/Unit/Total header cells
    // honor the admin's chosen style.
    expect(SRC).toMatch(
      /data-testid="estimate-line-items-thead"/);
    expect(SRC).toMatch(
      /_liStyle[\s\S]{0,120}backgroundColor:[\s\S]{0,120}_liStyle\.backgroundColor/);
  });

  it("applies template style to the line-item BODY rows (billable unlock)", () => {
    // ``rowStyle`` composes _tplCellStyle onto declined/undeclined
    // rows — the critical "Price/Unit/Total no longer locked to
    // white" ship.
    expect(SRC).toMatch(/_tplCellStyle/);
  });
});


// ══════════════════════════════════════════════════════════════════
//  Case 6  —  InvoiceView billable unlock
// ══════════════════════════════════════════════════════════════════

describe("Case 6 · InvoiceView billable unlock (source-level)", () => {
  const SRC = fs.readFileSync(
    path.resolve(__dirname, "../components/InvoiceView.jsx"),
    "utf8",
  );

  it("imports the runtime loader + style helper", () => {
    expect(SRC).toMatch(/useFormTemplateRuntime/);
    expect(SRC).toMatch(/styleToCss/);
  });

  it("loads the ``invoice`` template at the component level", () => {
    expect(SRC).toMatch(
      /useFormTemplateRuntime\(["']invoice["']\)/);
  });

  it("applies template style to the thead row (Cost/Rate · Qty/Hr · % · Total)",
    () => {
      expect(SRC).toMatch(
        /data-testid="invoice-line-items-thead"/);
      expect(SRC).toMatch(
        /_liStyle[\s\S]{0,120}backgroundColor:[\s\S]{0,120}_liStyle\.backgroundColor/);
    });

  it("applies template style to every line-item row", () => {
    // The ``line_items.map`` body renders ``<tr>`` with the inline
    // template style (billable unlock).
    expect(SRC).toMatch(
      /invoice-line-item-row-\$\{i\}[\s\S]{0,400}_liStyle/);
  });
});


// ══════════════════════════════════════════════════════════════════
//  Case 7-bis — Phase 7B preview no longer duplicates styleToCss
// ══════════════════════════════════════════════════════════════════

describe("Case 7-bis · Phase 7B preview uses shared styleToCss", () => {
  const PREVIEWS_SRC = fs.readFileSync(
    path.resolve(__dirname, "../components/form-editor/FormPreviews.jsx"),
    "utf8",
  );

  it("imports the shared helper from lib/formStyle", () => {
    expect(PREVIEWS_SRC).toMatch(/from ["']@\/lib\/formStyle["']/);
    expect(PREVIEWS_SRC).toMatch(/styleToCss/);
  });
});
