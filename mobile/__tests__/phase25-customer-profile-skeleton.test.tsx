/**
 * Phase 25 · Customer profile — action-row reposition (web Phase 20 ·
 * 6bf5306cf) + skeleton loader (web Phase 22 · 0a176aeeb).
 *
 *   1. Action row renders ABOVE the section stack; handlers preserved
 *
 *   2. Skeleton shell renders on mount BEFORE any fetch resolves, and
 *      flips to real data once the slim profile resolves.
 *   + skeleton silhouette (avatar / name / address / section badges)
 *   + pulse uses Animated.loop(Animated.sequence(...))
 *   + no bare spinner / blank frame
 */
import React from "react";
import { Animated, Linking, StyleSheet } from "react-native";
import { render, waitFor, act } from "@testing-library/react-native";

let resolveProfile: (v: any) => void = () => {};
const mockApiGet = jest.fn();
jest.mock("@/src/api", () => ({
  api: {
    get: (...a: any[]) => mockApiGet(...a),
    post: jest.fn(), patch: jest.fn(), put: jest.fn(), del: jest.fn(),
  },
}));
jest.mock("@/src/auth", () => ({
  useAuth: () => ({ user: { id: "u1", role: "admin", name: "Admin" }, startImpersonation: jest.fn() }),
}));
const mockPush = jest.fn();
jest.mock("expo-router", () => ({
  useRouter: () => ({ push: mockPush, back: jest.fn(), replace: jest.fn() }),
  useLocalSearchParams: () => ({ id: "cust-1" }),
  useFocusEffect: (cb: any) => require("react").useEffect(() => { cb(); }, []),
  Redirect: () => null,
}));
jest.mock("@expo/vector-icons", () => ({ Ionicons: () => null }));
jest.mock("expo-image", () => ({ Image: () => null }));
jest.mock("expo-image-picker", () => ({}));
jest.mock("@/src/components/ToastProvider", () => ({ useToast: () => ({ showToast: jest.fn() }) }));
jest.mock("@/src/services/readCache", () => ({ writeCache: jest.fn(async () => {}), readCache: jest.fn(async () => null) }));
jest.mock("@/src/components/ui", () => {
  const { View, Text, Pressable } = require("react-native");
  return {
    Loading: (p: any) => <View testID={p.testID || "loading"} />,
    PrimaryButton: ({ title, onPress }: any) => <Pressable onPress={onPress}><Text>{title}</Text></Pressable>,
    Sheet: () => null,
  };
});
jest.mock("@/src/components/widgets", () => {
  const { View } = require("react-native");
  return { Header: (p: any) => <View testID="header">{p.right}</View>, JobCard: (p: any) => <View testID={p.testID} /> };
});
jest.mock("@/src/components/ui/AppTextInput", () => {
  const { TextInput } = require("react-native");
  return function MockAppTextInput(p: any) { return <TextInput {...p} />; };
});
jest.mock("@/src/components/customer", () => ({ PhoneLink: () => null, AddressLink: () => null }));
jest.mock("@/src/utils/formatCustomerName", () => ({ formatCustomerName: (r: any) => r?.name || "Customer" }));
jest.mock("@/src/components/customers/CustomerEquipmentLibrary", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/customers/CustomerEquipmentUnits", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/warranties/CustomerWarrantiesSection", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/customers/MultiContact", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/customers/CustomerMultiContactEditor", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/customers/AutomationsMuteSection", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/customers/CustomerTasks", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/customers/ServiceNotes", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/customers/SendCreateSheet", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/customers/SendServiceRecordsLinkModal", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/customers/CustomerTagsSection", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/customers/PaymentMethodTiles", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/customers/CommunicationTimeline", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/comms/DemoAccountToggle", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/customers/MuteControlSheet", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/customers/CustomerDeleteModal", () => {
  const { View } = require("react-native");
  return { __esModule: true, default: (p: any) => (p.visible ? <View testID="customer-delete-modal-open" /> : null) };
});
jest.mock("@/src/components/subscriptions/SubscriptionsSection", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/customers/PortalAccessPanel", () => ({ __esModule: true, default: () => null }));

import CustomerDetail from "@/app/customer/[id]";
import CustomerProfileSkeleton, { SKELETON_SECTIONS, ACTION_SLOTS, KPI_SLOTS } from "@/src/components/customers/CustomerProfileSkeleton";

const CUSTOMER = {
  id: "cust-1", name: "Jane Test", email: "j@t.com", is_active: true, tags: [],
  has_login: true, mobiles: [{ number_e164: "+15550102000", is_primary: true }],
};

function testIdsInOrder(node: any, out: string[] = []): string[] {
  if (!node) return out;
  if (Array.isArray(node)) { node.forEach((n) => testIdsInOrder(n, out)); return out; }
  const id = node.props?.testID;
  if (typeof id === "string" && !out.includes(id)) out.push(id);
  testIdsInOrder(node.children, out);
  return out;
}

beforeEach(() => {
  jest.clearAllMocks();
  mockApiGet.mockImplementation((url: string) => {
    if (url === "/customers/cust-1?slim=1") return new Promise((res) => { resolveProfile = res; });
    if (url === "/customers/cust-1/summary") return Promise.resolve({ jobs_count: 7 });
    if (url.includes("/credits")) return Promise.resolve({ balance_cents: 0, ledger: [] });
    return Promise.resolve([]);
  });
});

describe("Phase 25 · customer profile skeleton", () => {
  it("2. skeleton renders on mount before the profile resolves, then flips to real data", async () => {
    const r = render(<CustomerDetail />);
    // Immediate shell — no spinner, no blank frame.
    expect(r.getByTestId("customer-detail-skeleton")).toBeTruthy();
    expect(r.queryByTestId("customer-detail-loading")).toBeNull();
    expect(r.queryByTestId("customer-status-pill")).toBeNull();
    expect(mockApiGet).toHaveBeenCalledWith("/customers/cust-1?slim=1");

    await act(async () => { resolveProfile(CUSTOMER); });
    await waitFor(() => r.getByTestId("customer-status-pill"));
    expect(r.queryByTestId("customer-detail-skeleton")).toBeNull();
    expect(r.getByTestId("customer-jobs-tab")).toBeTruthy();
  });

  it("silhouette mirrors the real footprint: action row → header card → tile area → body rows", () => {
    const r = render(<CustomerProfileSkeleton />);
    for (const id of ["cd-skeleton-action-row", "cd-skeleton-header-card", "cd-skeleton-avatar",
      "cd-skeleton-name", "cd-skeleton-address", "cd-skeleton-tile-area", "cd-skeleton-status-strip",
      "cd-skeleton-contact-card", "cd-skeleton-content", "cd-skeleton-sections"]) {
      expect(r.getByTestId(id)).toBeTruthy();
    }
    ACTION_SLOTS.forEach((k) => expect(r.getByTestId(`cd-skeleton-action-${k}`)).toBeTruthy());
    SKELETON_SECTIONS.forEach((k) => {
      expect(r.getByTestId(`cd-skeleton-section-${k}`)).toBeTruthy();
      expect(r.getByTestId(`cd-skeleton-badge-${k}`)).toBeTruthy();
    });
    const order = testIdsInOrder(r.toJSON());
    const idx = (id: string) => order.indexOf(id);
    // Phase 35 · identity header card slot leads, then the action row.
    expect(idx("cd-skeleton-header-card")).toBeLessThan(idx("cd-skeleton-action-row"));
    expect(idx("cd-skeleton-action-row")).toBeLessThan(idx("cd-skeleton-tile-area"));
    expect(idx("cd-skeleton-tile-area")).toBeLessThan(idx("cd-skeleton-content"));
  });

  it("pulse runs Animated.loop(Animated.sequence) and stops on unmount", () => {
    const stop = jest.fn();
    const start = jest.fn();
    const loopSpy = jest.spyOn(Animated, "loop").mockReturnValue({ start, stop, reset: jest.fn() } as any);
    const seqSpy = jest.spyOn(Animated, "sequence");
    const r = render(<CustomerProfileSkeleton />);
    expect(seqSpy).toHaveBeenCalledTimes(1);
    expect(loopSpy).toHaveBeenCalledTimes(1);
    expect(start).toHaveBeenCalled();
    r.unmount();
    expect(stop).toHaveBeenCalled();
    loopSpy.mockRestore();
    seqSpy.mockRestore();
  });
});

describe("Phase 25 · Phase 20 · action row above the section stack", () => {
  async function mountLoaded() {
    const r = render(<CustomerDetail />);
    await act(async () => { resolveProfile(CUSTOMER); });
    await waitFor(() => r.getByTestId("customer-action-row"));
    return r;
  }

  it("1. action row renders before every section (Phase 35: identity card + status pill sit ABOVE it)", async () => {
    const r = await mountLoaded();
    const order = testIdsInOrder(r.toJSON());
    const row = order.indexOf("customer-action-row");
    expect(row).toBeGreaterThanOrEqual(0);
    for (const id of ["customer-jobs-tab", "customer-credits-section"]) {
      const i = order.indexOf(id);
      if (i >= 0) expect([id, row < i]).toEqual([id, true]);
    }
    expect(order.indexOf("cd-identity-card")).toBeLessThan(row);
    expect(order.indexOf("customer-status-pill")).toBeLessThan(row);
    expect(order.indexOf("customer-jobs-tab")).toBeGreaterThan(row);
  });

  it("relocated buttons keep their testIDs and live INSIDE the row", async () => {
    const r = await mountLoaded();
    const row = r.getByTestId("customer-action-row");
    const inRow = testIdsInOrder(row);
    for (const id of ["customer-action-edit", "customer-action-call",
      "impersonate-customer-button", "customer-delete-button"]) {
      expect([id, inRow.includes(id)]).toEqual([id, true]);
    }
    expect(r.getAllByTestId("customer-delete-button")).toHaveLength(1);
    expect(r.getAllByTestId("impersonate-customer-button")).toHaveLength(1);
    expect(r.getByTestId("edit-customer-button")).toBeTruthy(); // header edit icon preserved
  });

  it("handlers preserved: Edit → editor route, Call → primary mobile, Delete → existing confirm modal", async () => {
    const spy = jest.spyOn(Linking, "openURL").mockResolvedValue(true as any);
    const r = await mountLoaded();
    const { fireEvent } = require("@testing-library/react-native");
    fireEvent.press(r.getByTestId("customer-action-edit"));
    expect(mockPush).toHaveBeenCalledWith("/customer/new?id=cust-1");
    fireEvent.press(r.getByTestId("customer-action-call"));
    expect(spy).toHaveBeenCalledWith("tel:+15550102000");
    spy.mockRestore();
    expect(r.queryByTestId("customer-delete-modal-open")).toBeNull();
    fireEvent.press(r.getByTestId("customer-delete-button"));
    expect(r.getByTestId("customer-delete-modal-open")).toBeTruthy();
  });
});

describe("Phase 32 · skeleton is TWO-TONE (white page, dark nav/action/KPI regions); structure + testIDs unchanged", () => {
  const flat = (el: any) => StyleSheet.flatten(el.props.style) || {};
  it("root + cards light (#FFFFFF / #E4E4E7 / r12); pulse bars light; action slots dark navy", () => {
    const r = render(<CustomerProfileSkeleton />);
    expect(flat(r.getByTestId("customer-detail-skeleton")).backgroundColor).toBe("#FFFFFF");
    for (const id of ["cd-skeleton-header-card", "cd-skeleton-contact-card"]) {
      const st = flat(r.getByTestId(id));
      expect([id, st.backgroundColor, st.borderColor, st.borderRadius]).toEqual([id, "#FFFFFF", "#E4E4E7", 12]);
    }
    expect(flat(r.getByTestId("cd-skeleton-avatar")).backgroundColor).toBe("#E4E4E7");
    const slot = flat(r.getByTestId("cd-skeleton-action-edit"));
    expect([slot.backgroundColor, slot.borderColor]).toEqual(["#03002e", "#1E293B"]);
  });

  it("tile area reserves the 6 KPI tiles in locked order", () => {
    const r = render(<CustomerProfileSkeleton />);
    const area = testIdsInOrder(r.getByTestId("cd-skeleton-tile-area"));
    const kpis = area.filter((i) => i.startsWith("cd-skeleton-kpi-") && i !== "cd-skeleton-kpi-grid");
    expect(kpis).toEqual(KPI_SLOTS.map((k) => `cd-skeleton-kpi-${k}`));
    expect(KPI_SLOTS).toEqual(["balance-due", "past-due", "credit", "overdue", "pending-est", "unread-msgs"]);
    KPI_SLOTS.forEach((k) => {
      const st = flat(r.getByTestId(`cd-skeleton-kpi-${k}`));
      expect([k, st.backgroundColor, st.borderColor]).toEqual([k, "#03002e", "#1E293B"]);
    });
  });
});
