/**
 * Feb-2026 · Payment Processors save flow + same-provider validation.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";


const mockGet = vi.fn();
const mockPatch = vi.fn();
const mockPost = vi.fn();
const mockToastSuccess = vi.fn();
const mockToastError = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: (...a) => mockGet(...a),
    patch: (...a) => mockPatch(...a),
    post: (...a) => mockPost(...a),
  },
}));
vi.mock("sonner", () => ({
  toast: Object.assign(() => {},
    { success: (...a) => mockToastSuccess(...a),
      error: (...a) => mockToastError(...a) }),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (_k, def) => def }),
}));

import PaymentProvidersCard from "../components/settings/PaymentProvidersCard";


const _available = [
  { short_name: "stripe", provider_key: "pay_stripe",
    is_configured: true, requires_tenant_config: false },
  { short_name: "lumino", provider_key: "pay_lumino",
    is_configured: true, requires_tenant_config: true },
];


describe("PaymentProvidersCard · save flow", () => {
  beforeEach(() => {
    mockGet.mockReset();
    mockPatch.mockReset();
    mockPost.mockReset();
    mockToastSuccess.mockReset();
    mockToastError.mockReset();
    mockGet.mockImplementation((path) => {
      if (path.includes("/settings/payment-providers")) {
        return Promise.resolve({
          primary_provider: "stripe",
          backup_provider: null,
          available: _available,
        });
      }
      return Promise.resolve({ total: 0, rows: [] });
    });
  });

  it("saves primary + backup via PATCH and shows success toast", async () => {
    mockPatch.mockResolvedValue({
      primary_provider: "stripe",
      backup_provider: "lumino",
      available: _available,
    });

    render(<PaymentProvidersCard />);

    const backup = await screen.findByTestId("payment-providers-backup-select");
    fireEvent.change(backup, { target: { value: "lumino" } });

    const saveBtn = screen.getByTestId("payment-providers-save-button");
    fireEvent.click(saveBtn);

    await waitFor(() => expect(mockPatch).toHaveBeenCalledTimes(1));
    expect(mockPatch).toHaveBeenCalledWith(
      "/tenants/mine/settings/payment-providers",
      { primary_provider: "stripe", backup_provider: "lumino" },
    );
    await waitFor(() =>
      expect(mockToastSuccess).toHaveBeenCalled(),
    );
  });

  it("shows same-provider validation error inline and disables Save", async () => {
    render(<PaymentProvidersCard />);

    const primary = await screen.findByTestId("payment-providers-primary-select");
    const backup = screen.getByTestId("payment-providers-backup-select");
    fireEvent.change(primary, { target: { value: "lumino" } });
    fireEvent.change(backup, { target: { value: "lumino" } });

    await waitFor(() =>
      expect(screen.getByTestId("payment-providers-same-provider-error"))
        .toBeInTheDocument(),
    );

    const saveBtn = screen.getByTestId("payment-providers-save-button");
    expect(saveBtn).toBeDisabled();
    fireEvent.click(saveBtn);
    // PATCH must NOT be issued when the client-side validation fires.
    expect(mockPatch).not.toHaveBeenCalled();
  });

  it("PATCH null backup when user clears backup", async () => {
    mockGet.mockImplementation((path) => {
      if (path.includes("/settings/payment-providers")) {
        return Promise.resolve({
          primary_provider: "stripe",
          backup_provider: "lumino",
          available: _available,
        });
      }
      return Promise.resolve({ total: 0, rows: [] });
    });
    mockPatch.mockResolvedValue({
      primary_provider: "stripe",
      backup_provider: null,
      available: _available,
    });

    render(<PaymentProvidersCard />);

    const backup = await screen.findByTestId("payment-providers-backup-select");
    // Change to the None sentinel (component internal value).
    fireEvent.change(backup, { target: { value: "__none__" } });

    fireEvent.click(screen.getByTestId("payment-providers-save-button"));
    await waitFor(() => expect(mockPatch).toHaveBeenCalledTimes(1));
    expect(mockPatch.mock.calls[0][1]).toEqual({
      primary_provider: "stripe",
      backup_provider: null,
    });
  });
});
