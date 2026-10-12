/**
 * Feb-2026 · Portal Edit Profile Modal — regression spec.
 *
 * Locks the hero-banner-opened quick-edit modal behavior:
 *   1. Modal renders when ``open={true}`` and hides when ``open={false}``.
 *   2. Four fields pre-fill from ``initial`` (first/last/phone/email).
 *   3. Client validation blocks submit on empty fields + bad email +
 *      <10-digit phone.
 *   4. ``Confirm current email`` input appears dynamically ONLY when
 *      the typed email differs from the pre-fill.
 *   5. Successful PATCH triggers ``onSaved`` and ``onClose``.
 *   6. Server ``confirmation-mismatch`` branches surface as a
 *      field-level error on the confirm-current-email input.
 *   7. ``Edit full profile →`` link closes the modal and navigates
 *      to ``/portal/profile``.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


const { patchSpy, navigateSpy, toastSuccessSpy } = vi.hoisted(() => ({
  patchSpy: vi.fn(),
  navigateSpy: vi.fn(),
  toastSuccessSpy: vi.fn(),
}));


vi.mock("@/api", () => ({
  TOKEN_KEY: "token",
  api_base: () => "http://localhost/api",
  api: {
    get: vi.fn(),
    post: vi.fn(),
    patch: (...a) => patchSpy(...a),
    del: vi.fn(),
  },
}));


vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return {
    ...actual,
    useNavigate: () => navigateSpy,
  };
});


vi.mock("sonner", () => ({
  toast: {
    success: (...a) => toastSuccessSpy(...a),
    error: vi.fn(),
  },
}));


import PortalEditProfileModal
  from "@/components/portal/PortalEditProfileModal";


function _render({ open = true, initial = {}, onSaved, onClose } = {}) {
  return render(
    <MemoryRouter>
      <PortalEditProfileModal
        open={open}
        onClose={onClose || vi.fn()}
        initial={initial}
        onSaved={onSaved || vi.fn()}
      />
    </MemoryRouter>,
  );
}


const _initial = {
  first_name: "Preview",
  last_name:  "Customer0143",
  phone:      "555-010-1143",
  email:      "customer@aquaterra.com",
};


beforeEach(() => {
  patchSpy.mockReset();
  navigateSpy.mockReset();
  toastSuccessSpy.mockReset();
});


describe("PortalEditProfileModal", () => {
  it("does not render when open=false", () => {
    _render({ open: false, initial: _initial });
    expect(screen.queryByTestId("portal-edit-profile-modal")).toBeNull();
  });

  it("renders modal + four pre-filled inputs when open=true", () => {
    _render({ initial: _initial });
    expect(screen.getByTestId("portal-edit-profile-modal")).toBeTruthy();
    expect(screen.getByTestId("portal-edit-profile-first-name").value)
      .toBe("Preview");
    expect(screen.getByTestId("portal-edit-profile-last-name").value)
      .toBe("Customer0143");
    expect(screen.getByTestId("portal-edit-profile-phone").value)
      .toBe("555-010-1143");
    expect(screen.getByTestId("portal-edit-profile-email").value)
      .toBe("customer@aquaterra.com");
    // Confirm-current-email is hidden when email matches initial.
    expect(screen.queryByTestId("portal-edit-profile-confirm-current-email"))
      .toBeNull();
  });

  it("blocks submit and shows field errors on empty required fields", async () => {
    _render({ initial: _initial });
    fireEvent.change(screen.getByTestId("portal-edit-profile-first-name"),
                      { target: { value: "" } });
    fireEvent.submit(screen.getByTestId("portal-edit-profile-form"));
    await waitFor(() => {
      expect(screen.getByTestId("portal-edit-profile-first-name-error"))
        .toBeTruthy();
    });
    expect(patchSpy).not.toHaveBeenCalled();
  });

  it("blocks submit on malformed email and <10-digit phone", async () => {
    _render({ initial: _initial });
    fireEvent.change(screen.getByTestId("portal-edit-profile-email"),
                      { target: { value: "not-an-email" } });
    fireEvent.change(screen.getByTestId("portal-edit-profile-phone"),
                      { target: { value: "123" } });
    fireEvent.submit(screen.getByTestId("portal-edit-profile-form"));
    await waitFor(() => {
      expect(screen.getByTestId("portal-edit-profile-email-error"))
        .toBeTruthy();
      expect(screen.getByTestId("portal-edit-profile-phone-error"))
        .toBeTruthy();
    });
    expect(patchSpy).not.toHaveBeenCalled();
  });

  it("reveals Confirm current email dynamically when email diverges", async () => {
    _render({ initial: _initial });
    expect(screen.queryByTestId("portal-edit-profile-confirm-current-email"))
      .toBeNull();
    fireEvent.change(screen.getByTestId("portal-edit-profile-email"),
                      { target: { value: "new@aquaterra.com" } });
    expect(screen.getByTestId("portal-edit-profile-confirm-current-email"))
      .toBeTruthy();
  });

  it("submits only the 4 fields on happy path, fires onSaved + onClose, toasts success", async () => {
    patchSpy.mockResolvedValue({ ok: true });
    const onSaved = vi.fn();
    const onClose = vi.fn();
    _render({ initial: _initial, onSaved, onClose });
    fireEvent.submit(screen.getByTestId("portal-edit-profile-form"));
    await waitFor(() => expect(patchSpy).toHaveBeenCalled());
    const [path, body] = patchSpy.mock.calls[0];
    expect(path).toBe("/customer-portal/profile");
    expect(body).toEqual({
      first_name: "Preview",
      last_name:  "Customer0143",
      phone:      "555-010-1143",
      email:      "customer@aquaterra.com",
    });
    // Email unchanged → no confirm_current_email field in payload.
    expect(body.confirm_current_email).toBeUndefined();
    expect(onSaved).toHaveBeenCalledWith({ ok: true });
    expect(toastSuccessSpy).toHaveBeenCalledWith("Profile updated.");
    // onClose fires after the 350ms close delay.
    await waitFor(() => expect(onClose).toHaveBeenCalled(), { timeout: 1500 });
  });

  it("submits with confirm_current_email when email changed", async () => {
    patchSpy.mockResolvedValue({ ok: true });
    _render({ initial: _initial });
    fireEvent.change(screen.getByTestId("portal-edit-profile-email"),
                      { target: { value: "new@aquaterra.com" } });
    fireEvent.change(
      screen.getByTestId("portal-edit-profile-confirm-current-email"),
      { target: { value: "customer@aquaterra.com" } },
    );
    fireEvent.submit(screen.getByTestId("portal-edit-profile-form"));
    await waitFor(() => expect(patchSpy).toHaveBeenCalled());
    const [, body] = patchSpy.mock.calls[0];
    expect(body.email).toBe("new@aquaterra.com");
    expect(body.confirm_current_email).toBe("customer@aquaterra.com");
  });

  it("surfaces confirmation-mismatch as a field-level error on the confirm input", async () => {
    patchSpy.mockRejectedValue(new Error("confirmation-mismatch"));
    _render({ initial: _initial });
    fireEvent.change(screen.getByTestId("portal-edit-profile-email"),
                      { target: { value: "new@aquaterra.com" } });
    fireEvent.change(
      screen.getByTestId("portal-edit-profile-confirm-current-email"),
      { target: { value: "wrong@aquaterra.com" } },
    );
    fireEvent.submit(screen.getByTestId("portal-edit-profile-form"));
    await waitFor(() => {
      expect(screen.getByTestId(
        "portal-edit-profile-confirm-current-email-error",
      )).toBeTruthy();
    });
  });

  it("Edit full profile link navigates to /portal/profile and closes the modal", async () => {
    const onClose = vi.fn();
    _render({ initial: _initial, onClose });
    fireEvent.click(screen.getByTestId("portal-edit-profile-full-profile-link"));
    expect(onClose).toHaveBeenCalled();
    expect(navigateSpy).toHaveBeenCalledWith("/portal/profile");
  });
});
