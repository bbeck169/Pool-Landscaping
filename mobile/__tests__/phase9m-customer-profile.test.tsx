/**
 * Phase 9-M · Customer profile perf + Crews stale-closure audit
 * (web parity b5c09c9dc · Phase 9d, 81d0566756 · Phase 9).
 *
 *   1. Crews: mobile has no crew-edit surface (ComingSoon) and no crew
 *      writes — regression lock so a future edit screen gets audited.
 *   7. Profile base fetch uses ?slim=1
 *   8. /customers/{id}/summary fetched on mount
 *   9. Job History badge count comes from summary.jobs_count
 *  10. First expand fetches jobs; re-expand within TTL hits cache;
 *      re-expand after TTL re-fetches
 *  +   useCustomerTabCache cross-customer isolation + invalidate
 */
import React from "react";
import fs from "fs";
import path from "path";
import { render, fireEvent, waitFor, act, renderHook } from "@testing-library/react-native";

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
jest.mock("expo-router", () => {
  const R = require("react");
  return {
    useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: jest.fn() }),
    useLocalSearchParams: () => ({ id: "cust-1" }),
    useFocusEffect: (cb: any) => { R.useEffect(() => { cb(); }, []); },
    Redirect: () => null,
  };
});
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
import {
  useCustomerTabCache,
  _resetCacheForTest,
  _getCacheSizeForTest,
  DEFAULT_TAB_CACHE_TTL_MS,
} from "@/src/hooks/useCustomerTabCache";

const CUSTOMER = { id: "cust-1", name: "Jane Test", email: "j@t.com", is_active: true, tags: [] };
const SUMMARY = { customer_id: "cust-1", jobs_count: 103, invoices_count: 96, quotes_count: 73 };
const JOBS = [{ id: "j1", title: "Pool clean" }, { id: "j2", title: "Filter" }];

const urls = () => mockApiGet.mock.calls.map((c) => c[0] as string);
const jobsCalls = () => urls().filter((u) => u.startsWith("/jobs?customer_id="));

beforeEach(() => {
  jest.clearAllMocks();
  _resetCacheForTest();
  mockApiGet.mockImplementation(async (url: string) => {
    if (url === "/customers/cust-1?slim=1") return CUSTOMER;
    if (url === "/customers/cust-1/summary") return SUMMARY;
    if (url.startsWith("/jobs?customer_id=")) return JOBS;
    if (url.includes("/credits")) return { balance_cents: 0, ledger: [] };
    return [];
  });
});
afterEach(() => { jest.restoreAllMocks(); });

async function mountProfile() {
  const r = render(<CustomerDetail />);
  await waitFor(() => r.getByTestId("customer-jobs-tab"));
  return r;
}

describe("1 · Crews stale-closure audit (mobile)", () => {
  const root = path.join(__dirname, "..");
  it("crews.tsx is a read-only ComingSoon surface — no edit state to fix", () => {
    const src = fs.readFileSync(path.join(root, "app/crews.tsx"), "utf8");
    expect(src).toMatch(/ComingSoonPage/);
    expect(src).not.toMatch(/setForm|tech_ids/);
  });
  it("no mobile file writes to /crews (any future edit screen must use functional setForm)", () => {
    const hits: string[] = [];
    const walk = (dir: string) => {
      for (const f of fs.readdirSync(dir, { withFileTypes: true })) {
        const p = path.join(dir, f.name);
        if (f.isDirectory()) { if (f.name !== "node_modules") walk(p); continue; }
        if (!/\.(tsx?|jsx?)$/.test(f.name)) continue;
        const s = fs.readFileSync(p, "utf8");
        if (/api\.(post|patch|put)\(\s*[`"']\/crews/.test(s)) hits.push(p);
        if (/setForm\(\{\s*\.\.\.form,\s*tech_ids/.test(s)) hits.push(p);
      }
    };
    walk(path.join(root, "app"));
    walk(path.join(root, "src"));
    expect(hits).toEqual([]);
  });
});

describe("Phase 9-M · Customer profile", () => {
  it("7. base profile fetch uses ?slim=1 (never the heavy non-slim URL)", async () => {
    await mountProfile();
    expect(urls()).toContain("/customers/cust-1?slim=1");
    expect(urls()).not.toContain("/customers/cust-1");
  });

  it("8. summary endpoint called on mount", async () => {
    await mountProfile();
    expect(urls()).toContain("/customers/cust-1/summary");
  });

  it("9. Job History badge renders summary.jobs_count before any jobs fetch", async () => {
    const r = await mountProfile();
    await waitFor(() => expect(r.getByTestId("customer-jobs-tab-badge").props.children).toBe(103));
    expect(jobsCalls()).toHaveLength(0);
  });

  it("10. first expand fetches; re-expand within TTL cached; after TTL re-fetches", async () => {
    let now = 1_000_000;
    jest.spyOn(Date, "now").mockImplementation(() => now);
    const r = await mountProfile();
    const tab = () => r.getByTestId("customer-jobs-tab");

    await act(async () => { fireEvent.press(tab()); });
    await waitFor(() => r.getByTestId("customer-job-j1"));
    expect(jobsCalls()).toEqual(["/jobs?customer_id=cust-1&limit=50&offset=0&sort=scheduled_date_desc"]);

    await act(async () => { fireEvent.press(tab()); }); // collapse
    now += 60 * 1000;
    await act(async () => { fireEvent.press(tab()); }); // re-expand within TTL
    await waitFor(() => r.getByTestId("customer-job-j1"));
    expect(jobsCalls()).toHaveLength(1);

    await act(async () => { fireEvent.press(tab()); }); // collapse
    now += DEFAULT_TAB_CACHE_TTL_MS;
    await act(async () => { fireEvent.press(tab()); }); // re-expand after TTL
    await waitFor(() => expect(jobsCalls()).toHaveLength(2));
  });
});

describe("useCustomerTabCache", () => {
  it("default TTL is 5 minutes; keys isolated per customer; invalidate busts one tab", async () => {
    expect(DEFAULT_TAB_CACHE_TTL_MS).toBe(5 * 60 * 1000);
    const a = renderHook(() => useCustomerTabCache("A")).result.current;
    const b = renderHook(() => useCustomerTabCache("B")).result.current;
    const f = jest.fn(async () => "x");
    await a.getOrFetch("jobs", f);
    await b.getOrFetch("jobs", f);
    await a.getOrFetch("jobs", f);
    expect(f).toHaveBeenCalledTimes(2);
    expect(_getCacheSizeForTest()).toBe(2);
    a.invalidate("jobs");
    await a.getOrFetch("jobs", f);
    expect(f).toHaveBeenCalledTimes(3);
    b.clearCustomer();
    expect(_getCacheSizeForTest()).toBe(1);
  });
});
