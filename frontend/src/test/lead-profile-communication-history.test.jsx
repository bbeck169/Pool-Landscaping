/**
 * Ticket Z4 · Feb-2026 — Lead Profile Overview ▾ communication
 * history panel vitest.
 *
 * Surfaces covered:
 *   * Overview ▾ toggle opens + closes the inline panel.
 *   * GET /leads/{id}/communications is called with `limit=50`
 *     on first open; items cached across re-opens.
 *   * Loading / empty / error states.
 *   * Row rendering — SMS + email items in DESC order with
 *     channel badge + status + direction label + timestamp.
 *   * Truncate + reveal-on-click on bodies > 400 chars.
 *   * "Load more" pagination fires a second GET with the
 *     returned cursor.
 *   * Z3 (+ Create ▾) placeholder stays disabled.
 *   * Z2 Send ▾ wiring from the previous commit still works.
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
// Compose modal stays mocked — not under test here.
vi.mock("@/pages/leads/LeadComposeModal", () => ({
  __esModule: true,
  default: () => <div data-testid="lead-compose-modal-mock" />,
}));

import LeadProfile from "@/pages/leads/LeadProfile";
import { api } from "@/api";


const LEAD = {
  id: "lead-z4-1",
  name: "Lex Hartman",
  email: "lex@example.com",
  phone: "+1 480-555-0122",
  service_address: "22 Pine Ln · Mesa AZ",
  status: "contacted",
  source: "website_form",
  notes: "",
  created_at: "2026-02-11T15:00:00Z",
  meta: {},
};

const _LONG_BODY = "x".repeat(600); // > 400 char truncation threshold

const PAGE1 = {
  items: [
    {
      id: "comm-1", type: "sms", channel: "sms", direction: "outbound",
      subject: null, body: "Hi Lex, following up on the quote.",
      status: "sent", created_at: "2026-02-12T10:05:00Z",
    },
    {
      id: "comm-2", type: "email", channel: "email", direction: "outbound",
      subject: "Follow-up on your request",
      body: _LONG_BODY,
      status: "sent", created_at: "2026-02-12T09:00:00Z",
    },
    {
      id: "comm-3", type: "sms", channel: "sms", direction: "inbound",
      subject: null, body: "Thanks — sounds good.",
      status: "received", created_at: "2026-02-11T22:14:00Z",
    },
  ],
  next_cursor: "2026-02-11T22:14:00Z|comm-3",
  has_more: true,
};

const PAGE2 = {
  items: [
    {
      id: "comm-4", type: "status_change", channel: null, direction: null,
      subject: null, body: null, status: "contacted",
      created_at: "2026-02-10T18:00:00Z",
    },
  ],
  next_cursor: null,
  has_more: false,
};


function _mount(lead = LEAD) {
  return render(
    <MemoryRouter initialEntries={[`/leads/${lead.id}`]}>
      <Routes>
        <Route path="/leads/:id" element={<LeadProfile />} />
      </Routes>
    </MemoryRouter>,
  );
}


afterEach(() => { cleanup(); vi.clearAllMocks(); });


describe("LeadProfile · Ticket Z4 · Overview ▾ history panel", () => {
  it("panel is hidden by default; Overview ▾ button toggles it open "
     + "and triggers one GET /leads/{id}/communications call",
     async () => {
    api.get.mockImplementation((url) => {
      if (url.includes("/raw-submission")) return Promise.resolve(null);
      if (url.includes("/communications")) return Promise.resolve(PAGE1);
      return Promise.resolve(LEAD);
    });
    _mount();
    await screen.findByTestId("lead-profile-footer-overview-btn");
    // Hidden by default.
    expect(screen.queryByTestId("lead-profile-history-panel")).toBeNull();
    fireEvent.click(screen.getByTestId("lead-profile-footer-overview-btn"));
    const panel = await screen.findByTestId("lead-profile-history-panel");
    expect(panel).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getAllByTestId(/^lead-profile-history-row-(sms|email|status_change)$/))
        .toHaveLength(3),
    );
    // One communications fetch so far.
    const commsCalls = api.get.mock.calls.filter(([u]) =>
      String(u).includes("/communications"));
    expect(commsCalls).toHaveLength(1);
    expect(String(commsCalls[0][0])).toMatch(/limit=50/);
  });

  it("re-opening the panel does NOT trigger a second fetch "
     + "(items cached across re-opens)",
     async () => {
    api.get.mockImplementation((url) => {
      if (url.includes("/raw-submission")) return Promise.resolve(null);
      if (url.includes("/communications")) return Promise.resolve(PAGE1);
      return Promise.resolve(LEAD);
    });
    _mount();
    const toggle = await screen.findByTestId(
      "lead-profile-footer-overview-btn",
    );
    fireEvent.click(toggle);
    await screen.findByTestId("lead-profile-history-panel");
    fireEvent.click(toggle); // close
    await waitFor(() =>
      expect(screen.queryByTestId("lead-profile-history-panel")).toBeNull(),
    );
    fireEvent.click(toggle); // re-open
    await screen.findByTestId("lead-profile-history-panel");
    const commsCalls = api.get.mock.calls.filter(([u]) =>
      String(u).includes("/communications"));
    expect(commsCalls).toHaveLength(1);
  });

  it("renders empty-state copy when the endpoint returns zero items",
     async () => {
    api.get.mockImplementation((url) => {
      if (url.includes("/raw-submission")) return Promise.resolve(null);
      if (url.includes("/communications")) {
        return Promise.resolve({ items: [], has_more: false,
          next_cursor: null });
      }
      return Promise.resolve(LEAD);
    });
    _mount();
    fireEvent.click(await screen.findByTestId(
      "lead-profile-footer-overview-btn",
    ));
    await screen.findByTestId("lead-profile-history-empty");
    expect(screen.getByTestId("lead-profile-history-empty"))
      .toHaveTextContent(/No communication history/i);
  });

  it("renders error-state when the endpoint rejects", async () => {
    api.get.mockImplementation((url) => {
      if (url.includes("/raw-submission")) return Promise.resolve(null);
      if (url.includes("/communications")) {
        return Promise.reject(new Error("boom-500"));
      }
      return Promise.resolve(LEAD);
    });
    _mount();
    fireEvent.click(await screen.findByTestId(
      "lead-profile-footer-overview-btn",
    ));
    const err = await screen.findByTestId("lead-profile-history-error");
    expect(err).toHaveTextContent(/boom-500/);
  });

  it("renders the SMS, email, and inbound-SMS rows with channel "
     + "badges + status + inbound label",
     async () => {
    api.get.mockImplementation((url) => {
      if (url.includes("/raw-submission")) return Promise.resolve(null);
      if (url.includes("/communications")) return Promise.resolve(PAGE1);
      return Promise.resolve(LEAD);
    });
    _mount();
    fireEvent.click(await screen.findByTestId(
      "lead-profile-footer-overview-btn",
    ));
    await screen.findByTestId("lead-profile-history-panel");
    const rows = await screen.findAllByTestId(/^lead-profile-history-row-(sms|email|status_change)$/);
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveAttribute("data-row-id", "comm-1");
    // Inbound label appears on the inbound-SMS row.
    const inboundRow = rows.find((r) =>
      r.getAttribute("data-row-id") === "comm-3");
    expect(inboundRow).toBeTruthy();
    expect(inboundRow.textContent.toLowerCase())
      .toContain("inbound");
  });

  it("truncates long bodies and reveals full body on Show more click",
     async () => {
    api.get.mockImplementation((url) => {
      if (url.includes("/raw-submission")) return Promise.resolve(null);
      if (url.includes("/communications")) return Promise.resolve(PAGE1);
      return Promise.resolve(LEAD);
    });
    _mount();
    fireEvent.click(await screen.findByTestId(
      "lead-profile-footer-overview-btn",
    ));
    await screen.findByTestId("lead-profile-history-panel");
    // The long email body row has a reveal-on-click toggle.
    const toggles = await screen.findAllByTestId(
      "lead-profile-history-row-toggle",
    );
    expect(toggles).toHaveLength(1);
    expect(toggles[0]).toHaveTextContent(/Show more/);
    fireEvent.click(toggles[0]);
    await waitFor(() =>
      expect(screen.getByTestId("lead-profile-history-row-toggle"))
        .toHaveTextContent(/Show less/),
    );
  });

  it("Load more fires a second GET with the returned cursor and "
     + "appends new rows",
     async () => {
    const commsResponses = [PAGE1, PAGE2];
    let commsCall = 0;
    api.get.mockImplementation((url) => {
      if (url.includes("/raw-submission")) return Promise.resolve(null);
      if (url.includes("/communications")) {
        const r = commsResponses[commsCall] || { items: [], has_more: false };
        commsCall += 1;
        return Promise.resolve(r);
      }
      return Promise.resolve(LEAD);
    });
    _mount();
    fireEvent.click(await screen.findByTestId(
      "lead-profile-footer-overview-btn",
    ));
    const loadMore = await screen.findByTestId(
      "lead-profile-history-load-more",
    );
    fireEvent.click(loadMore);
    await waitFor(() =>
      expect(screen.getAllByTestId(/^lead-profile-history-row-(sms|email|status_change)$/))
        .toHaveLength(4),
    );
    const commsCalls = api.get.mock.calls.filter(([u]) =>
      String(u).includes("/communications"));
    expect(commsCalls).toHaveLength(2);
    expect(String(commsCalls[1][0]))
      .toContain("cursor=" + encodeURIComponent(PAGE1.next_cursor));
    // Load more disappears when has_more flips false.
    expect(screen.queryByTestId("lead-profile-history-load-more"))
      .toBeNull();
  });

  it("preserves Z3 (+ Create ▾) placeholder as disabled; Z2 Send ▾ "
     + "wiring remains intact",
     async () => {
    api.get.mockImplementation((url) => {
      if (url.includes("/raw-submission")) return Promise.resolve(null);
      if (url.includes("/communications")) return Promise.resolve(PAGE1);
      return Promise.resolve(LEAD);
    });
    _mount();
    const createBtn = await screen.findByTestId(
      "lead-profile-footer-create-btn",
    );
    expect(createBtn).toBeDisabled();
    expect(createBtn).toHaveAttribute("data-phase-placeholder", "z3");
    // Z2 Send ▾ still a live trigger.
    const sendBtn = screen.getByTestId("lead-profile-footer-send-btn");
    expect(sendBtn).not.toBeDisabled();
    expect(sendBtn.getAttribute("title"))
      .toBe("Send SMS or Email to this lead");
  });
});
