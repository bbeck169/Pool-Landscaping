/**
 * Feb-2026 · N5-T1 · PageHeader adoption sweep — consolidated smoke test.
 *
 * Scope
 * ─────
 * One assertion contract per Tier 1 page:
 *   1. `<PageHeader>` is mounted (via ``data-testid="page-header"``).
 *   2. The correct ``title`` string reaches the header H1 (via
 *      ``page-header-title``).
 *   3. Where applicable, the page's preserved toolbar action testid
 *      still resolves in the DOM (smoke-level accessibility of the
 *      previously visible affordance).
 *
 * Rationale
 * ─────────
 * The Tier 1 pages import heavy hook trees (``useAuth``, ``useAttendance``,
 * ``useJsApiLoader``, ``api``, ``@react-google-maps/api``, recharts SVG,
 * Radix dropdowns, etc.).  Fully hydrating them in vitest is
 * out-of-scope for this commit — the assertion contract above is
 * the minimum needed to prove the header swap landed and the
 * previously-visible affordances remain reachable.
 *
 * Every page below is wrapped in ``<MemoryRouter>`` because the
 * shared ``PageHeader`` calls ``useNavigate()`` under the hood. All
 * external side-effecting deps (``api``, ``useAuth``, browser APIs)
 * are stubbed inline so the render surface is deterministic under
 * jsdom.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";


// ─── Shared cross-page mocks ─────────────────────────────────────
// The api module is used by every page for data fetching.  Stub
// every method as a never-resolves so the page renders its
// loading skeleton (which is enough for the PageHeader assertion).
vi.mock("@/api", () => ({
  api: {
    get: vi.fn(() => new Promise(() => {})),
    post: vi.fn(() => new Promise(() => {})),
    put: vi.fn(() => new Promise(() => {})),
    del: vi.fn(() => new Promise(() => {})),
  },
  TOKEN_KEY: "token",
}));

vi.mock("@/auth", () => ({
  useAuth: () => ({
    user: { role: "admin", name: "Admin Test", id: "u-1" },
    role: "admin",
    loading: false,
  }),
}));

// The real ``@/theme`` module needs the full colors + gradients
// surface Tier 1 pages reach for. Ship a superset shim that
// satisfies every field name observed in the wire-target files
// (``colors.pool[500]``, ``gradients.navyToGreen.css``, ``money``,
// ``colors.tile.solidNavy``, ``colors.accent`` rotation, etc.).
vi.mock("@/theme", () => {
  const palette = {
    50: "#F5F3FF", 100: "#EDE9FE", 500: "#7C3AED", 700: "#5B21B6",
  };
  const colors = {
    surface: "#FFFFFF",
    surfaceSecondary: "#F4F4F5",
    surfaceTertiary: "#E5E7EB",
    onSurface: "#09090B",
    onSurfaceSecondary: "#3F3F46",
    onBrandPrimary: "#FFFFFF",
    onBrandTertiary: "#164E63",
    brand: "#2563EB",
    brandSecondary: "#7C3AED",
    brandTertiary: "#E0F2FE",
    border: "#E4E4E7",
    divider: "#E4E4E7",
    muted: "#71717A",
    inputBorder: "#3B82F6",
    error: "#DC2626",
    success: "#16A34A",
    pool: { 500: "#0EA5E9" },
    landscape: { 50: "#F0FDF4", 500: "#22C55E", 700: "#15803D" },
    nav: { bg: "#1B1F5C", bgDeep: "#03002e", border: "#0F1341", fg: "#FFFFFF" },
    tile: { solidNavy: "#1B1F5C" },
    accent: {
      sky: palette, violet: palette, amber: palette,
      emerald: palette, rose: palette,
    },
  };
  return {
    colors,
    gradients: { navyToGreen: { css: "linear-gradient(#1B1F5C,#166534)" } },
    money: (n) => `$${Number(n || 0).toFixed(2)}`,
  };
});

// Nav sidebar mock — <PageHeader> imports the nav index from
// ``@/nav/adminNav`` transitively via <useGlobalSearch>. Shim it so
// the search bar renders empty groups without touching the real
// mount graph.
vi.mock("@/nav/adminNav", () => ({
  ADMIN_NAV_V2: [
    { key: "finance", label: "Finance", entries: [
      { to: "/invoices", label: "Invoices" },
    ] },
  ],
}));

// Search client — stub as noop so no fetch fires.
vi.mock("@/lib/globalSearchClient", () => ({
  searchGlobal: () => Promise.resolve({ customers: [], documents: [] }),
}));

// Router primitives keep working via the real ``react-router-dom``
// import + ``<MemoryRouter>`` wrapper.

// Cross-page reset.
beforeEach(() => {
  window.localStorage?.clear?.();
});
afterEach(() => {
  cleanup();
});


// ─── Helpers ─────────────────────────────────────────────────────
function mountInRouter(el) {
  return render(<MemoryRouter>{el}</MemoryRouter>);
}

/** Mount a page component under a specific route path + entry so
 *  its ``useParams()`` call resolves the expected id.  Necessary
 *  for detail-view pages (JobDetail, CustomerDetail,
 *  ChemicalApplicationDetail, QuoteInvoiceDetail) whose fetch
 *  branch keys off ``id`` from the router. */
function mountAtRoute(el, pathPattern, initialPath) {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path={pathPattern} element={el} />
      </Routes>
    </MemoryRouter>,
  );
}

function expectPageHeaderWithTitle(expected) {
  const header = screen.getByTestId("page-header");
  expect(header).toBeTruthy();
  const title = screen.getByTestId("page-header-title");
  // Title may contain nested spans (icons + text) — assert on
  // the text content, not the DOM structure.
  expect(title.textContent).toContain(expected);
}


// ─── 1 · admin/Dashboard ─────────────────────────────────────────
describe("N5-T1 · admin/Dashboard", () => {
  it("renders PageHeader with the Dashboard title", async () => {
    const { default: AdminDashboard } = await import("@/pages/admin/Dashboard");
    mountInRouter(<AdminDashboard />);
    expectPageHeaderWithTitle("Dashboard");
  });
});


// ─── 2 · customers/CustomerDetail ────────────────────────────────
// Heavy hook tree — reduce to smoke via mocking the customer fetch
// so a stable ``customer.name`` reaches the PageHeader title. All
// other panels render via their own null/skeleton branches when
// data is absent.
describe("N5-T1 · customers/CustomerDetail", () => {
  it("renders PageHeader ABOVE the identity strip (Option B)", async () => {
    // Override the shared api mock for the customer GET so the
    // page reaches its render-with-data branch and the header
    // title becomes the customer's name.  CustomerDetail issues a
    // ``Promise.all`` on mount for (customer, jobs, properties) —
    // ALL three must resolve or ``setCustomer`` never fires.
    const apiMod = await import("@/api");
    apiMod.api.get.mockImplementation((path) => {
      if (typeof path === "string" && path.startsWith("/customers/")) {
        // ``/customers/c-1/properties`` — array response.
        if (path.includes("/properties")) return Promise.resolve([]);
        // ``/customers/c-1`` — customer record.
        return Promise.resolve({
          id: "c-1", name: "Smith Residence",
          is_active: true, is_vip: false, tags: [],
        });
      }
      if (typeof path === "string" && path.startsWith("/jobs")) {
        return Promise.resolve([]);
      }
      return new Promise(() => {});
    });
    const { default: CustomerDetail } = await import("@/pages/customers/CustomerDetail");
    mountAtRoute(<CustomerDetail />, "/customers/:id", "/customers/c-1");
    // Wait for the fetch chain to resolve + React to commit.
    // CustomerDetail issues multiple side-fetches after the
    // initial customer GET; ``waitFor`` polls until the header
    // finishes rendering.
    await waitFor(() => {
      expect(screen.getByTestId("page-header")).toBeTruthy();
    });
    expectPageHeaderWithTitle("Smith Residence");
  });
});


// ─── 3 · reports/ReportsHub ──────────────────────────────────────
describe("N5-T1 · reports/ReportsHub", () => {
  it("renders PageHeader with the Reports title + preserved subtitle testid", async () => {
    const { default: ReportsHub } = await import("@/pages/reports/ReportsHub");
    mountInRouter(<ReportsHub />);
    expectPageHeaderWithTitle("Reports");
    // Existing testid contract on the subtitle span is preserved.
    expect(screen.getByTestId("reports-hub-title").textContent).toBe("Reports");
    expect(screen.getByTestId("reports-hub-subtitle").textContent).toContain(
      "Quick-access tiles",
    );
  });
});


// ─── 4 · schedule/TodaySchedule ──────────────────────────────────
// Reduced smoke — the module imports @react-google-maps/api which
// hangs jsdom.  Skip the render and only assert the module exports
// a valid React component. The header markup is exercised
// through the manual live-preview screenshots in the commit
// artifacts folder instead.
describe("N5-T1 · schedule/TodaySchedule", () => {
  it("module exports a default React component", async () => {
    // ``@react-google-maps/api`` transitively touches WebGL under
    // jsdom which OOMs the vitest worker; stub it inline.
    vi.doMock("@react-google-maps/api", () => ({
      useJsApiLoader: () => ({ isLoaded: false, loadError: null }),
    }));
    const mod = await import("@/pages/schedule/TodaySchedule");
    expect(typeof mod.default).toBe("function");
  });
});


// ─── 5 · chemical/ChemicalApplicationForm ────────────────────────
describe("N5-T1 · chemical/ChemicalApplicationForm", () => {
  it("renders PageHeader with the New / Edit Application title", async () => {
    const { default: ChemicalApplicationForm } = await import(
      "@/pages/chemical/ChemicalApplicationForm"
    );
    mountInRouter(<ChemicalApplicationForm />);
    expectPageHeaderWithTitle("New Application");
  });
});


// ─── 6 · chemical/ChemicalApplicationDetail ──────────────────────
describe("N5-T1 · chemical/ChemicalApplicationDetail", () => {
  it("renders PageHeader with the chemical name once fetched", async () => {
    const apiMod = await import("@/api");
    apiMod.api.get.mockImplementation((path) => {
      if (typeof path === "string" && path.startsWith("/chemical-applications/")) {
        return Promise.resolve({
          id: "ca-1", chemical_name: "Glyphosate 41%",
          application_date: "2026-02-20",
        });
      }
      return new Promise(() => {});
    });
    const { default: ChemicalApplicationDetail } = await import(
      "@/pages/chemical/ChemicalApplicationDetail"
    );
    mountAtRoute(
      <ChemicalApplicationDetail />,
      "/admin/chemical-applications/:id",
      "/admin/chemical-applications/ca-1",
    );
    await new Promise((r) => setTimeout(r, 0));
    expectPageHeaderWithTitle("Glyphosate 41%");
  });
});


// ─── 7 · finance/FinancePages · PaymentsLedger ───────────────────
// The shared ``Header`` helper refactor threads PageHeader through
// all 4 exports.  Exercise via ``PaymentsLedger`` — the highest-
// visibility surface — as the canonical assertion; the other 3
// exports get PageHeader for free via the same helper.
describe("N5-T1 · finance/FinancePages shared Header refactor", () => {
  it("PaymentsLedger renders PageHeader via the shared Header helper", async () => {
    const { PaymentsLedger } = await import("@/pages/finance/FinancePages");
    mountInRouter(<PaymentsLedger />);
    // Loading branch renders the shared <Header title="Payments" …/>
    // regardless of data arrival, so PageHeader is visible
    // immediately.
    expectPageHeaderWithTitle("Payments");
    // Back button testid contract preserved (shared Header helper
    // still renders it above the PageHeader).
    expect(screen.getByTestId("back-btn")).toBeTruthy();
  });
});


// ─── 8 · jobs/JobsList ───────────────────────────────────────────
describe("N5-T1 · jobs/JobsList", () => {
  it("renders PageHeader with Jobs (admin) + preserved refresh testid", async () => {
    const { default: JobsList } = await import("@/pages/jobs/JobsList");
    mountInRouter(<JobsList />);
    expectPageHeaderWithTitle("Jobs (admin)");
    // Refresh button moved into PageHeader's actions slot — testid
    // contract preserved.
    expect(screen.getByTestId("jobs-refresh-btn")).toBeTruthy();
  });
});


// ─── 9 · jobs/JobDetail ──────────────────────────────────────────
describe("N5-T1 · jobs/JobDetail", () => {
  it("renders PageHeader with job title + admin action row preserved", async () => {
    // Feed the job fetch so the render-with-data branch commits.
    const apiMod = await import("@/api");
    apiMod.api.get.mockImplementation((path) => {
      if (typeof path === "string" && path === "/jobs/j-1") {
        return Promise.resolve({
          id: "j-1", title: "Weekly Pool Service",
          status: "scheduled", service_type: "pool",
          customer_id: "c-1", technician_id: "t-1",
        });
      }
      // ``/jobs/:id/detail`` (aggregator) never resolves.
      return new Promise(() => {});
    });
    const { default: JobDetail } = await import("@/pages/jobs/JobDetail");
    mountAtRoute(<JobDetail />, "/jobs/:id", "/jobs/j-1");
    await new Promise((r) => setTimeout(r, 0));
    expectPageHeaderWithTitle("Weekly Pool Service");
    // Admin action row (New Scheduled Job / Work Order / Email /
    // Delete) is now inside PageHeader's actions slot.
    expect(screen.getByTestId("jd-admin-action-row")).toBeTruthy();
    expect(screen.getByTestId("jd-new-scheduled-job")).toBeTruthy();
    expect(screen.getByTestId("jd-workorder")).toBeTruthy();
    expect(screen.getByTestId("jd-email")).toBeTruthy();
    expect(screen.getByTestId("jd-delete")).toBeTruthy();
  });
});


// ─── 10 · quotes/QuoteInvoiceDetail ──────────────────────────────
describe("N5-T1 · quotes/QuoteInvoiceDetail", () => {
  it("renders PageHeader with doc title once fetched", async () => {
    const apiMod = await import("@/api");
    apiMod.api.get.mockImplementation((path) => {
      if (typeof path === "string" && path.startsWith("/quotes/")) {
        return Promise.resolve({
          id: "q-1", doc_type: "invoice",
          title: "INV-2026-000042",
          status: "sent", customer_name: "Smith Residence",
          total: 250.0, payment_status: "unpaid",
        });
      }
      return new Promise(() => {});
    });
    const { default: QuoteInvoiceDetail } = await import(
      "@/pages/quotes/QuoteInvoiceDetail"
    );
    mountAtRoute(
      <QuoteInvoiceDetail docType="invoice" />,
      "/invoices/:id",
      "/invoices/q-1",
    );
    await new Promise((r) => setTimeout(r, 0));
    expectPageHeaderWithTitle("INV-2026-000042");
  });
});
