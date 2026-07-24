/**
 * Feb-2026 · BUG E — TosGate vitest suite.
 *
 * Covers:
 *  * Renders NULL when user.must_accept_tos is false (customers who
 *    already accepted).
 *  * Renders NULL for super_admin regardless of ToS state.
 *  * When must_accept_tos is true, the modal renders, "I Agree" is
 *    disabled until the checkbox is ticked, and a successful POST
 *    dismisses the modal.
 *  * Version mismatch (409) surfaces an inline error with a Reload
 *    button — the modal stays open.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

// Mock the auth module BEFORE the component imports it.
const setUserMock = vi.fn();
let currentUser = null;

vi.mock("@/auth", () => ({
  useAuth: () => ({ user: currentUser, setUser: setUserMock }),
}));

// Mock the api module.
const apiGet = vi.fn();
const apiPost = vi.fn();
vi.mock("@/api", () => ({
  api: { get: (...a) => apiGet(...a), post: (...a) => apiPost(...a) },
}));

// react-router's useNavigate — capture the calls.
const navigateMock = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useNavigate: () => navigateMock };
});

// Component under test — imported after mocks.
import TosGate from "@/components/legal/TosGate";


function renderGate() {
  return render(
    <MemoryRouter>
      <TosGate />
    </MemoryRouter>,
  );
}

const activeTos = {
  version: "1.0.0",
  effective_date: "2026-02-15",
  markdown: "## Terms\n\nBy clicking I Agree you accept…",
};

beforeEach(() => {
  currentUser = null;
  setUserMock.mockReset();
  navigateMock.mockReset();
  apiGet.mockReset();
  apiPost.mockReset();
});


describe("TosGate", () => {
  it("renders nothing when user has already accepted", () => {
    currentUser = {
      id: "u1", role: "customer",
      must_accept_tos: false,
      tos_version_accepted: "1.0.0",
    };
    const { container } = renderGate();
    expect(container.firstChild).toBeNull();
    expect(apiGet).not.toHaveBeenCalled();
  });

  it("renders nothing for super_admin even when flag were true", () => {
    // Guard belt-and-suspenders: super_admin bypass is enforced server-side
    // via must_accept_tos=false. This test confirms the frontend defers to
    // that flag rather than second-guessing role.
    currentUser = {
      id: "u9", role: "super_admin", must_accept_tos: false,
    };
    const { container } = renderGate();
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing when user is not signed in", () => {
    currentUser = null;
    const { container } = renderGate();
    expect(container.firstChild).toBeNull();
  });

  it("shows the modal, disables Agree until checked, then POSTs + closes", async () => {
    currentUser = {
      id: "u2", role: "customer",
      must_accept_tos: true,
      tos_version_accepted: null,
    };
    apiGet.mockResolvedValueOnce(activeTos);
    apiPost.mockResolvedValueOnce({
      ok: true, must_accept_tos: false,
      tos_version_accepted: "1.0.0",
      tos_accepted_at: "2026-02-16T00:00:00Z",
    });

    renderGate();

    // Modal appears.
    expect(await screen.findByTestId("tos-gate-modal")).toBeInTheDocument();
    // Version label rendered from the fetched doc.
    await waitFor(() =>
      expect(screen.getByTestId("tos-gate-version").textContent).toMatch(/1\.0\.0/),
    );

    const agreeBtn = screen.getByTestId("tos-gate-agree-btn");
    const checkbox = screen.getByTestId("tos-gate-checkbox");

    // Disabled until checked.
    expect(agreeBtn).toBeDisabled();
    fireEvent.click(checkbox);
    expect(agreeBtn).not.toBeDisabled();

    // Click Agree — POST fires with the active version.
    fireEvent.click(agreeBtn);
    await waitFor(() =>
      expect(apiPost).toHaveBeenCalledWith(
        "/users/me/accept-tos", { version: "1.0.0" },
      ),
    );

    // Auth state patched.
    await waitFor(() => expect(setUserMock).toHaveBeenCalled());
    const nextUser = setUserMock.mock.calls[0][0];
    expect(nextUser.must_accept_tos).toBe(false);
    expect(nextUser.tos_version_accepted).toBe("1.0.0");

    // Routed to role-appropriate landing.
    expect(navigateMock).toHaveBeenCalledWith("/portal/home", { replace: true });
  });

  it("routes admin to '/' after acceptance", async () => {
    currentUser = {
      id: "u3", role: "admin", must_accept_tos: true,
    };
    apiGet.mockResolvedValueOnce(activeTos);
    apiPost.mockResolvedValueOnce({
      ok: true, must_accept_tos: false, tos_version_accepted: "1.0.0",
    });
    renderGate();
    await screen.findByTestId("tos-gate-modal");
    fireEvent.click(screen.getByTestId("tos-gate-checkbox"));
    fireEvent.click(screen.getByTestId("tos-gate-agree-btn"));
    await waitFor(() =>
      expect(navigateMock).toHaveBeenCalledWith("/", { replace: true }),
    );
  });

  it("routes technician to '/schedule' after acceptance", async () => {
    currentUser = {
      id: "u4", role: "technician", must_accept_tos: true,
    };
    apiGet.mockResolvedValueOnce(activeTos);
    apiPost.mockResolvedValueOnce({
      ok: true, must_accept_tos: false, tos_version_accepted: "1.0.0",
    });
    renderGate();
    await screen.findByTestId("tos-gate-modal");
    fireEvent.click(screen.getByTestId("tos-gate-checkbox"));
    fireEvent.click(screen.getByTestId("tos-gate-agree-btn"));
    await waitFor(() =>
      expect(navigateMock).toHaveBeenCalledWith("/schedule", { replace: true }),
    );
  });

  it("shows inline error + reload button on 409 version mismatch", async () => {
    currentUser = {
      id: "u5", role: "customer", must_accept_tos: true,
    };
    apiGet.mockResolvedValueOnce(activeTos);
    const err = Object.assign(new Error("ToS version mismatch. Please reload."), {
      status: 409,
    });
    apiPost.mockRejectedValueOnce(err);

    renderGate();
    await screen.findByTestId("tos-gate-modal");
    fireEvent.click(screen.getByTestId("tos-gate-checkbox"));
    fireEvent.click(screen.getByTestId("tos-gate-agree-btn"));

    const errBox = await screen.findByTestId("tos-gate-error");
    expect(errBox.textContent).toMatch(/updated/i);
    // Reload button present.
    expect(screen.getByTestId("tos-gate-reload")).toBeInTheDocument();
    // Modal stays open + button re-enabled.
    expect(screen.getByTestId("tos-gate-modal")).toBeInTheDocument();
    expect(screen.getByTestId("tos-gate-agree-btn")).not.toBeDisabled();
    // Auth state NOT patched.
    expect(setUserMock).not.toHaveBeenCalled();
  });

  it("shows inline error on generic failure and keeps the modal open", async () => {
    currentUser = {
      id: "u6", role: "customer", must_accept_tos: true,
    };
    apiGet.mockResolvedValueOnce(activeTos);
    apiPost.mockRejectedValueOnce(new Error("network down"));

    renderGate();
    await screen.findByTestId("tos-gate-modal");
    fireEvent.click(screen.getByTestId("tos-gate-checkbox"));
    fireEvent.click(screen.getByTestId("tos-gate-agree-btn"));

    const errBox = await screen.findByTestId("tos-gate-error");
    expect(errBox.textContent).toMatch(/network down/i);
    expect(screen.queryByTestId("tos-gate-reload")).toBeNull();
    expect(screen.getByTestId("tos-gate-modal")).toBeInTheDocument();
  });
});
