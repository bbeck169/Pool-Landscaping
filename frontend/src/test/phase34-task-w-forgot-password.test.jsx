/**
 * Phase 34 · Task W · Feb 2026 — refresh the /forgot-password test
 * spec so it asserts the CURRENT real-form structure (Task O), not
 * the earlier "temporarily unavailable" honest-stub copy.
 *
 * The honest-stub was correctly superseded when Task O shipped —
 * this spec locks the real-form contract:
 *   - email input   (`data-testid="forgot-password-email"`)
 *   - submit button (`data-testid="forgot-password-submit"`)
 *   - after submit, a neutral confirmation renders
 *     (`data-testid="forgot-password-confirmation"`) with "if an
 *     account exists…" copy so the endpoint remains enum-safe.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

// api.post is mocked so the test never hits the network — we only
// care about the surface behaviour.
vi.mock("@/api", () => ({
  api: { post: vi.fn().mockResolvedValue({ ok: true }) },
}));

import ForgotPassword from "@/pages/ForgotPassword";
import { api } from "@/api";

const renderPage = () =>
  render(
    <MemoryRouter>
      <ForgotPassword />
    </MemoryRouter>
  );

describe("/forgot-password — real form (Task O)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the real email input + submit button (no honest-stub copy)", () => {
    renderPage();
    expect(screen.getByTestId("forgot-password-page")).toBeInTheDocument();
    expect(screen.getByTestId("forgot-password-title")).toHaveTextContent(
      /forgot password/i
    );
    expect(screen.getByTestId("forgot-password-email")).toBeInTheDocument();
    expect(screen.getByTestId("forgot-password-submit")).toBeInTheDocument();
    // The honest-stub yellow banner should NOT be present.
    expect(
      screen.queryByTestId("forgot-password-unavailable")
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(/temporarily unavailable/i)
    ).not.toBeInTheDocument();
  });

  it("submits the email and shows the neutral confirmation", async () => {
    renderPage();
    fireEvent.change(screen.getByTestId("forgot-password-email"), {
      target: { value: "someone@example.com" },
    });
    fireEvent.click(screen.getByTestId("forgot-password-submit"));

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith("/auth/forgot-password", {
        email: "someone@example.com",
      });
    });
    // Neutral confirmation copy — never leaks whether the account exists.
    const conf = await screen.findByTestId("forgot-password-confirmation");
    expect(conf).toHaveTextContent(/if an account exists for that email/i);
  });

  it("still confirms neutrally when the backend errors", async () => {
    api.post.mockRejectedValueOnce(new Error("network go boom"));
    renderPage();
    fireEvent.change(screen.getByTestId("forgot-password-email"), {
      target: { value: "someone@example.com" },
    });
    fireEvent.click(screen.getByTestId("forgot-password-submit"));

    // Even on a network error the enum-safe UI shows the same
    // confirmation — so an attacker can't probe by looking for
    // different error toasts.
    const conf = await screen.findByTestId("forgot-password-confirmation");
    expect(conf).toHaveTextContent(/if an account exists for that email/i);
  });
});
