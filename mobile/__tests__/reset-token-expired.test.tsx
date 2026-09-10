/**
 * Reset token expired test.
 *
 * Tests:
 *   1. Token expired error → friendly alert + return to login.
 *   2. Normal API error → inline error message.
 *   3. Empty password → validation error.
 *   4. Passwords don't match → validation error.
 */
import React from "react";
import { render, fireEvent, waitFor, act } from "@testing-library/react-native";
import { Alert } from "react-native";

/* ── Mocks ────────────────────────────────────────────────────────── */
const mockPush = jest.fn();
const mockReplace = jest.fn();
jest.mock("expo-router", () => ({
  useRouter: () => ({ push: mockPush, replace: mockReplace, back: jest.fn(), canGoBack: () => true }),
  useLocalSearchParams: () => ({
    reset_token: "expired-tok",
    email: "test@example.com",
    ttl: "15",
  }),
  Redirect: () => null,
}));

jest.mock("react-native-safe-area-context", () => ({
  useSafeAreaInsets: () => ({ top: 44, bottom: 34, left: 0, right: 0 }),
}));

jest.mock("@expo/vector-icons", () => {
  const { Text: T } = require("react-native");
  return { Ionicons: ({ name, ...p }: any) => <T {...p}>{name}</T> };
});

jest.mock("@/src/theme", () => ({
  colors: { brand: "#0EA5E9", onSurface: "#0F172A", error: "#DC2626", muted: "#94A3B8", surface: "#FFF", surfaceSecondary: "#F8FAFC", border: "#E2E8F0", onSurfaceSecondary: "#64748B", success: "#16A34A" },
  font: { regular: "Sys", medium: "Sys", semibold: "Sys", bold: "Sys" },
  fontSize: { xs: 10, sm: 13, base: 15, lg: 17, xl: 20 },
  spacing: { xs: 4, sm: 8, md: 12, lg: 16, xl: 20 },
  radius: { sm: 6, md: 10, lg: 14, pill: 999 },
}));

const mockLogin = jest.fn();
const mockPost = jest.fn();

jest.mock("@/src/auth", () => ({
  useAuth: () => ({
    login: mockLogin,
    user: null,
    finalizeAccountChoice: jest.fn(),
    logout: jest.fn(),
  }),
}));

jest.mock("@/src/api", () => ({
  api: {
    get: jest.fn(),
    post: (...a: any[]) => mockPost(...a),
    patch: jest.fn(), put: jest.fn(), del: jest.fn(),
  },
}));

jest.mock("@/src/components/ui", () => {
  const { Pressable: P, Text: T } = require("react-native");
  return {
    PrimaryButton: ({ title, onPress, testID, disabled }: any) => (
      <P testID={testID} onPress={onPress} disabled={disabled}><T>{title}</T></P>
    ),
    Loading: () => null,
    EmptyState: () => null,
  };
});

jest.mock("react-native-keyboard-controller", () => {
  const { ScrollView } = require("react-native");
  return { KeyboardAwareScrollView: ScrollView };
});

import SetPasswordScreen from "../app/set-password";


/* ── Tests ──────────────────────────────────────────────────────── */
describe("Reset token expired", () => {
  let alertSpy: jest.SpyInstance;

  beforeEach(() => {
    jest.clearAllMocks();
    mockPost.mockReset();
    mockLogin.mockReset();
    mockReplace.mockClear();
    // Spy on Alert.alert to verify the friendly message
    alertSpy = jest.spyOn(Alert, "alert").mockImplementation(() => {});
  });

  afterEach(() => {
    alertSpy.mockRestore();
  });

  it("1. token expired error → friendly alert", async () => {
    mockPost.mockRejectedValue(new Error("Token expired or invalid"));

    const { getByTestId } = render(<SetPasswordScreen />);

    // Fill in passwords
    fireEvent.changeText(getByTestId("set-password-input"), "newpass123");
    fireEvent.changeText(getByTestId("set-password-confirm-input"), "newpass123");

    await act(async () => {
      fireEvent.press(getByTestId("set-password-submit"));
    });

    await waitFor(() => {
      expect(alertSpy).toHaveBeenCalledWith(
        "Link expired",
        expect.stringContaining("expired"),
        expect.any(Array),
      );
    });
  });

  it("2. non-expired error → inline error message", async () => {
    mockPost.mockRejectedValue(new Error("Server error: 500"));

    const { getByTestId } = render(<SetPasswordScreen />);

    fireEvent.changeText(getByTestId("set-password-input"), "newpass123");
    fireEvent.changeText(getByTestId("set-password-confirm-input"), "newpass123");

    await act(async () => {
      fireEvent.press(getByTestId("set-password-submit"));
    });

    await waitFor(() => {
      expect(getByTestId("set-password-error")).toBeTruthy();
    });

    // Alert NOT called for non-token errors
    expect(alertSpy).not.toHaveBeenCalled();
  });

  it("3. short password → validation error", async () => {
    const { getByTestId } = render(<SetPasswordScreen />);

    fireEvent.changeText(getByTestId("set-password-input"), "ab");
    fireEvent.changeText(getByTestId("set-password-confirm-input"), "ab");

    await act(async () => {
      fireEvent.press(getByTestId("set-password-submit"));
    });

    await waitFor(() => {
      const err = getByTestId("set-password-error");
      expect(err.children.join("")).toContain("6 characters");
    });

    // API was NOT called
    expect(mockPost).not.toHaveBeenCalled();
  });

  it("4. mismatched passwords → validation error", async () => {
    const { getByTestId } = render(<SetPasswordScreen />);

    fireEvent.changeText(getByTestId("set-password-input"), "newpass123");
    fireEvent.changeText(getByTestId("set-password-confirm-input"), "differentpass");

    await act(async () => {
      fireEvent.press(getByTestId("set-password-submit"));
    });

    await waitFor(() => {
      const err = getByTestId("set-password-error");
      expect(err.children.join("")).toContain("match");
    });

    expect(mockPost).not.toHaveBeenCalled();
  });

  it("5. successful reset → silent re-login → /(app)", async () => {
    mockPost.mockResolvedValue({ ok: true, message: "Password reset." });
    mockLogin.mockResolvedValue({ kind: "success" });

    const { getByTestId } = render(<SetPasswordScreen />);

    fireEvent.changeText(getByTestId("set-password-input"), "permanent123");
    fireEvent.changeText(getByTestId("set-password-confirm-input"), "permanent123");

    await act(async () => {
      fireEvent.press(getByTestId("set-password-submit"));
    });

    // Reset was called
    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith("/auth/reset-password", {
        token: "expired-tok",
        new_password: "permanent123",
      });
    });

    // Silent re-login
    expect(mockLogin).toHaveBeenCalledWith("test@example.com", "permanent123");

    // Redirected to app
    expect(mockReplace).toHaveBeenCalledWith("/(app)");
  });
});
