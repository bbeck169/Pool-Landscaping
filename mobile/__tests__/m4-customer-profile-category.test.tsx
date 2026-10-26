/**
 * M4 · Customer Profile combined category badge + per-property selector (web Ticket AA).
 * Renders the real app/customer/[id] screen (mock set from phase35-customer-identity-header).
 */
import React from "react";
import { render, waitFor, act, fireEvent } from "@testing-library/react-native";

const mockApiGet = jest.fn();
const mockApiPatch = jest.fn();
const mockToast = jest.fn();
let mockRole = "admin";
jest.mock("@/src/api", () => {
  class ApiError extends Error { status: number; detail: string; constructor(s: number, m?: string) { super(m || "Error"); this.status = s; this.detail = m || "Error"; } }
  class ApiNetworkError extends Error { kind = "network"; }
  return { api: { get: (...a: any[]) => mockApiGet(...a), patch: (...a: any[]) => mockApiPatch(...a), post: jest.fn(), put: jest.fn(), del: jest.fn() }, ApiError, ApiNetworkError, TOKEN_KEY: "token" };
});
jest.mock("@/src/auth", () => ({ useAuth: () => ({ user: { id: "u1", role: mockRole, name: "U" }, startImpersonation: jest.fn() }) }));
jest.mock("expo-router", () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: jest.fn() }),
  useLocalSearchParams: () => ({ id: "cust-1" }), usePathname: () => "/", useSegments: () => [],
  useFocusEffect: (cb: any) => require("react").useEffect(() => { cb(); }, []), Redirect: () => null,
}));
jest.mock("react-native-safe-area-context", () => ({ useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }) }));
jest.mock("@/src/hooks/useBreadcrumbs", () => ({ useBreadcrumbs: () => [] }));
jest.mock("@/src/hooks/useTenantBrand", () => ({ __esModule: true, default: () => ({ logoUri: null }), useTenantBrand: () => ({ logoUrl: null }) }));
jest.mock("@expo/vector-icons", () => { const { View } = require("react-native"); return { Ionicons: () => <View /> }; });
jest.mock("expo-image", () => ({ Image: () => null }));
jest.mock("expo-image-picker", () => ({}));
jest.mock("@/src/components/ToastProvider", () => ({ useToast: () => ({ showToast: (...a: any[]) => mockToast(...a) }) }));
jest.mock("@/src/services/readCache", () => ({ writeCache: jest.fn(async () => {}), readCache: jest.fn(async () => null) }));
jest.mock("@/src/components/ui", () => {
  const { View, Text, Pressable } = require("react-native");
  return { Loading: () => <View />, PrimaryButton: ({ title, onPress }: any) => <Pressable onPress={onPress}><Text>{title}</Text></Pressable>, Sheet: () => null, StatusChip: () => null };
});
jest.mock("@/src/components/widgets", () => { const { View } = require("react-native"); return { Header: (p: any) => <View>{p.right}</View>, JobCard: () => <View /> }; });
jest.mock("@/src/components/ui/AppTextInput", () => { const { TextInput } = require("react-native"); return function M(p: any) { return <TextInput {...p} />; }; });
jest.mock("@/src/components/customer", () => { const { View } = require("react-native"); return { PhoneLink: () => <View />, AddressLink: () => <View /> }; });
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
import { computeCombinedCategory } from "@/src/lib/combinedCategory";

const CUST = { id: "cust-1", name: "Jane Test", is_active: true, tags: [], mobiles: [] };
const prop = (id: string, cat: string | null, extra: any = {}) => ({ id, label: `Prop ${id}`, service_category: cat, sort_order: 1, address: { line1: `${id} St` }, ...extra });

async function mount(props: any[]) {
  mockApiGet.mockImplementation((url: string) => {
    if (url === "/customers/cust-1?slim=1") return Promise.resolve(CUST);
    if (url === "/customers/cust-1/properties") return Promise.resolve(props);
    if (url.includes("/credits")) return Promise.resolve({ balance_cents: 0, ledger: [] });
    if (url.endsWith("/kpi-summary")) return Promise.resolve({});
    return Promise.resolve([]);
  });
  const r = render(<CustomerDetail />);
  await waitFor(() => r.getByTestId("cd-identity-card"));
  await act(async () => {});
  return r;
}
const badge = (q: any) => q.getByTestId("customer-combined-category-text").props.children;
const selected = (q: any, c: string, pid: string) => q.getByTestId(`pc-cat-${c}-${pid}`).props.accessibilityState?.selected;

beforeEach(() => { mockApiGet.mockReset(); mockApiPatch.mockReset(); mockToast.mockReset(); mockRole = "admin"; });

it("A1 · combined label across every combination (canonical order, inactive ignored, empty → null)", () => {
  const P = (...c: (string | null)[]) => c.map((x, i) => ({ id: String(i), service_category: x }));
  expect(computeCombinedCategory(P("pool", "pool"))).toBe("Pool");
  expect(computeCombinedCategory(P("both", "both"))).toBe("Both");
  expect(computeCombinedCategory(P("landscaping", "pool"))).toBe("Pool + Landscaping");
  expect(computeCombinedCategory(P("both", "pool"))).toBe("Pool + Both");
  expect(computeCombinedCategory(P("both", "landscaping"))).toBe("Landscaping + Both");
  expect(computeCombinedCategory(P("both", "landscaping", "pool"))).toBe("Pool + Landscaping + Both");
  expect(computeCombinedCategory([])).toBeNull();
  expect(computeCombinedCategory(P(null, null))).toBeNull();
  expect(computeCombinedCategory([{ service_category: "pool", active: false }, { service_category: "both" }])).toBe("Both");
});

it("A2 · header badge renders the combined label; zero properties / all-null → muted '—'", async () => {
  let q = await mount([prop("p1", "pool"), prop("p2", "landscaping")]);
  expect(badge(q)).toBe("POOL + LANDSCAPING");
  expect(q.getByTestId("customer-combined-category-badge").props.accessibilityHint).toBe("Set category per property below");
  q.unmount();
  q = await mount([]);
  expect(badge(q)).toBe("—");
  q.unmount();
  q = await mount([prop("p1", null), prop("p2", null)]);
  expect(badge(q)).toBe("—");
});

it("A3 · admin sees an interactive chip-group on each property row", async () => {
  const q = await mount([prop("p1", "pool"), prop("p2", null)]);
  for (const pid of ["p1", "p2"]) expect(q.getByTestId(`pc-category-group-${pid}`)).toBeTruthy();
  expect(selected(q, "pool", "p1")).toBe(true);
  expect(selected(q, "landscaping", "p1")).toBe(false);
  expect(q.getByTestId("pc-cat-both-p2").props.accessibilityState).toEqual({ selected: false }); // interactive (not disabled)
});

it("A4 · non-admin (technician) sees read-only chips: no press handler, no PATCH", async () => {
  mockRole = "technician";
  const q = await mount([prop("p1", "pool")]);
  const chip = q.getByTestId("pc-cat-landscaping-p1");
  expect(chip.props.onPress).toBeUndefined();
  expect(chip.props.accessibilityState).toEqual({ selected: false, disabled: true });
  fireEvent.press(chip);
  expect(mockApiPatch).not.toHaveBeenCalled();
  expect(selected(q, "pool", "p1")).toBe(true);
});

it("A5 · admin tap → optimistic update + PATCH /properties/{pid} {service_category} + badge recomputes", async () => {
  let resolve: any;
  mockApiPatch.mockReturnValueOnce(new Promise((r) => { resolve = r; }));
  const q = await mount([prop("p1", "pool"), prop("p2", null)]);
  fireEvent.press(q.getByTestId("pc-cat-landscaping-p2"));
  expect(selected(q, "landscaping", "p2")).toBe(true); // optimistic
  expect(badge(q)).toBe("POOL + LANDSCAPING");
  expect(mockApiPatch).toHaveBeenCalledWith("/properties/p2", { service_category: "landscaping" });
  await act(async () => { resolve({ id: "p2", service_category: "landscaping", service_category_source: "admin_override" }); });
  expect(badge(q)).toBe("POOL + LANDSCAPING");
  expect(mockToast).toHaveBeenCalledWith("Property category set to landscaping");
});

it("A6 · 4xx rollback restores the prior chip + badge and toasts the error", async () => {
  mockApiPatch.mockRejectedValueOnce(Object.assign(new Error("Admin access required"), { status: 403 }));
  const q = await mount([prop("p1", "pool")]);
  await act(async () => { fireEvent.press(q.getByTestId("pc-cat-both-p1")); });
  expect(selected(q, "pool", "p1")).toBe(true);
  expect(selected(q, "both", "p1")).toBe(false);
  expect(badge(q)).toBe("POOL");
  expect(mockToast).toHaveBeenCalledWith("Category update failed: Admin access required", "error");
});

it("A7 · tapping the active chip clears it (null write) → badge falls back to '—'", async () => {
  mockApiPatch.mockResolvedValueOnce({ id: "p1", service_category: null });
  const q = await mount([prop("p1", "pool")]);
  await act(async () => { fireEvent.press(q.getByTestId("pc-cat-pool-p1")); });
  expect(mockApiPatch).toHaveBeenCalledWith("/properties/p1", { service_category: null });
  expect(selected(q, "pool", "p1")).toBe(false);
  expect(badge(q)).toBe("—");
  expect(mockToast).toHaveBeenCalledWith("Property category cleared");
});
