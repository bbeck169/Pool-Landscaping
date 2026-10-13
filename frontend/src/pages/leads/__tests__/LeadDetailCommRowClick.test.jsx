/**
 * P2 #5 · Feb-2026 — LeadDetail CommTimelineItem row click vitest.
 *
 * Locks three invariants on the Phase L3 lead-detail inline
 * CommTimelineItem (not shared with CommunicationTimeline.jsx):
 *   1. Admin viewer sees a "View details" button on every SMS /
 *      email row that carries an id.
 *   2. Click fires the shared detail fetch with the correct rowId.
 *   3. status_change items (synthesized from leads.timeline[])
 *      do NOT get the affordance — they lack a matching id in the
 *      log collections and would 404.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { render, screen, cleanup, fireEvent, waitFor }
  from "@testing-library/react";


const navigateMock = vi.fn();
const getMock = vi.fn();
const postMock = vi.fn();
const patchMock = vi.fn();

vi.mock("@/api", () => ({
  api: {
    get: (...a) => getMock(...a),
    post: (...a) => postMock(...a),
    patch: (...a) => patchMock(...a),
    put: (...a) => postMock(...a),
  },
  TOKEN_KEY: "token",
}));

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useNavigate: () => navigateMock };
});

const _authMock = vi.hoisted(() => ({ user: { role: "admin" } }));
vi.mock("@/auth", () => ({ useAuth: () => _authMock }));

vi.mock("@/components/telephony/ClickToCallButton", () => ({
  __esModule: true, default: () => null,
}));

vi.mock("@/components/customer", () => ({
  PhoneLink: ({ phone }) => <span>{phone}</span>,
  AddressLink: ({ children }) => <span>{children}</span>,
}));

vi.mock("@/pages/leads/LeadComposeModal", () => ({
  __esModule: true, default: () => null,
}));


import LeadDetail from "@/pages/leads/LeadDetail";


const BASE_LEAD = {
  id: "lead-abc", name: "Larry Lead",
  phone: "480-555-0001", email: "larry@example.com",
  service_address: "100 Palo Verde Way", address: "100 Palo Verde Way",
  status: "new", source: "admin_manual",
  timeline: [], notes: "", quotes_count: 0,
};

const COMMS = {
  items: [
    {
      id: "lcomm-sms-1", type: "sms", direction: "outbound",
      body: "Hi!", status: "sent",
      created_at: "2026-02-15T13:00:00+00:00",
    },
    {
      id: "lcomm-email-2", type: "email", direction: "outbound",
      subject: "Welcome", body: "<p>Hi</p>", status: "sent",
      created_at: "2026-02-15T14:00:00+00:00",
    },
    {
      // status_change items do not have a log-collection id — only
      // a type and payload. The View-details affordance must NOT render.
      type: "status_change", status_from: "new", status_to: "contacted",
      created_at: "2026-02-15T15:00:00+00:00",
    },
  ],
  next_cursor: null, has_more: false,
};


beforeEach(() => {
  _authMock.user = { role: "admin" };
  getMock.mockReset(); postMock.mockReset(); patchMock.mockReset();
  navigateMock.mockReset();
  getMock.mockImplementation((url) => {
    if (url.includes("/communications?")) return Promise.resolve(COMMS);
    if (url.includes("/quotes?")) return Promise.resolve({
      total: 0, limit: 10, items: [],
    });
    if (url.startsWith("/communications-detail/")) {
      return Promise.resolve({
        source: "lead_communications",
        channel: "sms",
        direction: "outbound",
        subject: "",
        body_available: true,
        body: "Hi!",
        body_format: "text",
      });
    }
    return Promise.resolve(BASE_LEAD);
  });
});


afterEach(() => { cleanup(); vi.restoreAllMocks(); });


function _mount() {
  return render(
    <MemoryRouter initialEntries={["/leads/lead-abc"]}>
      <Routes>
        <Route path="/leads/:id" element={<LeadDetail />} />
      </Routes>
    </MemoryRouter>,
  );
}


describe("LeadDetail · CommTimelineItem row click → shared Dialog modal", () => {
  it("renders View details on SMS and email rows with an id", async () => {
    _mount();
    await waitFor(() =>
      expect(screen.queryByTestId("lead-detail-page")).toBeTruthy());
    await screen.findByTestId("lead-comm-view-detail-lcomm-sms-1");
    expect(screen.getByTestId("lead-comm-view-detail-lcomm-email-2"))
      .toBeTruthy();
  });

  it("click fires detail fetch with correct rowId", async () => {
    _mount();
    await waitFor(() =>
      expect(screen.queryByTestId("lead-detail-page")).toBeTruthy());
    const btn = await screen.findByTestId("lead-comm-view-detail-lcomm-sms-1");
    fireEvent.click(btn);
    await waitFor(() => {
      expect(getMock).toHaveBeenCalledWith("/communications-detail/lcomm-sms-1");
    });
    await screen.findByTestId("comm-detail-modal");
  });

  it("status_change rows do NOT render View details", async () => {
    _mount();
    await waitFor(() =>
      expect(screen.queryByTestId("lead-detail-page")).toBeTruthy());
    // Status-change item has no id; nothing matching the testid prefix.
    const items = screen.queryAllByTestId(/^lead-comm-view-detail-/);
    expect(items.length).toBe(2);
    // And the status_change row still rendered (type testid present).
    expect(screen.getByTestId("lead-comm-item-status_change")).toBeTruthy();
  });
});
