/**
 * Phase 53c · Feb-2026 — Mobile EBIT panel jest suite.
 *
 * Mounts <EbitPanel /> with every native dep mocked. Covers:
 *   1. Role gate: super/admin edit; manager read-only; tech/customer
 *      see the forbidden banner.
 *   2. Adjustment mode: entering a delta updates effective + EBIT total.
 *   3. Override mode: flip → absolute replaces computed; clear reverts.
 *   4. Range picker: switching triggers a refetch.
 *   5. Save flow: POST → version pill updates.
 *   6. Version history modal: renders list, load places editor in
 *      read-only, fork restores editable.
 *   7. CSV export: writes the expected payload + calls shareAsync.
 *   8. PDF export: uses expo-print + expo-sharing (both bundled).
 */
import React from "react";
import { render, waitFor, fireEvent, act } from "@testing-library/react-native";

jest.setTimeout(15000);

// ── Mocks ────────────────────────────────────────────────────────────
const mockApiGet = jest.fn();
const mockApiPost = jest.fn();

let mockUserRole: any = { id: "u_admin", role: "super_admin", email: "a@ex.com", name: "Alice" };

jest.mock("@/src/auth", () => ({
  useAuth: () => ({ user: mockUserRole }),
}));

jest.mock("@/src/api", () => ({
  api: { get: (...a: any[]) => mockApiGet(...a), post: (...a: any[]) => mockApiPost(...a) },
  api_base: () => "https://example.test/api",
  getAuthToken: async () => "tok",
}));

const mockWriteAsString = jest.fn(async () => undefined);
jest.mock("expo-file-system/legacy", () => ({
  cacheDirectory: "file:///cache/",
  writeAsStringAsync: (...a: any[]) => mockWriteAsString(...a),
  EncodingType: { UTF8: "utf8" },
}));

const mockShareAsync = jest.fn(async () => undefined);
const mockIsSharingAvailable = jest.fn(async () => true);
jest.mock("expo-sharing", () => ({
  shareAsync: (...a: any[]) => mockShareAsync(...a),
  isAvailableAsync: (...a: any[]) => mockIsSharingAvailable(...a),
}));

const mockPrintToFile = jest.fn(async () => ({ uri: "file:///cache/ebit.pdf" }));
const mockPrintAsync = jest.fn(async () => undefined);
jest.mock("expo-print", () => ({
  printToFileAsync: (...a: any[]) => mockPrintToFile(...a),
  printAsync: (...a: any[]) => mockPrintAsync(...a),
}));

// react-native Alert
const mockAlert = jest.fn();
jest.mock("react-native/Libraries/Alert/Alert", () => ({
  alert: (...a: any[]) => mockAlert(...a),
}));

import EbitPanel from "@/src/components/admin/EbitPanel";

// Recursively concat all string leaves of a React element tree.
// RN Text `children` on a `View` returns a React element, not a
// string — so `.props.children` is a `<Text>` node. This walks it.
function textOf(el: any): string {
  if (el == null) return "";
  if (typeof el === "string" || typeof el === "number") return String(el);
  if (Array.isArray(el)) return el.map(textOf).join("");
  const kids = el?.props?.children;
  return kids !== undefined ? textOf(kids) : "";
}

const LIVE_CASH = {
  range_from: "2026-02-01", range_to: "2026-02-28",
  revenue_basis: "cash",
  revenue: 1500, cogs: 300, opex: 900, depreciation: 200, ebit: 100,
  breakdown: { invoice_count: 2, line_count: 2, opex_payroll: 700,
                opex_other: 200, opex_by_category: [],
                depreciation_by_category: [], wages_by_role: {} },
  line_adjustments: { revenue: 0, cogs: 0, opex: 0, depreciation: 0 },
  line_overrides:   { revenue: null, cogs: null, opex: null, depreciation: null },
};
const LIVE_ACCRUAL = { ...LIVE_CASH, revenue: 2300, ebit: 900, revenue_basis: "accrual" };

beforeEach(() => {
  mockApiGet.mockReset();
  mockApiPost.mockReset();
  mockWriteAsString.mockClear();
  mockShareAsync.mockClear();
  mockIsSharingAvailable.mockClear();
  mockPrintToFile.mockClear();
  mockPrintAsync.mockClear();
  mockUserRole = { id: "u_admin", role: "super_admin", email: "a@ex.com" };
});

// ═══════════════════════════════════════════════════════════════════
// 1. Role gate
// ═══════════════════════════════════════════════════════════════════
describe("Mobile · EbitPanel · role gate", () => {
  it("super_admin sees the editable panel", async () => {
    mockApiGet.mockResolvedValueOnce(LIVE_CASH);
    mockUserRole = { role: "super_admin", id: "u1" };
    const { getByTestId } = render(<EbitPanel />);
    await waitFor(() => expect(getByTestId("ebit-panel")).toBeTruthy());
    expect(getByTestId("ebit-save-btn")).toBeTruthy();
    expect(getByTestId("ebit-row-revenue-adjustment-mode")).toBeTruthy();
  });

  it("admin sees the editable panel", async () => {
    mockApiGet.mockResolvedValueOnce(LIVE_CASH);
    mockUserRole = { role: "admin", id: "u1" };
    const { getByTestId } = render(<EbitPanel />);
    await waitFor(() => expect(getByTestId("ebit-panel")).toBeTruthy());
    expect(getByTestId("ebit-save-btn")).toBeTruthy();
  });

  it("manager sees the panel read-only (inputs disabled, no save/flip, badge shown)", async () => {
    mockApiGet.mockResolvedValueOnce(LIVE_CASH);
    mockUserRole = { role: "manager", id: "u1" };
    const { getByTestId, queryByTestId } = render(<EbitPanel />);
    await waitFor(() => expect(getByTestId("ebit-panel")).toBeTruthy());

    // Phase 53c-fix · Feb-2026 — every adjustment row still renders
    // (so prior edits are visible) with ``editable={false}`` on the
    // TextInput. The save button and every flip-override button are
    // omitted, and the yellow read-only badge is present.
    expect(getByTestId("ebit-panel-readonly-badge")).toBeTruthy();
    expect(queryByTestId("ebit-save-btn")).toBeNull();
    for (const k of ["revenue", "cogs", "opex", "depreciation"]) {
      expect(getByTestId(`ebit-row-${k}-adjustment-mode`)).toBeTruthy();
      expect(getByTestId(`ebit-row-${k}-adjustment-input`).props.editable).toBe(false);
      expect(queryByTestId(`ebit-row-${k}-flip-override`)).toBeNull();
    }
    // History + exports remain reachable.
    expect(getByTestId("ebit-open-versions")).toBeTruthy();
    expect(getByTestId("ebit-export-csv")).toBeTruthy();
    expect(getByTestId("ebit-export-pdf")).toBeTruthy();
  });

  it("tech sees the forbidden banner and does NOT fetch", async () => {
    mockUserRole = { role: "technician", id: "u1" };
    const { getByTestId } = render(<EbitPanel />);
    expect(getByTestId("ebit-panel-forbidden")).toBeTruthy();
    expect(mockApiGet).not.toHaveBeenCalled();
  });

  it("customer sees the forbidden banner", async () => {
    mockUserRole = { role: "customer", id: "u1" };
    const { getByTestId } = render(<EbitPanel />);
    expect(getByTestId("ebit-panel-forbidden")).toBeTruthy();
  });
});

// ═══════════════════════════════════════════════════════════════════
// 2. Adjustment mode
// ═══════════════════════════════════════════════════════════════════
describe("Mobile · EbitPanel · adjustment mode", () => {
  it("entering a delta updates effective + EBIT total", async () => {
    mockApiGet.mockResolvedValueOnce(LIVE_CASH);
    const { getByTestId } = render(<EbitPanel />);
    await waitFor(() => expect(getByTestId("ebit-total-value")).toBeTruthy());
    expect(textOf(getByTestId("ebit-total-value"))).toContain("100.00");

    const input = getByTestId("ebit-row-revenue-adjustment-input");
    await act(async () => {
      fireEvent.changeText(input, "50");
    });
    // Revenue 1500 + 50 = 1550 → EBIT 100 + 50 = 150.
    expect(textOf(getByTestId("ebit-row-revenue-effective"))).toContain("1,550.00");
    expect(textOf(getByTestId("ebit-total-value"))).toContain("150.00");
  });
});

// ═══════════════════════════════════════════════════════════════════
// 3. Override mode
// ═══════════════════════════════════════════════════════════════════
describe("Mobile · EbitPanel · override mode", () => {
  it("flipping to override replaces computed; clearing reverts", async () => {
    mockApiGet.mockResolvedValueOnce(LIVE_CASH);
    const { getByTestId } = render(<EbitPanel />);
    await waitFor(() => getByTestId("ebit-total-value"));

    await act(async () => {
      fireEvent.press(getByTestId("ebit-row-depreciation-flip-override"));
    });
    const ovrInput = getByTestId("ebit-row-depreciation-override-input");
    await act(async () => {
      fireEvent.changeText(ovrInput, "999");
    });
    // Depreciation 999 → EBIT = 1500 - 300 - 900 - 999 = -699.
    expect(textOf(getByTestId("ebit-row-depreciation-effective"))).toContain("999.00");
    expect(textOf(getByTestId("ebit-total-value"))).toContain("-699.00");

    await act(async () => {
      fireEvent.press(getByTestId("ebit-row-depreciation-override-clear"));
    });
    expect(getByTestId("ebit-row-depreciation-adjustment-mode")).toBeTruthy();
    expect(textOf(getByTestId("ebit-total-value"))).toContain("100.00");
  });
});

// ═══════════════════════════════════════════════════════════════════
// 4. Time-range picker
// ═══════════════════════════════════════════════════════════════════
describe("Mobile · EbitPanel · range picker", () => {
  it("switching to quarterly triggers a refetch with range=quarterly", async () => {
    mockApiGet
      .mockResolvedValueOnce(LIVE_CASH)   // initial monthly
      .mockResolvedValueOnce(LIVE_CASH);  // quarterly
    const { getByTestId } = render(<EbitPanel />);
    await waitFor(() => expect(mockApiGet).toHaveBeenCalledTimes(1));
    expect(mockApiGet.mock.calls[0][0]).toMatch(/range=monthly/);

    await act(async () => {
      fireEvent.press(getByTestId("ebit-range-quarterly"));
    });
    await waitFor(() => expect(mockApiGet).toHaveBeenCalledTimes(2));
    expect(mockApiGet.mock.calls[1][0]).toMatch(/range=quarterly/);
  });

  it("switching to accrual basis refetches and shows new EBIT", async () => {
    mockApiGet
      .mockResolvedValueOnce(LIVE_CASH)
      .mockResolvedValueOnce(LIVE_ACCRUAL);
    const { getByTestId } = render(<EbitPanel />);
    await waitFor(() => expect(mockApiGet).toHaveBeenCalledTimes(1));

    await act(async () => {
      fireEvent.press(getByTestId("ebit-basis-accrual"));
    });
    await waitFor(() => expect(mockApiGet).toHaveBeenCalledTimes(2));
    expect(mockApiGet.mock.calls[1][0]).toMatch(/revenue_basis=accrual/);
    await waitFor(() =>
      expect(textOf(getByTestId("ebit-total-value"))).toContain("900.00"));
  });
});

// ═══════════════════════════════════════════════════════════════════
// 5. Save flow
// ═══════════════════════════════════════════════════════════════════
describe("Mobile · EbitPanel · save flow", () => {
  it("save posts to /ebit/snapshots and updates the version pill", async () => {
    mockApiGet.mockResolvedValueOnce(LIVE_CASH);
    mockApiPost.mockResolvedValueOnce({
      id: "snap-1", version: 3, ebit: 100,
      line_adjustments: {}, line_overrides: {}, saved_at: "2026-02-15",
      revenue_basis: "cash", author_user_id: "u1", note: "test",
    });
    mockApiGet.mockResolvedValueOnce({ snapshots: [] });  // post-save refresh

    const { getByTestId } = render(<EbitPanel />);
    await waitFor(() => getByTestId("ebit-save-btn"));

    await act(async () => {
      fireEvent.changeText(getByTestId("ebit-save-note"), "test");
    });
    await act(async () => {
      fireEvent.press(getByTestId("ebit-save-btn"));
    });
    await waitFor(() => expect(mockApiPost).toHaveBeenCalledTimes(1));
    expect(mockApiPost.mock.calls[0][0]).toBe("/ebit/snapshots");
    const body = mockApiPost.mock.calls[0][1];
    expect(body.range_kind).toBe("monthly");
    expect(body.revenue_basis).toBe("cash");
    expect(body.note).toBe("test");

    await waitFor(() =>
      expect(textOf(getByTestId("ebit-panel-loaded-version"))).toContain("v3"));
  });
});

// ═══════════════════════════════════════════════════════════════════
// 6. Version history modal
// ═══════════════════════════════════════════════════════════════════
describe("Mobile · EbitPanel · version history", () => {
  it("History opens modal; loading a version puts editor read-only + fork restores", async () => {
    mockApiGet
      .mockResolvedValueOnce(LIVE_CASH)  // initial compute
      .mockResolvedValueOnce({           // snapshots list
        snapshots: [
          { id: "s1", version: 2, ebit: 150, revenue_basis: "cash",
            saved_at: "2026-02-10T00:00:00Z", author_user_id: "u1abcdef",
            line_adjustments: { revenue: 50, cogs: 0, opex: 0, depreciation: 0 },
            line_overrides: { revenue: null, cogs: null, opex: null, depreciation: null },
            note: "prior" },
          { id: "s0", version: 1, ebit: 100, revenue_basis: "cash",
            saved_at: "2026-02-05T00:00:00Z", author_user_id: "u1abcdef",
            line_adjustments: {}, line_overrides: {}, note: "" },
        ],
      });

    const { getByTestId, queryByTestId } = render(<EbitPanel />);
    await waitFor(() => getByTestId("ebit-total-value"));

    await act(async () => {
      fireEvent.press(getByTestId("ebit-open-versions"));
    });
    await waitFor(() => getByTestId("ebit-versions-modal"));
    expect(getByTestId("ebit-versions-row-s1")).toBeTruthy();

    await act(async () => {
      fireEvent.press(getByTestId("ebit-versions-load-s1"));
    });
    expect(textOf(getByTestId("ebit-panel-loaded-version"))).toContain("v2");
    expect(getByTestId("ebit-fork-btn")).toBeTruthy();
    expect(queryByTestId("ebit-save-btn")).toBeNull();

    await act(async () => {
      fireEvent.press(getByTestId("ebit-fork-btn"));
    });
    expect(getByTestId("ebit-save-btn")).toBeTruthy();
  });
});

// ═══════════════════════════════════════════════════════════════════
// 7. CSV export
// ═══════════════════════════════════════════════════════════════════
describe("Mobile · EbitPanel · CSV export", () => {
  it("writes a CSV string then invokes SharingModule.shareAsync", async () => {
    mockApiGet.mockResolvedValueOnce(LIVE_CASH);
    const { getByTestId } = render(<EbitPanel />);
    await waitFor(() => getByTestId("ebit-export-csv"));

    await act(async () => {
      fireEvent.press(getByTestId("ebit-export-csv"));
    });
    await waitFor(() => expect(mockWriteAsString).toHaveBeenCalledTimes(1));
    const [path, csv, opts] = mockWriteAsString.mock.calls[0];
    expect(typeof path).toBe("string");
    expect(path).toMatch(/\.csv$/);
    expect(csv).toContain("revenue,");
    expect(csv).toContain("ebit,");
    expect(opts.encoding).toBe("utf8");

    await waitFor(() => expect(mockShareAsync).toHaveBeenCalledTimes(1));
    const [sharedPath, sharedOpts] = mockShareAsync.mock.calls[0];
    expect(sharedPath).toBe(path);
    expect(sharedOpts.mimeType).toBe("text/csv");
  });
});

// ═══════════════════════════════════════════════════════════════════
// 8. PDF export
// ═══════════════════════════════════════════════════════════════════
describe("Mobile · EbitPanel · PDF export", () => {
  it("uses expo-print then shares the produced file", async () => {
    mockApiGet.mockResolvedValueOnce(LIVE_CASH);
    const { getByTestId } = render(<EbitPanel />);
    await waitFor(() => getByTestId("ebit-export-pdf"));

    await act(async () => {
      fireEvent.press(getByTestId("ebit-export-pdf"));
    });
    await waitFor(() => expect(mockPrintToFile).toHaveBeenCalledTimes(1));
    const [opts] = mockPrintToFile.mock.calls[0];
    expect(typeof opts.html).toBe("string");
    expect(opts.html).toContain("EBIT");
    expect(opts.html).toContain(LIVE_CASH.range_basis === "accrual" ? "accrual" : "cash");
    await waitFor(() => expect(mockShareAsync).toHaveBeenCalledTimes(1));
    expect(mockShareAsync.mock.calls[0][1].mimeType).toBe("application/pdf");
  });
});
