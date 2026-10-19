/**
 * Dashboard parity · KPI drill-down targets honour the web query params.
 *  - admin `/admin/jobs?status=` (web JobsList) → GET /jobs?status=<s>
 *  - `/(app)/jobs?status=` (non-admin dashboard roles) seeds the FilterRow
 *  - `/(app)/customers?status=inactive` (web CustomersList ?status|?tab)
 */
import React from "react";
import { render, waitFor, fireEvent } from "@testing-library/react-native";

let mockParams: any = {};
let mockRole = "admin";
const mockSetParams = jest.fn();
const mockPush = jest.fn();
const mockGet = jest.fn(async (_url: string): Promise<any> => []);

jest.mock("@/src/api", () => ({
  api: {
    get: (u: string) => mockGet(u),
    post: jest.fn(async () => ({})), put: jest.fn(async () => ({})),
    patch: jest.fn(async () => ({})), del: jest.fn(async () => ({})),
  },
}));
jest.mock("@/src/auth", () => ({ useAuth: () => ({ user: { id: "u1", role: mockRole } }) }));
jest.mock("expo-router", () => {
  const React = jest.requireActual("react");
  const { Text } = jest.requireActual("react-native");
  return {
    useLocalSearchParams: () => mockParams,
    useRouter: () => ({ push: mockPush, back: jest.fn(), replace: jest.fn(), setParams: mockSetParams }),
    useFocusEffect: (cb: any) => React.useEffect(() => cb(), [cb]),
    Redirect: ({ href }: any) => <Text testID="redirect">{String(href)}</Text>,
    Link: ({ children }: any) => children,
  };
});
jest.mock("@/src/components/widgets", () => {
  const { View, Text, Pressable } = jest.requireActual("react-native");
  return {
    Header: (p: any) => <View><Text>{p.title}</Text>{p.right}</View>,
    IconButton: (p: any) => <View testID={p.testID} />,
    NotificationBell: () => null,
    OfflineBanner: () => null,
    JobCard: (p: any) => <View testID={p.testID} />,
    FilterRow: (p: any) => (
      <View testID={p.testID}>
        {p.options.map((o: any) => (
          <Pressable key={o.key} testID={`${p.testID}-${o.key}`} onPress={() => p.onChange(o.key)}>
            <Text>{o.key === p.value ? `[${o.label}]` : o.label}</Text>
          </Pressable>
        ))}
      </View>
    ),
  };
});
jest.mock("@/src/offline", () => ({
  useOnline: () => true,
  cacheJobs: jest.fn(),
  getCachedJobs: jest.fn(async () => null),
  flushPendingMutations: jest.fn(async () => {}),
}));
jest.mock("@/src/services/sync/photoWorker", () => ({ flushPhotos: jest.fn(async () => {}) }));
jest.mock("@/src/services/readCache", () => ({ writeCache: jest.fn(async () => {}), readCache: jest.fn(async () => null) }));
jest.mock("@/src/components/ImportExport", () => ({ ImportExport: () => null }));
jest.mock("@/src/components/bulk-select/BulkSelectToolkit", () => ({
  useBulkSelect: () => ({ selected: new Set(), count: 0, allSelected: false, indeterminate: false, toggleAll: jest.fn(), toggleOne: jest.fn(), clear: jest.fn() }),
  BulkCheckbox: () => null, BulkActionBar: () => null,
}));
jest.mock("@/src/components/customers/RestoreCustomerButton", () => () => null);
jest.mock("@/src/components/ToastProvider", () => ({ useToast: () => ({ showToast: jest.fn() }) }));

import AdminJobsList from "@/app/admin/jobs";
import Jobs from "@/app/(app)/jobs";
import Customers from "@/app/(app)/customers";

beforeEach(() => {
  mockGet.mockReset();
  mockGet.mockImplementation(async () => []);
  mockSetParams.mockClear();
  mockPush.mockClear();
  mockParams = {};
  mockRole = "admin";
});

describe("admin /admin/jobs (web JobsList)", () => {
  it("?status=active → GET /jobs?status=active, Active selected, row tap → job detail", async () => {
    mockParams = { status: "active" };
    mockGet.mockImplementation(async () => [{ id: "j1", title: "Weekly pool", status: "active", customer_name: "Alice" }]);
    const q = render(<AdminJobsList />);
    await waitFor(() => q.getByTestId("job-row-j1"));
    expect(mockGet).toHaveBeenCalledWith("/jobs?status=active");
    expect(q.getByText("[Active]")).toBeTruthy();
    fireEvent.press(q.getByTestId("job-row-j1"));
    expect(mockPush).toHaveBeenCalledWith("/job/j1");
  });

  it("?status=pending → GET /jobs?status=pending; empty copy matches web", async () => {
    mockParams = { status: "pending" };
    const q = render(<AdminJobsList />);
    await waitFor(() => q.getByTestId("jobs-empty"));
    expect(mockGet).toHaveBeenCalledWith("/jobs?status=pending");
    expect(q.getByText("No jobs match this filter.")).toBeTruthy();
  });

  it("no / unknown param → All (GET /jobs); changing filter refetches + writes the param", async () => {
    mockParams = { status: "bogus" };
    const q = render(<AdminJobsList />);
    await waitFor(() => expect(mockGet).toHaveBeenCalledWith("/jobs"));
    fireEvent.press(q.getByTestId("jobs-filter-status-completed"));
    await waitFor(() => expect(mockGet).toHaveBeenCalledWith("/jobs?status=completed"));
    expect(mockSetParams).toHaveBeenCalledWith({ status: "completed" });
  });

  it("non-admin is bounced (web AdminOnly)", () => {
    mockRole = "manager";
    const q = render(<AdminJobsList />);
    expect(q.getByTestId("redirect")).toBeTruthy();
  });
});

describe("/(app)/jobs ?status= (non-admin dashboard roles)", () => {
  it("manager + ?status=pending → filter seeded, GET /jobs?status=pending, param cleared", async () => {
    mockRole = "manager";
    mockParams = { status: "pending" };
    const q = render(<Jobs />);
    await waitFor(() => expect(mockGet).toHaveBeenCalledWith("/jobs?status=pending"));
    expect(q.getByText("[Pending]")).toBeTruthy();
    expect(mockSetParams).toHaveBeenCalledWith({ status: undefined });
  });

  it("no param → All (unchanged)", async () => {
    mockRole = "manager";
    render(<Jobs />);
    await waitFor(() => expect(mockGet).toHaveBeenCalledWith("/jobs"));
    expect(mockSetParams).not.toHaveBeenCalled();
  });
});

describe("/(app)/customers ?status=", () => {
  const custCalls = () => mockGet.mock.calls.map((c) => String(c[0])).filter((u) => u.startsWith("/customers?"));

  it("?status=inactive → Inactive segment fetch (is_active=false) + param cleared", async () => {
    mockParams = { status: "inactive" };
    render(<Customers />);
    await waitFor(() => expect(custCalls().some((u) => u.includes("is_active=false"))).toBe(true));
    expect(mockSetParams).toHaveBeenCalledWith({ tab: undefined, status: undefined });
  });

  it("?tab=inactive works too (web reads tab || status)", async () => {
    mockParams = { tab: "inactive" };
    render(<Customers />);
    await waitFor(() => expect(custCalls().some((u) => u.includes("is_active=false"))).toBe(true));
  });

  it("no param → K40 default Active (is_active=true), no setParams", async () => {
    render(<Customers />);
    await waitFor(() => expect(custCalls().length).toBeGreaterThan(0));
    expect(custCalls()[0]).toContain("is_active=true");
    expect(custCalls().some((u) => u.includes("is_active=false"))).toBe(false);
    expect(mockSetParams).not.toHaveBeenCalled();
  });
});
