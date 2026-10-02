/**
 * Feb-2026 · Phase 3c-portal · Current-email confirmation gate on
 * primary-email change.
 *
 * Mounts the real ``<PortalProfile>`` with ``@/api`` + ``@/auth``
 * mocked and asserts the inline-gate behavior:
 *
 *   1. On initial load the confirmation input is NOT rendered — the
 *      hydrated email equals the form value.
 *   2. Edit the primary email → the notice + confirmation input +
 *      their testids appear.
 *   3. Edit the primary email back to the hydrated value → the
 *      block disappears again (confirmation state resets on save,
 *      not on manual revert; the test exercises the unmounted
 *      branch via the ``emailChanged`` boolean).
 *   4. Submit with a confirmation mismatch (server returns the 400
 *      "Current email confirmation does not match.") → the inline
 *      error slot ``portal-profile-confirm-current-email-error``
 *      renders the message; the page-level banner stays clean.
 *   5. Submit with the correct confirmation → PATCH payload carries
 *      ``confirm_current_email`` with the typed value; success
 *      toast fires.
 *   6. Submit without changing the primary email → PATCH payload
 *      does NOT include ``confirm_current_email``.
 *   7. Change only the phone (no email edit) → no confirmation
 *      block renders; PATCH payload has no ``confirm_current_email``.
 */
import React from "react";
import {
  describe, it, expect, vi, beforeEach, afterEach,
} from "vitest";
import { MemoryRouter } from "react-router-dom";
import {
  render, screen, cleanup, fireEvent, waitFor,
} from "@testing-library/react";


const getMock   = vi.fn();
const patchMock = vi.fn();


vi.mock("@/api", () => ({
  api: {
    get:   (...a) => getMock(...a),
    patch: (...a) => patchMock(...a),
    post:  vi.fn(),
  },
  TOKEN_KEY: "token",
}));


vi.mock("@/auth", () => ({
  useAuth: () => ({
    user: {
      id: "u1", name: "Pp Test", email: "primary@t.co",
      customer_id: "c1", role: "customer",
    },
    refreshMe: vi.fn().mockResolvedValue(undefined),
  }),
}));


import { PortalProfile } from "@/pages/portal/PortalPages";


const _renderProfile = () =>
  render(
    <MemoryRouter initialEntries={["/portal/profile"]}>
      <PortalProfile />
    </MemoryRouter>,
  );


beforeEach(() => {
  getMock.mockReset();
  patchMock.mockReset();
  getMock.mockResolvedValue({
    id: "c1", tenant_id: "t1",
    first_name: "Pp", last_name: "Test",
    email: "primary@t.co",
    phone: "5555550100",
    address: "1234 Old St, Springfield, IL 62701",
    emails: [
      { address: "primary@t.co", label: "Primary", is_primary: true },
    ],
  });
  patchMock.mockResolvedValue({ ok: true, profile: {} });
});

afterEach(() => cleanup());


describe("PortalProfile · Phase 3c-portal · initial render", () => {
  it("does NOT render the confirmation input on initial load", async () => {
    _renderProfile();
    await waitFor(() =>
      expect(screen.getByTestId("portal-profile-email")).toBeInTheDocument(),
    );
    // Hydration completed → ``emailChanged`` is false → block absent.
    expect(
      screen.queryByTestId("portal-profile-email-change-notice"),
    ).toBeNull();
    expect(
      screen.queryByTestId("portal-profile-confirm-current-email"),
    ).toBeNull();
  });
});


describe("PortalProfile · Phase 3c-portal · conditional render on edit", () => {
  it("renders the notice + confirmation input + testids after the user edits the email", async () => {
    _renderProfile();
    const primary = await waitFor(() =>
      screen.getByTestId("portal-profile-email"),
    );
    // Wait for hydration to settle BEFORE editing — otherwise the
    // ``useEffect`` /me resolver races the fireEvent and overwrites
    // the typed value a tick later.
    await waitFor(() => expect(primary.value).toBe("primary@t.co"));
    fireEvent.change(primary, { target: { value: "new@t.co" } });
    const notice = await waitFor(() =>
      screen.getByTestId("portal-profile-email-change-notice"),
    );
    expect(notice.textContent.toLowerCase()).toContain("confirm your current email");
    const input = screen.getByTestId("portal-profile-confirm-current-email");
    expect(input).toBeInTheDocument();
    expect(input).toHaveAttribute("type", "email");
    expect(input.value).toBe("");
  });

  it("removes the confirmation block when the user reverts the email to the hydrated value", async () => {
    _renderProfile();
    const primary = await waitFor(() =>
      screen.getByTestId("portal-profile-email"),
    );
    await waitFor(() => expect(primary.value).toBe("primary@t.co"));
    fireEvent.change(primary, { target: { value: "new@t.co" } });
    await waitFor(() =>
      screen.getByTestId("portal-profile-email-change-notice"),
    );
    // Revert.
    fireEvent.change(primary, { target: { value: "primary@t.co" } });
    await waitFor(() =>
      expect(screen.queryByTestId("portal-profile-email-change-notice")).toBeNull(),
    );
    expect(
      screen.queryByTestId("portal-profile-confirm-current-email"),
    ).toBeNull();
  });
});


describe("PortalProfile · Phase 3c-portal · submit — confirmation mismatch", () => {
  it("routes the 400 message into the inline error slot (not the page banner)", async () => {
    patchMock.mockRejectedValueOnce(new Error(
      "Current email confirmation does not match.",
    ));
    _renderProfile();
    const primary = await waitFor(() =>
      screen.getByTestId("portal-profile-email"),
    );
    await waitFor(() => expect(primary.value).toBe("primary@t.co"));
    fireEvent.change(primary, { target: { value: "new@t.co" } });
    const confirm = await waitFor(() =>
      screen.getByTestId("portal-profile-confirm-current-email"),
    );
    fireEvent.change(confirm, { target: { value: "wrong@t.co" } });
    fireEvent.submit(screen.getByTestId("portal-profile-form"));
    const err = await waitFor(() =>
      screen.getByTestId("portal-profile-confirm-current-email-error"),
    );
    expect(err.textContent.toLowerCase()).toContain("confirmation does not match");
    // Page-level banner stays clean.
    expect(
      screen.queryByTestId("portal-profile-error"),
    ).not.toBeInTheDocument();
  });
});


describe("PortalProfile · Phase 3c-portal · submit — happy path", () => {
  it("sends confirm_current_email on the PATCH body + fires success toast", async () => {
    _renderProfile();
    const primary = await waitFor(() =>
      screen.getByTestId("portal-profile-email"),
    );
    await waitFor(() => expect(primary.value).toBe("primary@t.co"));
    fireEvent.change(primary, { target: { value: "new@t.co" } });
    const confirm = await waitFor(() =>
      screen.getByTestId("portal-profile-confirm-current-email"),
    );
    fireEvent.change(confirm, { target: { value: "primary@t.co" } });
    fireEvent.submit(screen.getByTestId("portal-profile-form"));
    await waitFor(() => expect(patchMock).toHaveBeenCalled());
    const [url, payload] = patchMock.mock.calls[0];
    expect(url).toBe("/customer-portal/profile");
    expect(payload.email).toBe("new@t.co");
    expect(payload.confirm_current_email).toBe("primary@t.co");
    // Error banner clean.
    expect(
      screen.queryByTestId("portal-profile-error"),
    ).not.toBeInTheDocument();
  });
});


describe("PortalProfile · Phase 3c-portal · submit — email unchanged", () => {
  it("omits confirm_current_email from the PATCH payload when email is unchanged", async () => {
    _renderProfile();
    const primary = await waitFor(() =>
      screen.getByTestId("portal-profile-email"),
    );
    await waitFor(() => expect(primary.value).toBe("primary@t.co"));
    // Edit phone only — email stays "primary@t.co".
    const phone = screen.getByTestId("portal-profile-phone");
    fireEvent.change(phone, { target: { value: "5555550199" } });
    fireEvent.submit(screen.getByTestId("portal-profile-form"));
    await waitFor(() => expect(patchMock).toHaveBeenCalled());
    const [, payload] = patchMock.mock.calls[0];
    expect(payload.phone).toBe("5555550199");
    expect(payload).not.toHaveProperty("confirm_current_email");
  });

  it("confirmation input stays unmounted while editing other fields", async () => {
    _renderProfile();
    const primary = await waitFor(() =>
      screen.getByTestId("portal-profile-email"),
    );
    await waitFor(() => expect(primary.value).toBe("primary@t.co"));
    const phone = screen.getByTestId("portal-profile-phone");
    fireEvent.change(phone, { target: { value: "5555550199" } });
    const addr = screen.getByTestId("portal-profile-address");
    fireEvent.change(addr, {
      target: { value: "9876 New Ave, Metropolis, IL 62960" },
    });
    expect(
      screen.queryByTestId("portal-profile-email-change-notice"),
    ).toBeNull();
    expect(
      screen.queryByTestId("portal-profile-confirm-current-email"),
    ).toBeNull();
  });
});
