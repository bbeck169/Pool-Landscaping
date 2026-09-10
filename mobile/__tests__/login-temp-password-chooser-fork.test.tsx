/**
 * Login temp-password + chooser fork test.
 *
 * Tests:
 *   1. Account chooser → select account → password_reset_required →
 *      navigates to set-password.
 *   2. Account chooser → select account → success → navigates to /(app).
 */
import React from "react";
import { render, fireEvent, waitFor, act } from "@testing-library/react-native";
import { View, Text, Pressable } from "react-native";

/* ── Mocks ────────────────────────────────────────────────────────── */
const mockPush = jest.fn();
const mockReplace = jest.fn();
jest.mock("expo-router", () => ({
  useRouter: () => ({ push: mockPush, replace: mockReplace, back: jest.fn(), canGoBack: () => true }),
  useLocalSearchParams: jest.fn(() => ({})),
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
  colors: { brand: "#0EA5E9", onSurface: "#0F172A", error: "#DC2626", muted: "#94A3B8", surface: "#FFF", surfaceSecondary: "#F8FAFC", border: "#E2E8F0", onSurfaceSecondary: "#64748B" },
  font: { regular: "Sys", medium: "Sys", semibold: "Sys", bold: "Sys" },
  fontSize: { xs: 10, sm: 13, base: 15, lg: 17, xl: 20 },
  spacing: { xs: 4, sm: 8, md: 12, lg: 16, xl: 20 },
  radius: { sm: 6, md: 10, lg: 14, pill: 999 },
}));

const mockFinalizeChoice = jest.fn();
jest.mock("@/src/auth", () => ({
  useAuth: () => ({
    login: jest.fn(),
    finalizeAccountChoice: mockFinalizeChoice,
    user: null,
    logout: jest.fn(),
  }),
}));

jest.mock("@/src/api", () => ({
  api: { get: jest.fn(), post: jest.fn(), patch: jest.fn(), put: jest.fn(), del: jest.fn() },
}));

/**
 * Mirror of the login.tsx chooser → pickAccount flow.
 */
function ChooserFlowMirror({ choices, choiceToken, email }: { choices: any[]; choiceToken: string; email: string }) {
  const { useRouter } = require("expo-router");
  const { useAuth } = require("@/src/auth");
  const router = useRouter();
  const { finalizeAccountChoice } = useAuth();
  const [error, setError] = React.useState("");

  const pickAccount = async (accountId: string) => {
    setError("");
    try {
      const result = await finalizeAccountChoice(choiceToken, accountId);
      if (result?.kind === "password_reset_required") {
        router.push({
          pathname: "/set-password",
          params: {
            reset_token: result.reset_token,
            email,
            ttl: String(result.token_ttl_minutes || 15),
          },
        });
        return;
      }
      router.replace("/(app)");
    } catch (err: any) {
      setError(err.message || "Error");
    }
  };

  return (
    <View testID="chooser-flow-mirror">
      {choices.map((c: any) => (
        <Pressable
          key={c.id}
          testID={`chooser-account-${c.id}`}
          onPress={() => pickAccount(c.id)}
        >
          <Text>{c.name}</Text>
        </Pressable>
      ))}
      {error ? <Text testID="chooser-error">{error}</Text> : null}
    </View>
  );
}

/* ── Tests ──────────────────────────────────────────────────────── */
describe("Login temp-password chooser fork", () => {
  const CHOICES = [
    { id: "acct-admin", name: "Admin Account", role: "admin" },
    { id: "acct-cust", name: "Customer Account", role: "customer" },
  ];

  beforeEach(() => {
    jest.clearAllMocks();
    mockFinalizeChoice.mockReset();
    mockPush.mockClear();
    mockReplace.mockClear();
  });

  it("1. chooser → select → password_reset_required → set-password", async () => {
    mockFinalizeChoice.mockResolvedValue({
      kind: "password_reset_required",
      reset_token: "chooser-tok-99",
      user_id: "uid-cust",
      token_ttl_minutes: 15,
    });

    const { getByTestId } = render(
      <ChooserFlowMirror
        choices={CHOICES}
        choiceToken="ct-xyz"
        email="brian@example.com"
      />,
    );

    await act(async () => {
      fireEvent.press(getByTestId("chooser-account-acct-cust"));
    });

    await waitFor(() => {
      expect(mockFinalizeChoice).toHaveBeenCalledWith("ct-xyz", "acct-cust");
      expect(mockPush).toHaveBeenCalledWith({
        pathname: "/set-password",
        params: expect.objectContaining({
          reset_token: "chooser-tok-99",
          email: "brian@example.com",
        }),
      });
    });

    expect(mockReplace).not.toHaveBeenCalled();
  });

  it("2. chooser → select → success → /(app)", async () => {
    mockFinalizeChoice.mockResolvedValue({ kind: "success" });

    const { getByTestId } = render(
      <ChooserFlowMirror
        choices={CHOICES}
        choiceToken="ct-xyz"
        email="brian@example.com"
      />,
    );

    await act(async () => {
      fireEvent.press(getByTestId("chooser-account-acct-admin"));
    });

    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/(app)");
    });

    expect(mockPush).not.toHaveBeenCalled();
  });
});
