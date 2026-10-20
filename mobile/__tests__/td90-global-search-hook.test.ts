/**
 * TD-90 · useGlobalSearch (web useGlobalSearchResults mirror) + route map.
 */
import { renderHook, act } from "@testing-library/react-native";

const mockGet = jest.fn();
jest.mock("@/src/api", () => ({ api: { get: (u: string) => mockGet(u) } }));

import { useGlobalSearch, canGlobalSearch } from "@/src/hooks/useGlobalSearch";
import { routeForSearchHit, GLOBAL_SEARCH_GROUPS } from "@/src/lib/globalSearchRoutes";

const RESP = {
  customers: [{ id: "c1", primary: "Alice", secondary: "a@x.com" }],
  jobs: [{ id: "j1", primary: "Weekly Pool Service", secondary: "Alice" }],
  invoices: [{ id: "i1", primary: "Invoice 1001", secondary: "Alice · $149.00" }],
  quotes: [{ id: "q1", primary: "Quote 7", secondary: "Alice · $1,316.52" }],
  leads: [{ id: "l1", primary: "Bob", secondary: "b@x.com" }],
};
const flush = async (ms: number) => { await act(async () => { jest.advanceTimersByTime(ms); }); await act(async () => {}); };

beforeEach(() => { jest.useFakeTimers(); mockGet.mockReset(); });
afterEach(() => { jest.useRealTimers(); });

it("2+ chars → one debounced GET /search?q=&limit=5 (300 ms), all 5 buckets mapped", async () => {
  mockGet.mockResolvedValue(RESP);
  const { result } = renderHook(() => useGlobalSearch("po", "admin"));
  expect(result.current.active).toBe(true);
  await flush(299);
  expect(mockGet).not.toHaveBeenCalled();
  await flush(1);
  expect(mockGet).toHaveBeenCalledTimes(1);
  expect(mockGet).toHaveBeenCalledWith("/search?q=po&limit=5");
  expect(result.current.buckets).toEqual(RESP);
  expect(result.current.total).toBe(5);
  expect(result.current.loading).toBe(false);
});

it("1 char / whitespace → no fetch, empty buckets", async () => {
  const { result, rerender } = renderHook(({ q }) => useGlobalSearch(q, "admin"), { initialProps: { q: "p" } });
  await flush(1000);
  rerender({ q: "   " });
  await flush(1000);
  expect(mockGet).not.toHaveBeenCalled();
  expect(result.current.active).toBe(false);
  expect(result.current.total).toBe(0);
});

it("fast typing → only the last query is fetched; query is URL-encoded and trimmed", async () => {
  mockGet.mockResolvedValue(RESP);
  const { rerender } = renderHook(({ q }) => useGlobalSearch(q, "manager"), { initialProps: { q: "po" } });
  await flush(100);
  rerender({ q: "poo" });
  await flush(100);
  rerender({ q: " 555 01&x " });
  await flush(300);
  expect(mockGet.mock.calls).toEqual([["/search?q=555%2001%26x&limit=5"]]);
});

it("stale response from a superseded query never lands", async () => {
  let resolveFirst: (v: any) => void = () => {};
  mockGet.mockImplementationOnce(() => new Promise((r) => { resolveFirst = r; }))
    .mockResolvedValueOnce({ ...RESP, customers: [{ id: "c2", primary: "Second" }] });
  const { result, rerender } = renderHook(({ q }) => useGlobalSearch(q, "admin"), { initialProps: { q: "ab" } });
  await flush(300);
  rerender({ q: "abc" });
  await flush(300);
  await act(async () => { resolveFirst({ ...RESP, customers: [{ id: "c1", primary: "First" }] }); });
  expect(result.current.buckets.customers.map((c) => c.id)).toEqual(["c2"]);
});

it("401 / 403 / network error → previous buckets kept + error flag; next success clears it", async () => {
  mockGet.mockResolvedValueOnce(RESP)
    .mockRejectedValueOnce(Object.assign(new Error("Not authenticated"), { status: 401 }))
    .mockRejectedValueOnce(Object.assign(new Error("Dashboard access required"), { status: 403 }))
    .mockResolvedValueOnce({ customers: [], jobs: [], invoices: [], quotes: [], leads: [] });
  const { result, rerender } = renderHook(({ q }) => useGlobalSearch(q, "admin"), { initialProps: { q: "al" } });
  await flush(300);
  rerender({ q: "ali" });
  await flush(300);
  expect(result.current.error).toBe(true);
  expect(result.current.buckets).toEqual(RESP);
  rerender({ q: "alic" });
  await flush(300);
  expect(result.current.error).toBe(true);
  expect(result.current.total).toBe(5);
  rerender({ q: "alice" });
  await flush(300);
  expect(result.current.error).toBe(false);
  expect(result.current.total).toBe(0);
});

it("tenant isolation is server-side: hook renders only BE rows and sends no tenant hint; rows without id dropped", async () => {
  mockGet.mockResolvedValue({ customers: [{ id: "c1", primary: "Mine" }, { primary: "no id" }], jobs: null });
  const { result } = renderHook(() => useGlobalSearch("mine", "admin"));
  await flush(300);
  expect(mockGet.mock.calls[0][0]).not.toMatch(/tenant/i);
  expect(result.current.buckets.customers).toEqual([{ id: "c1", primary: "Mine" }]);
  expect(result.current.buckets.jobs).toEqual([]);
});

it("role gate (G1): technician / customer / unknown never fetch; dashboard roles do", async () => {
  for (const role of ["technician", "customer", "customer_admin", "", undefined, null]) {
    const { result } = renderHook(() => useGlobalSearch("pool", role as any));
    await flush(400);
    expect(result.current.active).toBe(false);
  }
  expect(mockGet).not.toHaveBeenCalled();
  expect(["admin", "super_admin", "owner", "manager"].every((r) => canGlobalSearch(r))).toBe(true);
});

it("route map: customer/job/invoice→/quote/quote/lead; missing id → null; web group order", () => {
  expect(routeForSearchHit("customer", "c1")).toBe("/customer/c1");
  expect(routeForSearchHit("job", "j1")).toBe("/job/j1");
  expect(routeForSearchHit("invoice", "i1")).toBe("/quote/i1");
  expect(routeForSearchHit("quote", "q1")).toBe("/quote/q1");
  expect(routeForSearchHit("lead", "l1")).toBe("/leads/l1");
  expect(routeForSearchHit("job", "")).toBeNull();
  expect(routeForSearchHit("customer", "a/b")).toBe("/customer/a%2Fb");
  expect(GLOBAL_SEARCH_GROUPS.map((g) => g.label)).toEqual(["Customers", "Jobs", "Invoices", "Quotes", "Leads"]);
});
