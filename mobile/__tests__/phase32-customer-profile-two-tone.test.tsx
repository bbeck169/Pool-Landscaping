/**
 * Phase 32 · Customer profile two-tone layering.
 *   DARK  (#03002e / #1E293B): nav bar (Header dark prop), 6 KPI tiles
 *         (dynamic red/green intact), 6 Quick Action tiles, Edit/Call
 *         action buttons.
 *   LIGHT (#FFFFFF / #E4E4E7): page bg, property cards, and four new
 *         light card wrappers — Customer since, Active toggle, Mark
 *         Muted, Mute automated comms (border + r12 + padding).
 */
import React from "react";
import { StyleSheet } from "react-native";
import { render, waitFor, act, within } from "@testing-library/react-native";

const mockApiGet = jest.fn();
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
  useAuth: () => ({ user: { id: "u1", role: "admin", name: "Admin" }, startImpersonation: jest.fn() }),
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
jest.mock("@/src/components/ToastProvider", () => ({ useToast: () => ({ showToast: jest.fn() }) }));
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
jest.mock("@/src/components/customer", () => ({ PhoneLink: () => null, AddressLink: () => null }));
jest.mock("@/src/utils/formatCustomerName", () => ({ formatCustomerName: (r: any) => r?.name || "Customer" }));
jest.mock("@/src/components/customers/CustomerEquipmentLibrary", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/customers/CustomerEquipmentUnits", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/warranties/CustomerWarrantiesSection", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/customers/MultiContact", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/customers/CustomerMultiContactEditor", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/customers/AutomationsMuteSection", () => {
  const { View } = require("react-native");
  return { __esModule: true, default: () => <View testID="automations-mute-section" /> };
});
jest.mock("@/src/components/customers/CustomerTasks", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/customers/ServiceNotes", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/customers/SendCreateSheet", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/customers/SendServiceRecordsLinkModal", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/customers/CustomerTagsSection", () => ({ __esModule: true, default: () => null }));
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

const DARK = "#03002e", BORDER = "#1E293B", RED = "#7F1D1D", GREEN = "#064E3B";
const PAGE = "#FFFFFF", LBORDER = "#E4E4E7";
const flat = (el: any) => StyleSheet.flatten(el.props.style) || {};
const CUSTOMER = {
  id: "cust-1", name: "Jane Test", email: "j@t.com", is_active: true, tags: [], has_login: true,
  is_vip: true, customer_since: "2021-03-15T00:00:00Z", mobiles: [{ number_e164: "+15550102000", is_primary: true }],
};
const KPI_ORDER = ["balance-due", "past-due", "credit", "overdue", "pending-est", "unread-msgs"];
const QA = ["jobs", "tasks", "notes", "timeline", "equipment", "payments"];

async function mount(kpi: any = {}) {
  mockApiGet.mockImplementation((url: string) => {
    if (url === "/customers/cust-1?slim=1") return Promise.resolve(CUSTOMER);
    if (url === "/customers/cust-1/kpi-summary") return Promise.resolve(kpi);
    if (url.includes("/credits")) return Promise.resolve({ balance_cents: 0, ledger: [] });
    return Promise.resolve([]);
  });
  const r = render(<CustomerDetail />);
  await waitFor(() => r.getByTestId("cd-kpi-tile-grid"));
  await act(async () => {});
  return r;
}

beforeEach(() => jest.clearAllMocks());

describe("Phase 32 · LIGHT layer", () => {
  it("page root is white", async () => {
    const r = await mount();
    expect(flat(r.toJSON() as any).backgroundColor).toBe(PAGE);
  });

  it.each([
    // Phase 35 · Customer since + VIP + Active now live in the single light
    // identity card (web Phase 28 parity) — same light chassis.
    ["cd-identity-card", ["mobile-customer-since-label", "vip-badge", "customer-status-pill", "customer-active-toggle"]],
    ["cd-light-card-mark-muted", ["mute-control-btn-cust-1"]],
    ["cd-light-card-automations-mute", ["automations-mute-section"]],
  ])("%s is a light card (bg #FFFFFF, 1px #E4E4E7, r12, padding spacing.md=12) wrapping its control", async (id, kids) => {
    const r = await mount();
    const card = r.getByTestId(id as string);
    const st = flat(card);
    expect([st.backgroundColor, st.borderWidth, st.borderColor, st.borderRadius, st.padding])
      .toEqual([PAGE, 1, LBORDER, 12, 12]);
    for (const k of kids as string[]) expect(within(card).getByTestId(k)).toBeTruthy();
  });

  it("light cards in order (Phase 35: identity card → action row → mark-muted → automations)", async () => {
    const r = await mount();
    const order = ids(r.toJSON()).filter((i) => i === "cd-identity-card" || i === "customer-action-row" || i.startsWith("cd-light-card-"));
    expect(order).toEqual([
      "cd-identity-card", "customer-action-row", "cd-light-card-mark-muted", "cd-light-card-automations-mute",
    ]);
    expect(r.getByText(/Customer since March 2021/)).toBeTruthy();
  });
});

describe("Phase 32 · DARK layer (unchanged)", () => {
  it("nav bar: Header receives dark", async () => {
    const r = await mount();
    expect(r.getByTestId("header-stub-dark")).toBeTruthy();
    expect(r.queryByTestId("header-stub-light")).toBeNull();
  });

  it("6 KPI tiles dark navy in locked order with white value text", async () => {
    const r = await mount();
    const order = ids(r.toJSON()).filter((i) => /^cd-kpi-tile-[a-z-]+$/.test(i) && !i.endsWith("-value") && i !== "cd-kpi-tile-grid");
    expect(order).toEqual(KPI_ORDER.map((k) => `cd-kpi-tile-${k}`));
    for (const k of KPI_ORDER) {
      const st = flat(r.getByTestId(`cd-kpi-tile-${k}`));
      expect([k, st.backgroundColor, st.borderColor, st.shadowColor]).toEqual([k, DARK, BORDER, "#FFFFFF"]);
      expect(flat(r.getByTestId(`cd-kpi-tile-${k}-value`)).color).toBe("#FFFFFF");
    }
  });

  it("dynamic red/green intact", async () => {
    const r = await mount({ past_due_cents: 100, credit_cents: 50, overdue_count: 2 });
    const bg = (k: string) => flat(r.getByTestId(`cd-kpi-tile-${k}`)).backgroundColor;
    expect([bg("past-due"), bg("credit"), bg("overdue"), bg("balance-due")]).toEqual([RED, GREEN, RED, DARK]);
  });

  it("6 Quick Action tiles dark navy", async () => {
    const r = await mount();
    for (const k of QA) {
      const st = flat(r.getByTestId(`cd-quick-action-${k}`));
      expect([k, st.backgroundColor, st.borderColor]).toEqual([k, DARK, BORDER]);
    }
  });

  it("action row: Phase 20 testIDs present; Edit + Call dark navy", async () => {
    const r = await mount();
    for (const id of ["customer-action-row", "customer-action-edit", "customer-action-call", "impersonate-customer-button", "customer-delete-button"]) {
      expect(r.getByTestId(id)).toBeTruthy();
    }
    for (const id of ["customer-action-edit", "customer-action-call"]) {
      const st = flat(r.getByTestId(id));
      expect([id, st.backgroundColor, st.borderColor]).toEqual([id, DARK, BORDER]);
    }
  });
});

function ids(node: any, out: string[] = []): string[] {
  if (!node) return out;
  if (Array.isArray(node)) { node.forEach((n) => ids(n, out)); return out; }
  if (node.props?.testID) out.push(node.props.testID);
  (node.children || []).forEach((c: any) => typeof c === "object" && ids(c, out));
  return out;
}
