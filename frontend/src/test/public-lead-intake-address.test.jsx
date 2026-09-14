/**
 * Feb-2026 · Public "Get a Free Quote" lead form — street-address
 * capture + stable submission keys.
 *
 * Locks the acceptance contract:
 *   1. Visible required Street Address input with the standard
 *      testids + autocomplete + aria wiring.
 *   2. Empty submit → error surfaces via
 *      ``lead-form-address-error`` and blocks the POST.
 *   3. Valid submit → POST body carries ``address`` +
 *      ``service_interest`` keys verbatim (plus ``service_address``
 *      for backwards-compat with legacy extractors).
 *   4. Stable ``lead-form-service-interest`` hidden input carries
 *      the selected interest.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("sonner", () => ({
  Toaster: () => null,
  toast:   { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));
vi.mock("@/components/marketing/ThemedFormShell", () => ({
  default: ({ children }) => <div>{children}</div>,
}));

import PublicLeadIntake from "@/pages/public/PublicLeadIntake";


function _wrap(ui) { return <MemoryRouter>{ui}</MemoryRouter>; }


beforeEach(() => {
  global.fetch = vi.fn();
});
afterEach(() => {
  vi.clearAllMocks();
});


describe("PublicLeadIntake · Street Address capture", () => {
  it("renders the Street Address input with the required a11y wiring", () => {
    render(_wrap(<PublicLeadIntake />));
    const input = screen.getByTestId("lead-form-address-input");
    expect(input).toBeTruthy();
    // Semantic contract — HTML autofill + a11y + required.
    expect(input.getAttribute("id")).toBe("address");
    expect(input.getAttribute("name")).toBe("address");
    expect(input.getAttribute("autocomplete")).toBe("street-address");
    expect(input.getAttribute("aria-label")).toBe("Street Address");
    expect(input.hasAttribute("required")).toBe(true);
    expect(Number(input.getAttribute("minlength"))).toBe(3);
    // Visible label uses "Street Address" copy.
    expect(document.querySelector("label[for=\"address\"]").textContent)
      .toMatch(/Street Address/);
    // Stable hidden field for ``service_interest``.
    const svc = screen.getByTestId("lead-form-service-interest");
    expect(svc.getAttribute("name")).toBe("service_interest");
    expect(svc.value).toBe("Pool");
  });

  it("submitting without an address surfaces the address-error + does NOT POST", async () => {
    render(_wrap(<PublicLeadIntake />));
    // Fill name + email so the ``name`` guard passes and the address
    // check is the reason for the block.
    fireEvent.change(screen.getByTestId("public-lead-name"),
                       { target: { value: "Jane Doe" } });
    fireEvent.change(screen.getByTestId("public-lead-email"),
                       { target: { value: "jane@example.com" } });
    // Bypass browser's native ``required`` gate by clicking submit
    // programmatically via fireEvent.submit on the form. React
    // runs the handler; the client-side check fires the error.
    const form = document.querySelector("form[data-testid=\"public-lead-form\"]");
    await act(async () => { fireEvent.submit(form); });
    // Error banner surfaces.
    expect(await screen.findByTestId("lead-form-address-error"))
      .toBeTruthy();
    // No POST fired.
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it("POSTs both ``address`` + ``service_interest`` verbatim on a valid submit", async () => {
    global.fetch.mockResolvedValue({ ok: true, text: async () => "" });
    render(_wrap(<PublicLeadIntake />));
    fireEvent.change(screen.getByTestId("public-lead-name"),
                       { target: { value: "Jane Doe" } });
    fireEvent.change(screen.getByTestId("public-lead-email"),
                       { target: { value: "jane@example.com" } });
    fireEvent.change(screen.getByTestId("lead-form-address-input"),
                       { target: { value: "123 Main St, Peoria AZ" } });
    // Flip the interest to ``Both`` so the wire value differs from
    // the default and the test asserts the actual selection lands
    // on the payload.
    fireEvent.click(screen.getByTestId("public-lead-interest-both"));
    const form = document.querySelector("form[data-testid=\"public-lead-form\"]");
    await act(async () => { fireEvent.submit(form); });
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
    const [, opts] = global.fetch.mock.calls[0];
    const body = JSON.parse(opts.body);
    expect(body.address).toBe("123 Main St, Peoria AZ");
    // Backwards-compat: legacy alias emitted alongside the modern key.
    expect(body.service_address).toBe("123 Main St, Peoria AZ");
    expect(body.service_interest).toBe("Both");
    expect(body.name).toBe("Jane Doe");
  });

  it("clears the address-error as soon as the visitor types a valid value", async () => {
    render(_wrap(<PublicLeadIntake />));
    fireEvent.change(screen.getByTestId("public-lead-name"),
                       { target: { value: "Jane" } });
    fireEvent.change(screen.getByTestId("public-lead-email"),
                       { target: { value: "j@ex.com" } });
    const form = document.querySelector("form[data-testid=\"public-lead-form\"]");
    await act(async () => { fireEvent.submit(form); });
    expect(await screen.findByTestId("lead-form-address-error")).toBeTruthy();
    fireEvent.change(screen.getByTestId("lead-form-address-input"),
                       { target: { value: "123 Main" } });
    await waitFor(() =>
      expect(screen.queryByTestId("lead-form-address-error")).toBeNull(),
    );
  });
});
