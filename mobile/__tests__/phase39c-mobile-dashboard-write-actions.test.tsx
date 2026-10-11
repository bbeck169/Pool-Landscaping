/**
 * Phase 39C · mobile dashboard — Team CPO Readiness + Recommendations Queue.
 *   Per widget: fetch OK renders · fetch fail → error · write action hits
 *   the web endpoint · optimistic update + rollback on API error (+ toast).
 *   Dashboard: admin / super_admin mount (backend-effective gate), placed
 *   after Payments and before Revenue by Service.
 */
import React from "react";
import { render, waitFor, act, fireEvent } from "@testing-library/react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";

jest.setTimeout(20000);

const mockApiGet = jest.fn();
const mockApiPost = jest.fn();
const mockPush = jest.fn();
const mockToast = jest.fn();
let mockRole = "admin";
let mockDash: any = null;

jest.mock("@/src/api", () => ({ api: { get: (...a: any[]) => mockApiGet(...a), post: (...a: any[]) => mockApiPost(...a), patch: jest.fn() } }));
jest.mock("@/src/auth", () => ({ useAuth: () => ({ user: { role: mockRole, name: "Test Admin" } }) }));
jest.mock("@/src/components/ToastProvider", () => ({ useToast: () => ({ showToast: (...a: any[]) => mockToast(...a) }) }));
jest.mock("@/src/components/ConfirmModal", () => ({ showConfirm: (o: any) => o.onConfirm() }));
jest.mock("@/src/hooks/useOfflineQuery", () => ({
  useOfflineQuery: () => ({ data: mockDash, isLoading: false, error: null, refetch: jest.fn() }),
}));
jest.mock("expo-router", () => ({
  useRouter: () => ({ push: mockPush, replace: jest.fn() }),
  useFocusEffect: (cb: any) => require("react").useEffect(() => { const c = cb(); return typeof c === "function" ? c : undefined; }, []),
  Redirect: () => null,
}));
jest.mock("@expo/vector-icons", () => ({ Ionicons: () => null }));
jest.mock("@react-native-community/datetimepicker", () => {
  const { View } = require("react-native");
  return function MockPicker(p: any) { return <View testID={p.testID} />; };
});
jest.mock("@/src/components/widgets", () => {
  const { Text } = require("react-native");
  return { Header: ({ title }: any) => <Text testID="mock-header">{title}</Text> };
});
jest.mock("@/src/components/ui", () => {
  const { View, Text, Pressable } = require("react-native");
  return {
    Loading: (p: any) => <View testID={p.testID || "loading"} />,
    StatusChip: ({ status }: any) => <Text>{status}</Text>,
    Sheet: ({ visible, children, testID }: any) => (visible ? <View testID={testID}>{children}</View> : null),
    PrimaryButton: ({ title, onPress }: any) => <Pressable onPress={onPress}><Text>{title}</Text></Pressable>,
  };
});
jest.mock("@/src/components/ui/AppTextInput", () => {
  const { TextInput } = require("react-native");
  return function MockInput(p: any) { return <TextInput {...p} />; };
});
const stub = (id: string) => () => { const { View } = require("react-native"); return <View testID={id} />; };
jest.mock("@/src/components/SyncStatusPill", () => () => null);
jest.mock("@/src/components/sync/PendingChangesChip", () => ({ PendingChangesChip: () => null }));
jest.mock("@/src/components/ai/CreditsBudgetChip", () => () => null);
jest.mock("@/src/components/BudgetHealthCard", () => stub("stub-budget-health"));
jest.mock("@/src/components/LandscapingClockWidget", () => stub("stub-landscaping-clock"));
jest.mock("@/src/components/weather/WeatherWidget", () => stub("stub-weather"));
jest.mock("@/src/components/dashboard/EbitTile", () => stub("stub-ebit"));
jest.mock("@/src/components/dashboard/RevenueByCategoryTile", () => stub("stub-rev-cat"));
jest.mock("@/src/components/dashboard/IncomeByServiceCategoryTile", () => stub("stub-income-svc"));
jest.mock("@/src/components/dashboard/RevenueForecastTile", () => stub("stub-forecast"));
jest.mock("@/src/utils/formatCustomerName", () => ({ formatCustomerName: (r: any) => r?.customer_name || "Customer" }));

import Dashboard from "@/app/(app)/index";
import TeamCpoReadinessWidget, { buildCpoRows } from "@/src/components/dashboard/TeamCpoReadinessWidget";
import RecommendationsQueueWidget from "@/src/components/dashboard/RecommendationsQueueWidget";

const TEAM = [
  { id: "t1", name: "Cert Tech", role: "technician", department: "pool" },
  { id: "t2", name: "Prog Tech", role: "technician", department: "both" },
  { id: "t3", name: "New Tech", role: "technician", department: "" },
  { id: "t4", name: "Lawn Tech", role: "technician", department: "landscaping" },
  { id: "a1", name: "Boss", role: "admin" },
];
const CERTS = [{ user_id: "t1", module_code: "cpo-prep", quiz_score: 0.92, awarded_at: "2026-09-01T00:00:00Z" }, { user_id: "t2", module_code: "other" }];
const PROGRESS = [{ user_id: "t2", lessons_completed: ["a", "b"] }];
const RECS = { rows: [
  { id: "r1", customer_id: "c1", customer_name: "Ann", customer_email: "a@x.com", current_price: 100, recommended_price: 120, gap_pct: 20, age_days: 9, subject: "Price update" },
  { id: "r2", customer_id: "c2", customer_name: "Bob", current_price: 80, recommended_price: 90, gap_pct: 12.5, age_days: 14, subject: "Price update" },
] };

function deferred<T = any>() {
  let resolve!: (v: T) => void; let reject!: (e: any) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

function route(path: string): Promise<any> {
  if (path === "/training/certificates/admin") return Promise.resolve(CERTS);
  if (path === "/team") return Promise.resolve(TEAM);
  if (path.startsWith("/training/progress/admin")) return Promise.resolve(PROGRESS);
  if (path.startsWith("/recommendations-queue")) return Promise.resolve(RECS);
  if (path === "/maintenance/digest") return Promise.resolve({ overdue: 0, due_this_week: 0, items: [] });
  if (path === "/payments/summary") return Promise.resolve({ collected_this_month: 0, outstanding_total: 0, outstanding_count: 0, month_label: "Oct", overdue: [] });
  return Promise.resolve([]);
}
const gets = (p: string) => mockApiGet.mock.calls.map((c) => c[0] as string).filter((u) => u.startsWith(p));
function ids(node: any, out: string[] = []): string[] {
  if (!node) return out;
  if (Array.isArray(node)) { node.forEach((n) => ids(n, out)); return out; }
  if (node.props?.testID) out.push(node.props.testID);
  (node.children || []).forEach((c: any) => typeof c === "object" && ids(c, out));
  return out;
}

beforeEach(async () => {
  jest.clearAllMocks();
  await AsyncStorage.clear();
  mockRole = "admin";
  mockDash = { active_jobs: 1, pending_jobs: 0, outstanding: 0, requested_jobs: 0, revenue_series: [], recent_jobs: [], revenue_by_service: [{ label: "Pool", value: 10 }] };
  mockApiGet.mockImplementation(route);
});

describe("Phase 39C · Team CPO Readiness", () => {
  it("buildCpoRows: pool/both/blank techs only; cert > progress > not started", () => {
    const rows = buildCpoRows(CERTS, TEAM, PROGRESS);
    expect(rows.map((r) => [r.id, r.status])).toEqual([["t1", "Certified"], ["t2", "In progress"], ["t3", "Not started"]]);
    expect(rows[0].score).toBe(92);
  });

  it("fetch OK → summary, the 3 web endpoints, expand table", async () => {
    const r = render(<TeamCpoReadinessWidget />);
    await waitFor(() => r.getByTestId("cpo-readiness-summary"));
    expect(r.getByTestId("cpo-readiness-summary").props.children.join("")).toBe("1 of 3 pool techs certified · 1 in progress · 1 not started");
    expect(gets("/training")).toEqual(["/training/certificates/admin", "/training/progress/admin?module_code=cpo-prep"]);
    expect(gets("/team")).toEqual(["/team"]);
    fireEvent.press(r.getByTestId("cpo-readiness-toggle"));
    expect(r.getByTestId("cpo-readiness-row-t3")).toBeTruthy();
  });

  it("fetch fail → error state, no nudge button", async () => {
    mockApiGet.mockImplementation((p: string) => (p === "/team" ? Promise.reject(new Error("Admin access required")) : route(p)));
    const r = render(<TeamCpoReadinessWidget />);
    await waitFor(() => r.getByTestId("cpo-readiness-error"));
    expect(r.getByText("Admin access required")).toBeTruthy();
    expect(r.queryByTestId("cpo-nudge-btn")).toBeNull();
  });

  it("nudge → POST /training/nudge-non-starters; optimistic Nudged + loading; result on success", async () => {
    const d = deferred();
    mockApiPost.mockReturnValue(d.promise);
    const r = render(<TeamCpoReadinessWidget />);
    await waitFor(() => r.getByTestId("cpo-nudge-btn"));
    fireEvent.press(r.getByTestId("cpo-readiness-toggle"));
    fireEvent.press(r.getByTestId("cpo-nudge-btn"));
    fireEvent.press(r.getByTestId("cpo-nudge-send"));
    expect(mockApiPost).toHaveBeenCalledWith("/training/nudge-non-starters", { module_code: "cpo-prep", message: expect.stringContaining("CPO Prep"), include_email: false });
    expect(r.getByTestId("cpo-readiness-row-t3-nudged")).toBeTruthy();
    expect(r.getByTestId("cpo-nudge-sending")).toBeTruthy();
    await act(async () => { d.resolve({ count_nudged: 1, count_skipped_idempotent: 0 }); });
    expect(r.getByTestId("cpo-nudge-result")).toBeTruthy();
    expect(r.getByTestId("cpo-readiness-row-t3-nudged")).toBeTruthy();
    expect(mockToast).toHaveBeenCalledWith("Nudged 1 tech.", "success");
  });

  it("nudge API error → rollback Nudged + error banner + toast", async () => {
    const d = deferred();
    mockApiPost.mockReturnValue(d.promise);
    const r = render(<TeamCpoReadinessWidget />);
    await waitFor(() => r.getByTestId("cpo-nudge-btn"));
    fireEvent.press(r.getByTestId("cpo-readiness-toggle"));
    fireEvent.press(r.getByTestId("cpo-nudge-btn"));
    fireEvent.press(r.getByTestId("cpo-nudge-send"));
    expect(r.getByTestId("cpo-readiness-row-t3-nudged")).toBeTruthy();
    await act(async () => { d.reject(new Error("boom")); });
    expect(r.queryByTestId("cpo-readiness-row-t3-nudged")).toBeNull();
    expect(r.getByTestId("cpo-nudge-error")).toBeTruthy();
    expect(mockToast).toHaveBeenCalledWith("boom", "error");
  });
});

describe("Phase 39C · Recommendations Queue", () => {
  it("fetch OK → rows + summary from ?older_than_days=7", async () => {
    const r = render(<RecommendationsQueueWidget />);
    await waitFor(() => r.getByTestId("recs-queue-row-r1"));
    expect(gets("/recommendations-queue")).toEqual(["/recommendations-queue?older_than_days=7"]);
    expect(r.getByTestId("recs-queue-summary")).toBeTruthy();
    expect(r.getByTestId("recs-queue-row-r2")).toBeTruthy();
  });

  it("fetch fail → error state", async () => {
    mockApiGet.mockImplementation(() => Promise.reject(new Error("Admin access required")));
    const r = render(<RecommendationsQueueWidget />);
    await waitFor(() => r.getByTestId("recs-queue-error"));
    expect(r.queryByTestId("recs-queue-table")).toBeNull();
  });

  it("send → POST /{id}/send; row removed optimistically with Syncing…; toast + reload on success", async () => {
    const d = deferred();
    mockApiPost.mockReturnValue(d.promise);
    const r = render(<RecommendationsQueueWidget />);
    await waitFor(() => r.getByTestId("recs-queue-row-r1"));
    fireEvent.press(r.getByTestId("recs-queue-send-r1"));
    expect(mockApiPost).toHaveBeenCalledWith("/recommendations-queue/r1/send", {});
    expect(r.queryByTestId("recs-queue-row-r1")).toBeNull();
    expect(r.getByTestId("recs-queue-syncing")).toBeTruthy();
    mockApiGet.mockImplementation(() => Promise.resolve({ rows: [RECS.rows[1]] }));
    await act(async () => { d.resolve({ id: "r1", status: "sent", resend_id: "rs_1" }); });
    expect(mockToast).toHaveBeenCalledWith("Sent ✓ (rs_1)", "success");
    expect(gets("/recommendations-queue").length).toBe(2);
    expect(r.queryByTestId("recs-queue-syncing")).toBeNull();
    expect(r.queryByTestId("recs-queue-row-r1")).toBeNull();
  });

  it("send API error → row restored at original index + toast", async () => {
    const d = deferred();
    mockApiPost.mockReturnValue(d.promise);
    const r = render(<RecommendationsQueueWidget />);
    await waitFor(() => r.getByTestId("recs-queue-row-r1"));
    fireEvent.press(r.getByTestId("recs-queue-send-r1"));
    expect(r.queryByTestId("recs-queue-row-r1")).toBeNull();
    await act(async () => { d.reject(new Error("Row is not a draft")); });
    const order = ids(r.toJSON()).filter((i) => /^recs-queue-row-/.test(i));
    expect(order).toEqual(["recs-queue-row-r1", "recs-queue-row-r2"]);
    expect(mockToast).toHaveBeenCalledWith("Row is not a draft", "error");
  });

  it("discard (confirm) → POST /{id}/discard; optimistic remove; rollback on error", async () => {
    const d = deferred();
    mockApiPost.mockReturnValue(d.promise);
    const r = render(<RecommendationsQueueWidget />);
    await waitFor(() => r.getByTestId("recs-queue-row-r2"));
    fireEvent.press(r.getByTestId("recs-queue-discard-r2"));
    expect(mockApiPost).toHaveBeenCalledWith("/recommendations-queue/r2/discard", {});
    expect(r.queryByTestId("recs-queue-row-r2")).toBeNull();
    await act(async () => { d.reject(new Error("nope")); });
    expect(r.getByTestId("recs-queue-row-r2")).toBeTruthy();
    expect(mockToast).toHaveBeenCalledWith("nope", "error");
  });

  it("preview sheet → Send Now fires send and closes the sheet", async () => {
    mockApiPost.mockResolvedValue({ status: "not_sent_missing_key" });
    const r = render(<RecommendationsQueueWidget />);
    await waitFor(() => r.getByTestId("recs-queue-row-r1"));
    fireEvent.press(r.getByTestId("recs-queue-view-r1"));
    expect(r.getByTestId("recs-queue-preview")).toBeTruthy();
    await act(async () => { fireEvent.press(r.getByTestId("recs-queue-preview-send")); });
    expect(mockApiPost).toHaveBeenCalledWith("/recommendations-queue/r1/send", {});
    expect(r.queryByTestId("recs-queue-preview")).toBeNull();
  });
});

describe("Phase 39C · dashboard mount + role gate", () => {
  it("admin: both widgets between Payments and Revenue by Service", async () => {
    const r = render(<Dashboard />);
    await waitFor(() => r.getByTestId("recs-queue-row-r1"));
    const o = ids(r.toJSON());
    const seq = ["revenue-chart", "payments-widget", "cpo-readiness-widget", "recs-queue-widget", "revenue-by-service"];
    const idx = seq.map((id) => { const i = o.indexOf(id); expect([id, i >= 0]).toEqual([id, true]); return i; });
    expect([...idx].sort((a, b) => a - b)).toEqual(idx);
  });

  it.each(["manager", "owner"])("%s: neither widget mounts nor fetches", async (role) => {
    mockRole = role;
    const r = render(<Dashboard />);
    await waitFor(() => r.getByTestId("dashboard-kpi-grid"));
    await act(async () => {});
    expect(r.queryByTestId("cpo-readiness-widget")).toBeNull();
    expect(r.queryByTestId("recs-queue-widget")).toBeNull();
    expect(gets("/training")).toEqual([]);
    expect(gets("/recommendations-queue")).toEqual([]);
  });

  it("super_admin: both mount", async () => {
    mockRole = "super_admin";
    const r = render(<Dashboard />);
    await waitFor(() => r.getByTestId("cpo-readiness-widget"));
    expect(r.getByTestId("recs-queue-widget")).toBeTruthy();
  });
});
