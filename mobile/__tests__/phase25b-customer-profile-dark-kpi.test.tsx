/**
 * Phase 25b · Customer profile — web Phase 27 (66328fc7d) mobile parity:
 * dark navy chassis, 6 KPI tiles (locked order + dynamic red/green +
 * static glow) from /customers/{id}/kpi-summary, Quick Action tiles
 * above the section stack, Phase 20 action row preserved.
 */
import React from "react";
import { ScrollView, StyleSheet } from "react-native";
import { render, waitFor, act, fireEvent } from "@testing-library/react-native";

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

const DARK = "#03002e", BORDER = "#1E293B", RED = "#7F1D1D", GREEN = "#064E3B";
const ORDER = ["balance-due", "past-due", "credit", "overdue", "pending-est", "unread-msgs"];
const CUSTOMER = { id: "cust-1", name: "Jane Test", email: "j@t.com", is_active: true, tags: [],
  has_login: true, mobiles: [{ number_e164: "+15550102000", is_primary: true }] };
let mockKpi: any = {};
const flat = (el: any) => StyleSheet.flatten(el.props.style) || {};

function ids(node: any, out: string[] = []): string[] {
  if (!node) return out;
  if (Array.isArray(node)) { node.forEach((n) => ids(n, out)); return out; }
  const id = node.props?.testID;
  if (typeof id === "string" && !out.includes(id)) out.push(id);
  ids(node.children, out);
  return out;
}

beforeEach(() => {
  jest.clearAllMocks();
  mockApiGet.mockImplementation((url: string) => {
    if (url === "/customers/cust-1?slim=1") return Promise.resolve(CUSTOMER);
    if (url === "/customers/cust-1/summary") return Promise.resolve({ jobs_count: 7 });
    if (url === "/customers/cust-1/kpi-summary") return Promise.resolve(mockKpi);
    if (url.includes("/credits")) return Promise.resolve({ balance_cents: 0, ledger: [] });
    return Promise.resolve([]);
  });
});

async function mount(kpi: any) {
  mockKpi = kpi;
  const r = render(<CustomerDetail />);
  await waitFor(() => r.getByTestId("cd-kpi-tile-grid"));
  await act(async () => {});
  return r;
}

describe("Phase 25b · dark chassis", () => {
  it("page root is #03002e; section titles flip to light text", async () => {
    const r = await mount({});
    expect(flat(r.toJSON() as any).backgroundColor).toBe(DARK);
    const title = r.getByText(/Communication Timeline/);
    expect(flat(title).color).toBe("#FFFFFF");
  });

  it("un-restyled child sections sit in light inset panels (readable on navy)", async () => {
    const r = await mount({});
    for (const k of ["jobs", "tasks", "notes", "timeline", "equipment"]) {
      const st = flat(r.getByTestId(`cd-section-${k}`));
      expect([k, st.borderColor, st.borderRadius]).toEqual([k, BORDER, 12]);
    }
  });
});

describe("Phase 25b · KPI tiles (kpi-summary)", () => {
  it("fetches /customers/{id}/kpi-summary and renders 6 tiles in locked order", async () => {
    const r = await mount({});
    expect(mockApiGet).toHaveBeenCalledWith("/customers/cust-1/kpi-summary");
    const order = ids(r.getByTestId("cd-kpi-tile-grid")).filter((i) => /^cd-kpi-tile-[a-z-]+$/.test(i) && !i.endsWith("-value") && i !== "cd-kpi-tile-grid");
    expect(order).toEqual(ORDER.map((k) => `cd-kpi-tile-${k}`));
  });

  it("all-zero → every tile neutral dark with #1E293B border", async () => {
    const r = await mount({ balance_due_cents: 0, past_due_cents: 0, credit_cents: 0, overdue_count: 0 });
    for (const k of ORDER) {
      const st = flat(r.getByTestId(`cd-kpi-tile-${k}`));
      expect([k, st.backgroundColor, st.borderColor]).toEqual([k, DARK, BORDER]);
    }
  });

  it("dynamic: Past Due + Overdue red, Credit green when > 0; others stay neutral", async () => {
    const r = await mount({ balance_due_cents: 12345, past_due_cents: 500, credit_cents: 2500,
      overdue_count: 2, pending_estimates_count: 3, unread_messages_count: 4 });
    const bg = (k: string) => flat(r.getByTestId(`cd-kpi-tile-${k}`)).backgroundColor;
    expect(bg("past-due")).toBe(RED);
    expect(bg("overdue")).toBe(RED);
    expect(bg("credit")).toBe(GREEN);
    expect(bg("balance-due")).toBe(DARK);
    expect(bg("pending-est")).toBe(DARK);
    expect(bg("unread-msgs")).toBe(DARK);
    expect(r.getByTestId("cd-kpi-tile-balance-due-value").props.children).toBe("$123.45");
    expect(r.getByTestId("cd-kpi-tile-overdue-value").props.children).toBe("2");
    expect(flat(r.getByTestId("cd-kpi-tile-past-due-value")).color).toBe("#FFFFFF");
  });

  it("static soft white glow on every KPI tile (Phase 25 KPI_GLOW byte-for-byte)", async () => {
    const r = await mount({ past_due_cents: 1 });
    for (const k of ORDER) {
      const st = flat(r.getByTestId(`cd-kpi-tile-${k}`));
      expect([k, st.shadowColor, st.shadowOpacity, st.shadowRadius, st.elevation, st.shadowOffset])
        .toEqual([k, "#FFFFFF", 0.6, 20, 8, { width: 0, height: 0 }]);
    }
  });
});

describe("Phase 25b · Quick Actions + Phase 20 preserved", () => {
  it("order: action row → KPI grid → Quick Actions → section stack", async () => {
    const r = await mount({});
    const o = ids(r.toJSON());
    const i = (id: string) => o.indexOf(id);
    expect(i("customer-action-row")).toBeGreaterThanOrEqual(0);
    expect(i("customer-action-row")).toBeLessThan(i("cd-kpi-tile-grid"));
    expect(i("cd-kpi-tile-grid")).toBeLessThan(i("cd-quick-action-grid"));
    expect(i("cd-quick-action-grid")).toBeLessThan(i("customer-status-pill"));
    expect(i("cd-quick-action-grid")).toBeLessThan(i("customer-jobs-tab"));
    for (const id of ["customer-action-edit", "customer-action-call", "impersonate-customer-button", "customer-delete-button"]) {
      expect([id, ids(r.getByTestId("customer-action-row")).includes(id)]).toEqual([id, true]);
    }
  });

  it("each Quick Action tile scrolls to its section anchor (exactly once)", async () => {
    const r = await mount({});
    const sv: any = r.UNSAFE_getByType(ScrollView).instance;
    const ys: Record<string, number> = { jobs: 1400, tasks: 900, notes: 1100, timeline: 1700, equipment: 600 };
    for (const [k, y] of Object.entries(ys)) {
      fireEvent(r.getByTestId(`cd-section-${k}`), "layout", { nativeEvent: { layout: { x: 0, y, width: 300, height: 100 } } });
    }
    fireEvent(r.getByTestId("customer-payment-tiles-slot"), "layout", { nativeEvent: { layout: { x: 0, y: 300, width: 300, height: 100 } } });
    for (const [k, y] of Object.entries({ ...ys, payments: 300 })) {
      sv.scrollTo.mockClear();
      fireEvent.press(r.getByTestId(`cd-quick-action-${k}`));
      // jest host ``measure`` mocks never call back → stored-y fallback (120ms).
      await act(async () => { await new Promise((res) => setTimeout(res, 160)); });
      expect([k, sv.scrollTo.mock.calls.length, sv.scrollTo.mock.calls[0]?.[0]]).toEqual([k, 1, { y: y - 12, animated: true }]);
    }
  });
});
