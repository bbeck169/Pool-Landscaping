/**
 * Ticket Z1 · Feb-2026 — Lead Profile page vitest.
 *
 * Component-level tests cover the full LeadProfile render path
 * with ``@/api`` + ``sonner`` + ``@/auth`` + ``@/components/ui/
 * confirm-dialog`` mocked.  Row-click wiring on LeadsDashboardPage
 * is NOT directly tested here (dashboard is 1400 lines + has
 * many parent deps); the dashboard change is a one-liner
 * ``onClick={() => navigate(...)}``) swap and will be covered
 * by Z2's broader dashboard-interaction tests.
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

import LeadProfile from "@/pages/leads/LeadProfile";
import { api } from "@/api";


const FIXTURE_LEAD = {
  id: "lead-123",
  name: "Anil Biswal",
  email: "anil@example.com",
  phone: "+1 480-555-0199",
  service_address: "Lot 115 · Aloravita South Summit · Peoria AZ",
  status: "new",
  source: "website_form",
  notes: "Initial outreach pending.",
  created_at: "2026-02-10T14:00:00Z",
  meta: { submission_id: "sub-xyz" },
};

const FIXTURE_SUBMISSION = {
  submission_id: "sub-xyz",
  values: {
    services_requested: (
      "Looking for a site consultation and pool design quote "
      + "for Lot 115 in Aloravita South Summit. Family of 4, "
      + "would also appreciate landscape ideas tied to the pool "
      + "footprint. Available weekends."
    ),
    budget_range: "$75k-$120k",
  },
};


function _renderAt(path = "/leads/lead-123") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/leads/:id" element={<LeadProfile />} />
      </Routes>
    </MemoryRouter>,
  );
}


afterEach(() => { cleanup(); vi.clearAllMocks(); });


describe("LeadProfile · Ticket Z1", () => {
  it("renders at /leads/:id with hero name, status pill, "
     + "breadcrumb and back link", async () => {
    api.get.mockImplementation((url) => {
      if (url.includes("/raw-submission")) {
        return Promise.resolve(FIXTURE_SUBMISSION);
      }
      return Promise.resolve(FIXTURE_LEAD);
    });
    _renderAt();
    expect(await screen.findByTestId("lead-profile-name"))
      .toHaveTextContent(/Anil Biswal/i);
    expect(screen.getByTestId("lead-profile-status-pill"))
      .toHaveTextContent(/New/);
    expect(screen.getByTestId("lead-profile-breadcrumb"))
      .toHaveTextContent(/Home/i);
    expect(screen.getByTestId("lead-profile-breadcrumb"))
      .toHaveTextContent(/Leads/i);
    expect(screen.getByTestId("lead-profile-back-link"))
      .toHaveTextContent(/All leads/i);
  });

  it("renders the 4-card info grid (phone / email / address / "
     + "requested service)", async () => {
    api.get.mockImplementation((url) =>
      url.includes("raw-submission")
        ? Promise.resolve(FIXTURE_SUBMISSION)
        : Promise.resolve(FIXTURE_LEAD));
    _renderAt();
    await screen.findByTestId("lead-profile-info-grid");
    for (const t of [
      "lead-profile-phone-card",
      "lead-profile-email-card",
      "lead-profile-address-card",
      "lead-profile-requested-service-card",
    ]) {
      expect(screen.getByTestId(t)).toBeInTheDocument();
    }
    expect(screen.getByTestId("lead-profile-phone-card-value"))
      .toHaveTextContent("+1 480-555-0199");
    expect(screen.getByTestId("lead-profile-email-card-value"))
      .toHaveTextContent("anil@example.com");
    expect(screen.getByTestId("lead-profile-address-card-value"))
      .toHaveTextContent(/Aloravita South Summit/);
  });

  it("Requested Service card renders submitted form text verbatim "
     + "(multi-sentence paragraph) with NO truncation", async () => {
    api.get.mockImplementation((url) =>
      url.includes("raw-submission")
        ? Promise.resolve(FIXTURE_SUBMISSION)
        : Promise.resolve(FIXTURE_LEAD));
    _renderAt();
    const card = await screen.findByTestId(
      "lead-profile-requested-service-card-value",
    );
    expect(card.textContent).toContain(
      "Looking for a site consultation and pool design quote",
    );
    expect(card.textContent).toContain("Family of 4");
    expect(card.textContent).toContain("Available weekends");
    // Full text present (not truncated with ellipsis).
    expect(card.textContent).not.toContain("…");
  });

  it("Requested Service falls back to '—' when no submission "
     + "(legacy pre-P17 lead)", async () => {
    api.get.mockImplementation((url) => {
      if (url.includes("raw-submission")) {
        return Promise.reject(Object.assign(new Error("not found"),
                                               { status: 404 }));
      }
      return Promise.resolve({
        ...FIXTURE_LEAD, meta: {},  // no submission_id
      });
    });
    _renderAt();
    const card = await screen.findByTestId(
      "lead-profile-requested-service-card-value",
    );
    expect(card.textContent.trim()).toBe("—");
  });

  it("Status select + Notes textarea save via PUT /leads/{id}",
     async () => {
    api.get.mockImplementation((url) =>
      url.includes("raw-submission")
        ? Promise.resolve(FIXTURE_SUBMISSION)
        : Promise.resolve(FIXTURE_LEAD));
    api.put.mockResolvedValue({});
    _renderAt();
    await screen.findByTestId("lead-profile-notes-textarea");
    fireEvent.change(screen.getByTestId("lead-profile-status-select"),
                      { target: { value: "contacted" } });
    fireEvent.change(screen.getByTestId("lead-profile-notes-textarea"),
                      { target: { value: "Left voicemail." } });
    fireEvent.click(screen.getByTestId("lead-profile-save-btn"));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(
      "/leads/lead-123",
      { status: "contacted", notes: "Left voicemail." },
    ));
  });

  it("Convert-to-customer button present + wired to "
     + "POST /leads/{id}/convert", async () => {
    api.get.mockImplementation((url) =>
      url.includes("raw-submission")
        ? Promise.resolve(FIXTURE_SUBMISSION)
        : Promise.resolve(FIXTURE_LEAD));
    api.post.mockResolvedValue({ customer_id: "cust-999" });
    _renderAt();
    const btn = await screen.findByTestId("lead-profile-convert-btn");
    expect(btn).toBeInTheDocument();
    fireEvent.click(btn);
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      "/leads/lead-123/convert", {},
    ));
  });

  it("Footer bar renders Z2 Send ▾ + Z3 + Create ▾ + Z4 Overview ▾ "
     + "all as live triggers (Z3 ship — no more disabled placeholders)",
     async () => {
    api.get.mockImplementation((url) =>
      url.includes("raw-submission")
        ? Promise.resolve(FIXTURE_SUBMISSION)
        : Promise.resolve(FIXTURE_LEAD));
    _renderAt();
    const footer = await screen.findByTestId("lead-profile-footer-bar");
    expect(footer).toBeInTheDocument();
    // All three footer buttons are now live triggers.
    const sendBtn = screen.getByTestId("lead-profile-footer-send-btn");
    const createBtn = screen.getByTestId("lead-profile-footer-create-btn");
    const overviewBtn = screen.getByTestId("lead-profile-footer-overview-btn");
    expect(sendBtn).not.toBeDisabled();
    expect(createBtn).not.toBeDisabled();
    expect(overviewBtn).not.toBeDisabled();
    expect(sendBtn.getAttribute("title"))
      .toBe("Send SMS or Email to this lead");
    // No `data-phase-placeholder` markers remain.
    expect(createBtn).not.toHaveAttribute("data-phase-placeholder");
    expect(overviewBtn).not.toHaveAttribute("data-phase-placeholder");
  });

  it("Edit button is present (routes to /leads?edit=<id>)", async () => {
    api.get.mockImplementation((url) =>
      url.includes("raw-submission")
        ? Promise.resolve(FIXTURE_SUBMISSION)
        : Promise.resolve(FIXTURE_LEAD));
    _renderAt();
    const edit = await screen.findByTestId("lead-profile-edit-link");
    expect(edit.getAttribute("href")).toBe("/leads?edit=lead-123");
  });

  it("not-found when GET /leads/{id} fails", async () => {
    api.get.mockRejectedValueOnce(
      Object.assign(new Error("not found"), { status: 404 }),
    );
    _renderAt();
    expect(await screen.findByTestId("lead-profile-not-found"))
      .toBeInTheDocument();
  });

  it("Requested Service picks ``message`` key when "
     + "``services_requested`` is absent (legacy form shape)",
     async () => {
    api.get.mockImplementation((url) => {
      if (url.includes("raw-submission")) {
        return Promise.resolve({
          submission_id: "sub-legacy",
          values: {
            message: "Need pool resurface quote ASAP.",
          },
        });
      }
      return Promise.resolve(FIXTURE_LEAD);
    });
    _renderAt();
    const card = await screen.findByTestId(
      "lead-profile-requested-service-card-value",
    );
    expect(card.textContent).toContain("Need pool resurface quote ASAP.");
  });
});
