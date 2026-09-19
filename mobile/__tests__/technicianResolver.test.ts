/**
 * K43 · technicianResolver — unit tests.
 *
 * 1. Fast-path: user.technician_id is present → returns immediately.
 * 2. Slow-path: calls GET /api/technicians/me → returns data.id.
 * 3. 404 → returns null (tech not in roster).
 * 4. Cache: second call for same user.id doesn't refetch.
 * 5. Other errors → returns null but doesn't cache.
 */
const mockGet = jest.fn();
jest.mock("@/src/api", () => ({
  api: {
    get: (...args: any[]) => mockGet(...args),
  },
}));

import {
  resolveTechnicianId,
  clearTechnicianIdCache,
  _testCache,
} from "@/lib/technicianResolver";

beforeEach(() => {
  jest.clearAllMocks();
  clearTechnicianIdCache();
});

describe("resolveTechnicianId", () => {
  it("returns immediately when user.technician_id is present (fast-path)", async () => {
    const result = await resolveTechnicianId({
      id: "u1",
      technician_id: "t1",
    });
    expect(result).toBe("t1");
    expect(mockGet).not.toHaveBeenCalled();
  });

  it("calls GET /technicians/me when technician_id is null", async () => {
    mockGet.mockResolvedValueOnce({ id: "t-resolved-42" });

    const result = await resolveTechnicianId({
      id: "u2",
      technician_id: null,
    });

    expect(mockGet).toHaveBeenCalledWith("/technicians/me");
    expect(result).toBe("t-resolved-42");
  });

  it("calls GET /technicians/me when technician_id is undefined", async () => {
    mockGet.mockResolvedValueOnce({ id: "t-resolved-99" });

    const result = await resolveTechnicianId({
      id: "u3",
    });

    expect(mockGet).toHaveBeenCalledWith("/technicians/me");
    expect(result).toBe("t-resolved-99");
  });

  it("returns null on 404 (tech not in roster)", async () => {
    const err: any = new Error("Not found");
    err.status = 404;
    mockGet.mockRejectedValueOnce(err);

    const result = await resolveTechnicianId({
      id: "u4",
      technician_id: null,
    });

    expect(result).toBeNull();
    // Should also cache the null
    expect(_testCache.get("u4")).toBeNull();
  });

  it("caches the resolved value — second call skips fetch", async () => {
    mockGet.mockResolvedValueOnce({ id: "t-cached" });

    const user = { id: "u5", technician_id: null as string | null };
    const r1 = await resolveTechnicianId(user);
    const r2 = await resolveTechnicianId(user);

    expect(r1).toBe("t-cached");
    expect(r2).toBe("t-cached");
    expect(mockGet).toHaveBeenCalledTimes(1); // Only one fetch
  });

  it("does NOT cache on non-404 error (allows retry)", async () => {
    mockGet.mockRejectedValueOnce(new Error("Network error"));
    mockGet.mockResolvedValueOnce({ id: "t-retry-ok" });

    const user = { id: "u6", technician_id: null as string | null };
    const r1 = await resolveTechnicianId(user);
    expect(r1).toBeNull(); // First attempt fails

    const r2 = await resolveTechnicianId(user);
    expect(r2).toBe("t-retry-ok"); // Second attempt succeeds
    expect(mockGet).toHaveBeenCalledTimes(2);
  });

  it("returns null for null user", async () => {
    const result = await resolveTechnicianId(null);
    expect(result).toBeNull();
    expect(mockGet).not.toHaveBeenCalled();
  });

  it("returns null for user with no id", async () => {
    const result = await resolveTechnicianId({ id: null, technician_id: null });
    expect(result).toBeNull();
    expect(mockGet).not.toHaveBeenCalled();
  });

  it("clearTechnicianIdCache clears the module cache", async () => {
    mockGet.mockResolvedValueOnce({ id: "t-clear" });
    await resolveTechnicianId({ id: "u8", technician_id: null });
    expect(_testCache.has("u8")).toBe(true);

    clearTechnicianIdCache();
    expect(_testCache.has("u8")).toBe(false);
  });
});
