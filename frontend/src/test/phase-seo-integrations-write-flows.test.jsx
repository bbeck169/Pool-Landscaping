/**
 * Sep-2026 · DataForSEO card · Save + Test + Remove flows.
 *
 * Consolidated to keep the test suite compact while covering all 3
 * write-path flows against mocked ``@/api``.
 */
import React from "react";
import { render, screen, waitFor, fireEvent, act } from "@testing-library/react";
import "@testing-library/jest-dom";
import { vi, describe, it, expect, beforeEach } from "vitest";
import { I18nextProvider } from "react-i18next";
import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import commonEN from "../i18n/locales/en/common.json";

const apiGetMock = vi.fn();
const apiPutMock = vi.fn();
const apiPostMock = vi.fn();
const apiDeleteMock = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get:    (...a) => apiGetMock(...a),
    put:    (...a) => apiPutMock(...a),
    post:   (...a) => apiPostMock(...a),
    delete: (...a) => apiDeleteMock(...a),
  },
}));

// sonner toast — silence it in tests.
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

beforeEach(async () => {
  apiGetMock.mockReset();
  apiPutMock.mockReset();
  apiPostMock.mockReset();
  apiDeleteMock.mockReset();
  if (!i18n.isInitialized) {
    await i18n.use(initReactI18next).init({
      lng: "en", fallbackLng: "en",
      resources: { en: { common: commonEN } },
      interpolation: { escapeValue: false },
      react: { useSuspense: false },
    });
  }
});

async function _render() {
  const { default: Card } = await import("../components/settings/DataForSEOIntegrationCard");
  return render(
    <I18nextProvider i18n={i18n}>
      <Card />
    </I18nextProvider>,
  );
}

describe("DataForSEOIntegrationCard · write flows (SP3-DFS)", () => {
  it("Save fires PUT with correct payload and rerenders as configured", async () => {
    apiGetMock.mockResolvedValueOnce({ configured: false, login_masked: null });
    apiPutMock.mockResolvedValue({
      configured: true, login_masked: "bri***@plofv.com",
      configured_at: "2026-09-17T05:00:00Z",
    });
    await _render();
    await waitFor(() => expect(apiGetMock).toHaveBeenCalled());
    fireEvent.change(screen.getByTestId("dfs-login-input"),
                       { target: { value: "brian@plofv.com" } });
    fireEvent.change(screen.getByTestId("dfs-password-input"),
                       { target: { value: "secret-token-123" } });
    await act(async () => {
      fireEvent.click(screen.getByTestId("dfs-save-btn"));
    });
    await waitFor(() => expect(apiPutMock).toHaveBeenCalled());
    const [url, payload] = apiPutMock.mock.calls[0];
    expect(url).toBe("/tenants/me/integrations/dataforseo");
    expect(payload).toEqual({ login: "brian@plofv.com", password: "secret-token-123" });
    // Now shows configured state + masked login.
    await waitFor(() => expect(screen.getByTestId("dfs-login-masked")).toBeInTheDocument());
    expect(screen.getByTestId("dfs-status-pill")).toHaveTextContent(/Configured/i);
  });

  it("Test Connection fires POST and renders latency on success", async () => {
    apiGetMock.mockResolvedValue({
      configured: true, login_masked: "bri***@plofv.com",
      last_verified_at: null,
    });
    apiPostMock.mockResolvedValue({
      ok: true, latency_ms: 234,
      last_verified_at: "2026-09-17T05:30:00Z",
      source: "tenant",
    });
    await _render();
    await waitFor(() => expect(screen.getByTestId("dfs-test-btn")).toBeInTheDocument());
    await act(async () => {
      fireEvent.click(screen.getByTestId("dfs-test-btn"));
    });
    await waitFor(() => expect(apiPostMock).toHaveBeenCalled());
    expect(apiPostMock.mock.calls[0][0]).toBe("/tenants/me/integrations/dataforseo/test");
    const result = await screen.findByTestId("dfs-test-result");
    expect(result.textContent).toMatch(/Connected in 234ms/);
    // Last-verified timestamp now rendered.
    await waitFor(() =>
      expect(screen.getByTestId("dfs-last-verified")).toBeInTheDocument()
    );
  });

  it("Test Connection failure renders the error string", async () => {
    apiGetMock.mockResolvedValue({
      configured: true, login_masked: "bri***@plofv.com",
    });
    apiPostMock.mockResolvedValue({
      ok: false, latency_ms: 0, error: "auth_failed",
    });
    await _render();
    await waitFor(() => expect(screen.getByTestId("dfs-test-btn")).toBeInTheDocument());
    await act(async () => {
      fireEvent.click(screen.getByTestId("dfs-test-btn"));
    });
    const result = await screen.findByTestId("dfs-test-result");
    expect(result.textContent).toMatch(/auth_failed/);
  });

  it("Remove requires confirm dialog + fires DELETE + reverts to default", async () => {
    apiGetMock.mockResolvedValue({
      configured: true, login_masked: "bri***@plofv.com",
    });
    apiDeleteMock.mockResolvedValue({ configured: false, login_masked: null });
    await _render();
    await waitFor(() => expect(screen.getByTestId("dfs-remove-btn")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("dfs-remove-btn"));
    // Confirm dialog present, DELETE not yet fired.
    expect(screen.getByTestId("dfs-remove-confirm")).toBeInTheDocument();
    expect(apiDeleteMock).not.toHaveBeenCalled();
    // Cancel first — dialog closes.
    fireEvent.click(screen.getByTestId("dfs-remove-confirm-no"));
    expect(screen.queryByTestId("dfs-remove-confirm")).not.toBeInTheDocument();
    expect(apiDeleteMock).not.toHaveBeenCalled();
    // Reopen + confirm.
    fireEvent.click(screen.getByTestId("dfs-remove-btn"));
    await act(async () => {
      fireEvent.click(screen.getByTestId("dfs-remove-confirm-yes"));
    });
    await waitFor(() => expect(apiDeleteMock).toHaveBeenCalled());
    // Pill flipped back to Using platform default.
    await waitFor(() =>
      expect(screen.getByTestId("dfs-status-pill")).toHaveTextContent(/platform default/i)
    );
  });
});
