/**
 * Phase 35 · web parity b40352a (Phase 28) — mobile identity header card.
 *   - cd-identity-card renders FIRST below the (dark) nav bar, ABOVE the
 *     Phase 20 action row, KPI grid and Quick Actions.
 *   - Consolidates name, Customer since, VIP (read-only badge), Active
 *     pill + toggle, phone, email, address, pool, gate code (only when
 *     set) and tags — each rendered exactly once on the page.
 *   - Light chassis (#FFFFFF / 1px #E4E4E7 / r12 / padding 12).
 *   - Billing address, multi-contact editor, Mark Muted and Mute
 *     automated comms stay outside the card, below the action row.
 */
import React from "react";
import { StyleSheet, Alert } from "react-native";
import { render, waitFor, act, within, fireEvent } from "@testing-library/react-native";

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

const flat = (el: any) => StyleSheet.flatten(el.props.style) || {};
const BASE = {
  id: "cust-1", name: "Jane Test", email: "j@t.com", is_active: true, tags: ["vip-pool"], has_login: true,
  is_vip: true, customer_since: "2021-03-15T00:00:00Z", mobiles: [{ number_e164: "+15550102000", is_primary: true }],
  address: "1 Palm Way, Tampa, FL", billing_address: "PO Box 9", pool_gallons: 15000, gate_code: "4321",
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

function ids(node: any, out: string[] = []): string[] {
  if (!node) return out;
  if (Array.isArray(node)) { node.forEach((n) => ids(n, out)); return out; }
  if (node.props?.testID) out.push(node.props.testID);
  (node.children || []).forEach((c: any) => typeof c === "object" && ids(c, out));
  return out;
}

beforeEach(() => jest.clearAllMocks());

describe("Phase 35 · placement", () => {
  it("identity card is the first content below the nav bar, above action row → KPI → Quick Actions", async () => {
    const r = await mount();
    const order = ids(r.toJSON());
    const at = (id: string) => order.indexOf(id);
    expect(order[0]).toBe("header-stub-dark");
    const inHeader = new Set(ids(r.getByTestId("header-stub-dark").children as any));
    const firstContent = order.find((i) => i !== "header-stub-dark" && !inHeader.has(i));
    expect(firstContent).toBe("cd-identity-card");
    expect(at("cd-identity-card")).toBeLessThan(at("customer-action-row"));
    expect(at("customer-action-row")).toBeLessThan(at("cd-kpi-tile-grid"));
    expect(at("cd-kpi-tile-grid")).toBeLessThan(at("cd-quick-action-grid"));
  });

  it("fields render inside the card in web Phase 28 order", async () => {
    const r = await mount();
    const inCard = ids(r.getByTestId("cd-identity-card").children as any);
    const seq = ["customer-detail-inline-name", "cd-identity-since-row", "mobile-customer-since-label", "vip-badge",
      "cd-identity-active-row", "customer-status-pill", "customer-active-toggle", "customer-phone-link",
      "customer-email-link", "customer-address-link", "customer-pool-gallons-display", "cd-identity-gate-code",
      "cd-identity-tags", "customer-tags-section-stub"];
    const pos = seq.map((id) => inCard.indexOf(id));
    expect(pos.every((p) => p >= 0)).toBe(true);
    expect([...pos].sort((a, b) => a - b)).toEqual(pos);
    expect(within(r.getByTestId("cd-identity-card")).getByText("Jane Test")).toBeTruthy();
  });

  it("each moved field renders exactly once (old scattered slots removed)", async () => {
    const r = await mount();
    for (const id of ["customer-phone-link", "customer-email-link", "customer-address-link", "customer-pool-gallons-display",
      "mobile-customer-since-label", "vip-badge", "customer-status-pill", "customer-active-toggle", "customer-tags-section-stub"]) {
      expect([id, r.getAllByTestId(id).length]).toEqual([id, 1]);
    }
    expect(r.queryByTestId("cd-light-card-customer-since")).toBeNull();
    expect(r.queryByTestId("cd-light-card-active")).toBeNull();
  });

  it("billing address, multi-contact editor, Mark Muted, Mute automated comms stay outside the card, below the action row", async () => {
    const r = await mount();
    const card = within(r.getByTestId("cd-identity-card"));
    const order = ids(r.toJSON());
    const row = order.indexOf("customer-action-row");
    for (const id of ["customer-billing-link", "multi-contact-editor-stub", "cd-light-card-mark-muted", "cd-light-card-automations-mute"]) {
      expect([id, card.queryByTestId(id)]).toEqual([id, null]);
      expect([id, order.indexOf(id) > row]).toEqual([id, true]);
    }
  });
});

describe("Phase 35 · chassis + fields", () => {
  it("light chassis: #FFFFFF bg, 1px #E4E4E7, r12, padding 12; name #09090B", async () => {
    const r = await mount();
    const st = flat(r.getByTestId("cd-identity-card"));
    expect([st.backgroundColor, st.borderWidth, st.borderColor, st.borderRadius, st.padding]).toEqual(["#FFFFFF", 1, "#E4E4E7", 12, 12]);
    expect(flat(r.getByTestId("customer-detail-inline-name")).color).toBe("#09090B");
  });

  it("gate code: labeled row, muted label + dark value when set", async () => {
    const r = await mount();
    expect(r.getByTestId("cd-identity-gate-code")).toBeTruthy();
    expect(r.getByTestId("cd-identity-gate-code-value").props.children).toBe("4321");
    const { Text } = require("react-native");
    const [outer] = within(r.getByTestId("cd-identity-gate-code")).UNSAFE_getAllByType(Text);
    expect(flat(outer).color).toBe("#09090B");
    const label = r.getByText("Gate code: ");
    expect(flat(label).color).toBe("#52525B");
  });

  it.each([[""], [null], [undefined]])("gate code hidden when %p", async (g) => {
    const r = await mount({ gate_code: g });
    expect(r.queryByTestId("cd-identity-gate-code")).toBeNull();
    expect(r.queryByText(/Gate code/)).toBeNull();
  });

  it("VIP stays a read-only badge (no press handler); hidden when !is_vip", async () => {
    const r = await mount();
    const badge = r.getByTestId("vip-badge");
    expect(badge.props.onPress).toBeUndefined();
    expect(badge.props.onClick).toBeUndefined();
    const r2 = await mount({ is_vip: false });
    expect(r2.queryByTestId("vip-badge")).toBeNull();
  });

  it("pool placeholder when unset; email row opens mailto; tags passed through", async () => {
    const spy = jest.spyOn(require("react-native").Linking, "openURL").mockResolvedValue(true as any);
    const r = await mount({ pool_gallons: null });
    expect(within(r.getByTestId("customer-pool-gallons-display")).getByText("Pool: — (not set)")).toBeTruthy();
    fireEvent.press(r.getByTestId("customer-email-link"));
    expect(spy).toHaveBeenCalledWith("mailto:j@t.com");
    expect(r.getByTestId("customer-tags-section-stub").props.accessibilityLabel).toBe("vip-pool");
    spy.mockRestore();
  });

  it("Active toggle still drives the existing activation confirm flow", async () => {
    const alertSpy = jest.spyOn(Alert, "alert").mockImplementation(() => {});
    const r = await mount();
    fireEvent(r.getByTestId("customer-active-toggle"), "valueChange", false);
    expect(alertSpy).toHaveBeenCalled();
    expect(alertSpy.mock.calls[0][0]).toBe("Mark customer inactive?");
    alertSpy.mockRestore();
  });

  it("Phase 20 action-row testIDs unchanged", async () => {
    const r = await mount();
    const row = within(r.getByTestId("customer-action-row"));
    for (const id of ["customer-action-edit", "customer-action-call", "impersonate-customer-button", "customer-delete-button"]) {
      expect(row.getByTestId(id)).toBeTruthy();
    }
  });
});
