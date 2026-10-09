/**
 * Phase 9d · Feb-2026 — Customer profile lazy tabs + TTL cache
 * contract tests. Mix of unit tests on ``useCustomerTabCache`` and
 * source-body checks against ``CustomerDetail.jsx``.
 *
 * Locks:
 *   1. ``useCustomerTabCache`` returns cached data within the TTL
 *      window (fetcher called ONCE).
 *   2. After TTL expiry the fetcher is called again.
 *   3. ``invalidate`` busts a single tab entry (keeps other tabs
 *      warm — same-customer, different tab-key).
 *   4. ``clearCustomer`` busts every entry for the current
 *      customer (and only that customer).
 *   5. Default TTL = 5 minutes (exported constant).
 *   6. ``CustomerDetail.jsx`` passes ``?slim=1`` on the profile
 *      fetch (opt-in to Phase 9d slim projection).
 *   7. ``CustomerDetail.jsx`` fetches ``/customers/{id}/summary``
 *      in parallel with the slim profile load and stores the
 *      result on ``summary`` state.
 */
import { renderHook, act } from "@testing-library/react";
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect, beforeEach } from "vitest";

import {
  useCustomerTabCache,
  _resetCacheForTest,
  _setTtlForTest,
  _getCacheSizeForTest,
  DEFAULT_TAB_CACHE_TTL_MS,
} from "@/hooks/useCustomerTabCache";


const CUSTOMER_DETAIL_SRC = fs.readFileSync(
  path.resolve(process.cwd(), "src/pages/customers/CustomerDetail.jsx"),
  "utf-8",
);


describe("Phase 9d · useCustomerTabCache TTL semantics", () => {
  beforeEach(() => {
    _resetCacheForTest();
  });

  it("1. Returns cached data within the TTL window (fetcher called ONCE)", async () => {
    const { result } = renderHook(() => useCustomerTabCache("c-1"));
    let fetchCount = 0;
    const fetcher = async () => {
      fetchCount += 1;
      return { rows: [1, 2, 3] };
    };

    const first = await act(async () =>
      result.current.getOrFetch("jobs", fetcher),
    );
    expect(first).toEqual({ rows: [1, 2, 3] });
    expect(fetchCount).toBe(1);

    // Second call inside TTL window — fetcher must NOT re-run.
    const second = await act(async () =>
      result.current.getOrFetch("jobs", fetcher),
    );
    expect(second).toEqual({ rows: [1, 2, 3] });
    expect(fetchCount).toBe(1);
  });

  it("2. After TTL expiry the fetcher is called again", async () => {
    _setTtlForTest(10); // 10ms TTL for the test
    const { result } = renderHook(() => useCustomerTabCache("c-2"));
    let fetchCount = 0;
    const fetcher = async () => {
      fetchCount += 1;
      return { v: fetchCount };
    };

    const first = await act(async () =>
      result.current.getOrFetch("invoices", fetcher),
    );
    expect(first.v).toBe(1);

    // Wait past the TTL — the next getOrFetch must re-run.
    await new Promise((r) => setTimeout(r, 25));
    const second = await act(async () =>
      result.current.getOrFetch("invoices", fetcher),
    );
    expect(second.v).toBe(2);
    expect(fetchCount).toBe(2);
  });

  it("3. invalidate busts a single tab entry (other tabs stay warm)", async () => {
    const { result } = renderHook(() => useCustomerTabCache("c-3"));
    let jobsCount = 0;
    let invCount = 0;
    const jobsFetcher = async () => ({ v: ++jobsCount });
    const invFetcher = async () => ({ v: ++invCount });

    await act(async () => result.current.getOrFetch("jobs", jobsFetcher));
    await act(async () => result.current.getOrFetch("invoices", invFetcher));
    expect(jobsCount).toBe(1);
    expect(invCount).toBe(1);

    // Invalidate ``jobs`` only. ``invoices`` must stay warm.
    act(() => result.current.invalidate("jobs"));

    await act(async () => result.current.getOrFetch("jobs", jobsFetcher));
    expect(jobsCount).toBe(2);
    await act(async () => result.current.getOrFetch("invoices", invFetcher));
    expect(invCount).toBe(1); // untouched
  });

  it("4. clearCustomer busts every entry for the current customer only", async () => {
    const hookA = renderHook(() => useCustomerTabCache("c-A"));
    const hookB = renderHook(() => useCustomerTabCache("c-B"));
    let aCount = 0;
    let bCount = 0;

    await act(async () =>
      hookA.result.current.getOrFetch("jobs", async () => ({ v: ++aCount })),
    );
    await act(async () =>
      hookA.result.current.getOrFetch("invoices", async () => ({ v: ++aCount })),
    );
    await act(async () =>
      hookB.result.current.getOrFetch("jobs", async () => ({ v: ++bCount })),
    );
    expect(aCount).toBe(2);
    expect(bCount).toBe(1);

    act(() => hookA.result.current.clearCustomer());

    // Customer A — both tabs re-fetch.
    await act(async () =>
      hookA.result.current.getOrFetch("jobs", async () => ({ v: ++aCount })),
    );
    await act(async () =>
      hookA.result.current.getOrFetch("invoices", async () => ({ v: ++aCount })),
    );
    expect(aCount).toBe(4);

    // Customer B — stays warm, no re-fetch.
    await act(async () =>
      hookB.result.current.getOrFetch("jobs", async () => ({ v: ++bCount })),
    );
    expect(bCount).toBe(1);
  });

  it("5. Default TTL is 5 minutes (exported constant)", () => {
    expect(DEFAULT_TAB_CACHE_TTL_MS).toBe(5 * 60 * 1000);
  });

  it("5a. Cache helper surface area for tests is complete", () => {
    _resetCacheForTest();
    expect(_getCacheSizeForTest()).toBe(0);
  });
});


describe("Phase 9d · CustomerDetail slim fetch + summary parallel load", () => {
  it("6. CustomerDetail.jsx passes ?slim=1 on the profile fetch", () => {
    // Static source-body grep — the exact fetch line must carry
    // ``?slim=1`` so the embedded jobs payload is skipped. Removing
    // this param silently reverts the Phase 9d perf win.
    expect(CUSTOMER_DETAIL_SRC).toMatch(
      /api\.get\(`\/customers\/\$\{id\}\?slim=1`\)/,
    );
  });

  it("7. CustomerDetail.jsx fetches /customers/{id}/summary in parallel with load()", () => {
    // The summary fetch rides inside the same Promise.all as the
    // slim profile fetch so the lightweight counts arrive on the
    // first paint rather than deferring to a second round-trip.
    expect(CUSTOMER_DETAIL_SRC).toMatch(
      /api\.get\(`\/customers\/\$\{id\}\/summary`\)\.catch\(\(\)\s*=>\s*null\)/,
    );
    // Summary state slot exists.
    expect(CUSTOMER_DETAIL_SRC).toMatch(
      /const\s+\[\s*summary\s*,\s*setSummary\s*\]\s*=\s*useState\(null\);/,
    );
    expect(CUSTOMER_DETAIL_SRC).toMatch(/setSummary\(/);
  });
});
