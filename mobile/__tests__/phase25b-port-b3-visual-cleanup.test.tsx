/**
 * Phase 25b · Port B3 — visual cleanup on the dark customer profile:
 *   1. Property cards → #03002e bg / #1E293B border / white text.
 *   2. Error/retry screen → #03002e bg, white retry + error text.
 *   3. Shared Header opt-in ``dark`` prop (customer profile only);
 *      default Header stays light for every other caller.
 * LightPanel sections remain light (B3 keeps them untouched).
 */
import React from "react";
import { StyleSheet } from "react-native";
import { render, waitFor, act } from "@testing-library/react-native";

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

const DARK = "#03002e", BORDER = "#1E293B", WHITE = "#FFFFFF", MUTED = "rgba(255,255,255,0.7)";
const flat = (el: any) => StyleSheet.flatten(el.props.style) || {};
const CUSTOMER = { id: "cust-1", name: "Jane Test", email: "j@t.com", is_active: true, tags: [], has_login: false };
const PROPERTY = {
  id: "p1", label: "Main House", sort_order: 0, active: true, service_types: ["pool"], pool_size_gallons: 15000,
  address: { line1: "1 Palm Way", city: "Tampa", state: "FL", postal_code: "33601" },
};

function mockOk() {
  mockApiGet.mockImplementation((url: string) => {
    if (url === "/customers/cust-1?slim=1") return Promise.resolve(CUSTOMER);
    if (url === "/customers/cust-1/properties") return Promise.resolve([PROPERTY]);
    if (url === "/customers/cust-1/kpi-summary") return Promise.resolve({});
    if (url.includes("/credits")) return Promise.resolve({ balance_cents: 0, ledger: [] });
    return Promise.resolve([]);
  });
}

beforeEach(() => jest.clearAllMocks());

// Phase 32 reverses B3.1 + B3.2 (two-tone: white page, light property
// cards + light error screen). B3.3 Header dark prop is unchanged.
describe("B3.1 → Phase 32 · property cards light", () => {
  it("card #FFFFFF / #E4E4E7; label #09090B; address + meta #52525B", async () => {
    mockOk();
    const r = render(<CustomerDetail />);
    await waitFor(() => r.getByTestId("mobile-property-p1"));
    await act(async () => {});
    const card = flat(r.getByTestId("mobile-property-p1"));
    expect([card.backgroundColor, card.borderColor, card.borderWidth]).toEqual([WHITE, "#E4E4E7", 1]);
    expect(flat(r.getByText("Main House")).color).toBe("#09090B");
    expect(flat(r.getByText("1 Palm Way, Tampa, FL, 33601")).color).toBe("#52525B");
    expect(flat(r.getByText("pool")).color).toBe("#52525B");
    expect(flat(r.getByText(/Pool: 15,000 gal/)).color).toBe("#52525B");
  });

  it("profile passes dark to Header; LightPanel sections untouched (border #1E293B, light surface)", async () => {
    mockOk();
    const r = render(<CustomerDetail />);
    await waitFor(() => r.getByTestId("cd-kpi-tile-grid"));
    await act(async () => {});
    expect(r.getByTestId("header-stub-dark")).toBeTruthy();
    expect(r.queryByTestId("header-stub-light")).toBeNull();
    for (const k of ["jobs", "tasks", "notes", "timeline", "equipment"]) {
      const st = flat(r.getByTestId(`cd-section-${k}`));
      expect([k, st.borderColor, st.backgroundColor === DARK]).toEqual([k, BORDER, false]);
    }
  });
});

describe("B3.2 → Phase 32 · error/retry screen light (nav bar stays dark)", () => {
  it("root #FFFFFF, title #09090B, retry text #fff on brand button, Header dark", async () => {
    const { ApiError } = jest.requireMock("@/src/api");
    mockApiGet.mockImplementation(() => Promise.reject(new ApiError(403, "Forbidden")));
    const r = render(<CustomerDetail />);
    await waitFor(() => r.getByTestId("customer-detail-error"));
    expect(flat(r.getByTestId("customer-detail-error")).backgroundColor).toBe(WHITE);
    expect(flat(r.getByTestId("customer-detail-error-title")).color).toBe("#09090B");
    expect(flat(r.getByText("Retry")).color).toBe("#fff");
    expect(r.getByTestId("customer-detail-retry-btn")).toBeTruthy();
    expect(r.getByTestId("header-stub-dark")).toBeTruthy();
  });
});

describe("B3.3 · shared Header opt-in dark prop", () => {
  const { Header } = jest.requireActual("@/src/components/widgets");
  const iconColor = (r: any, name: string) => r.getAllByTestId(`icon-${name}`)[0].props.accessibilityHint;

  it("dark: navy bar, #1E293B bottom border, white title/sub/back/sprocket/hamburger", () => {
    const r = render(<Header title="Jane" subtitle="Sub" back dark />);
    const bar = flat(r.getByTestId("header-dark"));
    expect([bar.backgroundColor, bar.borderBottomColor]).toEqual([DARK, BORDER]);
    expect(flat(r.getByText("Jane")).color).toBe(WHITE);
    expect(flat(r.getByText("Sub")).color).toBe(MUTED);
    expect(iconColor(r, "chevron-back")).toBe(WHITE);
    expect(iconColor(r, "settings-outline")).toBe(WHITE);
    expect(iconColor(r, "menu-outline")).toBe(WHITE);
    const sp = flat(r.getByTestId("header-settings-sprocket"));
    expect([sp.backgroundColor, sp.borderColor]).toEqual([DARK, BORDER]);
    const hb = flat(r.getByTestId("mobile-menu-trigger"));
    expect([hb.backgroundColor, hb.borderColor]).toEqual([DARK, BORDER]);
  });

  it("default (no prop): unchanged light chrome — no dark testID, no navy anywhere", () => {
    const r = render(<Header title="Dashboard" subtitle="Sub" back />);
    expect(r.queryByTestId("header-dark")).toBeNull();
    const bar = flat((r.toJSON() as any));
    expect(bar.backgroundColor).not.toBe(DARK);
    expect(flat(r.getByText("Dashboard")).color).not.toBe(WHITE);
    expect(iconColor(r, "chevron-back")).not.toBe(WHITE);
    expect(flat(r.getByTestId("header-settings-sprocket")).backgroundColor).not.toBe(DARK);
    expect(flat(r.getByTestId("mobile-menu-trigger")).backgroundColor).not.toBe(DARK);
  });
});
