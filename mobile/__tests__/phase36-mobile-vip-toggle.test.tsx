/**
 * Phase 36 · Port A — mobile VIP toggle (web parity ``customer-vip-toggle``).
 *   - Admin: Pressable ``customer-vip-toggle`` wraps the badge; inner view
 *     keeps ``vip-badge`` when VIP, ``vip-badge-off`` ("Flag as VIP") when not.
 *   - Non-admin: read-only ``vip-badge`` when VIP, nothing otherwise
 *     (backend PATCH /customers/{cid}/vip is require_admin).
 *   - Optimistic flip → PATCH { is_vip, vip_note } → rollback + error toast.
 *   - Spinner + disabled while in flight; double-tap fires once.
 */
import React from "react";
import { StyleSheet, Alert } from "react-native";
import { render, waitFor, act, within, fireEvent } from "@testing-library/react-native";

const mockApiGet = jest.fn();
const mockShowToast = jest.fn();
let mockRole = "admin";
jest.mock("@/src/api", () => {
  class ApiError extends Error {
    status: number; detail: string;
    constructor(status: number, message?: string) { super(message || "Error"); this.status = status; this.detail = message || "Error"; }
  }
  class ApiNetworkError extends Error { kind = "network"; constructor(m?: string) { super(m || "Network error"); } }
  return {
    api: { get: (...a: any[]) => mockApiGet(...a), post: jest.fn(), patch: jest.fn(), put: jest.fn(), del: jest.fn() },
    ApiError, ApiNetworkError, TOKEN_KEY: "token",
  };
});
jest.mock("@/src/auth", () => ({
  useAuth: () => ({ user: { id: "u1", role: mockRole, name: "Admin" }, startImpersonation: jest.fn() }),
}));
jest.mock("expo-router", () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: jest.fn() }),
  useLocalSearchParams: () => ({ id: "cust-1" }),
  usePathname: () => "/",
  useSegments: () => [],
  useFocusEffect: (cb: any) => require("react").useEffect(() => { cb(); }, []),
  Redirect: () => null,
}));
jest.mock("react-native-safe-area-context", () => ({
  useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }),
}));
jest.mock("@/src/hooks/useBreadcrumbs", () => ({ useBreadcrumbs: () => [] }));
jest.mock("@/src/hooks/useTenantBrand", () => ({
  __esModule: true,
  default: () => ({ logoUri: null, loading: false, error: null }),
  useTenantBrand: () => ({ logoUrl: null, loading: false, error: null }),
}));
jest.mock("@expo/vector-icons", () => {
  const { View } = require("react-native");
  return { Ionicons: (p: any) => <View testID={`icon-${p.name}`} accessibilityHint={p.color} /> };
});
jest.mock("expo-image", () => ({ Image: () => null }));
jest.mock("expo-image-picker", () => ({}));
jest.mock("@/src/components/ToastProvider", () => ({ useToast: () => ({ showToast: mockShowToast }) }));
jest.mock("@/src/services/readCache", () => ({ writeCache: jest.fn(async () => {}), readCache: jest.fn(async () => null) }));
jest.mock("@/src/components/ui", () => {
  const { View, Text, Pressable } = require("react-native");
  return {
    Loading: (p: any) => <View testID={p.testID || "loading"} />,
    PrimaryButton: ({ title, onPress }: any) => <Pressable onPress={onPress}><Text>{title}</Text></Pressable>,
    Sheet: () => null,
    StatusChip: () => null,
  };
});
// Screen sees a Header stub that records the ``dark`` prop; the real
// Header is exercised directly below via requireActual.
jest.mock("@/src/components/widgets", () => {
  const { View } = require("react-native");
  return {
    Header: (p: any) => <View testID={p.dark ? "header-stub-dark" : "header-stub-light"}>{p.right}</View>,
    JobCard: (p: any) => <View testID={p.testID} />,
  };
});
jest.mock("@/src/components/ui/AppTextInput", () => {
  const { TextInput } = require("react-native");
  return function MockAppTextInput(p: any) { return <TextInput {...p} />; };
});
jest.mock("@/src/components/customer", () => {
  const { View } = require("react-native");
  return {
    PhoneLink: (p: any) => <View testID={p.testID} accessibilityLabel={String(p.phone)} />,
    AddressLink: (p: any) => <View testID={p.testID} accessibilityLabel={String(p.address)} />,
  };
});
jest.mock("@/src/utils/formatCustomerName", () => ({ formatCustomerName: (r: any) => r?.name || "Customer" }));
jest.mock("@/src/components/customers/CustomerEquipmentLibrary", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/customers/CustomerEquipmentUnits", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/warranties/CustomerWarrantiesSection", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/customers/MultiContact", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/customers/CustomerMultiContactEditor", () => {
  const { View } = require("react-native");
  return { __esModule: true, default: () => <View testID="multi-contact-editor-stub" /> };
});
jest.mock("@/src/components/customers/AutomationsMuteSection", () => {
  const { View } = require("react-native");
  return { __esModule: true, default: () => <View testID="automations-mute-section" /> };
});
jest.mock("@/src/components/customers/CustomerTasks", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/customers/ServiceNotes", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/customers/SendCreateSheet", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/customers/SendServiceRecordsLinkModal", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/customers/CustomerTagsSection", () => {
  const { View } = require("react-native");
  return { __esModule: true, default: (p: any) => <View testID="customer-tags-section-stub" accessibilityLabel={(p.value || []).join(",")} /> };
});
jest.mock("@/src/components/customers/PaymentMethodTiles", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/customers/CommunicationTimeline", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/comms/DemoAccountToggle", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/customers/MuteControlSheet", () => {
  const { View } = require("react-native");
  return { __esModule: true, default: (p: any) => <View testID={`mute-control-btn-${p.customer?.id}`} /> };
});
jest.mock("@/src/components/customers/CustomerDeleteModal", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/subscriptions/SubscriptionsSection", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/customers/PortalAccessPanel", () => ({ __esModule: true, default: () => null }));

import CustomerDetail from "@/app/customer/[id]";
import { toggleVip } from "@/src/api/customers";

const mockPatch = () => jest.requireMock("@/src/api").api.patch as jest.Mock;
const BASE = {
  id: "cust-1", name: "Jane Test", email: "j@t.com", is_active: true, tags: [], has_login: true,
  is_vip: false, vip_note: "met at expo", customer_since: "2021-03-15T00:00:00Z",
};

async function mount(over: any = {}) {
  const cust = { ...BASE, ...over };
  mockApiGet.mockImplementation((url: string) => {
    if (url === "/customers/cust-1?slim=1") return Promise.resolve(cust);
    if (url === "/customers/cust-1/kpi-summary") return Promise.resolve({});
    if (url.includes("/credits")) return Promise.resolve({ balance_cents: 0, ledger: [] });
    return Promise.resolve([]);
  });
  const r = render(<CustomerDetail />);
  await waitFor(() => r.getByTestId("cd-identity-card"));
  await act(async () => {});
  return r;
}

function deferred<T = any>() {
  let resolve!: (v: T) => void, reject!: (e: any) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

beforeEach(() => { jest.clearAllMocks(); mockRole = "admin"; });

describe("Phase 36 · render states", () => {
  it("admin + VIP: Pressable customer-vip-toggle wraps the preserved vip-badge (star + VIP)", async () => {
    const r = await mount({ is_vip: true });
    const t = r.getByTestId("customer-vip-toggle");
    expect(within(t).getByTestId("vip-badge")).toBeTruthy();
    expect(within(t).getByText("VIP")).toBeTruthy();
    expect(within(r.getByTestId("vip-badge")).getByTestId("icon-star")).toBeTruthy();
    expect(t.props.accessibilityState).toMatchObject({ checked: true, busy: false });
    expect(within(r.getByTestId("cd-identity-card")).getByTestId("customer-vip-toggle")).toBeTruthy();
  });

  it("admin + not VIP: toggle shows 'Flag as VIP' off-state; no vip-badge", async () => {
    const r = await mount({ is_vip: false });
    const t = r.getByTestId("customer-vip-toggle");
    expect(within(t).getByTestId("vip-badge-off")).toBeTruthy();
    expect(within(t).getByText("Flag as VIP")).toBeTruthy();
    expect(r.queryByTestId("vip-badge")).toBeNull();
    expect(t.props.accessibilityState).toMatchObject({ checked: false });
  });

  it("non-admin: read-only vip-badge when VIP, nothing when not; never a toggle", async () => {
    mockRole = "technician";
    const r = await mount({ is_vip: true });
    expect(r.getByTestId("vip-badge")).toBeTruthy();
    expect(r.queryByTestId("customer-vip-toggle")).toBeNull();
    const r2 = await mount({ is_vip: false });
    expect(r2.queryByTestId("vip-badge")).toBeNull();
    expect(r2.queryByTestId("vip-badge-off")).toBeNull();
    expect(r2.queryByTestId("customer-vip-toggle")).toBeNull();
  });
});

describe("Phase 36 · toggle flow", () => {
  it("OFF→ON: optimistic flip + spinner + disabled while in flight; PATCH body mirrors web; success toast", async () => {
    const d = deferred();
    mockPatch().mockReturnValueOnce(d.promise);
    const r = await mount({ is_vip: false });
    fireEvent.press(r.getByTestId("customer-vip-toggle"));
    // optimistic — before the request settles
    expect(r.getByTestId("vip-badge")).toBeTruthy();
    expect(r.getByTestId("customer-vip-toggle-spinner")).toBeTruthy();
    expect(r.getByTestId("customer-vip-toggle").props.accessibilityState).toMatchObject({ checked: true, busy: true, disabled: true });
    expect(mockPatch()).toHaveBeenCalledWith("/customers/cust-1/vip", { is_vip: true, vip_note: "met at expo" });
    await act(async () => { d.resolve({ id: "cust-1", is_vip: true, vip_since: "2026-10-10T00:00:00Z", vip_note: "met at expo" }); });
    expect(r.queryByTestId("customer-vip-toggle-spinner")).toBeNull();
    expect(r.getByTestId("vip-badge")).toBeTruthy();
    expect(mockShowToast).toHaveBeenCalledWith("Flagged as VIP");
  });

  it("ON→OFF: sends is_vip false; ends in off-state; 'Removed VIP flag' toast", async () => {
    mockPatch().mockResolvedValueOnce({ id: "cust-1", is_vip: false, vip_since: null, vip_note: "met at expo" });
    const r = await mount({ is_vip: true });
    await act(async () => { fireEvent.press(r.getByTestId("customer-vip-toggle")); });
    expect(mockPatch()).toHaveBeenCalledWith("/customers/cust-1/vip", { is_vip: false, vip_note: "met at expo" });
    expect(r.queryByTestId("vip-badge")).toBeNull();
    expect(r.getByTestId("vip-badge-off")).toBeTruthy();
    expect(mockShowToast).toHaveBeenCalledWith("Removed VIP flag");
  });

  it("error: rolls back to the previous state + error toast; spinner cleared", async () => {
    const d = deferred();
    mockPatch().mockReturnValueOnce(d.promise);
    const r = await mount({ is_vip: false });
    fireEvent.press(r.getByTestId("customer-vip-toggle"));
    expect(r.getByTestId("vip-badge")).toBeTruthy(); // optimistic
    await act(async () => { d.reject(new Error("Admin access required")); });
    expect(r.queryByTestId("vip-badge")).toBeNull();
    expect(r.getByTestId("vip-badge-off")).toBeTruthy();
    expect(r.queryByTestId("customer-vip-toggle-spinner")).toBeNull();
    expect(mockShowToast).toHaveBeenCalledWith("Admin access required", "error");
  });

  it("double-tap while in flight fires a single PATCH", async () => {
    const d = deferred();
    mockPatch().mockReturnValueOnce(d.promise);
    const r = await mount({ is_vip: false });
    fireEvent.press(r.getByTestId("customer-vip-toggle"));
    fireEvent.press(r.getByTestId("customer-vip-toggle"));
    expect(mockPatch()).toHaveBeenCalledTimes(1);
    await act(async () => { d.resolve({ is_vip: true }); });
  });

  it("server response is authoritative (ON request, server says false → off-state)", async () => {
    mockPatch().mockResolvedValueOnce({ id: "cust-1", is_vip: false });
    const r = await mount({ is_vip: false });
    await act(async () => { fireEvent.press(r.getByTestId("customer-vip-toggle")); });
    expect(r.getByTestId("vip-badge-off")).toBeTruthy();
  });

  it("toggles back and forth: true → false → true with matching bodies", async () => {
    mockPatch()
      .mockResolvedValueOnce({ is_vip: false, vip_note: "met at expo" })
      .mockResolvedValueOnce({ is_vip: true, vip_note: "met at expo" });
    const r = await mount({ is_vip: true });
    await act(async () => { fireEvent.press(r.getByTestId("customer-vip-toggle")); });
    expect(r.getByTestId("vip-badge-off")).toBeTruthy();
    await act(async () => { fireEvent.press(r.getByTestId("customer-vip-toggle")); });
    expect(r.getByTestId("vip-badge")).toBeTruthy();
    expect(mockPatch().mock.calls.map((c: any[]) => c[1].is_vip)).toEqual([false, true]);
  });
});

describe("Phase 36 · api wrapper", () => {
  it("toggleVip → PATCH /customers/{id}/vip with vip_note defaulting to null", async () => {
    mockPatch().mockResolvedValueOnce({ is_vip: true });
    await toggleVip("c9", true);
    expect(mockPatch()).toHaveBeenCalledWith("/customers/c9/vip", { is_vip: true, vip_note: null });
  });
});
