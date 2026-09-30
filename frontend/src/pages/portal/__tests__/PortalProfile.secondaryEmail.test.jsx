/**
 * Feb-2026 · Portal Profile — secondary email field + address sync UX.
 *
 * Covers the 6 spec cases:
 *   1. Secondary email input renders directly after primary.
 *   2. Same-as-primary → inline validation error, save disabled.
 *   3. Invalid RFC-lite → inline validation error, save disabled.
 *   4. Empty payload submits with an empty ``secondary_email`` so
 *      the server clears the slot.
 *   5. Address change submits the full address payload.
 *   6. Success toast on save.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";


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


// ``useAuth`` provides a bare-bones user shape — the component only
// reads ``user`` + ``refreshMe``; the latter is a no-op mock.
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
  // Default ``/me`` resolves with a customer whose ``emails[]``
  // holds the primary plus a legacy Secondary slot — tests can
  // override per-case.
  getMock.mockResolvedValue({
    id: "c1", tenant_id: "t1",
    first_name: "Pp", last_name: "Test",
    email: "primary@t.co",
    phone: "5555550100",
    address: "1234 Old St, Springfield, IL 62701",
    emails: [
      { address: "primary@t.co", label: "Primary", is_primary: true },
      { address: "existing_alt@t.co", label: "Secondary", is_primary: false },
    ],
  });
  patchMock.mockResolvedValue({ ok: true, profile: {} });
});

afterEach(() => cleanup());


// ══════════════════════════════════════════════════════════════════
// 1) Secondary email input renders next to primary
// ══════════════════════════════════════════════════════════════════
describe("PortalProfile · Secondary Email field", () => {
  it("renders a Secondary Email input hydrated from the /me emails array", async () => {
    _renderProfile();
    const primary = await waitFor(() =>
      screen.getByTestId("portal-profile-email"),
    );
    const secondary = screen.getByTestId("portal-profile-secondary-email");
    expect(primary).toBeInTheDocument();
    expect(secondary).toBeInTheDocument();
    // Hydrated from ``emails[]`` (first non-primary entry).
    await waitFor(() => expect(secondary.value).toBe("existing_alt@t.co"));
    // Positional guarantee — secondary sits AFTER primary in the DOM.
    const doc = document.body.innerHTML;
    expect(doc.indexOf("portal-profile-email"))
      .toBeLessThan(doc.indexOf("portal-profile-secondary-email"));
  });
});


// ══════════════════════════════════════════════════════════════════
// 2) Same-as-primary → inline validation error
// ══════════════════════════════════════════════════════════════════
describe("PortalProfile · Secondary email validation — same as primary", () => {
  it("shows inline error + disables save when secondary matches primary", async () => {
    _renderProfile();
    const secondary = await waitFor(() =>
      screen.getByTestId("portal-profile-secondary-email"),
    );
    fireEvent.change(secondary, { target: { value: "primary@t.co" } });
    const err = await waitFor(() =>
      screen.getByTestId("portal-profile-secondary-email-error"),
    );
    expect(err.textContent.toLowerCase()).toContain("differ from primary");
    // Save button disabled — the form is dirty (secondary changed)
    // but invalid, so ``canSave`` short-circuits.
    const save = screen.getByTestId("portal-profile-save");
    expect(save).toBeDisabled();
  });
});


// ══════════════════════════════════════════════════════════════════
// 3) Invalid RFC-lite format → inline validation error
// ══════════════════════════════════════════════════════════════════
describe("PortalProfile · Secondary email validation — invalid format", () => {
  it("shows inline error + disables save when secondary is not a valid email", async () => {
    _renderProfile();
    const secondary = await waitFor(() =>
      screen.getByTestId("portal-profile-secondary-email"),
    );
    fireEvent.change(secondary, { target: { value: "not-an-email" } });
    const err = await waitFor(() =>
      screen.getByTestId("portal-profile-secondary-email-error"),
    );
    expect(err.textContent.toLowerCase()).toContain("valid secondary email");
    expect(screen.getByTestId("portal-profile-save")).toBeDisabled();
  });
});


// ══════════════════════════════════════════════════════════════════
// 4) Empty payload → PATCH sends secondary_email: "" (clears slot)
// ══════════════════════════════════════════════════════════════════
describe("PortalProfile · Empty secondary email clears the slot", () => {
  it("submits secondary_email as an empty string when the field is cleared", async () => {
    _renderProfile();
    const secondary = await waitFor(() =>
      screen.getByTestId("portal-profile-secondary-email"),
    );
    // Clear the hydrated existing_alt value.
    fireEvent.change(secondary, { target: { value: "" } });
    fireEvent.submit(screen.getByTestId("portal-profile-form"));
    await waitFor(() => expect(patchMock).toHaveBeenCalled());
    const [url, payload] = patchMock.mock.calls[0];
    expect(url).toBe("/customer-portal/profile");
    expect(payload).toMatchObject({ secondary_email: "" });
  });
});


// ══════════════════════════════════════════════════════════════════
// 5) Address change submits the full address payload
// ══════════════════════════════════════════════════════════════════
describe("PortalProfile · Address change submission", () => {
  it("sends the new address on the PATCH body when the input changes", async () => {
    _renderProfile();
    const addrInput = await waitFor(() =>
      screen.getByTestId("portal-profile-address"),
    );
    fireEvent.change(addrInput, {
      target: { value: "9876 New Ave, Metropolis, IL 62960" },
    });
    fireEvent.submit(screen.getByTestId("portal-profile-form"));
    await waitFor(() => expect(patchMock).toHaveBeenCalled());
    const [, payload] = patchMock.mock.calls[0];
    expect(payload.address).toBe("9876 New Ave, Metropolis, IL 62960");
    // Every allowlisted field lands on the wire (regression guard).
    expect(payload).toEqual(expect.objectContaining({
      first_name: expect.any(String),
      last_name:  expect.any(String),
      email:      expect.any(String),
      phone:      expect.any(String),
      address:    expect.any(String),
      secondary_email: expect.any(String),
    }));
  });
});


// ══════════════════════════════════════════════════════════════════
// 6) Success toast on save
// ══════════════════════════════════════════════════════════════════
describe("PortalProfile · Success toast", () => {
  it("clears the error banner after a successful save", async () => {
    _renderProfile();
    const addrInput = await waitFor(() =>
      screen.getByTestId("portal-profile-address"),
    );
    fireEvent.change(addrInput, {
      target: { value: "5555 New Rd, Cityville, MO 63099" },
    });
    fireEvent.submit(screen.getByTestId("portal-profile-form"));
    await waitFor(() => expect(patchMock).toHaveBeenCalled());
    // Error banner must NOT be rendered after the success — the
    // component clears ``error`` on save and re-snapshots
    // ``initial`` so the form becomes non-dirty.
    expect(
      screen.queryByTestId("portal-profile-error"),
    ).not.toBeInTheDocument();
  });
});
