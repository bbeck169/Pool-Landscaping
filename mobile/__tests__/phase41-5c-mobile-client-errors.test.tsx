/**
 * Phase 41.5c · Feb-2026 — Mobile Client Errors diagnostics render test.
 *
 * Boots ``app/admin/diagnostics/errors.tsx`` with every native dep
 * mocked. Covers:
 *   1. Admin sees the list from GET /admin/client-errors (no
 *      component filter on first mount).
 *   2. Filter input + refresh button hits the endpoint with
 *      ``?component=…``.
 *   3. Tapping a row opens the detail modal showing message, stack
 *      trace, URL, and user agent.
 *   4. Copy-to-clipboard invokes expo-clipboard with the stack.
 *   5. Pull-to-refresh (RefreshControl.onRefresh) triggers refetch.
 *   6. Technician + customer are blocked by the role gate.
 *   7. Empty response renders the "no client-side errors" empty state.
 *   8. GET failure surfaces the inline error banner.
 */
import React from "react";
import { render, waitFor, act, fireEvent } from "@testing-library/react-native";

jest.setTimeout(15000);

// ── Mocks ────────────────────────────────────────────────────────────
const mockApiGet = jest.fn();
jest.mock("@/src/api", () => ({
  api: { get: (...a: any[]) => mockApiGet(...a) },
}));

let mockUser: any = { id: "u_admin", role: "admin", email: "a@ex.com" };
jest.mock("@/src/auth", () => ({
  useAuth: () => ({ user: mockUser }),
}));

jest.mock("@/src/components/widgets", () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const ReactMock = require("react");
  const RN = jest.requireActual("react-native");
  return {
    Header: ({ title }: { title: string }) =>
      ReactMock.createElement(RN.Text, { testID: "test-header" }, title),
  };
});

const mockClipboardSet = jest.fn(async () => undefined);
jest.mock("expo-clipboard", () => ({
  setStringAsync: (...a: any[]) => mockClipboardSet(...a),
}));

// eslint-disable-next-line import/first
import { Alert as RNAlert } from "react-native";
const mockAlert = jest.spyOn(RNAlert, "alert").mockImplementation(() => {});

// eslint-disable-next-line import/first
import ClientErrorsScreen from "@/app/admin/diagnostics/errors";

const ROWS = [
  {
    id: "err_1",
    created_at: "2026-02-14T09:30:15.222Z",
    component: "DispatchBoard",
    message: "Cannot read properties of undefined (reading 'route')",
    url: "https://app.example.com/dispatch",
    user_email: "alice@ex.com",
    user_agent: "Mozilla/5.0 (Macintosh) Firefox/125",
    stack: "TypeError: Cannot read properties of undefined\n  at Board.jsx:42",
  },
  {
    id: "err_2",
    created_at: "2026-02-14T09:25:03.000Z",
    component: null,
    message: "Network request failed",
    url: null,
    user_email: null,
    user_agent: "Mozilla/5.0 (iPhone)",
    stack: null,
  },
];

beforeEach(() => {
  mockApiGet.mockReset();
  mockClipboardSet.mockClear();
  mockAlert.mockReset();
  mockUser = { id: "u_admin", role: "admin", email: "a@ex.com" };
});

describe("Phase 41.5c · mobile Client Errors diagnostics", () => {
  it("admin sees the newest-100 list from /admin/client-errors", async () => {
    mockApiGet.mockResolvedValueOnce({ errors: ROWS, count: ROWS.length });
    const { getByTestId } = render(<ClientErrorsScreen />);
    await waitFor(() => expect(mockApiGet).toHaveBeenCalledTimes(1));
    // No filter → endpoint hit without querystring.
    expect(mockApiGet.mock.calls[0][0]).toBe("/admin/client-errors");
    await waitFor(() =>
      expect(getByTestId("client-errors-row-err_1")).toBeTruthy());
    expect(getByTestId("client-errors-row-err_2")).toBeTruthy();
    // Timestamp + message hooks are exposed.
    expect(getByTestId("client-errors-when-err_1")).toBeTruthy();
    expect(getByTestId("client-errors-message-err_1")).toBeTruthy();
  });

  it("component filter + refresh hits endpoint with ?component=…", async () => {
    mockApiGet.mockResolvedValue({ errors: [], count: 0 });
    const { getByTestId } = render(<ClientErrorsScreen />);
    await waitFor(() => expect(mockApiGet).toHaveBeenCalledTimes(1));

    await act(async () => {
      fireEvent.changeText(getByTestId("client-errors-filter"), "DispatchBoard");
    });
    // The filter change refetches automatically (load is memoized on componentFilter).
    await waitFor(() => expect(mockApiGet).toHaveBeenCalledTimes(2));
    expect(mockApiGet.mock.calls[1][0]).toBe("/admin/client-errors?component=DispatchBoard");

    // Refresh button also refetches with the current filter.
    await act(async () => {
      fireEvent.press(getByTestId("client-errors-refresh"));
    });
    await waitFor(() => expect(mockApiGet).toHaveBeenCalledTimes(3));
    expect(mockApiGet.mock.calls[2][0]).toBe("/admin/client-errors?component=DispatchBoard");
  });

  it("tapping a row opens the detail modal with stack + url + UA", async () => {
    mockApiGet.mockResolvedValueOnce({ errors: ROWS, count: 2 });
    const { getByTestId } = render(<ClientErrorsScreen />);
    await waitFor(() =>
      expect(getByTestId("client-errors-row-err_1")).toBeTruthy());

    await act(async () => {
      fireEvent.press(getByTestId("client-errors-row-err_1"));
    });
    await waitFor(() => expect(getByTestId("client-errors-detail-modal")).toBeTruthy());

    const textOf = (el: any): string => {
      if (el == null) return "";
      if (typeof el === "string" || typeof el === "number") return String(el);
      if (Array.isArray(el)) return el.map(textOf).join("");
      const k = el?.props?.children;
      return k !== undefined ? textOf(k) : "";
    };
    expect(textOf(getByTestId("client-errors-detail-message")))
      .toContain("Cannot read properties of undefined");
    expect(textOf(getByTestId("client-errors-detail-url")))
      .toBe("https://app.example.com/dispatch");
    expect(textOf(getByTestId("client-errors-detail-ua")))
      .toContain("Firefox/125");
    expect(textOf(getByTestId("client-errors-detail-stack")))
      .toContain("TypeError");
  });

  it("copy-to-clipboard invokes expo-clipboard with the stack", async () => {
    mockApiGet.mockResolvedValueOnce({ errors: ROWS, count: 2 });
    const { getByTestId } = render(<ClientErrorsScreen />);
    await waitFor(() => getByTestId("client-errors-row-err_1"));

    await act(async () => {
      fireEvent.press(getByTestId("client-errors-row-err_1"));
    });
    await waitFor(() => getByTestId("client-errors-copy-stack"));
    await act(async () => {
      fireEvent.press(getByTestId("client-errors-copy-stack"));
    });
    await waitFor(() => expect(mockClipboardSet).toHaveBeenCalledTimes(1));
    expect(mockClipboardSet.mock.calls[0][0]).toContain("TypeError");
    // Success toast is fired.
    await waitFor(() => expect(mockAlert).toHaveBeenCalledTimes(1));
    expect(mockAlert.mock.calls[0][0]).toBe("Copied");
  });

  it("pull-to-refresh triggers a refetch", async () => {
    mockApiGet.mockResolvedValue({ errors: ROWS, count: 2 });
    const { getByTestId } = render(<ClientErrorsScreen />);
    await waitFor(() => expect(mockApiGet).toHaveBeenCalledTimes(1));

    const scroll = getByTestId("client-errors-list");
    const refreshControl = scroll.props.refreshControl;
    expect(refreshControl).toBeDefined();
    await act(async () => { refreshControl.props.onRefresh(); });
    await waitFor(() => expect(mockApiGet).toHaveBeenCalledTimes(2));
  });

  it("empty response renders the empty-state card", async () => {
    mockApiGet.mockResolvedValueOnce({ errors: [], count: 0 });
    const { getByTestId } = render(<ClientErrorsScreen />);
    await waitFor(() => expect(mockApiGet).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(getByTestId("client-errors-empty")).toBeTruthy());
  });

  it("GET failure surfaces the inline error banner", async () => {
    mockApiGet.mockRejectedValueOnce(new Error("service unavailable"));
    const { getByTestId } = render(<ClientErrorsScreen />);
    await waitFor(() => expect(mockApiGet).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(getByTestId("client-errors-error")).toBeTruthy());
  });

  it("technician sees the role gate and no fetch runs", () => {
    mockUser = { id: "u_t", role: "technician", email: "t@ex.com" };
    const { getByTestId, queryByTestId } = render(<ClientErrorsScreen />);
    expect(getByTestId("client-errors-role-gate")).toBeTruthy();
    expect(queryByTestId("client-errors-screen")).toBeNull();
    expect(mockApiGet).not.toHaveBeenCalled();
  });

  it("customer is blocked by the role gate too", () => {
    mockUser = { id: "u_c", role: "customer", email: "c@ex.com" };
    const { getByTestId } = render(<ClientErrorsScreen />);
    expect(getByTestId("client-errors-role-gate")).toBeTruthy();
    expect(mockApiGet).not.toHaveBeenCalled();
  });
});
