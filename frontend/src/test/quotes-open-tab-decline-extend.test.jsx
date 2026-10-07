/**
 * QUOTES-OPEN-TAB-DECLINE-EXTEND · Feb-2026 — QuotesList coverage
 * for the extended Open-tab predicate wiring, the new Accepted
 * tab button, the 5-status × 4-role Decline matrix, and the
 * silent-decline (no-confirmation) UX contract.
 *
 * The actual Mongo predicate for ``view=open`` / ``view=accepted``
 * is validated backend-side (see
 * ``backend/tests/test_quote_decline_reopen.py`` +
 * ``test_quotes_decline_extended.py``). This suite focuses on:
 *
 *   1.  The segmented control renders the 5-tab shell including the
 *       new ``quotes-list-filter-accepted`` entry.
 *   2.  Clicking each lifecycle tab issues a GET to
 *       ``/quotes?doc_type=quote&view=<v>``; the Open tab is the
 *       default on first mount.
 *   3.  The Decline button renders for every privileged
 *       (status × role) combination; does NOT render for employee /
 *       technician / dispatcher; does NOT render on converted rows
 *       (``converted_invoice_id`` set) even when the role allows.
 *   4.  Clicking Decline silently POSTs to ``/quotes/{id}/decline``
 *       — ``window.confirm`` is NEVER consulted.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor, fireEvent, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


// ── Shared mocks ─────────────────────────────────────────────
const _apiGet = vi.fn();
const _apiPost = vi.fn();
let _mockedRole = "admin";

vi.mock("@/api", () => ({
  api: {
    get: (...args) => _apiGet(...args),
    post: (...args) => _apiPost(...args),
    put: vi.fn(() => Promise.resolve({})),
    del: vi.fn(() => Promise.resolve({})),
  },
  TOKEN_KEY: "token",
}));

vi.mock("@/auth", () => ({
  useAuth: () => ({
    user: { role: _mockedRole, id: "u-1" },
    role: _mockedRole,
    loading: false,
  }),
}));

vi.mock("sonner", () => ({
  toast: { success: () => {}, error: () => {}, info: () => {} },
}));


// Reference quote rows covering every status × converted combination
// the Decline-matrix tests care about.  Each quote carries a stable
// id so the ``quote-row-decline-<id>`` testid is deterministic.
const FIXTURES = [
  { id: "q-draft",     title: "Draft quote",     total: 100, status: "draft",     customer_id: "c-1" },
  { id: "q-sent",      title: "Sent quote",      total: 200, status: "sent",      customer_id: "c-2" },
  { id: "q-viewed",    title: "Viewed quote",    total: 300, status: "viewed",    customer_id: "c-3" },
  { id: "q-accepted",  title: "Accepted quote",  total: 400, status: "accepted",  customer_id: "c-4" },
  { id: "q-cancelled", title: "Cancelled quote", total: 500, status: "cancelled", customer_id: "c-5" },
  { id: "q-declined",  title: "Declined quote",  total: 600, status: "declined",  customer_id: "c-6" },
  {
    id: "q-converted",
    title: "Converted quote",
    total: 700,
    status: "accepted",
    customer_id: "c-7",
    converted_invoice_id: "inv-999",
  },
];


beforeEach(() => {
  _apiGet.mockReset();
  _apiPost.mockReset();
  _mockedRole = "admin";
  _apiGet.mockImplementation((path) => {
    const p = typeof path === "string" ? path : "";
    if (p.startsWith("/quotes")) return Promise.resolve(FIXTURES);
    if (p.startsWith("/customers")) return Promise.resolve([]);
    return Promise.resolve([]);
  });
  _apiPost.mockResolvedValue({});
  window.localStorage?.clear?.();
});
afterEach(() => { cleanup(); });


async function _mountList(role = "admin") {
  _mockedRole = role;
  const mod = await import("@/pages/quotes/QuotesList");
  const ListPage = mod.default;
  return render(
    <MemoryRouter initialEntries={["/quotes"]}>
      <ListPage />
    </MemoryRouter>,
  );
}


// ═════════════════════════════════════════════════════════════════
// 1 · Lifecycle tab shell — 5 tabs including the new Accepted tab
// ═════════════════════════════════════════════════════════════════
describe("QuotesList · lifecycle tab shell", () => {
  it("renders all 5 tabs with stable testids including the new Accepted tab", async () => {
    await _mountList();
    await screen.findByTestId("quotes-list-filter");
    for (const v of ["open", "accepted", "converted", "declined", "all"]) {
      expect(screen.getByTestId(`quotes-list-filter-${v}`)).toBeTruthy();
    }
  });

  it("Open is the default-selected tab on first mount", async () => {
    await _mountList();
    const openBtn = await screen.findByTestId("quotes-list-filter-open");
    expect(openBtn.getAttribute("aria-pressed")).toBe("true");
  });

  it("clicking Accepted sends ``view=accepted`` to the backend", async () => {
    await _mountList();
    await screen.findByTestId("quotes-list-filter-accepted");
    _apiGet.mockClear();
    fireEvent.click(screen.getByTestId("quotes-list-filter-accepted"));
    await waitFor(() => {
      const quoteCalls = _apiGet.mock.calls
        .map((c) => String(c[0] || ""))
        .filter((p) => p.startsWith("/quotes"));
      expect(quoteCalls.some((p) => p.includes("view=accepted"))).toBe(true);
    });
  });
});


// ═════════════════════════════════════════════════════════════════
// 2 · Decline-button render matrix — 5 statuses × 4 privileged roles
//      × negative cases (employee/tech/dispatcher, converted row)
// ═════════════════════════════════════════════════════════════════
const PRIVILEGED_ROLES = ["admin", "super_admin", "owner", "manager"];
const DECLINE_STATUSES = ["draft", "sent", "viewed", "accepted", "cancelled"];
const UNPRIVILEGED_ROLES = ["technician", "dispatcher", "customer", "employee"];

describe("QuotesList · Decline-button render matrix", () => {
  for (const role of PRIVILEGED_ROLES) {
    for (const status of DECLINE_STATUSES) {
      it(`renders Decline for role=${role} status=${status}`, async () => {
        await _mountList(role);
        const row = await screen.findByTestId(`quote-row-q-${status}`);
        const btn = within(row).queryByTestId(`quote-row-decline-q-${status}`);
        expect(btn).toBeTruthy();
      });
    }
  }

  for (const role of UNPRIVILEGED_ROLES) {
    it(`does NOT render Decline for role=${role}`, async () => {
      await _mountList(role);
      await screen.findByTestId("quote-row-q-sent");
      // No Decline button anywhere — fast assertion across all rows.
      expect(screen.queryAllByTestId(/^quote-row-decline-/).length).toBe(0);
    });
  }

  it("does NOT render Decline on a converted row even for admin", async () => {
    await _mountList("admin");
    const row = await screen.findByTestId("quote-row-q-converted");
    expect(within(row).queryByTestId("quote-row-decline-q-converted")).toBeNull();
  });

  it("does NOT render Decline on a declined row", async () => {
    await _mountList("admin");
    const row = await screen.findByTestId("quote-row-q-declined");
    expect(within(row).queryByTestId("quote-row-decline-q-declined")).toBeNull();
  });
});


// ═════════════════════════════════════════════════════════════════
// 3 · Silent decline — no window.confirm, direct API POST
// ═════════════════════════════════════════════════════════════════
describe("QuotesList · silent decline UX", () => {
  it("clicking Decline on a cancelled quote POSTs without window.confirm", async () => {
    await _mountList("admin");
    const confirmSpy = vi.spyOn(window, "confirm")
      .mockImplementation(() => false);
    const row = await screen.findByTestId("quote-row-q-cancelled");
    const btn = within(row).getByTestId("quote-row-decline-q-cancelled");
    fireEvent.click(btn);
    await waitFor(() => {
      expect(_apiPost).toHaveBeenCalledWith(
        "/quotes/q-cancelled/decline", {},
      );
    });
    // Confirm never consulted — silent decline contract.
    expect(confirmSpy).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  it("clicking Decline on a sent quote POSTs without window.confirm", async () => {
    await _mountList("admin");
    const confirmSpy = vi.spyOn(window, "confirm")
      .mockImplementation(() => false);
    const row = await screen.findByTestId("quote-row-q-sent");
    const btn = within(row).getByTestId("quote-row-decline-q-sent");
    fireEvent.click(btn);
    await waitFor(() => {
      expect(_apiPost).toHaveBeenCalledWith(
        "/quotes/q-sent/decline", {},
      );
    });
    expect(confirmSpy).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });
});
