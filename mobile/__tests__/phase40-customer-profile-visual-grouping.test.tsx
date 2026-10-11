/**
 * Phase 40 · mobile customer profile — web Phase 38 (4a675b669) visual grouping.
 *   - Palette tokens mirror web exactly (tile-level; page stays Phase 32 white).
 *   - KPI neutral tiles teal #115E59 + slate-300 labels; Phase 24 red/green kept.
 *   - Quick Actions: 12 tiles in web TABS order, slate-900 bg, icon accents
 *     teal/indigo/slate by i % 3, indigo #4F46E5 outline on the active tile;
 *     Measurements / Chemical History / Quotes / Invoices / Reviews hidden;
 *     admin-only sections' tiles hidden for techs.
 *   - Overview scrolls to top; 6 new SectionAnchor targets scroll to section.
 *   - Buttons: Edit / View-as steel, Call emerald, Delete unchanged red.
 *   - Equipment section (pre-Phase-40 L895–909) is byte-identical.
 */
import React from "react";
import { StyleSheet, ScrollView } from "react-native";
import { render, waitFor, act, within, fireEvent } from "@testing-library/react-native";

const mockApiGet = jest.fn();
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
jest.mock("@/src/components/customers/CustomerEquipmentLibrary", () => {
  const { View } = require("react-native");
  return { __esModule: true, default: () => <View testID="equipment-library-stub" /> };
});
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

import { readFileSync } from "fs";
import { join } from "path";
import CustomerDetail from "@/app/customer/[id]";
import * as T from "@/src/lib/customerDarkTokens";

const flat = (el: any) => StyleSheet.flatten(el.props.style) || {};
const CUSTOMER = {
  id: "cust-1", name: "Jane Test", email: "j@t.com", is_active: true, tags: [], has_login: true,
  mobiles: [{ number_e164: "+15550102000", is_primary: true }],
};
const ORDER12 = ["overview", "properties", "jobs", "documents", "equipment", "warranties", "tasks", "notes", "credits", "payments", "subscriptions", "portal"];
const ICONS: Record<string, string> = {
  overview: "person-circle-outline", properties: "home-outline", jobs: "briefcase-outline", documents: "folder-open-outline",
  equipment: "construct-outline", warranties: "shield-checkmark-outline", tasks: "checkbox-outline", notes: "document-text-outline",
  credits: "wallet-outline", payments: "card-outline", subscriptions: "repeat-outline", portal: "key-outline",
};

async function mount(kpi: any = {}) {
  mockApiGet.mockImplementation((url: string) => {
    if (url === "/customers/cust-1?slim=1") return Promise.resolve(CUSTOMER);
    if (url === "/customers/cust-1/kpi-summary") return Promise.resolve(kpi);
    if (url.includes("/credits")) return Promise.resolve({ balance_cents: 0, ledger: [] });
    return Promise.resolve([]);
  });
  const r = render(<CustomerDetail />);
  await waitFor(() => r.getByTestId("cd-quick-action-grid"));
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
const qaKeys = (r: any) => ids(r.toJSON()).filter((i) => /^cd-quick-action-[a-z_]+$/.test(i) && i !== "cd-quick-action-grid").map((i) => i.replace("cd-quick-action-", ""));
const iconColor = (r: any, k: string) => within(r.getByTestId(`cd-quick-action-${k}`)).getByTestId(`icon-${ICONS[k]}`).props.accessibilityHint;

beforeEach(() => { jest.clearAllMocks(); mockRole = "admin"; });

describe("Phase 40 · tokens", () => {
  it("mirror web Phase 38 hex values", () => {
    expect([T.CD_FINANCIAL_NEUTRAL_BG, T.CD_FINANCIAL_NEUTRAL_LABEL, T.CD_ACTION_BTN_BG, T.CD_ACTION_BTN_BORDER, T.CD_NAV_TILE_BG,
      T.CD_ICON_ACCENT_TEAL, T.CD_ICON_ACCENT_INDIGO, T.CD_ICON_ACCENT_SLATE, T.CD_ACTIVE_TILE_BORDER, T.CD_CALL_BTN_BG, T.CD_NAV_TILE_ACTIVE_BG])
      .toEqual(["#115E59", "#CBD5E1", "#334155", "#64748B", "#0F172A", "#2DD4BF", "#818CF8", "#94A3B8", "#4F46E5", "#059669", "#0a0940"]);
    expect(T.CD_ICON_ACCENTS).toEqual(["#2DD4BF", "#818CF8", "#94A3B8"]);
  });
});

describe("Phase 40 · financial KPI tiles", () => {
  it("neutral tiles teal with slate-300 labels; white values; glow kept", async () => {
    const r = await mount();
    for (const k of ["balance-due", "past-due", "credit", "overdue", "pending-est", "unread-msgs"]) {
      const st = flat(r.getByTestId(`cd-kpi-tile-${k}`));
      expect([k, st.backgroundColor, st.borderColor, st.shadowColor]).toEqual([k, "#115E59", "#1E293B", "#FFFFFF"]);
      expect(flat(r.getByTestId(`cd-kpi-tile-${k}-value`)).color).toBe("#FFFFFF");
    }
    expect(flat(within(r.getByTestId("cd-kpi-tile-balance-due")).getByText("Balance Due")).color).toBe("#CBD5E1");
  });
  it("Phase 24 thresholds still flip red / green (labels revert to muted white on those)", async () => {
    const r = await mount({ past_due_cents: 1, credit_cents: 1, overdue_count: 1 });
    const bg = (k: string) => flat(r.getByTestId(`cd-kpi-tile-${k}`)).backgroundColor;
    expect([bg("past-due"), bg("credit"), bg("overdue"), bg("balance-due")]).toEqual(["#7F1D1D", "#064E3B", "#7F1D1D", "#115E59"]);
    expect(flat(within(r.getByTestId("cd-kpi-tile-past-due")).getByText("Past Due")).color).toBe("rgba(255,255,255,0.7)");
  });
});

describe("Phase 40 · navigation tile grid", () => {
  it("admin: 12 tiles in web TABS order; 5 web-only tabs + retired Messages tile absent", async () => {
    const r = await mount();
    expect(qaKeys(r)).toEqual(ORDER12);
    for (const k of ["measurements", "chemical_history", "quotes", "invoices", "reviews", "timeline"]) {
      expect([k, r.queryByTestId(`cd-quick-action-${k}`)]).toEqual([k, null]);
    }
    expect(within(r.getByTestId("cd-quick-action-portal")).getByText("Portal Access")).toBeTruthy();
    expect(within(r.getByTestId("cd-quick-action-notes")).getByText("Notes")).toBeTruthy();
  });
  it("technician: admin-only section tiles hidden (documents / credits / payments / subscriptions / portal)", async () => {
    mockRole = "technician";
    const r = await mount();
    expect(qaKeys(r)).toEqual(["overview", "properties", "jobs", "equipment", "warranties", "tasks", "notes"]);
  });
  it("slate-900 base, #1E293B border, icon accents cycle teal / indigo / slate by index", async () => {
    const r = await mount();
    ORDER12.forEach((k, i) => {
      const st = flat(r.getByTestId(`cd-quick-action-${k}`));
      expect([k, st.backgroundColor, st.borderColor]).toEqual([k, "#0F172A", "#1E293B"]);
      expect([k, iconColor(r, k)]).toEqual([k, ["#2DD4BF", "#818CF8", "#94A3B8"][i % 3]]);
    });
  });
  it("active tile: indigo #4F46E5 outline + #0a0940 bg + white icon; moves on next pick", async () => {
    const r = await mount();
    fireEvent.press(r.getByTestId("cd-quick-action-jobs"));
    let st = flat(r.getByTestId("cd-quick-action-jobs"));
    expect([st.backgroundColor, st.borderColor]).toEqual(["#0a0940", "#4F46E5"]);
    expect(iconColor(r, "jobs")).toBe("#FFFFFF");
    expect(r.getByTestId("cd-quick-action-jobs").props.accessibilityState).toMatchObject({ selected: true });
    fireEvent.press(r.getByTestId("cd-quick-action-credits"));
    st = flat(r.getByTestId("cd-quick-action-jobs"));
    expect([st.backgroundColor, st.borderColor]).toEqual(["#0F172A", "#1E293B"]);
    expect(iconColor(r, "jobs")).toBe("#94A3B8"); // index 2 → slate
    expect(flat(r.getByTestId("cd-quick-action-credits")).borderColor).toBe("#4F46E5");
  });
  it("Overview scrolls to top; new anchors scroll to their section exactly once", async () => {
    const r = await mount();
    const sv: any = r.UNSAFE_getByType(ScrollView).instance;
    sv.scrollTo.mockClear();
    fireEvent.press(r.getByTestId("cd-quick-action-overview"));
    expect(sv.scrollTo.mock.calls).toEqual([[{ y: 0, animated: true }]]);
    const ys: Record<string, number> = { properties: 2100, documents: 1900, warranties: 2700, credits: 1500, subscriptions: 1300, portal: 1700 };
    for (const [k, y] of Object.entries(ys)) {
      fireEvent(r.getByTestId(`cd-anchor-${k}`), "layout", { nativeEvent: { layout: { x: 0, y, width: 300, height: 100 } } });
    }
    for (const [k, y] of Object.entries(ys)) {
      sv.scrollTo.mockClear();
      fireEvent.press(r.getByTestId(`cd-quick-action-${k}`));
      await act(async () => { await new Promise((res) => setTimeout(res, 160)); });
      expect([k, sv.scrollTo.mock.calls.length, sv.scrollTo.mock.calls[0]?.[0]]).toEqual([k, 1, { y: y - 12, animated: true }]);
    }
  });
  it("anchors wrap the right sections", async () => {
    const r = await mount();
    expect(within(r.getByTestId("cd-anchor-credits")).getByTestId("customer-credits-section")).toBeTruthy();
    expect(within(r.getByTestId("cd-anchor-portal")).getByTestId("customer-has-login")).toBeTruthy();
    expect(within(r.getByTestId("cd-anchor-documents")).getByTestId("share-document-button")).toBeTruthy();
  });
});

describe("Phase 40 · action buttons", () => {
  it("Edit + View-as steel / white text; Call emerald / white; Delete keeps red", async () => {
    const r = await mount();
    for (const id of ["customer-action-edit", "impersonate-customer-button"]) {
      const st = flat(r.getByTestId(id));
      expect([id, st.backgroundColor, st.borderColor]).toEqual([id, "#334155", "#64748B"]);
    }
    expect(flat(within(r.getByTestId("customer-action-edit")).getByText("Edit")).color).toBe("#FFFFFF");
    const call = flat(r.getByTestId("customer-action-call"));
    expect([call.backgroundColor, call.borderColor]).toEqual(["#059669", "#059669"]);
    expect(flat(within(r.getByTestId("customer-action-call")).getByText("Call")).color).toBe("#FFFFFF");
    expect(flat(within(r.getByTestId("customer-delete-button")).getByText("Delete customer")).color).toBe("#B91C1C");
  });
});

describe("Phase 40 · Equipment section untouched", () => {
  const EQUIPMENT_BLOCK = "        {/* Phase 56.11-mobile \u2014 Equipment photo library section (legacy). */}\n        <Text style={styles.sectionTitle}>Equipment Photos</Text>\n        <LightPanel anchor=\"equipment\" onAnchor={onAnchor} onNode={onNode}>\n          <CustomerEquipmentLibrary customerId={id as string} />\n        </LightPanel>\n\n        {/* Equipment Units \u2014 structured equipment library (brand/model/serial + S3 photos). */}\n        {isAdminOrTech ? (\n          <>\n            <Text style={styles.sectionTitle}>Equipment Library</Text>\n            <LightPanel>\n              <CustomerEquipmentUnits customerId={id as string} />\n            </LightPanel>\n          </>\n        ) : null}\n";
  it("pre-Phase-40 Equipment block (L895–909) is present byte-for-byte, exactly once", () => {
    const src = readFileSync(join(__dirname, "..", "app", "customer", "[id].tsx"), "utf8");
    expect(src.split(EQUIPMENT_BLOCK).length - 1).toBe(1);
  });
  it("Equipment tile still scrolls to the Equipment Photos panel wrapping CustomerEquipmentLibrary", async () => {
    const r = await mount();
    expect(within(r.getByTestId("cd-section-equipment")).getByTestId("equipment-library-stub")).toBeTruthy();
  });
});

describe("Phase 40b · Issue Credit command-strip button", () => {
  it("admin: in the action row after View-as / before Delete; steel bg + border, white text", async () => {
    const r = await mount();
    const row = ids(r.toJSON()).filter((i) => ["customer-action-edit", "impersonate-customer-button", "customer-action-issue-credit", "customer-delete-button"].includes(i));
    expect(row).toEqual(["customer-action-edit", "impersonate-customer-button", "customer-action-issue-credit", "customer-delete-button"]);
    expect(within(r.getByTestId("customer-action-row")).getByTestId("customer-action-issue-credit")).toBeTruthy();
    const st = flat(r.getByTestId("customer-action-issue-credit"));
    expect([st.backgroundColor, st.borderColor]).toEqual(["#334155", "#64748B"]);
    expect(flat(within(r.getByTestId("customer-action-issue-credit")).getByText("Issue Credit")).color).toBe("#FFFFFF");
  });
  it("tap scrolls to the Credits anchor exactly once; Adjust modal stays closed", async () => {
    const r = await mount();
    const sv: any = r.UNSAFE_getByType(ScrollView).instance;
    fireEvent(r.getByTestId("cd-anchor-credits"), "layout", { nativeEvent: { layout: { x: 0, y: 1500, width: 300, height: 100 } } });
    sv.scrollTo.mockClear();
    fireEvent.press(r.getByTestId("customer-action-issue-credit"));
    await act(async () => { await new Promise((res) => setTimeout(res, 160)); });
    expect(sv.scrollTo.mock.calls).toEqual([[{ y: 1500 - 12, animated: true }]]);
    expect(r.queryByTestId("adjust-credits-modal")).toBeNull();
  });
  it("super_admin sees it; manager / owner / technician do not (Credits section is admin-only on mobile)", async () => {
    mockRole = "super_admin";
    let r = await mount();
    expect(r.getByTestId("customer-action-issue-credit")).toBeTruthy();
    for (const role of ["manager", "owner", "technician"]) {
      r.unmount();
      mockRole = role;
      r = await mount();
      expect([role, r.queryByTestId("customer-action-issue-credit"), r.queryByTestId("customer-credits-section")]).toEqual([role, null, null]);
    }
  });
});
