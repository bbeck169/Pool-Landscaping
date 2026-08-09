/**
 * Phase 41.5c · Feb-2026 — Mobile RingCentral settings render test.
 *
 * Boots the ``app/settings/ringcentral.tsx`` screen with every
 * native dep mocked. Covers:
 *   1. Admin/super_admin sees the form pre-populated from GET
 *      /settings/ringcentral (api_key input is always empty because
 *      the backend never returns it).
 *   2. Technician + customer hit the "Admin only" role gate — no
 *      fetch is issued.
 *   3. Editing account_id + api_key + tapping save fires PUT with
 *      the exact patch shape the backend accepts (masked api_key
 *      is only sent when the user typed a new value).
 *   4. If the user does NOT rotate the api_key, the PUT payload
 *      omits ``api_key`` entirely (avoids clobbering the stored
 *      value with an empty string).
 */
import React from "react";
import { render, waitFor, act, fireEvent } from "@testing-library/react-native";

jest.setTimeout(15000);

// ── Mocks ────────────────────────────────────────────────────────────
const mockApiGet = jest.fn();
const mockApiPut = jest.fn();
jest.mock("@/src/api", () => ({
  api: {
    get: (...a: any[]) => mockApiGet(...a),
    put: (...a: any[]) => mockApiPut(...a),
  },
}));

let mockUserRole: any = { id: "u_admin", role: "admin", email: "a@ex.com" };
jest.mock("@/src/auth", () => ({
  useAuth: () => ({ user: mockUserRole }),
}));

// Stub the shared ``Header`` — it pulls expo-router + safe-area
// insets. Keep the rest of the RN surface real.
jest.mock("@/src/components/widgets", () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const ReactMock = require("react");
  const RN = jest.requireActual("react-native");
  return {
    Header: ({ title }: { title: string }) =>
      ReactMock.createElement(RN.Text, { testID: "test-header" }, title),
  };
});

// expo-router's ``useFocusEffect`` requires a real navigation
// container at runtime — stub it to run the callback on mount only.
jest.mock("expo-router", () => ({
  useFocusEffect: (cb: any) => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const ReactMock = require("react");
    ReactMock.useEffect(() => {
      const teardown = cb();
      return typeof teardown === "function" ? teardown : undefined;
    }, [cb]);
  },
}));

// react-native Alert — spy on the real Alert.alert to avoid dragging
// TurboModule shims into the jest env.
// eslint-disable-next-line import/first
import { Alert as RNAlert } from "react-native";
const mockAlert = jest.spyOn(RNAlert, "alert").mockImplementation(() => {});

// eslint-disable-next-line import/first
import RingCentralSettings from "@/app/settings/ringcentral";

beforeEach(() => {
  mockApiGet.mockReset();
  mockApiPut.mockReset();
  mockAlert.mockReset();
  mockUserRole = { id: "u_admin", role: "admin", email: "a@ex.com" };
});

describe("Phase 41.5c · mobile RingCentral settings", () => {
  it("admin sees the form pre-populated from GET /settings/ringcentral", async () => {
    mockApiGet.mockResolvedValueOnce({
      webhook_url: "https://tenants.example/api/ringcentral/webhook",
      account_id: "~999999",
      configured: true,
    });
    const { getByTestId } = render(<RingCentralSettings />);
    await waitFor(() => expect(mockApiGet).toHaveBeenCalledTimes(1));
    expect(mockApiGet.mock.calls[0][0]).toBe("/settings/ringcentral");

    await waitFor(() =>
      expect(getByTestId("ringcentral-settings-form")).toBeTruthy());
    // Webhook + account inputs carry the GET values verbatim.
    expect(getByTestId("ringcentral-settings-input-webhook_url").props.value)
      .toBe("https://tenants.example/api/ringcentral/webhook");
    expect(getByTestId("ringcentral-settings-input-account_id").props.value)
      .toBe("~999999");
    // api_key input is ALWAYS empty (the backend never returns it).
    expect(getByTestId("ringcentral-settings-input-api_key").props.value)
      .toBe("");
    // "configured" hint is shown.
    expect(getByTestId("ringcentral-settings-configured")).toBeTruthy();
  });

  it("shows the 'not configured' hint when the tenant has never saved a key", async () => {
    mockApiGet.mockResolvedValueOnce({ configured: false });
    const { getByTestId } = render(<RingCentralSettings />);
    await waitFor(() => expect(mockApiGet).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(getByTestId("ringcentral-settings-not-configured")).toBeTruthy());
  });

  it("technician sees the role gate and no fetch runs", async () => {
    mockUserRole = { id: "u_t", role: "technician", email: "t@ex.com" };
    const { getByTestId, queryByTestId } = render(<RingCentralSettings />);
    expect(getByTestId("ringcentral-settings-role-gate")).toBeTruthy();
    expect(queryByTestId("ringcentral-settings-screen")).toBeNull();
    expect(mockApiGet).not.toHaveBeenCalled();
  });

  it("customer sees the role gate too", () => {
    mockUserRole = { id: "u_c", role: "customer", email: "c@ex.com" };
    const { getByTestId } = render(<RingCentralSettings />);
    expect(getByTestId("ringcentral-settings-role-gate")).toBeTruthy();
    expect(mockApiGet).not.toHaveBeenCalled();
  });

  it("super_admin can also load the form", async () => {
    mockUserRole = { id: "u_sa", role: "super_admin", email: "s@ex.com" };
    mockApiGet.mockResolvedValueOnce({ webhook_url: "", account_id: "", configured: false });
    const { getByTestId } = render(<RingCentralSettings />);
    await waitFor(() => expect(mockApiGet).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(getByTestId("ringcentral-settings-form")).toBeTruthy());
  });

  it("edit + save posts PUT with webhook/account/api_key and toasts success", async () => {
    mockApiGet.mockResolvedValueOnce({
      webhook_url: "https://old.example/hook",
      account_id: "~111111",
      configured: true,
    });
    mockApiPut.mockResolvedValueOnce({
      webhook_url: "https://old.example/hook",
      account_id: "~222222",
      configured: true,
    });
    const { getByTestId } = render(<RingCentralSettings />);
    await waitFor(() => expect(mockApiGet).toHaveBeenCalledTimes(1));
    await waitFor(() => getByTestId("ringcentral-settings-form"));

    await act(async () => {
      fireEvent.changeText(getByTestId("ringcentral-settings-input-account_id"), "~222222");
    });
    await act(async () => {
      fireEvent.changeText(getByTestId("ringcentral-settings-input-api_key"), "rc_new_secret");
    });
    await act(async () => {
      fireEvent.press(getByTestId("ringcentral-settings-save-btn"));
    });

    await waitFor(() => expect(mockApiPut).toHaveBeenCalledTimes(1));
    expect(mockApiPut.mock.calls[0][0]).toBe("/settings/ringcentral");
    const body = mockApiPut.mock.calls[0][1];
    expect(body.webhook_url).toBe("https://old.example/hook");
    expect(body.account_id).toBe("~222222");
    expect(body.api_key).toBe("rc_new_secret");

    // Toast confirms.
    await waitFor(() => expect(mockAlert).toHaveBeenCalledTimes(1));
    expect(mockAlert.mock.calls[0][0]).toBe("Saved");
    expect(mockAlert.mock.calls[0][1]).toMatch(/RingCentral/i);
  });

  it("save without typing a new api_key omits ``api_key`` from the PUT payload", async () => {
    mockApiGet.mockResolvedValueOnce({
      webhook_url: "https://old.example/hook",
      account_id: "~111111",
      configured: true,
    });
    mockApiPut.mockResolvedValueOnce({
      webhook_url: "https://new.example/hook",
      account_id: "~111111",
      configured: true,
    });
    const { getByTestId } = render(<RingCentralSettings />);
    await waitFor(() => expect(mockApiGet).toHaveBeenCalledTimes(1));
    await waitFor(() => getByTestId("ringcentral-settings-form"));

    await act(async () => {
      fireEvent.changeText(getByTestId("ringcentral-settings-input-webhook_url"),
                            "https://new.example/hook");
    });
    await act(async () => {
      fireEvent.press(getByTestId("ringcentral-settings-save-btn"));
    });

    await waitFor(() => expect(mockApiPut).toHaveBeenCalledTimes(1));
    const body = mockApiPut.mock.calls[0][1];
    expect(body.webhook_url).toBe("https://new.example/hook");
    expect(body.account_id).toBe("~111111");
    // Critical: no ``api_key`` field so backend keeps the stored value.
    expect(Object.prototype.hasOwnProperty.call(body, "api_key")).toBe(false);
  });

  it("save failure surfaces an error alert without crashing", async () => {
    mockApiGet.mockResolvedValueOnce({ webhook_url: "", account_id: "", configured: false });
    mockApiPut.mockRejectedValueOnce(new Error("boom"));
    const { getByTestId } = render(<RingCentralSettings />);
    await waitFor(() => expect(mockApiGet).toHaveBeenCalledTimes(1));
    await waitFor(() => getByTestId("ringcentral-settings-form"));

    await act(async () => {
      fireEvent.press(getByTestId("ringcentral-settings-save-btn"));
    });
    await waitFor(() => expect(mockAlert).toHaveBeenCalledTimes(1));
    expect(mockAlert.mock.calls[0][0]).toBe("Error");
    expect(mockAlert.mock.calls[0][1]).toMatch(/boom/);
  });
});
