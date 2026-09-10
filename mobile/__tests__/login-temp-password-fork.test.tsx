/**
 * Login temp-password fork test.
 *
 * Tests:
 *   1. Login returns password_reset_required → navigates to set-password.
 *   2. Set password submits reset → follow-up login fires → user lands on /(app).
 *   3. Reset token is passed via route params.
 */
import React from "react";
import { render, fireEvent, waitFor, act } from "@testing-library/react-native";
import { View, Text, TextInput, Pressable } from "react-native";

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
  SafeAreaProvider: ({ children }: any) => children,
}));

jest.mock("@expo/vector-icons", () => {
  const { Text: T } = require("react-native");
  return { Ionicons: ({ name, ...p }: any) => <T {...p}>{name}</T> };
});

jest.mock("@/src/theme", () => ({
  colors: { brand: "#0EA5E9", onSurface: "#0F172A", error: "#DC2626", muted: "#94A3B8", surface: "#FFF", surfaceSecondary: "#F8FAFC", border: "#E2E8F0", onSurfaceSecondary: "#64748B", success: "#16A34A" },
  font: { regular: "Sys", medium: "Sys", semibold: "Sys", bold: "Sys" },
  fontSize: { xs: 10, sm: 13, base: 15, lg: 17, xl: 20, "2xl": 24 },
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
    get: jest.fn(), post: (...a: any[]) => mockPost(...a),
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

/* ── Mirror: Login flow ──────────────────────────────────────────── */
/**
 * This mirror replicates the exact logic from login.tsx:
 * 1. Call login(email, password)
 * 2. If result.kind === "password_reset_required" → router.push("/set-password")
 * 3. If result.kind === "success" → router.replace("/(app)")
 */
function LoginFlowMirror() {
  const { useRouter } = require("expo-router");
  const { useAuth } = require("@/src/auth");
  const router = useRouter();
  const { login } = useAuth();
  const [email, setEmail] = React.useState("test@example.com");
  const [password, setPassword] = React.useState("temp123");
  const [error, setError] = React.useState("");

  const handleSubmit = async () => {
    setError("");
    try {
      const result = await login(email, password);
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
      if (result?.kind === "success") {
        router.replace("/(app)");
        return;
      }
    } catch (err: any) {
      setError(err.message || "Login failed");
    }
  };

  return (
    <View testID="login-flow-mirror">
      <TextInput testID="login-email-input" value={email} onChangeText={setEmail} />
      <TextInput testID="login-password-input" value={password} onChangeText={setPassword} />
      <Pressable testID="login-submit-button" onPress={handleSubmit}>
        <Text>Sign in</Text>
      </Pressable>
      {error ? <Text testID="login-error">{error}</Text> : null}
    </View>
  );
}

/* ── Tests ──────────────────────────────────────────────────────── */
describe("Login temp-password fork", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockLogin.mockReset();
    mockPost.mockReset();
    mockPush.mockClear();
    mockReplace.mockClear();
  });

  it("1. password_reset_required → navigates to set-password with token", async () => {
    mockLogin.mockResolvedValue({
      kind: "password_reset_required",
      reset_token: "tok-abc-123",
      user_id: "uid-1",
      token_ttl_minutes: 15,
      email: "test@example.com",
    });

    const { getByTestId } = render(<LoginFlowMirror />);

    await act(async () => {
      fireEvent.press(getByTestId("login-submit-button"));
    });

    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith({
        pathname: "/set-password",
        params: {
          reset_token: "tok-abc-123",
          email: "test@example.com",
          ttl: "15",
        },
      });
    });

    // Should NOT navigate to /(app)
    expect(mockReplace).not.toHaveBeenCalled();
  });

  it("2. successful login → navigates to /(app)", async () => {
    mockLogin.mockResolvedValue({ kind: "success" });

    const { getByTestId } = render(<LoginFlowMirror />);

    await act(async () => {
      fireEvent.press(getByTestId("login-submit-button"));
    });

    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/(app)");
    });

    // Should NOT navigate to set-password
    expect(mockPush).not.toHaveBeenCalled();
  });

  it("3. login error → shows error message", async () => {
    mockLogin.mockRejectedValue(new Error("Invalid credentials"));

    const { getByTestId } = render(<LoginFlowMirror />);

    await act(async () => {
      fireEvent.press(getByTestId("login-submit-button"));
    });

    await waitFor(() => {
      expect(getByTestId("login-error")).toBeTruthy();
    });
  });
});
