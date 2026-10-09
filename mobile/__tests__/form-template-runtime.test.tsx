/**
 * Phase 7D · Form Template Runtime (mobile) — helpers, loader, context.
 */
import React from "react";
import { Text } from "react-native";
import { render, renderHook, waitFor } from "@testing-library/react-native";

const mockGet = jest.fn();
jest.mock("@/src/api", () => {
  class ApiNetworkError extends Error { kind = "network"; }
  class ApiError extends Error { status: number; constructor(m: string, s: number) { super(m); this.status = s; } }
  return { api: { get: (...a: any[]) => mockGet(...a) }, ApiNetworkError, ApiError };
});
let mockTenant = "t1";
jest.mock("@/src/auth", () => ({ useAuth: () => ({ user: { role: "admin", tenant_id: mockTenant } }) }));
const { ApiNetworkError, ApiError } = jest.requireMock("@/src/api");

import { styleToRNStyle, widthColsToPercent, PADDING_Y_MULTIPLIER_PX } from "@/src/lib/formStyle";
import { useFormTemplateRuntime, invalidateFormTemplateRuntime, normalizeTemplate } from "@/src/hooks/useFormTemplateRuntime";
import { TemplateFieldProvider, useTemplateField, useFormTemplateOrder } from "@/src/components/form-renderer/TemplateFieldContext";

const TPL = {
  version: 3,
  fields: [
    { field_id: "notes", order: 2, locked_reorder: false, style: { bg_color: "#112233", bg_alpha: 0.5, text_color: "#FFFFFF", border_color: "#000000", width_cols: 6, padding_y: 3 } },
    { field_id: "photos", order: 1, locked_reorder: true, style: {} },
  ],
};

beforeEach(() => { invalidateFormTemplateRuntime(); mockGet.mockReset(); mockTenant = "t1"; });

describe("styleToRNStyle", () => {
  it("composes bg_color + bg_alpha into rgba and validates colours", () => {
    expect(styleToRNStyle({ bg_color: "#112233", bg_alpha: 0.5 }).backgroundColor).toBe("rgba(17, 34, 51, 0.5)");
    expect(styleToRNStyle({ bg_color: "#112233", bg_alpha: 7 }).backgroundColor).toBe("rgba(17, 34, 51, 1)");
    const d = styleToRNStyle({ bg_color: "red", text_color: "blue", border_color: "#ABC" });
    expect(d).toMatchObject({ backgroundColor: "rgba(255, 255, 255, 1)", color: "#111827", borderColor: "#E5E7EB" });
    expect(styleToRNStyle(null).paddingVertical).toBe(2 * PADDING_Y_MULTIPLIER_PX);
    expect(styleToRNStyle({ padding_y: 99 }).paddingVertical).toBe(32);
  });
  it("maps width_cols to percentages (width in stacks, flexBasis in rows)", () => {
    expect(widthColsToPercent(6)).toBe(50);
    expect(widthColsToPercent(4)).toBe(33.33);
    expect(widthColsToPercent(0)).toBeCloseTo(8.33);
    expect(widthColsToPercent(40)).toBe(100);
    expect(styleToRNStyle({ width_cols: 12 }).width).toBe("100%");
    const row = styleToRNStyle({ width_cols: 3 }, { layout: "row" });
    expect(row).toMatchObject({ flexBasis: "25%", maxWidth: "25%" });
    expect(row.width).toBeUndefined();
    expect(styleToRNStyle({ width_cols: 3 }).flexBasis).toBeUndefined();
  });
});

describe("useFormTemplateRuntime", () => {
  it("resolves fieldsById + fieldsOrdered; caches per (tenant, form_type)", async () => {
    mockGet.mockResolvedValue(TPL);
    const a = renderHook(() => useFormTemplateRuntime("pool_service_report"));
    expect(a.result.current.isLoading).toBe(true);
    await waitFor(() => expect(a.result.current.isEmpty).toBe(false));
    expect(a.result.current.fieldsOrdered.map((f) => f.field_id)).toEqual(["photos", "notes"]);
    expect(a.result.current.version).toBe(3);
    expect(mockGet).toHaveBeenCalledWith("/form-templates/pool_service_report");
    renderHook(() => useFormTemplateRuntime("pool_service_report"));
    expect(mockGet).toHaveBeenCalledTimes(1); // cache hit
    mockTenant = "t2";
    const c = renderHook(() => useFormTemplateRuntime("pool_service_report"));
    await waitFor(() => expect(c.result.current.isEmpty).toBe(false));
    expect(mockGet).toHaveBeenCalledTimes(2); // different tenant → separate key
  });

  it.each([
    ["404", () => new ApiError("Unknown form_type", 404), "http_404"],
    ["403 (tech role)", () => new ApiError("Forbidden", 403), "http_403"],
    ["500", () => new ApiError("boom", 500), "http_500"],
    ["network", () => new ApiNetworkError("offline"), "network"],
  ])("FALLBACK: %s → isEmpty, no retry", async (_l, mk, code) => {
    mockGet.mockRejectedValue(mk());
    const { result } = renderHook(() => useFormTemplateRuntime("estimate"));
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current).toMatchObject({ isEmpty: true, error: code, fieldsOrdered: [] });
    expect(mockGet).toHaveBeenCalledTimes(1);
  });

  it("FALLBACK: malformed / empty payloads → isEmpty; null formType never fetches", async () => {
    expect(normalizeTemplate({ fields: [] })).toBeNull();
    expect(normalizeTemplate({ fields: [{ nope: 1 }] })).toBeNull();
    mockGet.mockResolvedValue("<html>");
    const { result } = renderHook(() => useFormTemplateRuntime("invoice"));
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.isEmpty).toBe(true);
    const n = renderHook(() => useFormTemplateRuntime(null));
    expect(n.result.current.isEmpty).toBe(true);
    expect(mockGet).toHaveBeenCalledTimes(1);
  });
});

describe("TemplateFieldContext", () => {
  const byId = normalizeTemplate(TPL)!.fieldsById;
  it("useTemplateField returns mapped style/order/lock for a known field_id", () => {
    const wrapper = ({ children }: any) => <TemplateFieldProvider fieldsById={byId}>{children}</TemplateFieldProvider>;
    const { result } = renderHook(() => useTemplateField("notes"), { wrapper });
    expect(result.current).toMatchObject({ order: 2, isLocked: false, hasTemplate: true });
    expect(result.current.style).toMatchObject({ backgroundColor: "rgba(17, 34, 51, 0.5)", color: "#FFFFFF", paddingVertical: 12, width: "50%" });
    expect(renderHook(() => useTemplateField("photos"), { wrapper }).result.current.isLocked).toBe(true);
    expect(renderHook(() => useTemplateField("nope"), { wrapper }).result.current).toEqual({ style: null, order: null, isLocked: false, hasTemplate: false });
  });
  it("no provider / empty map → null style + null order", () => {
    expect(renderHook(() => useTemplateField("notes")).result.current.hasTemplate).toBe(false);
    function Order() { const o = useFormTemplateOrder(); return <Text testID="o">{JSON.stringify(o)}</Text>; }
    expect(render(<Order />).getByTestId("o").props.children).toBe("null");
    expect(render(<TemplateFieldProvider fieldsById={byId}><Order /></TemplateFieldProvider>).getByTestId("o").props.children).toBe('["photos","notes"]');
  });
});
