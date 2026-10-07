/**
 * LEAD-CREATE-QUOTE · Feb-2026 — "Create Quote" button on the
 * lead-detail Actions column.
 *
 * Locks four invariants:
 *   1. Button renders for admin / super_admin / owner (matches the
 *      backend ``POST /quotes`` ``require_admin`` dep — if this
 *      drifts the ROUTE-GUARD-AUDIT ticket catches it).
 *   2. Button is HIDDEN for manager / technician / employee roles.
 *   3. Click navigates to
 *      ``/quotes/new?recipient_type=lead&recipient_id=<id>`` —
 *      exact Phase-2 Quote-to-Lead Recipient URL contract.
 *   4. Count badge renders when ``lead.quotes_count > 0`` and is
 *      HIDDEN when the count is zero.
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
  toast: Object.assign(vi.fn(), {
    success: vi.fn(), error: vi.fn(),
  }),
}));

// react-router-dom partial mock — keep MemoryRouter/Route/Routes
// real so the ``:id`` useParams hook still resolves.
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return {
    ...actual,
    useNavigate: () => navigateMock,
  };
});

const _authMock = vi.hoisted(() => ({ user: { role: "admin" } }));
vi.mock("@/auth", () => ({
  useAuth: () => _authMock,
}));

// ClickToCallButton is dead-weight for this test — stub it so we
// don't drag the telephony fetch chain into the test harness.
vi.mock("@/components/telephony/ClickToCallButton", () => ({
  __esModule: true,
  default: () => null,
}));

// PhoneLink / AddressLink are presentational — stub.
vi.mock("@/components/customer", () => ({
  PhoneLink: ({ phone }) => <span>{phone}</span>,
  AddressLink: ({ children }) => <span>{children}</span>,
}));

// LeadComposeModal is lazy — stub so it doesn't block renders.
vi.mock("@/pages/leads/LeadComposeModal", () => ({
  __esModule: true,
  default: () => null,
}));


import LeadDetail from "@/pages/leads/LeadDetail";


const BASE_LEAD = {
  id: "lead-abc",
  name: "Larry Lead",
  phone: "480-555-0001",
  email: "larry@example.com",
  service_address: "100 Palo Verde Way",
  address: "100 Palo Verde Way",
  status: "new",
  source: "admin_manual",
  timeline: [],
  notes: "",
  quotes_count: 0,
};


function _mountDetail({ leadDoc = BASE_LEAD, communications = {
  items: [], next_cursor: null, has_more: false,
} } = {}) {
  getMock.mockImplementation((url) => {
    if (url.includes("/communications")) {
      return Promise.resolve(communications);
    }
    return Promise.resolve(leadDoc);
  });
  return render(
    <MemoryRouter initialEntries={["/leads/lead-abc"]}>
      <Routes>
        <Route path="/leads/:id" element={<LeadDetail />} />
      </Routes>
    </MemoryRouter>,
  );
}


afterEach(() => {
  cleanup();
  getMock.mockReset();
  postMock.mockReset();
  patchMock.mockReset();
  navigateMock.mockReset();
  _authMock.user = { role: "admin" };
});


describe("LeadDetail · Create Quote button", () => {
  it("renders the button for role=admin", async () => {
    _authMock.user = { role: "admin" };
    _mountDetail();
    await waitFor(() =>
      expect(screen.queryByTestId("lead-detail-page")).toBeTruthy(),
    );
    expect(screen.getByTestId("lead-create-quote")).toBeTruthy();
  });

  it("renders the button for role=super_admin", async () => {
    _authMock.user = { role: "super_admin" };
    _mountDetail();
    await waitFor(() =>
      expect(screen.queryByTestId("lead-detail-page")).toBeTruthy(),
    );
    expect(screen.getByTestId("lead-create-quote")).toBeTruthy();
  });

  it("renders the button for role=owner", async () => {
    _authMock.user = { role: "owner" };
    _mountDetail();
    await waitFor(() =>
      expect(screen.queryByTestId("lead-detail-page")).toBeTruthy(),
    );
    expect(screen.getByTestId("lead-create-quote")).toBeTruthy();
  });

  it.each([
    "manager", "technician", "employee", "customer",
  ])("hides the button for role=%s (matches POST /quotes gate)",
    async (role) => {
      _authMock.user = { role };
      _mountDetail();
      await waitFor(() =>
        expect(screen.queryByTestId("lead-detail-page")).toBeTruthy(),
      );
      expect(screen.queryByTestId("lead-create-quote")).toBeNull();
    });

  it("click navigates to /quotes/new?recipient_type=lead&recipient_id=<id>",
    async () => {
      _authMock.user = { role: "admin" };
      _mountDetail();
      await waitFor(() =>
        expect(screen.queryByTestId("lead-detail-page")).toBeTruthy(),
      );
      fireEvent.click(screen.getByTestId("lead-create-quote"));
      expect(navigateMock).toHaveBeenCalledWith(
        "/quotes/new?recipient_type=lead&recipient_id=lead-abc",
      );
    });

  it("count badge renders when quotes_count > 0", async () => {
    _authMock.user = { role: "admin" };
    _mountDetail({ leadDoc: { ...BASE_LEAD, quotes_count: 3 } });
    await waitFor(() =>
      expect(screen.queryByTestId("lead-detail-page")).toBeTruthy(),
    );
    const badge = screen.getByTestId("lead-create-quote-count");
    expect(badge.textContent).toContain("3");
  });

  it("count badge is HIDDEN when quotes_count = 0", async () => {
    _authMock.user = { role: "admin" };
    _mountDetail({ leadDoc: { ...BASE_LEAD, quotes_count: 0 } });
    await waitFor(() =>
      expect(screen.queryByTestId("lead-detail-page")).toBeTruthy(),
    );
    expect(screen.queryByTestId("lead-create-quote-count")).toBeNull();
  });

  it("count badge is HIDDEN when quotes_count field is absent "
     + "(legacy GET /leads/{lid} payload back-compat)", async () => {
    _authMock.user = { role: "admin" };
    const { quotes_count: _, ...legacyLead } = BASE_LEAD;
    _mountDetail({ leadDoc: legacyLead });
    await waitFor(() =>
      expect(screen.queryByTestId("lead-detail-page")).toBeTruthy(),
    );
    expect(screen.getByTestId("lead-create-quote")).toBeTruthy();
    expect(screen.queryByTestId("lead-create-quote-count")).toBeNull();
  });
});
