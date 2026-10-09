/**
 * Phase 25 · Customer profile skeleton loader (mobile parity with web
 * Phase 22 · 0a176aeeb).
 *
 *   2. Skeleton shell renders on mount BEFORE any fetch resolves, and
 *      flips to real data once the slim profile resolves.
 *   + skeleton silhouette (avatar / name / address / section badges)
 *   + pulse uses Animated.loop(Animated.sequence(...))
 *   + no bare spinner / blank frame
 */
import React from "react";
import { Animated } from "react-native";
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
jest.mock("expo-router", () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: jest.fn() }),
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
  return { Header: () => <View testID="header" />, JobCard: (p: any) => <View testID={p.testID} /> };
});
jest.mock("@/src/components/ui/AppTextInput", () => {
  const { TextInput } = require("react-native");
  return (p: any) => <TextInput {...p} />;
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
jest.mock("@/src/components/customers/CustomerDeleteModal", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/subscriptions/SubscriptionsSection", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/customers/PortalAccessPanel", () => ({ __esModule: true, default: () => null }));

import CustomerDetail from "@/app/customer/[id]";
import CustomerProfileSkeleton, { SKELETON_SECTIONS } from "@/src/components/customers/CustomerProfileSkeleton";

const CUSTOMER = { id: "cust-1", name: "Jane Test", email: "j@t.com", is_active: true, tags: [] };

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

  it("silhouette: header card (avatar / name / address) + section labels with badge placeholders", () => {
    const r = render(<CustomerProfileSkeleton />);
    for (const id of ["cd-skeleton-header-card", "cd-skeleton-avatar", "cd-skeleton-name",
      "cd-skeleton-address", "cd-skeleton-status-strip", "cd-skeleton-contact-card", "cd-skeleton-sections"]) {
      expect(r.getByTestId(id)).toBeTruthy();
    }
    SKELETON_SECTIONS.forEach((k) => {
      expect(r.getByTestId(`cd-skeleton-section-${k}`)).toBeTruthy();
      expect(r.getByTestId(`cd-skeleton-badge-${k}`)).toBeTruthy();
    });
    expect(r.queryByTestId("cd-skeleton-action-row")).toBeNull(); // F1 flagged: no mobile action row
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
