/**
 * BULK-PORTAL-INVITE-FILTER · Feb-2026 — contract vitest for the
 * inline "Bulk Portal Invite" button in the Customers filter bar.
 *
 * Covers:
 *   1. Admin-tier role gate — button rendered for admin / super_admin
 *      / owner, hidden for manager / technician.
 *   2. Disabled state when the visible list is empty (``0 shown``).
 *   3. Click → preview GET fires with the current filter state +
 *      hard ``first_access=never`` + ``page_size=200`` override.
 *   4. Confirmation modal shows the eligible count returned by the
 *      preview envelope's ``total`` field.
 *   5. Cancel path — no POST fires.
 *   6. Confirm path — POST fires to the existing Phase-H1 bulk
 *      endpoint with the preview-returned customer ids.
 *   7. Cap warning banner renders when ``total > 200`` (the single-
 *      batch backend cap).
 *   8. Zero-eligible edge — modal renders the empty-pool note +
 *      the Send CTA is disabled.
 *
 * Sibling to the pre-existing ``customers-bulk-portal-invite.test
 * .jsx`` (which covers the SELECTION-driven Phase-H1 flow in the
 * top-right toolbar + Waitlist tab) — the two surfaces share a
 * backend endpoint but have different UX entry points.
 */
import React from "react";
import {
  describe, it, expect, vi, beforeEach, afterEach,
} from "vitest";
import {
  render, screen, cleanup, fireEvent, waitFor,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


const { getSpy, postSpy } = vi.hoisted(() => ({
  getSpy:  vi.fn(),
  postSpy: vi.fn(),
}));

vi.mock("@/api", () => ({
  TOKEN_KEY: "token",
  api: {
    get:  (...a) => getSpy(...a),
    post: (...a) => postSpy(...a),
    put:  vi.fn(),
    delete: vi.fn(),
    patch: vi.fn(),
  },
}));

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), {
    success: vi.fn(), error: vi.fn(), warning: vi.fn(),
  }),
}));


// Role hook — swapped per describe-block via ``_currentRole``.
let _currentRole = "admin";
vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    role: _currentRole, effectiveRole: _currentRole,
    perms: { can_view: true, can_edit: true, can_delete: true },
  }),
}));


// Stub heavy children so the test harness stays snappy.
vi.mock("@/components/customers/CustomersTagFilterDropdown",
         () => ({ default: () => <div data-testid="tag-dd" /> }));
vi.mock("@/components/customers/MuteControl",
         () => ({ default: () => <span /> }));
vi.mock("@/components/customers/RestoreCustomerButton",
         () => ({ default: () => <span /> }));
vi.mock("@/components/customers/CustomersPager",
         () => ({ default: () => <div data-testid="pager" /> }));
vi.mock("@/components/customers/MergeCustomersModal",
         () => ({ default: () => null }));
vi.mock("@/pages/customers/ImportCsvModalP41",
         () => ({ default: () => null }));
vi.mock("@/components/customers/PortalOnboardingHealthTile",
         () => ({ default: () => <div data-testid="onboarding-tile" /> }));


import CustomersList from "@/pages/customers/CustomersList.jsx";


function _mount() {
  return render(
    <MemoryRouter initialEntries={["/customers"]}>
      <CustomersList />
    </MemoryRouter>,
  );
}


/* Seed the baseline GET /customers list the page fires on mount
 * so the component completes its initial load. */
function _seedList(rows, extra = {}) {
  getSpy.mockImplementation(async (p) => {
    if (p.startsWith("/customers?")) {
      return {
        items: rows,
        total: rows.length,
        total_pages: 1,
        counts_by_status: { active: rows.length, inactive: 0 },
        ...extra,
      };
    }
    if (p === "/customer-tags?only_used=true") {
      return { items: [] };
    }
    if (p.startsWith("/customers/counts")) return {};
    return {};
  });
}


beforeEach(() => {
  getSpy.mockReset();
  postSpy.mockReset();
  _currentRole = "admin";
});

afterEach(() => cleanup());


describe("Customers · filter-bar Bulk Portal Invite · role gate", () => {
  it.each([
    ["admin",       true],
    ["super_admin", true],
    ["owner",       true],
  ])("renders the button for admin-tier role %s", async (role, visible) => {
    _currentRole = role;
    _seedList([{ id: "c1", name: "Alpha" }]);
    _mount();
    const btn = await waitFor(() =>
      screen.queryByTestId("customers-filter-bulk-portal-invite-btn"),
    );
    if (visible) {
      expect(btn).toBeInTheDocument();
    } else {
      expect(btn).toBeNull();
    }
  });

  it.each([
    ["manager"],
    ["technician"],
  ])("HIDES the button for non-admin-tier role %s", async (role) => {
    _currentRole = role;
    _seedList([{ id: "c1", name: "Alpha" }]);
    _mount();
    await waitFor(() => expect(getSpy).toHaveBeenCalled());
    expect(
      screen.queryByTestId("customers-filter-bulk-portal-invite-btn"),
    ).toBeNull();
  });
});


describe("Customers · filter-bar Bulk Portal Invite · disabled state",
          () => {
  it("disabled when the visible list is empty (zero shown)", async () => {
    _seedList([]);
    _mount();
    const btn = await screen.findByTestId(
      "customers-filter-bulk-portal-invite-btn",
    );
    expect(btn).toBeDisabled();
  });

  it("enabled when the visible list has >=1 row", async () => {
    _seedList([{ id: "c1", name: "Alpha" }]);
    _mount();
    const btn = await screen.findByTestId(
      "customers-filter-bulk-portal-invite-btn",
    );
    expect(btn).not.toBeDisabled();
  });
});


describe("Customers · filter-bar Bulk Portal Invite · preview + "
         + "confirmation", () => {
  it("fires preview GET with first_access=never + page_size=200 "
     + "overrides and shows the eligible total in the modal",
     async () => {
    _seedList([{ id: "c1", name: "Alpha" },
                { id: "c2", name: "Bravo" }]);
    _mount();
    const btn = await screen.findByTestId(
      "customers-filter-bulk-portal-invite-btn",
    );
    // Chain a second GET response for the preview call (the mount
    // GET already resolved).
    getSpy.mockImplementationOnce(async () => ({
      items: [
        { id: "c1", name: "Alpha" },
        { id: "c2", name: "Bravo" },
      ],
      total: 2,
    }));

    fireEvent.click(btn);

    await screen.findByTestId("bulk-portal-invite-modal");
    expect(screen.getByTestId("bulk-portal-invite-count"))
      .toHaveTextContent("2");

    // Preview URL carries the two hard overrides.
    const previewCall = getSpy.mock.calls.find(
      ([p]) => typeof p === "string"
        && p.startsWith("/customers?")
        && p.includes("first_access=never"),
    );
    expect(previewCall).toBeDefined();
    expect(previewCall[0]).toMatch(/first_access=never/);
    expect(previewCall[0]).toMatch(/page_size=200/);
  });

  it("Cancel button closes the modal without firing a POST",
     async () => {
    _seedList([{ id: "c1", name: "Alpha" }]);
    _mount();
    const btn = await screen.findByTestId(
      "customers-filter-bulk-portal-invite-btn",
    );
    getSpy.mockImplementationOnce(async () => ({
      items: [{ id: "c1", name: "Alpha" }], total: 1,
    }));
    fireEvent.click(btn);
    await screen.findByTestId("bulk-portal-invite-modal");
    fireEvent.click(screen.getByTestId("bulk-portal-invite-cancel-btn"));
    await waitFor(() =>
      expect(screen.queryByTestId("bulk-portal-invite-modal"))
        .toBeNull(),
    );
    expect(postSpy).not.toHaveBeenCalled();
  });

  it("Confirm button POSTs the preview-returned ids to the "
     + "existing bulk endpoint", async () => {
    _seedList([{ id: "c1", name: "Alpha" },
                { id: "c2", name: "Bravo" }]);
    _mount();
    const btn = await screen.findByTestId(
      "customers-filter-bulk-portal-invite-btn",
    );
    getSpy.mockImplementationOnce(async () => ({
      items: [{ id: "c1", name: "Alpha" },
              { id: "c2", name: "Bravo" }],
      total: 2,
    }));
    postSpy.mockResolvedValue({ queued: 2, sent: 0,
                                   failed_send: 0,
                                   batch_id: "b-1" });
    fireEvent.click(btn);
    await screen.findByTestId("bulk-portal-invite-modal");
    fireEvent.click(screen.getByTestId("bulk-portal-invite-confirm-btn"));

    await waitFor(() => expect(postSpy).toHaveBeenCalled());
    const [path, body] = postSpy.mock.calls[0];
    expect(path).toBe("/admin/customers/portal-invite/bulk");
    expect(body.customer_ids).toEqual(["c1", "c2"]);
    expect(body.reason).toBe("bulk-filter-invite");
  });
});


describe("Customers · filter-bar Bulk Portal Invite · cap warning + "
         + "zero-eligible edge", () => {
  it("shows the >200 cap warning banner when total > 200", async () => {
    _seedList([{ id: "c1", name: "Alpha" }]);
    _mount();
    const btn = await screen.findByTestId(
      "customers-filter-bulk-portal-invite-btn",
    );
    getSpy.mockImplementationOnce(async () => ({
      items: Array.from({ length: 200 }, (_, i) => (
        { id: `c${i + 1}`, name: `n${i + 1}` })),
      total: 1247,
    }));
    fireEvent.click(btn);
    await screen.findByTestId("bulk-portal-invite-modal");
    expect(screen.getByTestId("bulk-portal-invite-cap-warning"))
      .toBeInTheDocument();
    // Count badge shows the un-clamped eligible count so the
    // operator sees the true backlog.
    expect(screen.getByTestId("bulk-portal-invite-count"))
      .toHaveTextContent("1247");
    // Send button label clamps to 200 to match the single POST.
    expect(screen.getByTestId("bulk-portal-invite-confirm-btn"))
      .toHaveTextContent(/Send 200 Invites/i);
  });

  it("renders the empty-pool note + disables Send when total === 0",
     async () => {
    _seedList([{ id: "c1", name: "Alpha" }]);
    _mount();
    const btn = await screen.findByTestId(
      "customers-filter-bulk-portal-invite-btn",
    );
    getSpy.mockImplementationOnce(async () => ({
      items: [], total: 0,
    }));
    fireEvent.click(btn);
    await screen.findByTestId("bulk-portal-invite-modal");
    expect(screen.getByTestId("bulk-portal-invite-zero"))
      .toBeInTheDocument();
    expect(screen.getByTestId("bulk-portal-invite-confirm-btn"))
      .toBeDisabled();
  });
});
