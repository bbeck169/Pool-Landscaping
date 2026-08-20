/**
 * Portal Add-Card mobile flow — deployment-fix regression guard.
 *
 * These tests lock in the Feb-2026 fix for the mobile portal
 * ``payment-method.tsx`` screen after the two backing endpoints
 * (``/payments/method`` and ``/payments/setup-session``) were
 * deleted server-side.
 *
 *   1. Source-file guard: the two dead paths are ABSENT from the
 *      component file. No occurrence anywhere.
 *   2. On mount the component calls ``GET /customer-portal/payment-methods``.
 *   3. Tapping "Add card" first POSTs ``/payments/stripe/setup-intent``
 *      (preflight — validates auth + Stripe wiring).
 *   4. The URL passed to ``WebBrowser.openAuthSessionAsync`` never
 *      contains the literal ``/undefined``.
 *   5. After the browser session ends the methods list is refetched.
 */
import fs from "fs";
import path from "path";

import React from "react";
import { render, fireEvent, waitFor, act } from "@testing-library/react-native";
import * as WebBrowser from "expo-web-browser";

/* ── Hoisted mocks ─────────────────────────────────────────────── */

const mockApiGet = jest.fn();
const mockApiPost = jest.fn();

jest.mock("@/src/api", () => ({
  api: {
    get: (...a: any[]) => mockApiGet(...a),
    post: (...a: any[]) => mockApiPost(...a),
    put: jest.fn(),
    del: jest.fn(),
    delete: jest.fn(),
  },
  getAuthToken: jest.fn().mockResolvedValue("tok"),
}));

// expo-router's useFocusEffect boils down to a single-invocation
// useEffect for our purposes (no router mounted in this jest env).
jest.mock("expo-router", () => {
  const React = require("react");
  return {
    useFocusEffect: (cb: any) => React.useEffect(() => cb(), []),
    useRouter: () => ({ push: jest.fn(), replace: jest.fn(), back: jest.fn() }),
  };
});

jest.mock("expo-web-browser", () => ({
  openAuthSessionAsync: jest.fn(),
}));

// ``PrimaryButton`` / ``Header`` / ``Loading`` / ``Card`` are the
// mobile UI kit. Stub them to plain-RN so the test doesn't need
// theme/router context.
jest.mock("@/src/components/ui", () => {
  const React = require("react");
  const { Pressable, Text, View, ActivityIndicator } = require("react-native");
  return {
    Loading: () => React.createElement(ActivityIndicator, { testID: "loading" }),
    Card: ({ children, style }: any) => React.createElement(View, { style }, children),
    PrimaryButton: ({ title, onPress, testID, loading, disabled }: any) =>
      React.createElement(
        Pressable,
        {
          onPress,
          disabled: !!disabled || !!loading,
          testID,
          accessibilityState: { disabled: !!disabled || !!loading },
        },
        React.createElement(Text, {}, loading ? "Loading…" : title),
      ),
  };
});
jest.mock("@/src/components/widgets", () => {
  const React = require("react");
  const { View, Text } = require("react-native");
  return {
    Header: ({ title }: any) =>
      React.createElement(View, {}, React.createElement(Text, {}, title)),
  };
});

// Force a known backend host so the browser URL is deterministic.
const ORIGINAL_BASE = process.env.EXPO_PUBLIC_BACKEND_URL;
beforeAll(() => {
  process.env.EXPO_PUBLIC_BACKEND_URL = "https://poolscape-audit.preview.emergentagent.com";
});
afterAll(() => {
  process.env.EXPO_PUBLIC_BACKEND_URL = ORIGINAL_BASE;
});

import PaymentMethod from "@/app/portal/payment-method";

/* ── Static source-file assertions ─────────────────────────────── */

const SRC_PATH = path.resolve(
  __dirname,
  "..",
  "app",
  "portal",
  "payment-method.tsx",
);
const SOURCE = fs.readFileSync(SRC_PATH, "utf-8");

describe("Portal Add-Card mobile · source-file guards", () => {
  test("does NOT reference the deleted endpoint /payments/method", () => {
    // Line-comment history remains — we only care that the
    // executable code (non-comment lines) contains no call site.
    const codeOnly = SOURCE
      .split("\n")
      .filter((ln) => !/^\s*(?:\/\/|\*)/.test(ln))
      .join("\n");
    expect(codeOnly).not.toMatch(/["']\/payments\/method["']/);
    expect(codeOnly).not.toMatch(/api\.(get|post)\s*\(\s*["']\/payments\/method["']/);
  });

  test("does NOT reference the deleted endpoint /payments/setup-session", () => {
    const codeOnly = SOURCE
      .split("\n")
      .filter((ln) => !/^\s*(?:\/\/|\*)/.test(ln))
      .join("\n");
    expect(codeOnly).not.toMatch(/["']\/payments\/setup-session["']/);
  });

  test("uses the correct working endpoints", () => {
    expect(SOURCE).toMatch(/["']\/customer-portal\/payment-methods["']/);
    expect(SOURCE).toMatch(/["']\/payments\/stripe\/setup-intent["']/);
  });
});

/* ── Runtime behavior ──────────────────────────────────────────── */

beforeEach(() => {
  jest.clearAllMocks();
  mockApiGet.mockResolvedValue({
    methods: [],
    stripe_configured: true,
  });
  mockApiPost.mockResolvedValue({ client_secret: "seti_test_secret" });
  (WebBrowser.openAuthSessionAsync as jest.Mock).mockResolvedValue({ type: "dismiss" });
});


describe("Portal Add-Card mobile · runtime", () => {

  test("on mount fires GET /customer-portal/payment-methods (never /payments/method)", async () => {
    render(<PaymentMethod />);
    await waitFor(() => {
      expect(mockApiGet).toHaveBeenCalledWith("/customer-portal/payment-methods");
    });
    // Belt-and-suspenders: the dead path must NEVER be probed.
    const allGetCalls = mockApiGet.mock.calls.map((c) => c[0]);
    expect(allGetCalls).not.toContain("/payments/method");
  });

  test("empty-state shows 'No payment method on file'", async () => {
    const { findByTestId } = render(<PaymentMethod />);
    const summary = await findByTestId("pm-summary-label");
    expect(summary.props.children).toMatch(/No payment method on file/);
  });

  test("populated state shows brand + last4 for the default method", async () => {
    mockApiGet.mockResolvedValueOnce({
      methods: [
        { brand: "Visa", last4: "1111", is_default: false },
        { brand: "Mastercard", last4: "4444", is_default: true },
      ],
      stripe_configured: true,
    });
    const { findByTestId } = render(<PaymentMethod />);
    const summary = await findByTestId("pm-summary-label");
    expect(summary.props.children).toMatch(/MASTERCARD/);
    expect(summary.props.children).toMatch(/4444/);
  });

  test("Add-card tap triggers POST /payments/stripe/setup-intent (not /payments/setup-session)", async () => {
    const { findByTestId } = render(<PaymentMethod />);
    const btn = await findByTestId("add-payment-method");

    await act(async () => { fireEvent.press(btn); });

    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledWith("/payments/stripe/setup-intent", {});
    });
    // Regression guard — the dead path must NEVER be POSTed.
    const allPostCalls = mockApiPost.mock.calls.map((c) => c[0]);
    expect(allPostCalls).not.toContain("/payments/setup-session");
  });

  test("Add-card opens the web portal add-card page in expo-web-browser; URL contains no '/undefined'", async () => {
    const { findByTestId } = render(<PaymentMethod />);
    const btn = await findByTestId("add-payment-method");

    await act(async () => { fireEvent.press(btn); });

    await waitFor(() => {
      expect(WebBrowser.openAuthSessionAsync).toHaveBeenCalled();
    });
    const call = (WebBrowser.openAuthSessionAsync as jest.Mock).mock.calls[0];
    const openedUrl = String(call?.[0] || "");
    expect(openedUrl).toMatch(/\/portal\/payment-method$/);
    expect(openedUrl).not.toMatch(/\/undefined/);
    expect(openedUrl).toMatch(
      /^https:\/\/poolscape-audit\.preview\.emergentagent\.com\/portal\/payment-method$/,
    );
  });

  test("after browser session ends the methods list is refetched", async () => {
    const { findByTestId } = render(<PaymentMethod />);
    await waitFor(() => expect(mockApiGet).toHaveBeenCalledTimes(1));
    const btn = await findByTestId("add-payment-method");

    await act(async () => { fireEvent.press(btn); });

    await waitFor(() => {
      // 1 = mount, 2 = post-browser refetch.
      expect(mockApiGet).toHaveBeenCalledTimes(2);
      expect(mockApiGet).toHaveBeenLastCalledWith("/customer-portal/payment-methods");
    });
  });

  test("if setup-intent preflight fails, WebBrowser is NOT opened + user sees an alert", async () => {
    const RN = require("react-native");
    const alertSpy = jest.spyOn(RN.Alert, "alert").mockImplementation(() => {});
    mockApiPost.mockRejectedValueOnce(new Error("Stripe unavailable"));

    const { findByTestId } = render(<PaymentMethod />);
    const btn = await findByTestId("add-payment-method");
    await act(async () => { fireEvent.press(btn); });

    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledWith("/payments/stripe/setup-intent", {});
      expect(WebBrowser.openAuthSessionAsync).not.toHaveBeenCalled();
      expect(alertSpy).toHaveBeenCalled();
    });
    alertSpy.mockRestore();
  });
});
