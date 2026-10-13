/**
 * Resolve-duplicate · Phase 1 · Feb-2026 — vitest coverage for the
 * enriched 409 collision UI and ``ResolveDuplicateDialog``.
 *
 * Six cases:
 *   1. Error toast with ``error_code=email_bound_to_other_customer``
 *      renders both action buttons + conflicting customer name.
 *   2. "View conflicting customer" link points at /customers/{id}.
 *   3. "Resolve duplicate…" opens the ResolveDuplicateDialog with
 *      the conflicting customer's name pre-filled in the title.
 *   4. Submit disabled until BOTH ack checkbox is checked AND the
 *      conflicting customer's name is typed (case-insensitive).
 *   5. Submit calls the unbind endpoint; success closes the dialog
 *      and surfaces the auto-retry success toast.
 *   6. Option B (merge) renders as disabled with the "Coming soon"
 *      marker and the native-title tooltip attached.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import {
  render, screen, fireEvent, waitFor, within,
} from "@testing-library/react";

const { postSpy } = vi.hoisted(() => ({ postSpy: vi.fn() }));

vi.mock("@/api", () => ({
  TOKEN_KEY: "token",
  api: { post: (...a) => postSpy(...a), get: vi.fn() },
}));

// ``sonner`` is used by ResolveDuplicateDialog for secondary error
// toasts; stub it so the vitest run isn't noisy and so expectations
// in cases 5+ can observe success calls.
const { sonnerSuccess, sonnerError } = vi.hoisted(() => ({
  sonnerSuccess: vi.fn(),
  sonnerError: vi.fn(),
}));
vi.mock("sonner", () => ({
  toast: {
    success: (...a) => sonnerSuccess(...a),
    error: (...a) => sonnerError(...a),
  },
}));

beforeEach(() => {
  postSpy.mockReset();
  sonnerSuccess.mockReset();
  sonnerError.mockReset();
});

import { PortalInviteQuickAction }
  from "@/pages/customers/CustomerDetail";


function _collisionError(overrides = {}) {
  const err = new Error("Conflict");
  err.status = 409;
  err.data = {
    detail: {
      error_code: "email_bound_to_other_customer",
      code: "portal_user_email_collision",
      message:
        "This email is already linked to another customer in "
        + "this tenant. Resolve the duplicate before re-inviting.",
      existing_user_id_prefix: "abcd1234",
      existing_customer_id_prefix: "efgh5678",
      conflict: {
        customer_id: "cust-conflict-123",
        customer_name: "Alex Conflict",
        email_bound_at: "2026-01-10T12:00:00Z",
        has_active_portal_session: true,
        has_portal_password_set: true,
      },
      ...overrides,
    },
  };
  return err;
}


function _renderWithRouter(ui) {
  return render(<MemoryRouter>{ui}</MemoryRouter>);
}


describe("PortalInviteQuickAction · ResolveDuplicate Phase 1", () => {
  it("renders both action buttons + conflict name on collision", async () => {
    postSpy.mockRejectedValueOnce(_collisionError());
    const toastSpy = vi.fn();
    _renderWithRouter(
      <PortalInviteQuickAction
        customer={{
          id: "cust-xyz",
          name: "Target Caller",
          emails: [],
          email: "shared@synthetic.test",
        }}
        onToast={toastSpy}
      />,
    );

    fireEvent.click(screen.getByTestId("cd-portal-invite"));

    await waitFor(() => {
      expect(
        screen.queryByTestId("portal-invite-collision-panel"),
      ).toBeInTheDocument();
    });
    expect(
      screen.getByTestId("portal-invite-collision-name").textContent,
    ).toContain("Alex Conflict");
    expect(
      screen.getByTestId("portal-invite-view-conflicting-btn"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("portal-invite-resolve-duplicate-btn"),
    ).toBeInTheDocument();
    // Legacy test contract — toast still fired.
    expect(toastSpy).toHaveBeenCalledTimes(1);
  });

  it('"View conflicting customer" button links to /customers/{id}', async () => {
    postSpy.mockRejectedValueOnce(_collisionError());
    _renderWithRouter(
      <PortalInviteQuickAction
        customer={{ id: "cust-xyz", email: "shared@synthetic.test" }}
        onToast={() => {}}
      />,
    );
    fireEvent.click(screen.getByTestId("cd-portal-invite"));
    await waitFor(() =>
      screen.getByTestId("portal-invite-view-conflicting-btn"),
    );
    const link = screen.getByTestId("portal-invite-view-conflicting-btn");
    expect(link.getAttribute("href")).toBe(
      "/customers/cust-conflict-123",
    );
  });

  it('"Resolve duplicate…" opens the ResolveDuplicateDialog', async () => {
    postSpy.mockRejectedValueOnce(_collisionError());
    _renderWithRouter(
      <PortalInviteQuickAction
        customer={{ id: "cust-xyz", email: "shared@synthetic.test" }}
        onToast={() => {}}
      />,
    );
    fireEvent.click(screen.getByTestId("cd-portal-invite"));
    await waitFor(() =>
      screen.getByTestId("portal-invite-resolve-duplicate-btn"),
    );
    fireEvent.click(
      screen.getByTestId("portal-invite-resolve-duplicate-btn"),
    );
    expect(
      screen.getByTestId("resolve-duplicate-modal"),
    ).toBeInTheDocument();
    // Conflicting customer's name surfaces inside the dialog.
    const body = screen.getByTestId("resolve-duplicate-body");
    expect(body.textContent).toContain("Alex Conflict");
  });

  it("Unbind submit stays disabled until ack + typed name match", async () => {
    postSpy.mockRejectedValueOnce(_collisionError());
    _renderWithRouter(
      <PortalInviteQuickAction
        customer={{ id: "cust-xyz", email: "shared@synthetic.test" }}
        onToast={() => {}}
      />,
    );
    fireEvent.click(screen.getByTestId("cd-portal-invite"));
    await waitFor(() =>
      screen.getByTestId("portal-invite-resolve-duplicate-btn"),
    );
    fireEvent.click(
      screen.getByTestId("portal-invite-resolve-duplicate-btn"),
    );

    const submit = screen.getByTestId("resolve-duplicate-unbind-submit");
    expect(submit).toBeDisabled();

    // Check only the ack → still disabled.
    fireEvent.click(screen.getByTestId("resolve-duplicate-ack-checkbox"));
    expect(submit).toBeDisabled();

    // Type a wrong name → still disabled.
    const input = screen.getByTestId("resolve-duplicate-name-input");
    fireEvent.change(input, { target: { value: "Totally Wrong" } });
    expect(submit).toBeDisabled();

    // Type the right name (lowercase with trailing spaces to prove
    // case-insensitive, whitespace-collapsed match).
    fireEvent.change(input, { target: { value: "  alex conflict  " } });
    await waitFor(() => expect(submit).not.toBeDisabled());
  });

  it("Submit calls unbind endpoint + closes dialog + success toast on auto-retry", async () => {
    // Sequence of API responses: initial invite → 409 collision,
    // unbind → success, auto-retry invite → emailed success.
    postSpy
      .mockRejectedValueOnce(_collisionError())
      .mockResolvedValueOnce({
        status: "ok",
        released_email: "shared@synthetic.test",
        conflicting_customer_id: "cust-conflict-123",
        portal_sessions_invalidated: 1,
      })
      .mockResolvedValueOnce({
        emailed: true,
        email: "shared@synthetic.test",
        login_url: "https://x.test/login",
      });

    const toastSpy = vi.fn();
    _renderWithRouter(
      <PortalInviteQuickAction
        customer={{
          id: "cust-xyz",
          name: "Target Caller",
          email: "shared@synthetic.test",
        }}
        onToast={toastSpy}
      />,
    );
    // Trigger initial invite → collision.
    fireEvent.click(screen.getByTestId("cd-portal-invite"));
    await waitFor(() =>
      screen.getByTestId("portal-invite-resolve-duplicate-btn"),
    );
    // Open the resolve dialog.
    fireEvent.click(
      screen.getByTestId("portal-invite-resolve-duplicate-btn"),
    );
    // Fill the gates.
    fireEvent.click(screen.getByTestId("resolve-duplicate-ack-checkbox"));
    fireEvent.change(
      screen.getByTestId("resolve-duplicate-name-input"),
      { target: { value: "Alex Conflict" } },
    );
    // Submit.
    fireEvent.click(screen.getByTestId("resolve-duplicate-unbind-submit"));

    // Dialog closes.
    await waitFor(() =>
      expect(
        screen.queryByTestId("resolve-duplicate-modal"),
      ).not.toBeInTheDocument(),
    );
    // Unbind endpoint called with the right path + body.
    const unbindCall = postSpy.mock.calls.find(
      ([p]) => p === "/customers/cust-conflict-123/unbind-portal-email",
    );
    expect(unbindCall).toBeTruthy();
    expect(unbindCall[1]).toEqual({ confirmation_name: "Alex Conflict" });
    // Auto-retry fires + success toast surfaces.
    await waitFor(() => {
      const matched = toastSpy.mock.calls.find(
        ([t]) =>
          t?.testid === "resolve-duplicate-auto-retry-success-toast",
      );
      expect(matched).toBeTruthy();
    });
  });

  it("Option B (merge) renders disabled with Coming soon marker + tooltip", async () => {
    postSpy.mockRejectedValueOnce(_collisionError());
    _renderWithRouter(
      <PortalInviteQuickAction
        customer={{ id: "cust-xyz", email: "shared@synthetic.test" }}
        onToast={() => {}}
      />,
    );
    fireEvent.click(screen.getByTestId("cd-portal-invite"));
    await waitFor(() =>
      screen.getByTestId("portal-invite-resolve-duplicate-btn"),
    );
    fireEvent.click(
      screen.getByTestId("portal-invite-resolve-duplicate-btn"),
    );

    const optionB = screen.getByTestId("resolve-duplicate-option-b");
    expect(optionB).toBeInTheDocument();
    // Coming-soon marker.
    expect(
      within(optionB).getByTestId("resolve-duplicate-option-b-coming-soon"),
    ).toBeInTheDocument();
    // Tooltip (native title attribute).
    expect(optionB.getAttribute("title")).toContain("Coming soon");
    // Section is visually marked unavailable.
    expect(optionB.className).toContain("opacity-60");
    expect(optionB.className).toContain("cursor-not-allowed");
  });
});
