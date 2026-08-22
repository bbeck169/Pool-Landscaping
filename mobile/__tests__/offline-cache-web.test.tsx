/**
 * Offline cache web-variant isolation test.
 *
 * Proves that the ``.web.ts`` fallback does NOT import expo-sqlite.
 * Mirrors the P14 daily-route-map-web.test.tsx pattern.
 */

/* ── Bomb mock: any attempt to require expo-sqlite will throw ────── */
jest.mock("expo-sqlite", () => {
  throw new Error("expo-sqlite must NOT be imported on web");
});

// Import the .web variant DIRECTLY — proves it never reaches for expo-sqlite.
import {
  initCache,
  cacheWeekJobs,
  getCachedWeekJobs,
  getCachedJob,
  cacheCustomer,
  getCachedCustomer,
  cacheMe,
  getCachedMe,
  wipeCache,
  __resetForTests,
} from "@/src/lib/offline/cache.web";

describe("cache.web — in-memory shim isolation", () => {
  beforeEach(() => {
    __resetForTests();
  });

  it("imports without triggering expo-sqlite", () => {
    // If we got here, the bomb mock was never hit.
    expect(initCache).toBeDefined();
    expect(typeof initCache).toBe("function");
  });

  it("initCache resolves as a no-op", async () => {
    await expect(initCache()).resolves.toBeUndefined();
  });

  it("round-trips jobs through the in-memory store", async () => {
    const jobs = [
      { id: "j1", scheduled_date: "2026-03-10", customer_name: "Alice" },
      { id: "j2", scheduled_date: "2026-03-11", customer_name: "Bob" },
    ];
    await cacheWeekJobs("tech-1", jobs);

    const all = await getCachedWeekJobs("tech-1");
    expect(all).toHaveLength(2);

    const single = await getCachedJob("j1");
    expect(single?.customer_name).toBe("Alice");

    // Week filter
    const filtered = await getCachedWeekJobs("tech-1", "2026-03-10");
    expect(filtered).toHaveLength(2);
  });

  it("round-trips customer through the in-memory store", async () => {
    await cacheCustomer({ id: "c1", name: "Charlie" });
    const cached = await getCachedCustomer("c1");
    expect(cached?.name).toBe("Charlie");
  });

  it("round-trips user through the in-memory store", async () => {
    await cacheMe({ id: "u1", email: "test@test.com" });
    const cached = await getCachedMe();
    expect(cached?.email).toBe("test@test.com");
  });

  it("wipeCache clears all stores", async () => {
    await cacheWeekJobs("tech-1", [{ id: "j1", scheduled_date: "2026-03-10" }]);
    await cacheCustomer({ id: "c1", name: "X" });
    await cacheMe({ id: "u1", email: "y" });

    await wipeCache();

    expect(await getCachedWeekJobs("tech-1")).toHaveLength(0);
    expect(await getCachedCustomer("c1")).toBeNull();
    expect(await getCachedMe()).toBeNull();
  });
});
