/**
 * Sep-2026 · DataForSEO integration card — render smoke.
 *
 * Covers unconfigured + configured render paths, status pill state,
 * masked login display, and Save button gating on both fields.
 */
import React from "react";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
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

describe("DataForSEOIntegrationCard · render (SP3-DFS)", () => {
  it("shows 'Using platform default' pill and empty fields when unconfigured", async () => {
    apiGetMock.mockResolvedValue({ configured: false, login_masked: null });
    await _render();
    await waitFor(() => expect(apiGetMock).toHaveBeenCalled());
    expect(screen.getByTestId("dfs-integration-card")).toBeInTheDocument();
    expect(screen.getByTestId("dfs-integration-title")).toHaveTextContent(/DataForSEO/);
    expect(screen.getByTestId("dfs-status-pill")).toHaveTextContent(/platform default/i);
    expect(screen.getByTestId("dfs-login-input")).toBeInTheDocument();
    expect(screen.getByTestId("dfs-password-input")).toBeInTheDocument();
    // Save disabled until both fields have content.
    expect(screen.getByTestId("dfs-save-btn")).toBeDisabled();
    // No Test button until configured.
    expect(screen.queryByTestId("dfs-test-btn")).not.toBeInTheDocument();
    // No Remove button until configured.
    expect(screen.queryByTestId("dfs-remove-btn")).not.toBeInTheDocument();
  });

  it("shows 'Configured' pill + masked login + Test/Remove buttons when configured", async () => {
    apiGetMock.mockResolvedValue({
      configured: true, login_masked: "bri***@plofv.com",
      configured_at: "2026-09-17T05:00:00Z",
      last_verified_at: "2026-09-17T05:00:00Z",
    });
    await _render();
    await waitFor(() => expect(screen.getByTestId("dfs-login-masked")).toBeInTheDocument());
    expect(screen.getByTestId("dfs-status-pill")).toHaveTextContent(/Configured/i);
    expect(screen.getByTestId("dfs-login-masked")).toHaveTextContent(/bri\*\*\*@plofv\.com/);
    // Test + Remove present.
    expect(screen.getByTestId("dfs-test-btn")).toBeInTheDocument();
    expect(screen.getByTestId("dfs-remove-btn")).toBeInTheDocument();
    // Editing not entered by default.
    expect(screen.queryByTestId("dfs-login-input")).not.toBeInTheDocument();
    expect(screen.getByTestId("dfs-change-btn")).toBeInTheDocument();
  });

  it("Save button enables once both fields have content", async () => {
    apiGetMock.mockResolvedValue({ configured: false, login_masked: null });
    await _render();
    await waitFor(() => expect(apiGetMock).toHaveBeenCalled());
    const saveBtn = screen.getByTestId("dfs-save-btn");
    expect(saveBtn).toBeDisabled();
    fireEvent.change(screen.getByTestId("dfs-login-input"),
                       { target: { value: "u@x.com" } });
    expect(saveBtn).toBeDisabled(); // password still empty
    fireEvent.change(screen.getByTestId("dfs-password-input"),
                       { target: { value: "abc123" } });
    expect(saveBtn).not.toBeDisabled();
  });
});
