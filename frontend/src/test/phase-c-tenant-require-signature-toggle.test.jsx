/**
 * Feb-2026 · Phase C — TenantRequireSignatureBeforeApproveToggle
 * Vitest. Mirrors the Phase B pattern so both toggles share the
 * same round-trip contract against ``/api/tenants/mine/settings``.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";

vi.mock("@/api", () => ({
  api: { get: vi.fn(), patch: vi.fn(), post: vi.fn() },
  TOKEN_KEY: "token",
}));

import { api } from "@/api";
import { TenantRequireSignatureBeforeApproveToggle } from "@/pages/settings/NotificationPrefs";

beforeEach(() => {
  api.get.mockReset();
  api.patch.mockReset();
});


describe("Phase C · TenantRequireSignatureBeforeApproveToggle", () => {
  it("renders as OFF by default when the field is undefined", async () => {
    api.get.mockResolvedValue({ id: "t1" });
    render(<TenantRequireSignatureBeforeApproveToggle />);
    const sw = await waitFor(
      () => screen.getByTestId("tenant-require-signature-toggle"),
    );
    await waitFor(() =>
      expect(sw.getAttribute("aria-checked")).toBe("false"),
    );
    cleanup();
  });

  it("renders as ON when tenant has require_signature_before_approve=true",
    async () => {
      api.get.mockResolvedValue({
        id: "t1", require_signature_before_approve: true,
      });
      render(<TenantRequireSignatureBeforeApproveToggle />);
      const sw = await waitFor(
        () => screen.getByTestId("tenant-require-signature-toggle"),
      );
      await waitFor(() =>
        expect(sw.getAttribute("aria-checked")).toBe("true"),
      );
      cleanup();
    });

  it("click PATCHes /tenants/mine/settings with the new boolean",
    async () => {
      api.get.mockResolvedValue({
        id: "t1", require_signature_before_approve: false,
      });
      api.patch.mockResolvedValue({
        id: "t1", require_signature_before_approve: true,
      });
      render(<TenantRequireSignatureBeforeApproveToggle />);
      const sw = await waitFor(
        () => screen.getByTestId("tenant-require-signature-toggle"),
      );
      await waitFor(() =>
        expect(sw.getAttribute("aria-checked")).toBe("false"),
      );
      fireEvent.click(sw);
      await waitFor(() => {
        expect(api.patch).toHaveBeenCalledWith(
          "/tenants/mine/settings",
          { require_signature_before_approve: true },
        );
      });
      expect(sw.getAttribute("aria-checked")).toBe("true");
      await waitFor(() =>
        expect(
          screen.getByTestId("tenant-require-signature-toast").textContent,
        ).toMatch(/Saved/i),
      );
      cleanup();
    });

  it("PATCH failure rolls the optimistic flip back", async () => {
    api.get.mockResolvedValue({
      id: "t1", require_signature_before_approve: false,
    });
    api.patch.mockRejectedValue(new Error("boom"));
    render(<TenantRequireSignatureBeforeApproveToggle />);
    const sw = await waitFor(
      () => screen.getByTestId("tenant-require-signature-toggle"),
    );
    await waitFor(() =>
      expect(sw.getAttribute("aria-checked")).toBe("false"),
    );
    fireEvent.click(sw);
    await waitFor(() => expect(api.patch).toHaveBeenCalled());
    await waitFor(() =>
      expect(sw.getAttribute("aria-checked")).toBe("false"),
    );
    await waitFor(() =>
      expect(
        screen.getByTestId("tenant-require-signature-toast").textContent,
      ).toMatch(/boom|failed/i),
    );
    cleanup();
  });
});
