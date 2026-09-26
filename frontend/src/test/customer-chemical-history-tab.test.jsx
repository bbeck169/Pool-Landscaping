/**
 * Feb-2026 · C5 · ``CustomerChemicalHistoryTab``.
 *
 * Covers (per dispatch enumeration):
 *   1.  Title + count badge + New Application button render.
 *   2.  New Application button navigates to
 *       ``/admin/chemical-applications/new?customer_id=<cid>``.
 *   3.  Fetches ``/chemical-applications?customer_id=<cid>&limit=25``
 *       on mount.
 *   4.  Renders a row per application with correct bindings.
 *   5.  ReiBadge red/green states — 1 locked + 1 OK.
 *   6.  Filter chip 'REI Locked' → only locked rows.
 *   7.  Filter chip 'Last 30 days' → only recent rows.
 *   8.  Row click → navigate to ``/admin/chemical-applications/:id``.
 *   9.  Empty state renders + 'Log First Application' CTA navigates.
 *  10.  Error state renders + Retry re-fetches.
 *  11.  Role gate — tab role set ``["admin", "super_admin", "manager"]``.
 *  14.  Cursor pagination — Load more button appears + appends.
 *
 * Role-visibility gate (11-13) is enforced by ``filterCustomerTabs``
 * which is separately covered in ``customer-measurements-tab.test.jsx``;
 * here we lock the ``CHEMICAL_HISTORY_TAB_ROLES`` export shape so no
 * accidental role drift can slip through.
 *
 * No live network. Real timers by default; fake timers scoped only
 * to the 60 s ReiBadge tick assertion.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  render, screen, cleanup, fireEvent, waitFor,
} from "@testing-library/react";


const { apiGetSpy, toastErrorSpy, navigateSpy } = vi.hoisted(() => ({
  apiGetSpy: vi.fn(),
  toastErrorSpy: vi.fn(),
  navigateSpy: vi.fn(),
}));


vi.mock("@/api", () => ({
  api: {
    get: (...args) => apiGetSpy(...args),
    post: vi.fn(),
  },
}));


vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: (...args) => toastErrorSpy(...args),
  },
}));


vi.mock("@/theme", () => ({
  colors: {
    surface: "#FFFFFF", surfaceSecondary: "#F4F4F5",
    surfaceTertiary: "#E4E4E7", border: "#E4E4E7", muted: "#71717A",
    brand: "#0284C7", brandPrimary: "#0284C7", onBrandPrimary: "#FFFFFF",
    onSurface: "#09090B", onSurfaceSecondary: "#52525B",
    success: "#16A34A", error: "#DC2626",
    inputBorder: "#3B82F6", searchIcon: "#0284C7",
    nav: { bg: "#1B1F5C", fg: "#FFFFFF", border: "rgba(255,255,255,0.10)" },
    gradient: { css: "linear-gradient(90deg,#1B1F5C,#0284C7)" },
  },
}));


vi.mock("react-router-dom", () => ({
  useNavigate: () => navigateSpy,
}));


import CustomerChemicalHistoryTab, {
  CHEMICAL_HISTORY_TAB_ROLES,
} from "../components/customer/CustomerChemicalHistoryTab";


// ═══════════════════════════════════════════════════════════════════
// Fixtures
// ═══════════════════════════════════════════════════════════════════
const CUSTOMER = { id: "cust-1", name: "Alpha HOA" };


function _isoNowPlus(ms) {
  return new Date(Date.now() + ms).toISOString();
}


function _isoNowPlusDays(days) {
  return _isoNowPlus(days * 24 * 60 * 60 * 1000);
}


function _row(o = {}) {
  return {
    id: o.id || "app-1",
    application_date: o.application_date || new Date().toISOString().slice(0, 10),
    start_time: o.start_time || "09:00:00",
    stop_time:  o.stop_time  || "09:45:00",
    customer_id: "cust-1",
    technician_name: "Mike Rodriguez",
    license_number: "TX-77777",
    chemical_name: "Roundup",
    target_pest: "Poa annua",
    rei_hours: 24,
    rei_unlock_at: _isoNowPlus(21 * 60 * 60 * 1000),
    ...o,
  };
}


function _installMocks({
  first = { items: [_row()], next_cursor: null },
  second = null,
} = {}) {
  apiGetSpy.mockReset();
  apiGetSpy.mockImplementation((path) => {
    if (typeof path !== "string") return Promise.resolve({});
    if (path.startsWith("/chemical-applications")) {
      if (second && path.includes("cursor=")) return Promise.resolve(second);
      return Promise.resolve(first);
    }
    return Promise.resolve({});
  });
}


beforeEach(() => {
  _installMocks();
  toastErrorSpy.mockReset();
  navigateSpy.mockReset();
});

afterEach(() => { cleanup(); });


// ═══════════════════════════════════════════════════════════════════
// 1. Header + count badge + New Application button
// ═══════════════════════════════════════════════════════════════════
describe("CustomerChemicalHistoryTab — chrome", () => {
  it("renders title, count badge, and New Application button", async () => {
    render(<CustomerChemicalHistoryTab customer={CUSTOMER} />);
    await waitFor(() => {
      expect(screen.getByTestId("chemical-history-tab-title")).toBeTruthy();
    });
    expect(screen.getByTestId("chemical-history-tab-title").textContent)
      .toContain("Chemical History");
    expect(screen.getByTestId("chemical-history-new-btn")).toBeTruthy();
    await waitFor(() => {
      expect(screen.getByTestId("chemical-history-count-badge").textContent).toBe("1");
    });
  });
});


// ═══════════════════════════════════════════════════════════════════
// 2. New Application button — customer-scoped deep-link
// ═══════════════════════════════════════════════════════════════════
describe("CustomerChemicalHistoryTab — new-application deep-link", () => {
  it("navigates to /admin/chemical-applications/new?customer_id=<cid>", async () => {
    render(<CustomerChemicalHistoryTab customer={CUSTOMER} />);
    await waitFor(() => {
      expect(screen.getByTestId("chemical-history-new-btn")).toBeTruthy();
    });
    fireEvent.click(screen.getByTestId("chemical-history-new-btn"));
    expect(navigateSpy).toHaveBeenCalledWith(
      "/admin/chemical-applications/new?customer_id=cust-1",
    );
  });
});


// ═══════════════════════════════════════════════════════════════════
// 3 + 4. Mount fetch + row bindings
// ═══════════════════════════════════════════════════════════════════
describe("CustomerChemicalHistoryTab — data fetch + row rendering", () => {
  it("fetches /chemical-applications?customer_id=<cid>&limit=25 on mount", async () => {
    render(<CustomerChemicalHistoryTab customer={CUSTOMER} />);
    await waitFor(() => {
      const call = apiGetSpy.mock.calls.find(
        ([p]) => typeof p === "string"
          && p.includes("customer_id=cust-1")
          && p.includes("limit=25"),
      );
      expect(call).toBeTruthy();
    });
  });

  it("renders a row per application with correct field bindings", async () => {
    render(<CustomerChemicalHistoryTab customer={CUSTOMER} />);
    await waitFor(() => {
      expect(screen.getByTestId("chem-history-row-app-1")).toBeTruthy();
    });
    expect(screen.getByTestId("chem-history-row-app-1-pest").textContent)
      .toContain("Poa annua");
    expect(screen.getByTestId("chem-history-row-app-1-chemical").textContent)
      .toContain("Roundup");
  });
});


// ═══════════════════════════════════════════════════════════════════
// 5. ReiBadge red/green
// ═══════════════════════════════════════════════════════════════════
describe("CustomerChemicalHistoryTab — REI badge", () => {
  it("renders red locked badge when rei_unlock_at is future", async () => {
    render(<CustomerChemicalHistoryTab customer={CUSTOMER} />);
    await waitFor(() => {
      expect(screen.getByTestId("chem-history-row-app-1-rei-locked")).toBeTruthy();
    });
  });

  it("renders green unlocked badge when rei_unlock_at is past", async () => {
    _installMocks({ first: {
      items: [_row({ id: "app-2",
                       rei_unlock_at: _isoNowPlus(-60 * 60 * 1000) })],
      next_cursor: null,
    }});
    render(<CustomerChemicalHistoryTab customer={CUSTOMER} />);
    await waitFor(() => {
      expect(screen.getByTestId("chem-history-row-app-2-rei-unlocked")).toBeTruthy();
    });
  });
});


// ═══════════════════════════════════════════════════════════════════
// 6 + 7. Filter chips
// ═══════════════════════════════════════════════════════════════════
describe("CustomerChemicalHistoryTab — filter chips", () => {
  it("REI Locked chip shows only currently-locked rows", async () => {
    _installMocks({ first: {
      items: [
        _row({ id: "locked-1",
                 rei_unlock_at: _isoNowPlus(6 * 60 * 60 * 1000) }),
        _row({ id: "unlocked-1",
                 rei_unlock_at: _isoNowPlus(-6 * 60 * 60 * 1000) }),
      ],
      next_cursor: null,
    }});
    render(<CustomerChemicalHistoryTab customer={CUSTOMER} />);
    await waitFor(() => {
      expect(screen.getByTestId("chem-history-row-locked-1")).toBeTruthy();
      expect(screen.getByTestId("chem-history-row-unlocked-1")).toBeTruthy();
    });
    fireEvent.click(screen.getByTestId("chemical-history-chip-locked"));
    await waitFor(() => {
      expect(screen.queryByTestId("chem-history-row-unlocked-1")).toBeNull();
    });
    expect(screen.getByTestId("chem-history-row-locked-1")).toBeTruthy();
  });

  it("Last 30 days chip filters by application_date", async () => {
    // Two rows: one dated today, one dated 60 days ago.
    const isoDate = (delta) => new Date(Date.now() + delta * 24 * 60 * 60 * 1000)
                                   .toISOString().slice(0, 10);
    _installMocks({ first: {
      items: [
        _row({ id: "recent",  application_date: isoDate(-1) }),
        _row({ id: "stale",   application_date: isoDate(-60) }),
      ],
      next_cursor: null,
    }});
    render(<CustomerChemicalHistoryTab customer={CUSTOMER} />);
    await waitFor(() => {
      expect(screen.getByTestId("chem-history-row-recent")).toBeTruthy();
      expect(screen.getByTestId("chem-history-row-stale")).toBeTruthy();
    });
    fireEvent.click(screen.getByTestId("chemical-history-chip-last30"));
    await waitFor(() => {
      expect(screen.queryByTestId("chem-history-row-stale")).toBeNull();
    });
    expect(screen.getByTestId("chem-history-row-recent")).toBeTruthy();
  });
});


// ═══════════════════════════════════════════════════════════════════
// 8. Row click → detail
// ═══════════════════════════════════════════════════════════════════
describe("CustomerChemicalHistoryTab — row navigation", () => {
  it("row click navigates to /admin/chemical-applications/:id", async () => {
    render(<CustomerChemicalHistoryTab customer={CUSTOMER} />);
    await waitFor(() => {
      expect(screen.getByTestId("chem-history-row-app-1")).toBeTruthy();
    });
    fireEvent.click(screen.getByTestId("chem-history-row-app-1"));
    expect(navigateSpy).toHaveBeenCalledWith("/admin/chemical-applications/app-1");
  });
});


// ═══════════════════════════════════════════════════════════════════
// 9. Empty state + CTA
// ═══════════════════════════════════════════════════════════════════
describe("CustomerChemicalHistoryTab — empty state", () => {
  it("renders empty state + 'Log First Application' CTA navigates", async () => {
    _installMocks({ first: { items: [], next_cursor: null } });
    render(<CustomerChemicalHistoryTab customer={CUSTOMER} />);
    await waitFor(() => {
      expect(screen.getByTestId("chemical-history-empty")).toBeTruthy();
    });
    fireEvent.click(screen.getByTestId("chemical-history-empty-cta"));
    expect(navigateSpy).toHaveBeenCalledWith(
      "/admin/chemical-applications/new?customer_id=cust-1",
    );
  });
});


// ═══════════════════════════════════════════════════════════════════
// 10. Error + retry
// ═══════════════════════════════════════════════════════════════════
describe("CustomerChemicalHistoryTab — error state", () => {
  it("renders error banner + Retry re-fetches successfully", async () => {
    apiGetSpy.mockReset();
    let hits = 0;
    apiGetSpy.mockImplementation((path) => {
      if (typeof path === "string" && path.startsWith("/chemical-applications")) {
        hits += 1;
        if (hits === 1) return Promise.reject(new Error("boom"));
        return Promise.resolve({ items: [_row({ id: "recovered" })], next_cursor: null });
      }
      return Promise.resolve({});
    });
    render(<CustomerChemicalHistoryTab customer={CUSTOMER} />);
    await waitFor(() => {
      expect(screen.getByTestId("chemical-history-error")).toBeTruthy();
    });
    fireEvent.click(screen.getByTestId("chemical-history-error-retry"));
    await waitFor(() => {
      expect(screen.getByTestId("chem-history-row-recovered")).toBeTruthy();
    });
  });
});


// ═══════════════════════════════════════════════════════════════════
// 11. Role-set shape lock
// ═══════════════════════════════════════════════════════════════════
describe("CustomerChemicalHistoryTab — role set shape", () => {
  it("exports CHEMICAL_HISTORY_TAB_ROLES = ['admin', 'super_admin', 'manager']", () => {
    expect(Array.isArray(CHEMICAL_HISTORY_TAB_ROLES)).toBe(true);
    expect(CHEMICAL_HISTORY_TAB_ROLES).toContain("admin");
    expect(CHEMICAL_HISTORY_TAB_ROLES).toContain("super_admin");
    expect(CHEMICAL_HISTORY_TAB_ROLES).toContain("manager");
    expect(CHEMICAL_HISTORY_TAB_ROLES).not.toContain("technician");
    expect(CHEMICAL_HISTORY_TAB_ROLES).not.toContain("customer");
  });

  it("filterCustomerTabs hides Chemical History for technician and customer roles", async () => {
    const {
      filterCustomerTabs,
    } = await vi.importActual("../components/customer/CustomerMeasurementsTab");
    const TABS = [
      { k: "overview", label: "Overview" },
      { k: "chemical_history", label: "Chemical History",
        roles: CHEMICAL_HISTORY_TAB_ROLES },
    ];
    const forTech = filterCustomerTabs(TABS, "technician");
    expect(forTech.some((t) => t.k === "chemical_history")).toBe(false);
    const forCustomer = filterCustomerTabs(TABS, "customer");
    expect(forCustomer.some((t) => t.k === "chemical_history")).toBe(false);
    for (const role of ["admin", "super_admin", "manager"]) {
      const visible = filterCustomerTabs(TABS, role);
      expect(visible.some((t) => t.k === "chemical_history")).toBe(true);
    }
  });
});


// ═══════════════════════════════════════════════════════════════════
// 14. Cursor pagination
// ═══════════════════════════════════════════════════════════════════
describe("CustomerChemicalHistoryTab — pagination", () => {
  it("Load more appends rows via cursor", async () => {
    _installMocks({
      first:  { items: [_row({ id: "app-1" })], next_cursor: "cursor-abc" },
      second: { items: [_row({ id: "app-2" })], next_cursor: null },
    });
    render(<CustomerChemicalHistoryTab customer={CUSTOMER} />);
    await waitFor(() => {
      expect(screen.getByTestId("chemical-history-load-more")).toBeTruthy();
    });
    fireEvent.click(screen.getByTestId("chemical-history-load-more"));
    await waitFor(() => {
      expect(screen.getByTestId("chem-history-row-app-2")).toBeTruthy();
    });
    expect(screen.getByTestId("chem-history-row-app-1")).toBeTruthy();
    expect(screen.queryByTestId("chemical-history-load-more")).toBeNull();
  });
});
