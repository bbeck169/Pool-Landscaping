/**
 * Feb-2026 · P41 — CSV Import modal (Vitest).
 *
 * Contract pinned:
 *   1. Modal renders file input, radio group, template download link.
 *   2. Submit fires POST /api/customers/import-csv with multipart
 *      (file + target_status). We stub ``fetch`` so we can inspect
 *      the FormData payload without needing a live backend.
 *   3. Result modal shows created / updated / skipped / errored counts
 *      from the mocked response.
 *   4. Row-error list caps at 10 by default and expands to 100 on
 *      "Show all".
 *   5. Close on result → fires ``onDone`` (list refresh handler).
 *   6. Import CSV button is hidden for technician role on the parent
 *      customers page.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

import ImportCsvModalP41 from "@/pages/customers/ImportCsvModalP41";


// The modal calls window.fetch directly to preserve multipart headers,
// so we stub it globally per test.
let _lastFetch;

beforeEach(() => {
  _lastFetch = null;
  // Provide a token so the ``Authorization`` header is sent — proves
  // the modal wires auth correctly.
  localStorage.setItem("token", "unit-test-token");
  window.fetch = vi.fn(async (url, opts) => {
    _lastFetch = { url, opts };
    return {
      ok: true,
      status: 200,
      text: async () => JSON.stringify({
        ok: true,
        created: 2,
        updated: 1,
        skipped_no_new_data: 3,
        errored: 2,
        row_errors: [
          { row: 4, reason: "missing_required" },
          { row: 9, reason: "invalid_email",
             detail: "bad@no dot" },
        ],
      }),
    };
  });
});

afterEach(() => {
  // Feb-2026 · Housekeeping Batch A tightening — use ``clearAllMocks``
  // (call-history only) instead of ``restoreAllMocks`` (which wipes
  // ``.mockResolvedValue(...)`` implementations set at module hoist
  // time). ``restoreAllMocks`` was causing a race: React's passive-
  // effects flush fired ``api.get(...).catch(...)`` in
  // ``CustomersList.jsx:679`` AFTER the afterEach hook cleared the
  // resolved value, turning the mock into a bare ``vi.fn()`` that
  // returned ``undefined`` — so ``.catch`` threw an unhandled
  // rejection and vitest exited 1 despite zero test failures.
  vi.clearAllMocks();
});


describe("ImportCsvModalP41 · P41", () => {
  it("renders file input, radio group and template link", () => {
    render(<ImportCsvModalP41 open onClose={() => {}} />);
    expect(screen.getByTestId("import-csv-modal")).toBeTruthy();
    expect(screen.getByTestId("import-csv-file-input")).toBeTruthy();
    expect(screen.getByTestId("import-csv-target-active")).toBeTruthy();
    expect(screen.getByTestId("import-csv-target-inactive")).toBeTruthy();
    expect(screen.getByTestId("import-csv-template-link")).toBeTruthy();
    expect(screen.getByTestId("import-csv-submit")).toBeTruthy();
  });

  it("Submit POSTs multipart with file + target_status", async () => {
    render(<ImportCsvModalP41 open onClose={() => {}} setToast={() => {}} />);
    // Target radio → inactive.
    fireEvent.click(screen.getByTestId("import-csv-target-inactive"));
    // Attach a file.
    const file = new File(
      ["First Name,Last Name,Service Address,Email,Phone Number\nA,B,1 St,,"],
      "sample.csv", { type: "text/csv" });
    fireEvent.change(screen.getByTestId("import-csv-file-input"), {
      target: { files: [file] },
    });
    fireEvent.click(screen.getByTestId("import-csv-submit"));

    await waitFor(() => expect(_lastFetch).toBeTruthy());
    expect(_lastFetch.url).toMatch(/\/api\/customers\/import-csv$/);
    expect(_lastFetch.opts.method).toBe("POST");
    expect(_lastFetch.opts.headers.Authorization).toBe(
      "Bearer unit-test-token");
    // FormData body — inspect via .get().
    const fd = _lastFetch.opts.body;
    expect(fd instanceof FormData).toBe(true);
    expect(fd.get("target_status")).toBe("inactive");
    expect(fd.get("file")).toBeInstanceOf(File);
  });

  it("Result modal renders counts from the response envelope", async () => {
    render(<ImportCsvModalP41 open onClose={() => {}} setToast={() => {}} />);
    const file = new File(["x"], "x.csv", { type: "text/csv" });
    fireEvent.change(screen.getByTestId("import-csv-file-input"),
      { target: { files: [file] } });
    fireEvent.click(screen.getByTestId("import-csv-submit"));
    await waitFor(() => expect(screen.getByTestId(
      "import-csv-result-modal")).toBeTruthy());
    expect(screen.getByTestId("import-csv-result-created").textContent)
      .toBe("2");
    expect(screen.getByTestId("import-csv-result-updated").textContent)
      .toBe("1");
    expect(screen.getByTestId("import-csv-result-skipped").textContent)
      .toBe("3");
    expect(screen.getByTestId("import-csv-result-errored").textContent)
      .toBe("2");
    // Both errors visible (2 < 10 cap).
    expect(screen.getByTestId("import-csv-result-error-row-0")).toBeTruthy();
    expect(screen.getByTestId("import-csv-result-error-row-1")).toBeTruthy();
  });

  it("Row-error list expands from 10 to 100 on 'Show all'", async () => {
    // Return 25 errors so the default cap of 10 hides some.
    window.fetch = vi.fn(async () => ({
      ok: true, status: 200,
      text: async () => JSON.stringify({
        ok: true, created: 0, updated: 0, skipped_no_new_data: 0,
        errored: 25,
        row_errors: Array.from({ length: 25 }, (_, i) => ({
          row: i + 2, reason: "missing_required",
        })),
      }),
    }));
    render(<ImportCsvModalP41 open onClose={() => {}} setToast={() => {}} />);
    fireEvent.change(screen.getByTestId("import-csv-file-input"),
      { target: { files: [new File(["x"], "x.csv")] } });
    fireEvent.click(screen.getByTestId("import-csv-submit"));
    await waitFor(() => expect(screen.getByTestId(
      "import-csv-result-modal")).toBeTruthy());
    // Only 10 visible.
    expect(screen.queryByTestId("import-csv-result-error-row-9"))
      .toBeTruthy();
    expect(screen.queryByTestId("import-csv-result-error-row-10"))
      .toBeNull();
    fireEvent.click(screen.getByTestId("import-csv-errors-expand"));
    await waitFor(() => expect(screen.getByTestId(
      "import-csv-result-error-row-24")).toBeTruthy());
  });

  it("Close on result modal fires onDone (list refresh)", async () => {
    const onDone = vi.fn();
    render(<ImportCsvModalP41 open onClose={() => {}} onDone={onDone}
                                setToast={() => {}} />);
    fireEvent.change(screen.getByTestId("import-csv-file-input"),
      { target: { files: [new File(["x"], "x.csv")] } });
    fireEvent.click(screen.getByTestId("import-csv-submit"));
    await waitFor(() => expect(screen.getByTestId(
      "import-csv-result-modal")).toBeTruthy());
    fireEvent.click(screen.getByTestId("import-csv-result-close"));
    expect(onDone).toHaveBeenCalled();
  });

  it("matched_in_other_status renders as info (not error) styling",
      async () => {
    window.fetch = vi.fn(async () => ({
      ok: true, status: 200,
      text: async () => JSON.stringify({
        ok: true, created: 0, updated: 1, skipped_no_new_data: 0,
        errored: 0,
        row_errors: [
          { row: 2, reason: "matched_in_other_status",
             detail: "Customer exists in Active list; row will not be "
                        + "moved to Inactive. Fields merged in place." },
          { row: 3, reason: "missing_required" },
        ],
      }),
    }));
    render(<ImportCsvModalP41 open onClose={() => {}} setToast={() => {}} />);
    fireEvent.change(screen.getByTestId("import-csv-file-input"),
      { target: { files: [new File(["x"], "x.csv")] } });
    fireEvent.click(screen.getByTestId("import-csv-submit"));
    await waitFor(() => expect(screen.getByTestId(
      "import-csv-result-modal")).toBeTruthy());
    const infoRow = screen.getByTestId("import-csv-result-error-row-0");
    const errRow = screen.getByTestId("import-csv-result-error-row-1");
    expect(infoRow.getAttribute("data-reason"))
      .toBe("matched_in_other_status");
    expect(errRow.getAttribute("data-reason")).toBe("missing_required");
    // Info row uses the blue palette; error row uses the red palette.
    expect(infoRow.style.color).toBe("rgb(30, 58, 138)");
    expect(errRow.style.color).toBe("rgb(127, 29, 29)");
    // Errored top-level counter reflects the backend's exclusion of
    // the info row.
    expect(screen.getByTestId("import-csv-result-errored").textContent)
      .toBe("0");
    expect(screen.getByTestId("import-csv-result-updated").textContent)
      .toBe("1");
  });
});


// ── RBAC on the parent Customers list ──────────────────────────────
// We isolate this from the modal to keep the modal tests light. The
// button visibility is a pure permissions-hook check on the page.
vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({ role: "technician", effectiveRole: "technician" }),
}));
// Prevent the customers page from actually hitting the network on mount.
vi.mock("@/api", () => ({
  api: {
    get: vi.fn().mockResolvedValue({ items: [], total: 0, page: 1,
      pages: 1 }),
    post: vi.fn().mockResolvedValue({ ok: true }),
    patch: vi.fn().mockResolvedValue({ ok: true }),
    delete: vi.fn().mockResolvedValue({ ok: true }),
  },
}));
// Router surface used by the page — no real navigation needed.
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return {
    ...actual,
    useNavigate: () => () => {},
    useLocation: () => ({ pathname: "/customers", search: "" }),
    useSearchParams: () => [new URLSearchParams(), () => {}],
  };
});


import CustomersList from "@/pages/customers/CustomersList";


describe("CustomersList · P41 button RBAC", () => {
  it("does not render the Import CSV button for a technician", () => {
    render(<CustomersList />);
    expect(screen.queryByTestId("import-csv-btn")).toBeNull();
  });
});
