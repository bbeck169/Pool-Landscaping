/**
 * Feb-2026 · P35 — mobile Customers list infinite-scroll pagination.
 *
 * Coverage:
 *   1. Initial mount fetches page=1 with page_size=50
 *      (Phase 9-M · 10e050e48 — default 100 → 50, web parity b5c09c9dc).
 *   2. FlatList onEndReached triggers the next-page fetch (page=2).
 *   3. Once we've loaded the last page (page === total_pages),
 *      onEndReached becomes a no-op (no extra fetch fires).
 */
import React from "react";
import { render, act, waitFor } from "@testing-library/react-native";

// ── mocks ────────────────────────────────────────────────────────────
const mockApiGet = jest.fn();
const mockApiPost = jest.fn();
const mockApiPatch = jest.fn();

jest.mock("@/src/api", () => ({
  api: {
    get: (...args: any[]) => mockApiGet(...args),
    post: (...args: any[]) => mockApiPost(...args),
    patch: (...args: any[]) => mockApiPatch(...args),
  },
}));

jest.mock("@/src/auth", () => ({
  useAuth: () => ({ user: { id: "u1", role: "admin" }, token: "tok" }),
}));

jest.mock("expo-router", () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: jest.fn(), setParams: jest.fn() }),
  // Phase 9-M — customers list reads onboarding-tile filters from route params.
  useLocalSearchParams: () => ({}),
  useFocusEffect: (cb: any) => {
    const { useEffect } = require("react");
    useEffect(() => { cb(); }, []);
  },
}));

jest.mock("@expo/vector-icons", () => ({
  Ionicons: () => null,
}));

jest.mock("@/src/theme", () => ({
  colors: { bg: "#000", card: "#111", surface: "#222", surfaceHover: "#333",
             border: "#444", brand: "#0af", brandTertiary: "#0af",
             text: "#fff", muted: "#888", danger: "#f00", ok: "#0f0",
             warn: "#fa0", info: "#0af", success: "#0f0" },
  spacing: { xs: 4, sm: 8, md: 12, lg: 16, xl: 20, "2xl": 24, "3xl": 32 },
  radius: { sm: 4, md: 8, lg: 12, xl: 16 },
  font: { regular: "System", medium: "System", bold: "System" },
  fontSize: { xs: 10, sm: 12, md: 14, lg: 16, xl: 20 },
  // Phase 19 — Phase T1 sitewide input theme. AppTextInput reads
  // ``inputColors.bg`` / ``.text`` / ``.placeholder`` at module scope;
  // without this binding the mock crashed every case at import time.
  inputColors: { bg: "#FFFFFF", text: "#000080", placeholder: "rgba(0,0,128,0.55)" },
}));

jest.mock("@/src/components/ui", () => {
  const { View, Text } = require("react-native");
  return {
    Loading: (props: any) => (
      <View testID={props.testID || "loading"}><Text>Loading</Text></View>),
    EmptyState: (props: any) => (
      <View testID={props.testID || "empty"}><Text>{props.title}</Text></View>),
  };
});

jest.mock("@/src/components/widgets", () => {
  const { View, Pressable, Text } = require("react-native");
  return {
    Header: () => <View testID="header" />,
    IconButton: (props: any) => (
      <Pressable onPress={props.onPress} testID={props.testID}>
        <Text>{props.label || "btn"}</Text>
      </Pressable>),
  };
});

jest.mock("@/src/components/ImportExport", () => ({
  ImportExport: () => null,
}));

jest.mock("@/src/components/bulk-select/BulkSelectToolkit", () => {
  const { View } = require("react-native");
  return {
    useBulkSelect: () => ({
      selected: new Set<string>(),
      count: 0,
      toggleOne: () => {},
      clear: () => {},
      toggleAll: () => {},
    }),
    BulkCheckbox: () => <View />,
    BulkActionBar: () => <View />,
  };
});


// Envelope helper.
function _envelope(page: number, total = 250, page_size = 50) {
  const total_pages = Math.ceil(total / page_size);
  const from = (page - 1) * page_size + 1;
  const to = Math.min(page * page_size, total);
  const items = [];
  for (let i = from; i <= to; i++) {
    items.push({ id: `c-${i}`, name: `Customer ${i}` });
  }
  return { items, total, page, page_size, total_pages };
}


beforeEach(() => {
  mockApiGet.mockReset();
});


describe("Mobile Customers · P35 infinite-scroll pagination", () => {
  it("initial mount fetches page=1 & page_size=50", async () => {
    mockApiGet.mockImplementation((path: string) => {
      if (path.startsWith("/customers?")) return Promise.resolve(_envelope(1));
      return Promise.resolve({});
    });

    const Customers = require("../app/(app)/customers").default;
    render(<Customers />);

    await waitFor(() => {
      const calls = mockApiGet.mock.calls.map((c) => c[0]);
      expect(
        calls.some((p: any) => typeof p === "string"
          && p.startsWith("/customers?")
          && p.includes("page=1")
          && p.includes("page_size=50")),
      ).toBe(true);
    });
  });

  it("FlatList onEndReached triggers page=2 fetch", async () => {
    mockApiGet.mockImplementation((path: string) => {
      if (path.startsWith("/customers?")) {
        const p = parseInt(new URL("http://x" + path).searchParams.get("page")
                             || "1", 10);
        return Promise.resolve(_envelope(p));
      }
      return Promise.resolve({});
    });

    const Customers = require("../app/(app)/customers").default;
    const utils = render(<Customers />);

    // Wait for page 1 fetch to complete.
    await waitFor(() => {
      const calls = mockApiGet.mock.calls.map((c) => c[0]);
      expect(calls.some((p: any) => typeof p === "string"
        && p.includes("page=1"))).toBe(true);
    });

    // Grab the FlatList and fire onEndReached.
    const list = await utils.findByTestId("customers-list");
    await act(async () => {
      // React-native testing-library exposes the raw prop.
      list.props.onEndReached();
    });

    await waitFor(() => {
      const calls = mockApiGet.mock.calls.map((c) => c[0]);
      expect(
        calls.some((p: any) => typeof p === "string"
          && p.startsWith("/customers?")
          && p.includes("page=2")
          && p.includes("page_size=50")),
      ).toBe(true);
    });
  });

  it("onEndReached is a no-op once the last page has loaded", async () => {
    // Envelope returns total=50, total_pages=1 → first fetch is also
    // the last page. Subsequent onEndReached must NOT fire another
    // /customers?page=... request.
    mockApiGet.mockImplementation((path: string) => {
      if (path.startsWith("/customers?")) {
        return Promise.resolve(_envelope(1, 50));
      }
      return Promise.resolve({});
    });

    const Customers = require("../app/(app)/customers").default;
    const utils = render(<Customers />);

    await waitFor(() => {
      const calls = mockApiGet.mock.calls.map((c) => c[0]);
      expect(calls.some((p: any) => typeof p === "string"
        && p.includes("page=1"))).toBe(true);
    });

    const callsBefore = mockApiGet.mock.calls
      .filter((c) => typeof c[0] === "string" && c[0].startsWith("/customers?"))
      .length;

    // Hydration is done; total_pages=1 so onEndReached should short-circuit.
    // But the empty-state branch renders when items.length===0. total=50
    // returns 50 items so the FlatList mounts.
    const list = await utils.findByTestId("customers-list");
    await act(async () => { list.props.onEndReached(); });
    await act(async () => { list.props.onEndReached(); });

    const callsAfter = mockApiGet.mock.calls
      .filter((c) => typeof c[0] === "string" && c[0].startsWith("/customers?"))
      .length;
    // No new /customers? fetch after onEndReached at the tail.
    expect(callsAfter).toBe(callsBefore);
  });
});
