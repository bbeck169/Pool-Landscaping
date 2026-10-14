/**
 * P2 #11 mobile parity — Email Builder Commit 2: hardened test-send.
 *
 *  A. pure helpers — parseRetryAfter (ceil), interpretTestSend (200 / 400 /
 *     403 / 429 / 404 / 5xx), sentToastCopy (recipient always named)
 *  B. postTemplateTestSend — direct fetch: URL, bearer, body shape, and
 *     the Retry-After header surfaced (the whole reason it's raw fetch)
 *  C. EmailTestSendPanel — default recipient, success toast + 2s
 *     cooldown, 429 countdown disables button, 400 msg verbatim,
 *     403 generic, network error
 *  D. detail screen mounts the panel for email templates only
 */
import React from "react";
import { render, fireEvent, act, waitFor } from "@testing-library/react-native";

/* ── mocks ─────────────────────────────────────────────────────── */
jest.mock("@/src/api", () => ({
  api_base: () => "https://be.test/api",
  getAuthToken: jest.fn(async () => "tok-123"),
}));
let mockRole = "admin";
jest.mock("@/src/auth", () => ({
  useAuth: () => ({ user: { id: "u1", role: mockRole, email: "admin@aquaterra.com" } }),
}));
const mockToast = jest.fn();
jest.mock("@/src/components/ToastProvider", () => ({ useToast: () => ({ showToast: mockToast }) }));

let mockParams: any = { code: "system.appointment_reminder", channel: "email" };
jest.mock("expo-router", () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn() }),
  useLocalSearchParams: () => mockParams,
  useFocusEffect: (cb: any) => require("react").useEffect(() => { cb(); }, [cb]),
}));
jest.mock("react-native-safe-area-context", () => ({
  useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }),
}));
jest.mock("@/src/components/widgets", () => {
  const RN = require("react-native");
  return { Header: (p: any) => <RN.View>{p.right}</RN.View> };
});
jest.mock("react-native-webview", () => ({ WebView: () => null }));
jest.mock("@/src/api/comms", () => ({
  getEmailTemplate: jest.fn(async () => ({ code: "system.appointment_reminder", name: "Appt", subject: "S", blocks_json: [] })),
  getSmsTemplate: jest.fn(async () => ({ code: "sms.x", name: "SMS", body: "hi" })),
  previewEmailTemplate: jest.fn(),
  previewSmsTemplate: jest.fn(),
}));

import EmailTestSendPanel, {
  parseRetryAfter,
  interpretTestSend,
  sentToastCopy,
  postTemplateTestSend,
} from "@/src/components/comms/EmailTestSendPanel";
import CommsTemplateDetailScreen from "@/app/(app)/comms/templates/[code]";

const resp = (status: number, body: any, headers: Record<string, string> = {}) => ({
  status,
  json: async () => body,
  headers: { get: (k: string) => headers[k] ?? headers[k.toLowerCase()] ?? null },
});
const fetchMock = jest.fn();
beforeEach(() => {
  fetchMock.mockReset();
  (global as any).fetch = fetchMock;
  mockToast.mockReset();
  mockRole = "admin";
  mockParams = { code: "system.appointment_reminder", channel: "email" };
});
afterEach(() => jest.useRealTimers());

/* ── A. helpers ────────────────────────────────────────────────── */
describe("test-send helpers", () => {
  it("parseRetryAfter ceils seconds; HTTP-date; fallback 60", () => {
    expect(parseRetryAfter("42")).toBe(42);
    expect(parseRetryAfter("41.2")).toBe(42);
    expect(parseRetryAfter("0")).toBe(1);
    const now = Date.parse("2026-10-14T00:00:00Z");
    expect(parseRetryAfter("Wed, 14 Oct 2026 00:00:30 GMT", now)).toBe(30);
    expect(parseRetryAfter("soon")).toBe(60);
    expect(parseRetryAfter(null)).toBe(60);
  });

  it("interpretTestSend maps every status", () => {
    expect(interpretTestSend({ status: 200, body: { recipient: "a@x.com", status: "sent" }, retryAfter: null }))
      .toEqual({ kind: "sent", recipient: "a@x.com", deliveryStatus: "sent" });
    const notAllowed = { detail: { code: "test_recipient_not_allowed", msg: "Test-send recipient must be the caller or another admin…" } };
    expect(interpretTestSend({ status: 400, body: notAllowed, retryAfter: null }))
      .toEqual({ kind: "error", message: notAllowed.detail.msg });
    const forbidden = interpretTestSend({ status: 403, body: { detail: "roles admin,super_admin required" }, retryAfter: null });
    expect(forbidden).toEqual({ kind: "error", message: "Admin access required" });
    expect(interpretTestSend({ status: 429, body: {}, retryAfter: "17.4" }))
      .toEqual({ kind: "rate_limited", retryAfterS: 18, message: "Rate limit reached — try again in 18s" });
    expect(interpretTestSend({ status: 404, body: null, retryAfter: null }).kind).toBe("error");
    expect(interpretTestSend({ status: 502, body: null, retryAfter: null }))
      .toEqual({ kind: "error", message: "Test send failed (502)" });
  });

  it("sentToastCopy always names the recipient", () => {
    expect(sentToastCopy({ recipient: "a@x.com", deliveryStatus: "sent" })).toEqual({ msg: "Sent to a@x.com", variant: "success" });
    expect(sentToastCopy({ recipient: "a@x.com", deliveryStatus: null }).msg).toBe("Sent to a@x.com");
    expect(sentToastCopy({ recipient: "a@x.com", deliveryStatus: "suppressed_not_demo" }))
      .toEqual({ msg: "Sent to a@x.com — delivery suppressed not demo", variant: "info" });
    expect(sentToastCopy({ recipient: "a@x.com", deliveryStatus: "failed" }).variant).toBe("error");
  });
});

/* ── B. direct fetch ───────────────────────────────────────────── */
describe("postTemplateTestSend (direct fetch)", () => {
  it("POSTs with bearer + {to}; surfaces Retry-After", async () => {
    fetchMock.mockResolvedValueOnce(resp(429, { detail: { code: "test_send_rate_limited" } }, { "Retry-After": "120" }));
    const r = await postTemplateTestSend("system.a b", "peer@x.com");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("https://be.test/api/comms/email-templates/system.a%20b/test-send");
    expect(init.method).toBe("POST");
    expect(init.headers.Authorization).toBe("Bearer tok-123");
    expect(JSON.parse(init.body)).toEqual({ to: "peer@x.com" });
    expect(r).toEqual({ status: 429, body: { detail: { code: "test_send_rate_limited" } }, retryAfter: "120" });
  });

  it("empty recipient → {} body (server defaults to caller)", async () => {
    fetchMock.mockResolvedValueOnce(resp(200, { recipient: "admin@aquaterra.com" }));
    await postTemplateTestSend("c");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({});
  });
});

/* ── C. panel ──────────────────────────────────────────────────── */
describe("EmailTestSendPanel", () => {
  it("defaults to the caller's email; success → toast 'Sent to …' + 2s cooldown", async () => {
    jest.useFakeTimers();
    fetchMock.mockResolvedValueOnce(resp(200, { status: "sent", recipient: "admin@aquaterra.com" }));
    const { getByTestId } = render(<EmailTestSendPanel code="system.appointment_reminder" />);
    expect(getByTestId("comms-email-test-send-input").props.value).toBe("admin@aquaterra.com");

    await act(async () => { fireEvent.press(getByTestId("comms-email-test-send-submit")); });
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ to: "admin@aquaterra.com" });
    expect(mockToast).toHaveBeenCalledWith("Sent to admin@aquaterra.com", "success");
    expect(getByTestId("comms-email-test-send-message").props.children).toBe("Sent to admin@aquaterra.com");
    expect(getByTestId("comms-email-test-send-submit").props.accessibilityState.disabled).toBe(true);
    await act(async () => { jest.advanceTimersByTime(2000); });
    expect(getByTestId("comms-email-test-send-submit").props.accessibilityState.disabled).toBe(false);
  });

  it("429 → 'Retry in Ns' countdown (ceil) with the button disabled until it ends", async () => {
    jest.useFakeTimers();
    fetchMock.mockResolvedValueOnce(resp(429, { detail: { code: "test_send_rate_limited", msg: "Rate limit" } }, { "Retry-After": "2.3" }));
    const { getByTestId } = render(<EmailTestSendPanel code="c" />);
    await act(async () => { fireEvent.press(getByTestId("comms-email-test-send-submit")); });

    const label = () => getByTestId("comms-email-test-send-label").props.children;
    const disabled = () => getByTestId("comms-email-test-send-submit").props.accessibilityState.disabled;
    expect(label()).toBe("Retry in 3s");
    expect(disabled()).toBe(true);
    expect(mockToast).toHaveBeenCalledWith("Rate limit reached — try again in 3s", "error");

    fireEvent.press(getByTestId("comms-email-test-send-submit")); // ignored while disabled
    expect(fetchMock).toHaveBeenCalledTimes(1);

    await act(async () => { jest.advanceTimersByTime(1000); });
    expect(label()).toBe("Retry in 2s");
    await act(async () => { jest.advanceTimersByTime(2000); });
    expect(label()).toBe("Send test");
    expect(disabled()).toBe(false);
  });

  it("400 test_recipient_not_allowed → backend msg surfaced verbatim", async () => {
    const msg = "Test-send recipient must be the caller or another admin/super_admin/owner/manager user in the same tenant.";
    fetchMock.mockResolvedValueOnce(resp(400, { detail: { code: "test_recipient_not_allowed", msg } }));
    const { getByTestId } = render(<EmailTestSendPanel code="c" />);
    fireEvent.changeText(getByTestId("comms-email-test-send-input"), "stranger@example.com");
    await act(async () => { fireEvent.press(getByTestId("comms-email-test-send-submit")); });
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ to: "stranger@example.com" });
    expect(getByTestId("comms-email-test-send-message").props.children).toBe(msg);
    expect(mockToast).toHaveBeenCalledWith(msg, "error");
  });

  it("403 → generic message, server body not echoed", async () => {
    fetchMock.mockResolvedValueOnce(resp(403, { detail: "role=manager not in {admin,super_admin}" }));
    const { getByTestId } = render(<EmailTestSendPanel code="c" />);
    await act(async () => { fireEvent.press(getByTestId("comms-email-test-send-submit")); });
    expect(getByTestId("comms-email-test-send-message").props.children).toBe("Admin access required");
    expect(JSON.stringify(mockToast.mock.calls)).not.toContain("role=manager");
  });

  it("network failure → friendly error, button re-enabled", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("Network request failed"));
    const { getByTestId } = render(<EmailTestSendPanel code="c" />);
    await act(async () => { fireEvent.press(getByTestId("comms-email-test-send-submit")); });
    expect(getByTestId("comms-email-test-send-message").props.children).toMatch(/Network error/);
    expect(getByTestId("comms-email-test-send-submit").props.accessibilityState.disabled).toBe(false);
  });
});

/* ── D. detail screen mount ────────────────────────────────────── */
describe("template detail · test-send mount", () => {
  it("email template → panel rendered", async () => {
    const { findByTestId } = render(<CommsTemplateDetailScreen />);
    expect(await findByTestId("comms-email-test-send-panel")).toBeTruthy();
  });

  it("sms template → no panel", async () => {
    mockParams = { code: "sms.x", channel: "sms" };
    const { findByTestId, queryByTestId } = render(<CommsTemplateDetailScreen />);
    await findByTestId("comms-template-detail");
    await waitFor(() => expect(queryByTestId("comms-email-test-send-panel")).toBeNull());
  });
});
