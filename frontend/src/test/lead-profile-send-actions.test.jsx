/**
 * Ticket Z2 · Feb-2026 — Lead Profile Send ▾ dropdown vitest.
 *
 * Surfaces-only tests for the Send ▾ dropdown wiring on
 * ``/leads/:id``.  Modal internals (payload shape, consent gate,
 * char-counter) stay covered by ``lead-compose-modal.test.jsx``.
 *
 * We assert:
 *   * dropdown toggles open/close on trigger click
 *   * both menu items render (Send SMS + Send Email) when the
 *     lead has phone + email
 *   * each item disables (+ tooltips) when the matching contact
 *     field is empty on the lead
 *   * clicking an item mounts ``LeadComposeModal`` with the
 *     correct ``channel`` prop
 *   * Z3 + Z4 placeholder buttons remain disabled
 */
import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import {
  render, screen, cleanup, fireEvent, waitFor,
} from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";

vi.mock("@/api", () => ({
  api: {
    get: vi.fn(), post: vi.fn(), put: vi.fn(),
    patch: vi.fn(), del: vi.fn(),
  },
}));
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));
vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { id: "u1", role: "admin" } }),
}));
vi.mock("@/components/ui/confirm-dialog", () => ({
  mustConfirm: vi.fn(async () => true),
}));

// LeadComposeModal is mocked to a lightweight surface so we can
// assert mount + channel without exercising the real send flow.
vi.mock("@/pages/leads/LeadComposeModal", () => ({
  __esModule: true,
  default: ({ lead, channel, onClose }) => (
    <div
      data-testid="lead-compose-modal-mock"
      data-channel={channel}
      data-lead-id={lead?.id || ""}
    >
      mock-modal-{channel}
      <button
        type="button"
        onClick={onClose}
        data-testid="lead-compose-modal-mock-close"
      >
        close
      </button>
    </div>
  ),
}));

import LeadProfile from "@/pages/leads/LeadProfile";
import { api } from "@/api";


const BASE_LEAD = {
  id: "lead-z2-1",
  name: "Jamie Rowan",
  email: "jamie@example.com",
  phone: "+1 480-555-0101",
  service_address: "100 Oak St · Phoenix AZ",
  status: "new",
  source: "website_form",
  notes: "",
  created_at: "2026-02-10T14:00:00Z",
  meta: {},
};


function _mountAt(leadDoc) {
  api.get.mockImplementation((url) => {
    if (url.includes("/raw-submission")) return Promise.resolve(null);
    return Promise.resolve(leadDoc);
  });
  return render(
    <MemoryRouter initialEntries={[`/leads/${leadDoc.id}`]}>
      <Routes>
        <Route path="/leads/:id" element={<LeadProfile />} />
      </Routes>
    </MemoryRouter>,
  );
}


afterEach(() => { cleanup(); vi.clearAllMocks(); });


describe("LeadProfile · Ticket Z2 · Send ▾ dropdown", () => {
  it("renders the Send ▾ trigger with menu closed by default",
     async () => {
    _mountAt(BASE_LEAD);
    await screen.findByTestId("lead-profile-footer-send-btn");
    expect(screen.getByTestId("lead-profile-footer-send-btn"))
      .toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByTestId("lead-profile-send-menu"))
      .toBeNull();
  });

  it("opens the menu on click and exposes BOTH Send SMS + Send "
     + "Email items when the lead has phone + email",
     async () => {
    _mountAt(BASE_LEAD);
    const btn = await screen.findByTestId("lead-profile-footer-send-btn");
    fireEvent.click(btn);
    await screen.findByTestId("lead-profile-send-menu");
    const smsItem = screen.getByTestId("lead-profile-send-sms-item");
    const emailItem = screen.getByTestId("lead-profile-send-email-item");
    expect(smsItem).not.toBeDisabled();
    expect(emailItem).not.toBeDisabled();
    expect(smsItem).toHaveAttribute("title", "Send SMS to this lead");
    expect(emailItem).toHaveAttribute("title", "Send email to this lead");
  });

  it("disables Send SMS with 'No phone on file' tooltip when "
     + "lead.phone is empty",
     async () => {
    _mountAt({ ...BASE_LEAD, phone: "" });
    const btn = await screen.findByTestId("lead-profile-footer-send-btn");
    fireEvent.click(btn);
    const smsItem = await screen.findByTestId("lead-profile-send-sms-item");
    expect(smsItem).toBeDisabled();
    expect(smsItem).toHaveAttribute("title", "No phone on file");
  });

  it("disables Send Email with 'No email on file' tooltip when "
     + "lead.email is empty",
     async () => {
    _mountAt({ ...BASE_LEAD, email: "" });
    const btn = await screen.findByTestId("lead-profile-footer-send-btn");
    fireEvent.click(btn);
    const emailItem = await screen.findByTestId(
      "lead-profile-send-email-item",
    );
    expect(emailItem).toBeDisabled();
    expect(emailItem).toHaveAttribute("title", "No email on file");
  });

  it("mounts LeadComposeModal with channel='sms' when Send SMS "
     + "is clicked",
     async () => {
    _mountAt(BASE_LEAD);
    fireEvent.click(await screen.findByTestId(
      "lead-profile-footer-send-btn",
    ));
    fireEvent.click(await screen.findByTestId(
      "lead-profile-send-sms-item",
    ));
    const modal = await screen.findByTestId("lead-compose-modal-mock");
    expect(modal).toHaveAttribute("data-channel", "sms");
    expect(modal).toHaveAttribute("data-lead-id", BASE_LEAD.id);
    // menu closes once an item is picked
    expect(screen.queryByTestId("lead-profile-send-menu")).toBeNull();
  });

  it("mounts LeadComposeModal with channel='email' when Send "
     + "Email is clicked",
     async () => {
    _mountAt(BASE_LEAD);
    fireEvent.click(await screen.findByTestId(
      "lead-profile-footer-send-btn",
    ));
    fireEvent.click(await screen.findByTestId(
      "lead-profile-send-email-item",
    ));
    const modal = await screen.findByTestId("lead-compose-modal-mock");
    expect(modal).toHaveAttribute("data-channel", "email");
  });

  it("unmounts LeadComposeModal when onClose fires", async () => {
    _mountAt(BASE_LEAD);
    fireEvent.click(await screen.findByTestId(
      "lead-profile-footer-send-btn",
    ));
    fireEvent.click(await screen.findByTestId(
      "lead-profile-send-sms-item",
    ));
    await screen.findByTestId("lead-compose-modal-mock");
    fireEvent.click(screen.getByTestId("lead-compose-modal-mock-close"));
    await waitFor(() =>
      expect(screen.queryByTestId("lead-compose-modal-mock")).toBeNull(),
    );
  });

  it("preserves Z3 (+ Create ▾) and Z4 (Overview ▾) placeholder "
     + "buttons as disabled with phase-placeholder markers",
     async () => {
    _mountAt(BASE_LEAD);
    const createBtn = await screen.findByTestId(
      "lead-profile-footer-create-btn",
    );
    const overviewBtn = screen.getByTestId(
      "lead-profile-footer-overview-btn",
    );
    expect(createBtn).toBeDisabled();
    expect(createBtn).toHaveAttribute("data-phase-placeholder", "z3");
    expect(overviewBtn).toBeDisabled();
    expect(overviewBtn).toHaveAttribute("data-phase-placeholder", "z4");
  });
});
