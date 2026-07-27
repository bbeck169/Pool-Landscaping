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
 *
 * Feb 2026 update — converted from vitest ➔ Jest so it runs under
 * the same runner as the rest of the phase34 suite (was blocking
 * `yarn test` exit-code 0 with a SyntaxError on the vitest import).
 */
import "@testing-library/jest-dom";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

// react-router-dom v7 ships ESM and Jest can't resolve it under CJS
// transform without extra config — mock the two hooks the page uses.
jest.mock("react-router-dom", () => ({
  useNavigate: () => jest.fn(),
  Link: ({ children, ...rest }) => {
    const React = require("react");
    return React.createElement("a", rest, children);
  },
}), { virtual: true });

// api.post is mocked so the test never hits the network — we only
// care about the surface behaviour.
jest.mock("@/api", () => ({
  api: { post: jest.fn().mockResolvedValue({ ok: true }) },
}));

// eslint-disable-next-line import/first
import ForgotPassword from "@/pages/ForgotPassword";
// eslint-disable-next-line import/first
import { api } from "@/api";

const renderPage = () => render(<ForgotPassword />);

describe("/forgot-password — real form (Task O)", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    // Re-arm the default resolved mock after clearAllMocks wiped
    // the mockResolvedValue configured at module top.
    api.post.mockResolvedValue({ ok: true });
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
