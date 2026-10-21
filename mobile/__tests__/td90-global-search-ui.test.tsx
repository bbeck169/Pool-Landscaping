/**
 * TD-90 · global search in ToolsMenuBody — BOTH surfaces (menu sheet +
 * Tools tab share this body). Tools matches first, then web-ordered
 * groups; dashboard roles only; techs stay tools-only.
 */
import React from "react";
import { render, fireEvent, act } from "@testing-library/react-native";

let mockRole = "admin";
const mockPush = jest.fn();
const mockGet = jest.fn();
const mockMarkUsed = jest.fn();
jest.mock("@/src/api", () => ({ api: { get: (u: string) => mockGet(u) } }));
jest.mock("@/src/auth", () => ({ useAuth: () => ({ user: { id: "u1", role: mockRole } }) }));
jest.mock("expo-router", () => ({ useRouter: () => ({ push: mockPush }) }));
jest.mock("@/src/hooks/useToolsPreferences", () => ({
  useToolsPreferences: () => ({ pins: [], recents: [], togglePin: jest.fn(), markUsed: mockMarkUsed, MAX_PINS: 6 }),
}));
jest.mock("@/src/components/tools/sections", () => ({
  sectionsForRole: () => [{
    key: "ops", title: "Operations",
    tiles: [
      { key: "pool-chem", label: "Pool Chemistry", desc: "Readings", icon: "flask-outline", route: "/chemistry" },
      { key: "routes", label: "Routes", desc: "Daily routes", icon: "map-outline", route: "/routes" },
    ],
  }],
}));

import { ToolsMenuBody, GLOBAL_SEARCH_PLACEHOLDER } from "@/src/components/tools/ToolsMenuBody";

const RESP = {
  customers: [{ id: "c1", primary: "Preview Customer8616", secondary: "preview-customer8616@preview.local" }],
  jobs: [{ id: "j1", primary: "Weekly Pool Service", secondary: "Preview Customer1520" }],
  invoices: [{ id: "i1", primary: "Monthly Pool Service", secondary: "Preview Customer0143 · $149.00" }],
  quotes: [{ id: "q1", primary: "Pool tile replacement estimate", secondary: "Preview Customer0161 · $1,316.52" }],
  leads: [{ id: "l1", primary: "Pool Lead", secondary: "lead@x.com" }],
  technicians: [{ id: "t1", primary: "Pool Tech Pat", secondary: "pool_tech · 480-555-0199" }],
};
const EMPTY = { customers: [], jobs: [], invoices: [], quotes: [], leads: [], technicians: [] };

async function type(q: any, testID: string, text: string) {
  fireEvent.changeText(q.getByTestId(testID), text);
  // SearchBar timer (0 ms on global surfaces) → query committed → hook's 300 ms debounce → fetch.
  await act(async () => { jest.advanceTimersByTime(0); });
  await act(async () => { jest.advanceTimersByTime(300); });
  await act(async () => {});
}
const order = (q: any) => q.UNSAFE_root.findAll((n: any) => typeof n.type === "string" && /^(tools-section-|global-search-group-)/.test(String(n.props?.testID)))
  .map((n: any) => n.props.testID).filter((v: string, i: number, a: string[]) => a.indexOf(v) === i);

beforeEach(() => {
  jest.useFakeTimers();
  mockRole = "admin"; mockPush.mockClear(); mockGet.mockReset(); mockMarkUsed.mockClear();
});
afterEach(() => { jest.useRealTimers(); });

describe.each([["tab", "tools-search"], ["sheet", "mobile-menu-search"]] as const)("%s surface", (variant, inputID) => {
  it("admin: global placeholder; 'pool' → one /search call; tools first, then Customers·Jobs·Invoices·Quotes·Leads·Technicians", async () => {
    mockGet.mockResolvedValue(RESP);
    const q = render(<ToolsMenuBody variant={variant} onNavigate={variant === "sheet" ? jest.fn() : undefined} />);
    expect(q.getByTestId(inputID).props.placeholder).toBe(GLOBAL_SEARCH_PLACEHOLDER);
    await type(q, inputID, "pool");
    expect(mockGet.mock.calls).toEqual([["/search?q=pool&limit=5"]]);
    expect(order(q)).toEqual(["tools-section-ops", "global-search-group-customers", "global-search-group-jobs",
      "global-search-group-invoices", "global-search-group-quotes", "global-search-group-leads", "global-search-group-technicians"]);
    expect(q.getByText("Preview Customer0143 · $149.00")).toBeTruthy();
    expect(q.getByText("Technicians")).toBeTruthy();
    expect(q.getByTestId("global-search-row-technician-t1")).toBeTruthy();
    expect(q.getByText("pool_tech · 480-555-0199")).toBeTruthy();
  });

  it("TD-mobile-tech-search · empty technicians bucket → no Technicians header; other groups unchanged", async () => {
    mockGet.mockResolvedValue({ ...RESP, technicians: [] });
    const q = render(<ToolsMenuBody variant={variant} onNavigate={variant === "sheet" ? jest.fn() : undefined} />);
    await type(q, inputID, "pool");
    expect(q.queryByTestId("global-search-group-technicians")).toBeNull();
    expect(q.queryByText("Technicians")).toBeNull();
    expect(q.getByTestId("global-search-group-leads")).toBeTruthy();
  });

  it("1 char → tools filter only, no fetch", async () => {
    const q = render(<ToolsMenuBody variant={variant} />);
    await type(q, inputID, "p");
    expect(mockGet).not.toHaveBeenCalled();
    expect(q.queryByTestId("global-search-results")).toBeNull();
    expect(q.getByTestId("tools-section-ops")).toBeTruthy();
  });

  it("technician: 'Search tools…' placeholder, tools-only, no backend call (G1)", async () => {
    mockRole = "technician";
    const q = render(<ToolsMenuBody variant={variant} />);
    expect(q.getByTestId(inputID).props.placeholder).toBe("Search tools…");
    await type(q, inputID, "pool");
    await act(async () => { jest.advanceTimersByTime(500); });
    expect(mockGet).not.toHaveBeenCalled();
    expect(q.queryByTestId("global-search-results")).toBeNull();
  });
});

it("Tools tab: each kind pushes its mobile route (invoice + quote → /quote/[id]); recents untouched", async () => {
  mockGet.mockResolvedValue(RESP);
  const q = render(<ToolsMenuBody variant="tab" />);
  await type(q, "tools-search", "pool");
  for (const id of ["customer-c1", "job-j1", "invoice-i1", "quote-q1", "lead-l1", "technician-t1"]) fireEvent.press(q.getByTestId(`global-search-row-${id}`));
  expect(mockPush.mock.calls.map((c) => c[0])).toEqual(["/customer/c1", "/job/j1", "/quote/i1", "/quote/q1", "/leads/l1", "/technician/t1"]);
  expect(mockMarkUsed).not.toHaveBeenCalled();
});

it("menu sheet: hit tap goes through onNavigate (sheet closes, then pushes) — never router.push directly", async () => {
  mockGet.mockResolvedValue(RESP);
  const onNavigate = jest.fn();
  const q = render(<ToolsMenuBody variant="sheet" onNavigate={onNavigate} />);
  await type(q, "mobile-menu-search", "pool");
  fireEvent.press(q.getByTestId("global-search-row-invoice-i1"));
  expect(onNavigate).toHaveBeenCalledWith(expect.objectContaining({ route: "/quote/i1", label: "Monthly Pool Service" }));
  fireEvent.press(q.getByTestId("global-search-row-technician-t1"));
  expect(onNavigate).toHaveBeenLastCalledWith(expect.objectContaining({ route: "/technician/t1", label: "Pool Tech Pat" }));
  expect(mockPush).not.toHaveBeenCalled();
});

it("loading copy 'Searching…' while in flight; empty → web copy, tools empty-state suppressed", async () => {
  let resolve: (v: any) => void = () => {};
  mockGet.mockImplementation(() => new Promise((r) => { resolve = r; }));
  const q = render(<ToolsMenuBody variant="tab" />);
  await type(q, "tools-search", "zzzz");
  expect(q.getByText("Searching…")).toBeTruthy();
  await act(async () => { resolve(EMPTY); });
  expect(q.getByTestId("global-search-empty").props.children).toBe("No results for “zzzz”");
  expect(q.queryByTestId("tools-empty")).toBeNull();
  expect(q.queryByTestId("global-search-loading")).toBeNull();
});

it("error → previous results stay + muted inline error line", async () => {
  mockGet.mockResolvedValueOnce(RESP).mockRejectedValueOnce(new Error("Network request failed"));
  const q = render(<ToolsMenuBody variant="tab" />);
  await type(q, "tools-search", "pool");
  await type(q, "tools-search", "pools");
  expect(q.getByTestId("global-search-error")).toBeTruthy();
  expect(q.getByTestId("global-search-row-customer-c1")).toBeTruthy();
  expect(q.queryByTestId("global-search-empty")).toBeNull();
});
