/**
 * Feb-2026 · Customer self-serve profile-completion gate.
 *
 * Covers:
 * * Renders null when user is not a customer / flag is false.
 * * Renders when user.customer_record_missing===true, PATCHes on submit
 *   with POST /portal/complete-profile.
 * * "Skip for now" fires the audit call with ?skip=1 and hides the gate.
 * * Validation refuses empty first/last/phone/address before hitting API.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


const apiPost = vi.fn();
vi.mock("@/api", () => ({
  api: {
    post: (...a) => apiPost(...a),
  },
}));

const setUserMock = vi.fn();
let currentUser = null;
vi.mock("@/auth", () => ({
  useAuth: () => ({ user: currentUser, setUser: setUserMock }),
}));

// react-router-dom's `useNavigate` returns a spy so we can assert
// on the post-submit navigation.
const navigateMock = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return {
    ...actual,
    useNavigate: () => navigateMock,
  };
});

import ProfileCompletionGate from "@/components/portal/ProfileCompletionGate";


function renderGate() {
  return render(
    <MemoryRouter>
      <ProfileCompletionGate />
    </MemoryRouter>
  );
}


beforeEach(() => {
  apiPost.mockReset();
  setUserMock.mockReset();
  navigateMock.mockReset();
  currentUser = null;
  try { sessionStorage.clear(); } catch { /* noop */ }
});


describe("ProfileCompletionGate", () => {
  it("renders null when user is not a customer", () => {
    currentUser = { id: "u1", role: "admin", customer_record_missing: true };
    const { container } = renderGate();
    expect(container.querySelector('[data-testid="profile-completion-gate"]'))
      .toBeNull();
  });

  it("renders null when customer_record_missing is false", () => {
    currentUser = { id: "u1", role: "customer", customer_record_missing: false };
    const { container } = renderGate();
    expect(container.querySelector('[data-testid="profile-completion-gate"]'))
      .toBeNull();
  });

  it("renders modal when customer_record_missing is true", () => {
    currentUser = {
      id: "u1", role: "customer",
      customer_record_missing: true,
      name: "Jane Doe",
      phone: "5555550100",
    };
    renderGate();
    expect(screen.getByTestId("profile-completion-gate")).toBeInTheDocument();
    // Prefilled from `name`.
    expect(screen.getByTestId("profile-completion-first-name"))
      .toHaveValue("Jane");
    expect(screen.getByTestId("profile-completion-last-name"))
      .toHaveValue("Doe");
    expect(screen.getByTestId("profile-completion-phone"))
      .toHaveValue("5555550100");
  });

  it("submit validates required fields client-side", async () => {
    currentUser = {
      id: "u1", role: "customer",
      customer_record_missing: true,
      name: "",
      phone: "",
    };
    renderGate();
    fireEvent.click(screen.getByTestId("profile-completion-submit"));
    await waitFor(() => {
      expect(screen.getByTestId("profile-completion-error"))
        .toHaveTextContent(/first and last name/i);
    });
    expect(apiPost).not.toHaveBeenCalled();
  });

  it("submit POSTs to /portal/complete-profile and updates auth user", async () => {
    apiPost.mockResolvedValueOnce({
      ok: true,
      was_already_linked: false,
      customer_id: "cust-new",
      customer_record_missing: false,
    });
    currentUser = {
      id: "u1", role: "customer",
      customer_record_missing: true,
      name: "Jane Doe",
      phone: "5555550100",
      email: "jane@example.com",
    };
    renderGate();

    fireEvent.change(screen.getByTestId("profile-completion-service-address"), {
      target: { value: "42 Vistancia Blvd" },
    });
    fireEvent.change(screen.getByTestId("profile-completion-preferred-contact"), {
      target: { value: "sms" },
    });
    fireEvent.click(screen.getByTestId("profile-completion-submit"));

    await waitFor(() => {
      expect(apiPost).toHaveBeenCalledWith("/portal/complete-profile", {
        first_name: "Jane",
        last_name: "Doe",
        phone: "5555550100",
        service_address: "42 Vistancia Blvd",
        preferred_contact: "sms",
      });
    });
    expect(setUserMock).toHaveBeenCalledWith(
      expect.objectContaining({
        customer_id: "cust-new",
        customer_record_missing: false,
      })
    );
    expect(navigateMock).toHaveBeenCalledWith("/portal/home", { replace: true });
  });

  it("Skip fires the audit endpoint with ?skip=1 and hides the gate", async () => {
    apiPost.mockResolvedValueOnce({
      ok: true, skipped: true, customer_record_missing: true,
    });
    currentUser = {
      id: "u1", role: "customer",
      customer_record_missing: true,
      name: "Jane Doe",
      phone: "5555550100",
      email: "jane@example.com",
    };
    const { container } = renderGate();
    fireEvent.click(screen.getByTestId("profile-completion-skip"));
    // Gate hides immediately after skip.
    await waitFor(() => {
      expect(container.querySelector(
        '[data-testid="profile-completion-gate"]'
      )).toBeNull();
    });
    // Fire-and-forget POST with ?skip=1.
    await waitFor(() => {
      expect(apiPost).toHaveBeenCalledWith(
        "/portal/complete-profile?skip=1", {}
      );
    });
    // sessionStorage flag was set.
    expect(sessionStorage.getItem("profile_completion_skipped")).toBe("1");
  });

  it("surfaces server error on submit failure", async () => {
    apiPost.mockRejectedValueOnce(new Error("nope"));
    currentUser = {
      id: "u1", role: "customer",
      customer_record_missing: true,
      name: "Jane Doe",
      phone: "5555550100",
      email: "jane@example.com",
    };
    renderGate();
    fireEvent.change(screen.getByTestId("profile-completion-service-address"), {
      target: { value: "42 Vistancia Blvd" },
    });
    fireEvent.click(screen.getByTestId("profile-completion-submit"));
    await waitFor(() => {
      expect(screen.getByTestId("profile-completion-error"))
        .toHaveTextContent(/nope/i);
    });
    expect(setUserMock).not.toHaveBeenCalled();
    expect(navigateMock).not.toHaveBeenCalled();
  });
});
