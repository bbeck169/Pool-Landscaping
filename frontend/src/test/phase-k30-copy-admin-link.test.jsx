/**
 * Phase K30.copy-admin-link · Feb-2026 — Web unit tests.
 *
 * Covers the three exported surfaces:
 *   * canCopyResetLink(role) — role gate.
 *   * PortalResetLinkCopyConfirmModal — confirm-and-copy flow.
 *   * PortalResetLinkCopyFallbackModal — clipboard-permission
 *     fallback.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

import {
  canCopyResetLink,
  PortalResetLinkCopyConfirmModal,
  PortalResetLinkCopyFallbackModal,
} from "@/pages/customers/CustomerDetail";


describe("K30.copy · role gate", () => {
  it("only super_admin can copy the reset link", () => {
    expect(canCopyResetLink("super_admin")).toBe(true);
    expect(canCopyResetLink("admin")).toBe(false);
    expect(canCopyResetLink("owner")).toBe(false);
    expect(canCopyResetLink("manager")).toBe(false);
    expect(canCopyResetLink("technician")).toBe(false);
    expect(canCopyResetLink("customer")).toBe(false);
    expect(canCopyResetLink(undefined)).toBe(false);
    expect(canCopyResetLink(null)).toBe(false);
    expect(canCopyResetLink("")).toBe(false);
  });
});


describe("K30.copy · PortalResetLinkCopyConfirmModal", () => {
  it("renders confirm + cancel testids with customer name", () => {
    render(
      <PortalResetLinkCopyConfirmModal
        open
        customer={{ name: "Jane Doe" }}
        email="jane@example.com"
        onClose={() => {}}
        onConfirm={() => {}}
      />,
    );
    expect(screen.getByTestId("portal-reset-link-copy-modal-body")
      .textContent).toContain("Jane Doe");
    expect(screen.getByTestId("portal-reset-link-copy-cancel")).toBeTruthy();
    expect(screen.getByTestId("portal-reset-link-copy-confirm")).toBeTruthy();
  });

  it("disables confirm when the customer has no email", () => {
    render(
      <PortalResetLinkCopyConfirmModal
        open
        customer={{ name: "No Email" }}
        email=""
        onClose={() => {}}
        onConfirm={() => {}}
      />,
    );
    expect(
      screen.getByTestId("portal-reset-link-copy-confirm").hasAttribute("disabled"),
    ).toBe(true);
  });

  it("emits onConfirm when the confirm button is clicked", () => {
    const onConfirm = vi.fn();
    render(
      <PortalResetLinkCopyConfirmModal
        open
        customer={{ name: "Jane" }}
        email="jane@x.com"
        onClose={() => {}}
        onConfirm={onConfirm}
      />,
    );
    fireEvent.click(screen.getByTestId("portal-reset-link-copy-confirm"));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("does not render when open=false", () => {
    render(
      <PortalResetLinkCopyConfirmModal
        open={false}
        customer={{ name: "Jane" }}
        email="jane@x.com"
        onClose={() => {}}
        onConfirm={() => {}}
      />,
    );
    expect(screen.queryByTestId("portal-reset-link-copy-modal-body")).toBeNull();
  });
});


describe("K30.copy · PortalResetLinkCopyFallbackModal", () => {
  beforeEach(() => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn(() => Promise.resolve()) },
    });
  });

  it("renders the raw URL in a readonly input", () => {
    const url = "https://app.example.com/reset-password?token=abc123";
    render(
      <PortalResetLinkCopyFallbackModal
        open
        url={url}
        expiresAt={null}
        onClose={() => {}}
        onCopied={() => {}}
      />,
    );
    const input = screen.getByTestId("portal-reset-link-copy-fallback-input");
    expect(input.value).toBe(url);
    expect(input.hasAttribute("readonly")).toBe(true);
  });

  it("clicking Copy attempts clipboard.writeText and fires onCopied on success", async () => {
    const onCopied = vi.fn();
    const url = "https://app.example.com/reset-password?token=xyz";
    render(
      <PortalResetLinkCopyFallbackModal
        open
        url={url}
        expiresAt={null}
        onClose={() => {}}
        onCopied={onCopied}
      />,
    );
    fireEvent.click(screen.getByTestId("portal-reset-link-copy-fallback-copy"));
    await waitFor(() => expect(onCopied).toHaveBeenCalled());
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(url);
  });

  it("renders the expiry hint when expiresAt is provided", () => {
    render(
      <PortalResetLinkCopyFallbackModal
        open
        url="https://x/reset-password?token=t"
        expiresAt="2099-01-01T00:00:00Z"
        onClose={() => {}}
        onCopied={() => {}}
      />,
    );
    expect(
      screen.getByTestId("portal-reset-link-copy-fallback-expiry").textContent,
    ).toMatch(/Expires at/);
  });

  it("close button calls onClose", () => {
    const onClose = vi.fn();
    render(
      <PortalResetLinkCopyFallbackModal
        open
        url="https://x/reset-password?token=t"
        expiresAt={null}
        onClose={onClose}
        onCopied={() => {}}
      />,
    );
    fireEvent.click(screen.getByTestId("portal-reset-link-copy-fallback-close"));
    expect(onClose).toHaveBeenCalled();
  });
});
