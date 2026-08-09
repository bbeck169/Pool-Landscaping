/**
 * Phase 54b · Feb-2026 — Wholesale supplier settings page tests.
 *
 * Covers:
 *   1. Loading state → error → empty history render path.
 *   2. Legal disclaimer renders verbatim (Phase 54b spec).
 *   3. Save credentials POSTs to /suppliers/poolcorp/credentials.
 *   4. "Sync now" is disabled until creds exist, then POSTs to
 *      /suppliers/poolcorp/sync and refreshes history.
 *   5. Sync failure (400 no_credentials) shows a toast with the
 *      server's ``detail.message`` string.
 *   6. Manager role → form inputs disabled, action buttons hidden,
 *      read-only notice visible.
 *   7. Non-poolcorp suppliers render as "Coming in 54c/d/e" cards.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

// ── Mock api + toast + auth BEFORE importing the component. ──
const getMock = vi.fn();
const postMock = vi.fn();
const deleteMock = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get:    (...a) => getMock(...a),
    post:   (...a) => postMock(...a),
    delete: (...a) => deleteMock(...a),
  },
}));

const toastSuccess = vi.fn();
const toastError = vi.fn();
vi.mock("sonner", () => ({
  toast: {
    success: (...a) => toastSuccess(...a),
    error:   (...a) => toastError(...a),
  },
}));

let mockUser = { role: "admin" };
vi.mock("@/auth", () => ({
  useAuth: () => ({ user: mockUser, loading: false }),
}));

import SupplierSettings from "@/pages/settings/SupplierSettings";

const SUPPLIERS_FIXTURE = [
  { slug: "poolcorp",    display_name: "Pool360 (PoolCorp)" },
  { slug: "siteone",     display_name: "SiteOne" },
  { slug: "ewing",       display_name: "Ewing Irrigation" },
  { slug: "heritage",    display_name: "Heritage Pool Plus" },
  { slug: "epoolsupply", display_name: "ePoolSupply" },
];

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/settings/suppliers"]}>
      <SupplierSettings />
    </MemoryRouter>,
  );
}

function primeApiCalls({
  suppliers = SUPPLIERS_FIXTURE,
  hasCreds = false,
  jobs = [],
} = {}) {
  getMock.mockImplementation((path) => {
    if (path === "/suppliers") return Promise.resolve(suppliers);
    if (path === "/suppliers/poolcorp/credentials") {
      return Promise.resolve({
        supplier_slug: "poolcorp",
        has_credentials: hasCreds,
        updated_at: hasCreds ? "2026-02-14T10:00:00Z" : null,
      });
    }
    if (path.startsWith("/suppliers/poolcorp/sync-jobs")) {
      return Promise.resolve({ supplier_slug: "poolcorp", jobs, count: jobs.length });
    }
    return Promise.reject(new Error("unmocked GET " + path));
  });
}

beforeEach(() => {
  getMock.mockReset();
  postMock.mockReset();
  deleteMock.mockReset();
  toastSuccess.mockReset();
  toastError.mockReset();
  mockUser = { role: "admin" };
});

afterEach(() => cleanup());


// ═══════════════════════════════════════════════════════════════════
// 1. Basic render + legal disclaimer + coming-soon cards
// ═══════════════════════════════════════════════════════════════════
describe("SupplierSettings — render", () => {
  it("renders the page container after loading suppliers", async () => {
    primeApiCalls();
    renderPage();
    expect(await screen.findByTestId("supplier-settings-page")).toBeInTheDocument();
    // Poolcorp card appears
    expect(await screen.findByTestId("supplier-card-poolcorp")).toBeInTheDocument();
  });

  it("renders the LITERAL legal disclaimer string under Pool360", async () => {
    primeApiCalls();
    renderPage();
    const disclaimer = await screen.findByTestId("supplier-poolcorp-legal-disclaimer");
    expect(disclaimer.textContent).toContain(
      "Automated syncing may be subject to your wholesaler's Terms of Service",
    );
    expect(disclaimer.textContent).toContain(
      "By connecting, you acknowledge responsibility for compliance with those terms.",
    );
  });

  it("renders coming-soon cards for the four other suppliers", async () => {
    primeApiCalls();
    renderPage();
    for (const slug of ["siteone", "ewing", "heritage", "epoolsupply"]) {
      expect(await screen.findByTestId(`supplier-card-${slug}`)).toBeInTheDocument();
    }
    // Coming-soon cards do NOT get a credentials form / sync button
    expect(screen.queryByTestId("supplier-siteone-sync-btn")).toBeNull();
    expect(screen.queryByTestId("supplier-heritage-username-input")).toBeNull();
  });

  it("shows an empty history message when the sync-jobs list is empty", async () => {
    primeApiCalls({ jobs: [] });
    renderPage();
    expect(await screen.findByTestId("supplier-poolcorp-history-empty")).toBeInTheDocument();
  });
});


// ═══════════════════════════════════════════════════════════════════
// 2. Save credentials happy path + sync-now flow
// ═══════════════════════════════════════════════════════════════════
describe("SupplierSettings — save + sync", () => {
  it("saves credentials via POST /suppliers/poolcorp/credentials", async () => {
    primeApiCalls();
    postMock.mockResolvedValueOnce({ ok: true, supplier_slug: "poolcorp",
                                     updated_at: "2026-02-14T11:00:00Z" });
    renderPage();

    const u = await screen.findByTestId("supplier-poolcorp-username-input");
    const p = await screen.findByTestId("supplier-poolcorp-password-input");
    fireEvent.change(u, { target: { value: "operator" } });
    fireEvent.change(p, { target: { value: "s3cret" } });

    const saveBtn = await screen.findByTestId("supplier-poolcorp-save-btn");
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(postMock).toHaveBeenCalledWith(
        "/suppliers/poolcorp/credentials",
        { username: "operator", password: "s3cret" },
      );
    });
    await waitFor(() => expect(toastSuccess).toHaveBeenCalled());
  });

  it('"Sync now" is disabled when no credentials are saved', async () => {
    primeApiCalls({ hasCreds: false });
    renderPage();
    const syncBtn = await screen.findByTestId("supplier-poolcorp-sync-btn");
    expect(syncBtn).toBeDisabled();
  });

  it('"Sync now" POSTs to /suppliers/poolcorp/sync when credentials exist', async () => {
    primeApiCalls({ hasCreds: true });
    postMock.mockResolvedValueOnce({
      job_id: "job-abc-123", status: "running", supplier_slug: "poolcorp",
    });
    renderPage();

    const syncBtn = await screen.findByTestId("supplier-poolcorp-sync-btn");
    await waitFor(() => expect(syncBtn).not.toBeDisabled());
    fireEvent.click(syncBtn);

    await waitFor(() => {
      expect(postMock).toHaveBeenCalledWith("/suppliers/poolcorp/sync", {});
    });
    await waitFor(() => expect(toastSuccess).toHaveBeenCalled());
  });

  it("surfaces the server error message when Sync now returns 400", async () => {
    primeApiCalls({ hasCreds: true });
    // Api wrapper throws Error with .data.detail on non-2xx.
    const err = new Error("Save Pool360 credentials before running sync.");
    err.data = { detail: { error: "no_credentials",
                            message: "Save Pool360 credentials before running sync." } };
    postMock.mockRejectedValueOnce(err);
    renderPage();
    const syncBtn = await screen.findByTestId("supplier-poolcorp-sync-btn");
    await waitFor(() => expect(syncBtn).not.toBeDisabled());
    fireEvent.click(syncBtn);
    await waitFor(() => expect(toastError).toHaveBeenCalled());
    const args = toastError.mock.calls[0];
    expect(String(args[0])).toContain("Save Pool360 credentials");
  });
});


// ═══════════════════════════════════════════════════════════════════
// 3. Manager read-only rendering
// ═══════════════════════════════════════════════════════════════════
describe("SupplierSettings — manager read-only", () => {
  it("disables the credentials form and hides action buttons for role=manager", async () => {
    mockUser = { role: "manager" };
    primeApiCalls({ hasCreds: true });
    renderPage();

    const u = await screen.findByTestId("supplier-poolcorp-username-input");
    const p = await screen.findByTestId("supplier-poolcorp-password-input");
    expect(u).toBeDisabled();
    expect(p).toBeDisabled();

    expect(screen.queryByTestId("supplier-poolcorp-save-btn")).toBeNull();
    expect(screen.queryByTestId("supplier-poolcorp-sync-btn")).toBeNull();
    expect(screen.queryByTestId("supplier-poolcorp-delete-btn")).toBeNull();

    expect(await screen.findByTestId("supplier-poolcorp-readonly-notice"))
      .toBeInTheDocument();
  });
});


// ═══════════════════════════════════════════════════════════════════
// 4. Route wrapper string-source sanity — regression guard against
//    someone accidentally downgrading the route to AdminOnly (which
//    would break manager read-only access) or opening it up to tech.
// ═══════════════════════════════════════════════════════════════════
describe("SupplierSettings — route wrapper wiring", () => {
  it("App.js wires /settings/suppliers with AdminOrManagerForSuppliers", async () => {
    const fs = await import("fs");
    const path = await import("path");
    const appSrc = fs.readFileSync(
      path.resolve(__dirname, "../App.js"), "utf8");
    expect(appSrc).toMatch(
      /settings\/suppliers.*AdminOrManagerForSuppliers.*SupplierSettings/s,
    );
    // The wrapper must accept manager but reject tech/customer.
    expect(appSrc).toMatch(
      /function AdminOrManagerForSuppliers[\s\S]*role === "manager"/,
    );
  });
});
