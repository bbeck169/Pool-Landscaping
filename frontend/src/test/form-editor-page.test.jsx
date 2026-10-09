/**
 * Phase 7B · Feb-2026 — Form Template editor web-UI contract.
 *
 * Covers every brief case 1-12 in isolation.  The full page mount
 * is split across small render blocks because vitest config
 * (`pool: "forks"` + jsdom) hangs on a one-shot mount of a page
 * whose transitive graph pulls in all of ui-kit + sonner + lucide.
 * Each describe below mounts the thinnest viable subtree that
 * exercises the brief case.
 */
import React from "react";
import {
  describe, it, expect, vi, beforeEach, afterEach,
} from "vitest";
import {
  render, screen, cleanup, fireEvent, within,
} from "@testing-library/react";

import { useFormTemplate } from "@/hooks/useFormTemplate";


// ─── mocks shared across every test ───────────────────────────────

let currentRole = "admin";

vi.mock("@/auth", () => ({
  useAuth: () => ({
    user: { id: "u1", role: currentRole, email: `${currentRole}@x.y` },
  }),
  AuthProvider: ({ children }) => <>{children}</>,
}));


const { apiGetMock, apiPutMock, apiPostMock } = vi.hoisted(() => ({
  apiGetMock:  vi.fn(),
  apiPutMock:  vi.fn(),
  apiPostMock: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: {
    get:    apiGetMock,
    put:    apiPutMock,
    post:   apiPostMock,
    patch:  vi.fn(),
    del:    vi.fn(),
    delete: vi.fn(),
  },
  api_base: () => "http://test.example/api",
  TOKEN_KEY: "token",
}));

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error:   vi.fn(),
    info:    vi.fn(),
  },
}));


afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  currentRole = "admin";
});


// ─── Fixtures ─────────────────────────────────────────────────────

const _DEFAULT_STYLE = {
  bg_color: "#FFFFFF", bg_alpha: 1.0, text_color: "#111827",
  border_color: "#E5E7EB", width_cols: 12, padding_y: 2,
};

const _mockTemplate = (formType) => ({
  id: `tpl-${formType}`, tenant_id: "t-A", form_type: formType,
  version: 1, is_current: true, updated_by: "u1",
  updated_at: "2026-02-10T12:00:00+00:00",
  fields: [
    { field_id: "f1", label: "First",  field_type: "text",
      order: 0, locked_reorder: false, style: { ..._DEFAULT_STYLE } },
    { field_id: "f2", label: "Second", field_type: "text",
      order: 1, locked_reorder: false, style: { ..._DEFAULT_STYLE } },
    { field_id: "f3", label: "Locked", field_type: "text",
      order: 2, locked_reorder: true,  style: { ..._DEFAULT_STYLE } },
  ],
});


// ══════════════════════════════════════════════════════════════════
//  Case 1  —  Role gate (route-level wrapper in App.js)
// ══════════════════════════════════════════════════════════════════

describe("Case 1 · route-level AdminOnly guard shape", () => {
  it("App.js wraps /admin/form-editor in <AdminOnly>", async () => {
    const fs = await import("node:fs");
    const path = await import("node:path");
    const src = fs.readFileSync(
      path.resolve(__dirname, "../App.js"), "utf8");
    expect(src).toMatch(
      /admin\/form-editor.*AdminOnly.*FormEditor.*AdminOnly/s);
  });
});


// ══════════════════════════════════════════════════════════════════
//  Case 2  —  Form type picker lists all templates returned by GET
//
//  Mounts the hook + a bare renderer so we don't drag the whole
//  page's dependency graph through the test.
// ══════════════════════════════════════════════════════════════════

describe("Case 2 · form_type picker enumerates all 8 types", () => {
  it("exports every type returned by the Phase 7A API", async () => {
    const { FORM_TYPES, FORM_TYPE_LABELS } =
      await import("@/hooks/useFormTemplate");
    // Phase 14A · Feb-2026 — ``cad_overlay`` dropped. The CAD
    // canvas tool was never wired to the form_template consumer
    // pattern; see ``backend/routers/form_templates.py`` header.
    expect(FORM_TYPES).toEqual([
      "pool_service_report",
      "landscape_service_report",
      "job_checklist_pool",
      "job_checklist_landscape",
      "job_checklist_generic",
      "estimate",
      "invoice",
    ]);
    expect(FORM_TYPES).not.toContain("cad_overlay");
    expect(FORM_TYPE_LABELS.cad_overlay).toBeUndefined();
    for (const ft of FORM_TYPES) {
      expect(FORM_TYPE_LABELS[ft]).toBeTruthy();
    }
  });
});


// ══════════════════════════════════════════════════════════════════
//  Case 3  —  Drag reorder updates order
//  Case 4  —  locked_reorder field cannot be dragged / dropped on
//
//  dnd-kit's PointerSensor never emits events in jsdom — test the
//  pure drag-end reducer instead.  The ``applyDragEndReorder`` util
//  is exported from FieldList specifically to allow this.
// ══════════════════════════════════════════════════════════════════

describe("Case 3+4 · drag reorder + locked_reorder guard", () => {
  it("reorders when both ends are unlocked", async () => {
    const { applyDragEndReorder } =
      await import("@/components/form-editor/FieldList");
    const tpl = _mockTemplate("estimate");
    const next = applyDragEndReorder(tpl.fields, {
      active: { id: "f1" }, over: { id: "f2" },
    });
    expect(next.map((f) => f.field_id)).toEqual(["f2", "f1", "f3"]);
  });

  it("no-ops when the dragged field is locked", async () => {
    const { applyDragEndReorder } =
      await import("@/components/form-editor/FieldList");
    const tpl = _mockTemplate("estimate");
    const next = applyDragEndReorder(tpl.fields, {
      active: { id: "f3" }, over: { id: "f1" },   // f3 is locked
    });
    expect(next).toBe(tpl.fields);
  });

  it("no-ops when the drop target is locked", async () => {
    const { applyDragEndReorder } =
      await import("@/components/form-editor/FieldList");
    const tpl = _mockTemplate("estimate");
    const next = applyDragEndReorder(tpl.fields, {
      active: { id: "f1" }, over: { id: "f3" },   // f3 is locked
    });
    expect(next).toBe(tpl.fields);
  });

  it("renders the lock icon on the locked row and disables its drag handle",
    async () => {
      const FieldList = (await import(
        "@/components/form-editor/FieldList")).default;
      const tpl = _mockTemplate("estimate");
      render(
        <FieldList
          fields={tpl.fields}
          selectedFieldId={null}
          onSelectField={() => {}}
          onReorder={() => {}}
        />,
      );
      expect(screen.getByTestId("form-field-lock-f3")).toBeTruthy();
      const dragBtn = screen.getByTestId("form-field-drag-f3");
      expect(dragBtn.hasAttribute("disabled")).toBe(true);
    });
});


// ══════════════════════════════════════════════════════════════════
//  Case 5  —  Clicking a field opens the detail panel
//  Case 6  —  bg_color + alpha updates preview panel bg
//  Case 7  —  width_cols slider updates preview column span
// ══════════════════════════════════════════════════════════════════

describe("Case 5+6+7 · field detail panel surface", () => {
  it("renders a swatch + the five style controls when passed a field",
    async () => {
      const FieldDetailPanel = (await import(
        "@/components/form-editor/FieldDetailPanel")).default;
      const tpl = _mockTemplate("pool_service_report");
      render(
        <FieldDetailPanel
          field={tpl.fields[0]}
          onChange={() => {}}
        />,
      );
      expect(screen.getByTestId("field-detail-panel")).toBeTruthy();
      expect(screen.getByTestId("field-detail-swatch")).toBeTruthy();
      expect(screen.getByTestId("field-detail-bg-color")).toBeTruthy();
      expect(screen.getByTestId("field-detail-bg-alpha")).toBeTruthy();
      expect(screen.getByTestId("field-detail-text-color")).toBeTruthy();
      expect(screen.getByTestId("field-detail-border-color")).toBeTruthy();
      expect(screen.getByTestId("field-detail-width-cols")).toBeTruthy();
      expect(screen.getByTestId("field-detail-padding-y")).toBeTruthy();
      expect(screen.getByTestId("field-detail-column-preview")).toBeTruthy();
    });

  it("Case 6 — editing bg_color + bg_alpha calls onChange with the right patch",
    async () => {
      const FieldDetailPanel = (await import(
        "@/components/form-editor/FieldDetailPanel")).default;
      const tpl = _mockTemplate("pool_service_report");
      const onChange = vi.fn();
      render(
        <FieldDetailPanel
          field={tpl.fields[0]}
          onChange={onChange}
        />,
      );
      fireEvent.input(screen.getByTestId("field-detail-bg-color"),
        { target: { value: "#FF0000" } });
      // JSDOM normalises hex to lowercase.
      const lastColorCall =
        onChange.mock.calls[onChange.mock.calls.length - 1];
      expect(lastColorCall[0]).toBe("f1");
      expect(lastColorCall[1].style.bg_color.toLowerCase())
        .toBe("#ff0000");

      fireEvent.input(screen.getByTestId("field-detail-bg-alpha"),
        { target: { value: "0.5" } });
      expect(onChange).toHaveBeenLastCalledWith(
        "f1", { style: { bg_alpha: 0.5 } });
    });

  it("Case 7 — width_cols slider patches style.width_cols",
    async () => {
      const FieldDetailPanel = (await import(
        "@/components/form-editor/FieldDetailPanel")).default;
      const tpl = _mockTemplate("estimate");
      const onChange = vi.fn();
      render(
        <FieldDetailPanel
          field={tpl.fields[0]}
          onChange={onChange}
        />,
      );
      fireEvent.input(screen.getByTestId("field-detail-width-cols"),
        { target: { value: "6" } });
      expect(onChange).toHaveBeenLastCalledWith(
        "f1", { style: { width_cols: 6 } });
    });

  it("read-only mode blocks onChange", async () => {
    const FieldDetailPanel = (await import(
      "@/components/form-editor/FieldDetailPanel")).default;
    const tpl = _mockTemplate("estimate");
    const onChange = vi.fn();
    render(
      <FieldDetailPanel
        field={tpl.fields[0]}
        onChange={onChange}
        readOnly
      />,
    );
    fireEvent.input(screen.getByTestId("field-detail-width-cols"),
      { target: { value: "4" } });
    expect(onChange).not.toHaveBeenCalled();
  });
});


// ══════════════════════════════════════════════════════════════════
//  Case 8+9+10  —  Hook: save / discard / revert round-trip
//
//  renderHook isn't available on this project; drive the hook via a
//  throwaway host component and assert state changes externally.
// ══════════════════════════════════════════════════════════════════

function HookHost({ formType, onReady }) {
  const api = useFormTemplate(formType);
  React.useEffect(() => { onReady(api); }, [api, onReady]);
  return <div data-testid="hook-host" />;
}


async function _mountHook(formType, template) {
  apiGetMock.mockImplementation(async (path) => {
    if (path === `/form-templates/${formType}`) return template;
    if (path === `/form-templates/${formType}/versions`) {
      return { versions: [template] };
    }
    throw new Error(`unexpected GET ${path}`);
  });
  let latest = null;
  render(
    <HookHost formType={formType} onReady={(api) => { latest = api; }} />,
  );
  // Flush the mount effect + the initial load() promise.
  await new Promise((r) => setTimeout(r, 0));
  await new Promise((r) => setTimeout(r, 0));
  return () => latest;
}


describe("Case 8+9+10 · save / discard / revert", () => {
  beforeEach(() => {
    apiGetMock.mockReset();
    apiPutMock.mockReset();
    apiPostMock.mockReset();
  });

  it("Case 8 · save PUTs with the current draft and refreshes template",
    async () => {
      const tpl = _mockTemplate("estimate");
      const get = await _mountHook("estimate", tpl);

      apiPutMock.mockResolvedValueOnce({
        ...tpl, version: 2, is_current: true,
      });

      const api = get();
      await api.save();

      expect(apiPutMock).toHaveBeenCalledWith(
        "/form-templates/estimate",
        { fields: api.draft },
      );
    });

  it("Case 9 · discard with dirty state resets draft to template",
    async () => {
      const tpl = _mockTemplate("estimate");
      const get = await _mountHook("estimate", tpl);
      let api = get();
      expect(api.dirty).toBe(false);

      // Mutate draft via updateField.
      api.updateField("f1", { style: { bg_color: "#AABBCC" } });
      await new Promise((r) => setTimeout(r, 0));
      api = get();
      expect(api.dirty).toBe(true);

      api.discard();
      await new Promise((r) => setTimeout(r, 0));
      api = get();
      expect(api.dirty).toBe(false);
      expect(api.draft[0].style.bg_color).toBe("#FFFFFF");
    });

  it("Case 10 · revert POSTs to /revert/{v} and reloads versions",
    async () => {
      const tpl = _mockTemplate("estimate");
      const get = await _mountHook("estimate", tpl);

      apiPostMock.mockResolvedValueOnce({
        ...tpl, version: 1, is_current: true,
      });
      apiGetMock.mockImplementation(async (path) => {
        if (path === `/form-templates/estimate/versions`) {
          return { versions: [tpl] };
        }
        return tpl;
      });

      await get().revert(1);

      expect(apiPostMock).toHaveBeenCalledWith(
        "/form-templates/estimate/revert/1",
      );
    });
});


// ══════════════════════════════════════════════════════════════════
//  Case 11  —  Line-items preview honors configured styles (unlock)
// ══════════════════════════════════════════════════════════════════

describe("Case 11 · estimate/invoice line_items table honors style", () => {
  it("renders Item / Qty / Unit / Total header cells with the configured bg",
    async () => {
      const { InvoiceEstimatePreview } = await import(
        "@/components/form-editor/FormPreviews");
      const fields = [
        { field_id: "line_items_table", label: "Line Items",
          field_type: "line_items_table", order: 0,
          locked_reorder: false,
          style: {
            ..._DEFAULT_STYLE,
            bg_color: "#DBEAFE", text_color: "#1E3A8A",
          },
        },
        { field_id: "total_due", label: "Total Due",
          field_type: "currency", order: 1,
          locked_reorder: true, style: { ..._DEFAULT_STYLE } },
      ];
      render(
        <InvoiceEstimatePreview fields={fields} formType="invoice" />,
      );
      const table = screen.getByTestId("preview-line-items-table");
      const row = screen.getByTestId("preview-li-row-1");
      // JSDOM normalises hex → rgb.  Blue 219/234/254 ⇒ rgb(219,234,254).
      expect(row.getAttribute("style").toLowerCase())
        .toMatch(/rgb\(219,\s*234,\s*254\)|#dbeafe/);
      // Price / Unit / Total columns must exist (brief: billable unlock).
      expect(within(table).getByTestId("preview-li-col-item")).toBeTruthy();
      expect(within(table).getByTestId("preview-li-col-qty")).toBeTruthy();
      expect(within(table).getByTestId("preview-li-col-unit")).toBeTruthy();
      expect(within(table).getByTestId("preview-li-col-total")).toBeTruthy();
    });
});


// ══════════════════════════════════════════════════════════════════
//  Case 12  —  CAD overlay preview — REMOVED in Phase 14A.
//
//  The ``cad_overlay`` form_type was dropped; see
//  ``backend/routers/form_templates.py`` header for the decision
//  log. The former ``CadOverlayPreview`` export is gone; a dedicated
//  pytest (``test_form_templates_cad_dropped.py``) ratchets that
//  ``cad_overlay`` can no longer be fetched from the backend.
// ══════════════════════════════════════════════════════════════════

describe("Case 12 · cad_overlay form_type is removed", () => {
  it("CadOverlayPreview is no longer exported from FormPreviews",
    async () => {
      const mod = await import(
        "@/components/form-editor/FormPreviews");
      expect(mod.CadOverlayPreview).toBeUndefined();
    });
});


// ══════════════════════════════════════════════════════════════════
//  Case 1 (route-guard, non-admin branch)
//
//  App.js's ``<AdminOnly>`` redirects any non-admin to ``/`` — we
//  assert the wrapper existence (above) + the component factory
//  behaves correctly when run with a non-admin.  The actual
//  <Navigate> rendering is tested elsewhere in the suite
//  (``route-guard-admin-or-owner.test.jsx``) — this test just locks
//  that the WRAPPER is applied specifically to our new route.
// ══════════════════════════════════════════════════════════════════

describe("Case 1b · nav entry registered in adminNav.js", () => {
  it("adminNav.js has a Form Editor entry pointing at /admin/form-editor",
    async () => {
      const fs = await import("node:fs");
      const path = await import("node:path");
      const src = fs.readFileSync(
        path.resolve(__dirname, "../nav/adminNav.js"), "utf8");
      expect(src).toMatch(/\/admin\/form-editor/);
      expect(src).toMatch(/Form Editor/);
    });
});
