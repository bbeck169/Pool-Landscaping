/**
 * useTenantBrand hook tests.
 *
 * 1. Fetches on mount, caches per session.
 * 2. refresh() re-fetches.
 * 3. Offline mode returns cached URL without network call.
 */

// Use a global object that is accessible from inside jest.mock factories.
// @ts-ignore
global.__testState = {
  isOnline: true,
  storageData: {} as Record<string, string>,
  apiGetImpl: async () => ({ branding: null }),
};

jest.mock("@/src/services/sync/netBus", () => ({
  // @ts-ignore
  isOnlineNow: () => global.__testState.isOnline,
  on: jest.fn(() => jest.fn()),
}));

jest.mock("@/src/api", () => ({
  api: {
    // @ts-ignore
    get: (...args: any[]) => global.__testState.apiGetImpl(...args),
    post: jest.fn(),
    put: jest.fn(),
    patch: jest.fn(),
    del: jest.fn(),
  },
}));

jest.mock("@/src/utils/storage", () => ({
  storage: {
    getItem: async (key: string, def?: string) => {
      // @ts-ignore
      return global.__testState.storageData[key] ?? def ?? null;
    },
    setItem: async (key: string, val: string) => {
      // @ts-ignore
      global.__testState.storageData[key] = val;
    },
    removeItem: async (key: string) => {
      // @ts-ignore
      delete global.__testState.storageData[key];
    },
  },
}));

jest.mock("expo-router", () => ({
  useRouter: () => ({ push: jest.fn() }),
}));

jest.mock("@react-native-async-storage/async-storage", () => ({
  getItem: jest.fn(async () => null),
  setItem: jest.fn(async () => {}),
}));

import React from "react";
import { renderHook, act, waitFor } from "@testing-library/react-native";
import { useTenantBrand, __resetSessionCache } from "@/src/hooks/useTenantBrand";

describe("useTenantBrand hook", () => {
  beforeEach(() => {
    // @ts-ignore
    global.__testState.isOnline = true;
    // @ts-ignore
    global.__testState.storageData = {};
    // @ts-ignore
    global.__testState.apiGetImpl = async () => ({ branding: null });
    __resetSessionCache();
  });

  test("1 · fetches on mount and caches", async () => {
    // @ts-ignore
    global.__testState.apiGetImpl = async (url: string) => {
      return { branding: { logo_url: "https://example.com/logo.png" } };
    };

    const { result } = renderHook(() => useTenantBrand());

    await waitFor(() => {
      expect(result.current.logoUrl).toBe("https://example.com/logo.png");
    });
    expect(result.current.loading).toBe(false);
    // @ts-ignore
    expect(global.__testState.storageData["tenant_brand_logo_url"]).toBe("https://example.com/logo.png");
    console.log("✅ TB-T1: Fetches on mount, caches logo URL");
  });

  test("2 · refresh() re-fetches", async () => {
    // @ts-ignore
    global.__testState.apiGetImpl = async () => ({
      branding: { logo_url: "https://example.com/old.png" },
    });

    const { result } = renderHook(() => useTenantBrand());

    await waitFor(() => {
      expect(result.current.logoUrl).toBe("https://example.com/old.png");
    });

    // @ts-ignore
    global.__testState.apiGetImpl = async () => ({
      branding: { logo_url: "https://example.com/new.png" },
    });

    await act(async () => {
      await result.current.refresh();
    });

    expect(result.current.logoUrl).toBe("https://example.com/new.png");
    console.log("✅ TB-T2: refresh() re-fetches and updates logoUrl");
  });

  test("3 · offline returns cached URL without network call", async () => {
    // @ts-ignore
    global.__testState.storageData["tenant_brand_logo_url"] = "https://example.com/cached.png";
    // @ts-ignore
    global.__testState.isOnline = false;
    let apiCalled = false;
    // @ts-ignore
    global.__testState.apiGetImpl = async () => { apiCalled = true; return {}; };

    const { result } = renderHook(() => useTenantBrand());

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.logoUrl).toBe("https://example.com/cached.png");
    expect(apiCalled).toBe(false);
    console.log("✅ TB-T3: Offline returns cached URL without network call");
  });

  test("3b · returns null when no cache and offline", async () => {
    // @ts-ignore
    global.__testState.isOnline = false;
    let apiCalled = false;
    // @ts-ignore
    global.__testState.apiGetImpl = async () => { apiCalled = true; return {}; };

    const { result } = renderHook(() => useTenantBrand());

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.logoUrl).toBeNull();
    expect(apiCalled).toBe(false);
    console.log("✅ TB-T3b: Offline with no cache returns null (uses bundled default)");
  });
});
