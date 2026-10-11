/**
 * M-TAG-FIX · Feb-2026 — MergeTagPalette full-catalog-on-open guard.
 *
 * Historical bug:  the picker crashed to "No tags match" with an
 * empty payload because ``catalog_grouped()`` 500'd on the first
 * registry entry that omitted a ``description`` field.  The
 * endpoint hardening now returns the full flat catalog; this
 * vitest locks the UX invariant end-to-end:
 *
 *   1. Open modal → the FULL catalog renders BEFORE any typing.
 *   2. Type a query → the list filters client-side.
 *   3. Clear query → the full list returns.
 *   4. Click a row → ``onInsert({{TOKEN}})`` fires with the
 *      double-brace-wrapped token.
 *   5. Picker is re-rendered inside a parent that owns a subject
 *      input + a body input — the SAME palette dialog serves
 *      BOTH surfaces (Phase 9B invariant).
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";

// Mock the api layer BEFORE the palette module imports it.
vi.mock("@/api", () => ({
  api: {
    get: vi.fn(async (path) => {
      if (path === "/marketing/merge-tags") {
        return {
          categories: {
            Customer: [
              { token: "NAME",        label: "Name",        description: "Full name" },
              { token: "FIRST_NAME",  label: "First Name",  description: "First name" },
              { token: "LAST_NAME",   label: "Last Name",   description: "Last name" },
              { token: "EMAIL",       label: "Email",       description: "Email address" },
              { token: "PHONE",       label: "Phone",       description: "Phone number" },
              { token: "COMPANY_NAME",label: "Company",     description: "Company name" },
            ],
            Invoice: [
              { token: "INVOICE_NUMBER", label: "Invoice #",  description: "Invoice number" },
              { token: "INVOICE_AMOUNT", label: "Amount",     description: "Invoice amount" },
              { token: "DUE_DATE",       label: "Due Date",   description: "Invoice due date" },
            ],
            Job: [
              { token: "JOB_NAME", label: "Job Name", description: "Scheduled job name" },
            ],
            Portal: [
              { token: "PORTAL_URL", label: "Portal URL", description: "Portal auto-login" },
              { token: "LOGIN_URL",  label: "Login URL",  description: "Portal login link" },
            ],
          },
        };
      }
      throw new Error(`unexpected api.get path: ${path}`);
    }),
  },
}));


// Import AFTER mocks are registered.
import { MergeTagPalette, __resetMergeTagCacheForTests }
  from "@/components/marketing/MergeTagPalette";
import { api } from "@/api";


// M-TAG-FIX FOLLOWUP Fix 2 — three mock shapes exercised below.
// Backend emits BOTH ``key`` and ``token`` during the deprecation
// window; a legacy pre-rename cache would emit ``token`` only; a
// post-removal response would emit ``key`` only. The consumer MUST
// handle all three so no in-flight client breaks.
const _CATALOG_LEGACY_TOKEN_ONLY = {
  categories: {
    Customer: [
      { token: "NAME",       label: "Name",       description: "Full name" },
      { token: "FIRST_NAME", label: "First Name", description: "First name" },
    ],
  },
};

const _CATALOG_CANONICAL_KEY_ONLY = {
  categories: {
    Customer: [
      { key: "NAME",       label: "Name",       description: "Full name" },
      { key: "FIRST_NAME", label: "First Name", description: "First name" },
    ],
  },
};

const _CATALOG_DEPRECATION_WINDOW_BOTH = {
  categories: {
    Customer: [
      { key: "NAME",       token: "NAME",       label: "Name",       description: "Full name" },
      { key: "FIRST_NAME", token: "FIRST_NAME", label: "First Name", description: "First name" },
    ],
  },
};


function Harness({ onInsert }) {
  const [open, setOpen] = React.useState(false);
  return (
    <>
      <button data-testid="open-btn" onClick={() => setOpen(true)}>
        Open
      </button>
      <MergeTagPalette
        open={open}
        onOpenChange={setOpen}
        onInsert={onInsert}
      />
    </>
  );
}


beforeEach(() => {
  __resetMergeTagCacheForTests();
});


describe("MergeTagPalette · opens with full catalog, filters client-side", () => {
  it("renders ≥12 tags on open BEFORE the user types anything", async () => {
    const insert = vi.fn();
    render(<Harness onInsert={insert} />);
    fireEvent.click(screen.getByTestId("open-btn"));
    // Wait for the catalog fetch to settle + rows to mount.
    await waitFor(() => {
      expect(screen.queryByText(/Loading tag catalog/)).toBeNull();
    });
    const rows = await screen.findAllByTestId(/^merge-tag-row-/);
    expect(rows.length).toBeGreaterThanOrEqual(12);
    // Explicit presence of the Feb-2026 required set.
    for (const tok of [
      "NAME", "FIRST_NAME", "LAST_NAME", "EMAIL", "PHONE",
      "COMPANY_NAME",
      "INVOICE_NUMBER", "INVOICE_AMOUNT", "DUE_DATE",
      "JOB_NAME",
      "PORTAL_URL", "LOGIN_URL",
    ]) {
      expect(screen.getByTestId(`merge-tag-row-${tok}`)).toBeTruthy();
    }
  });

  it("renders categories grouped — Customer / Invoice / Job / Portal", async () => {
    render(<Harness onInsert={vi.fn()} />);
    fireEvent.click(screen.getByTestId("open-btn"));
    await screen.findByTestId("merge-tag-row-NAME");
    expect(
      screen.getByTestId("merge-tag-category-header-Customer"),
    ).toBeTruthy();
    expect(
      screen.getByTestId("merge-tag-category-header-Invoice"),
    ).toBeTruthy();
    expect(
      screen.getByTestId("merge-tag-category-header-Job"),
    ).toBeTruthy();
    expect(
      screen.getByTestId("merge-tag-category-header-Portal"),
    ).toBeTruthy();
  });

  it("search filters client-side — typing narrows the list, clearing " +
     "it returns the full list", async () => {
    render(<Harness onInsert={vi.fn()} />);
    fireEvent.click(screen.getByTestId("open-btn"));
    await screen.findByTestId("merge-tag-row-NAME");
    const search = screen.getByTestId("merge-tag-palette-search");
    fireEvent.change(search, { target: { value: "invoice" } });
    await waitFor(() => {
      // Customer rows now hidden.
      expect(screen.queryByTestId("merge-tag-row-NAME")).toBeNull();
    });
    // Invoice rows still visible.
    expect(screen.getByTestId("merge-tag-row-INVOICE_NUMBER")).toBeTruthy();
    expect(screen.getByTestId("merge-tag-row-INVOICE_AMOUNT")).toBeTruthy();
    // Clearing the search restores the full list.
    fireEvent.change(search, { target: { value: "" } });
    await waitFor(() => {
      expect(screen.getByTestId("merge-tag-row-NAME")).toBeTruthy();
    });
  });

  it("clicking a tag fires onInsert with the double-brace-wrapped " +
     "token", async () => {
    const insert = vi.fn();
    render(<Harness onInsert={insert} />);
    fireEvent.click(screen.getByTestId("open-btn"));
    await screen.findByTestId("merge-tag-row-NAME");
    fireEvent.click(screen.getByTestId("merge-tag-row-NAME"));
    expect(insert).toHaveBeenCalledWith("{{NAME}}");
  });
});


describe("MergeTagPalette · subject + body parity", () => {
  // Two independent instances mount of the SAME palette — one for
  // the subject input surface, one for the body input surface.
  // The picker is a self-contained Dialog, so parity here is a
  // smoke test that re-mounting on a fresh parent still yields the
  // full catalog.
  function TwoSurfaces() {
    const [subjOpen, setSubjOpen] = React.useState(false);
    const [bodyOpen, setBodyOpen] = React.useState(false);
    return (
      <>
        <input data-testid="subject-input" />
        <button data-testid="subject-open" onClick={() => setSubjOpen(true)}>
          Insert in subject
        </button>
        <textarea data-testid="body-textarea" />
        <button data-testid="body-open" onClick={() => setBodyOpen(true)}>
          Insert in body
        </button>
        <MergeTagPalette
          open={subjOpen}
          onOpenChange={setSubjOpen}
          onInsert={(t) => {
            const el = document.querySelector(
              "[data-testid=\"subject-input\"]",
            );
            el.value = (el.value || "") + t;
          }}
        />
        <MergeTagPalette
          open={bodyOpen}
          onOpenChange={setBodyOpen}
          onInsert={(t) => {
            const el = document.querySelector(
              "[data-testid=\"body-textarea\"]",
            );
            el.value = (el.value || "") + t;
          }}
        />
      </>
    );
  }

  it("picker opens from a subject input AND inserts into it", async () => {
    render(<TwoSurfaces />);
    fireEvent.click(screen.getByTestId("subject-open"));
    await screen.findByTestId("merge-tag-row-NAME");
    fireEvent.click(screen.getByTestId("merge-tag-row-NAME"));
    expect(
      screen.getByTestId("subject-input").value,
    ).toBe("{{NAME}}");
  });

  it("picker opens from a body textarea AND inserts into it", async () => {
    render(<TwoSurfaces />);
    fireEvent.click(screen.getByTestId("body-open"));
    await screen.findByTestId("merge-tag-row-EMAIL");
    fireEvent.click(screen.getByTestId("merge-tag-row-EMAIL"));
    expect(
      screen.getByTestId("body-textarea").value,
    ).toBe("{{EMAIL}}");
  });
});


// ═══════════════════════════════════════════════════════════════════
// M-TAG-FIX FOLLOWUP Fix 2 · key/token field rename deprecation window
//
// The backend grouped+flat merge-tag endpoints now canonicalise the
// identifier field to ``key`` and emit ``token`` as a DEPRECATED
// alias. This consumer MUST read ``t.key`` with a fallback to
// ``t.token`` so no in-flight client breaks during the deprecation
// window. See ``/app/memory/deprecations.md`` for the removal
// schedule.
// ═══════════════════════════════════════════════════════════════════
describe("MergeTagPalette · key/token field rename deprecation window", () => {
  function _TinyHarness({ onInsert }) {
    const [open, setOpen] = React.useState(false);
    return (
      <>
        <button data-testid="tiny-open" onClick={() => setOpen(true)}>
          Open
        </button>
        <MergeTagPalette
          open={open}
          onOpenChange={setOpen}
          onInsert={onInsert}
        />
      </>
    );
  }

  it("renders rows + inserts correctly when the API emits ONLY the " +
     "DEPRECATED ``token`` field (legacy pre-rename shape)", async () => {
    api.get.mockImplementationOnce(async () => _CATALOG_LEGACY_TOKEN_ONLY);
    const insert = vi.fn();
    render(<_TinyHarness onInsert={insert} />);
    fireEvent.click(screen.getByTestId("tiny-open"));
    const row = await screen.findByTestId("merge-tag-row-NAME");
    expect(row).toBeTruthy();
    expect(screen.getByTestId("merge-tag-row-FIRST_NAME")).toBeTruthy();
    fireEvent.click(row);
    expect(insert).toHaveBeenCalledWith("{{NAME}}");
  });

  it("renders rows + inserts correctly when the API emits ONLY the " +
     "canonical ``key`` field (post-removal shape)", async () => {
    api.get.mockImplementationOnce(async () => _CATALOG_CANONICAL_KEY_ONLY);
    const insert = vi.fn();
    render(<_TinyHarness onInsert={insert} />);
    fireEvent.click(screen.getByTestId("tiny-open"));
    const row = await screen.findByTestId("merge-tag-row-NAME");
    expect(row).toBeTruthy();
    expect(screen.getByTestId("merge-tag-row-FIRST_NAME")).toBeTruthy();
    fireEvent.click(row);
    expect(insert).toHaveBeenCalledWith("{{NAME}}");
  });

  it("renders rows + inserts correctly when the API emits BOTH " +
     "``key`` and ``token`` (deprecation-window shape — current " +
     "production backend)", async () => {
    api.get.mockImplementationOnce(
      async () => _CATALOG_DEPRECATION_WINDOW_BOTH,
    );
    const insert = vi.fn();
    render(<_TinyHarness onInsert={insert} />);
    fireEvent.click(screen.getByTestId("tiny-open"));
    const row = await screen.findByTestId("merge-tag-row-FIRST_NAME");
    expect(row).toBeTruthy();
    fireEvent.click(row);
    expect(insert).toHaveBeenCalledWith("{{FIRST_NAME}}");
  });

  it("search filter works against ``key`` when ``token`` is absent " +
     "(the canonical post-removal shape)", async () => {
    api.get.mockImplementationOnce(async () => _CATALOG_CANONICAL_KEY_ONLY);
    render(<_TinyHarness onInsert={vi.fn()} />);
    fireEvent.click(screen.getByTestId("tiny-open"));
    await screen.findByTestId("merge-tag-row-NAME");
    const search = screen.getByTestId("merge-tag-palette-search");
    fireEvent.change(search, { target: { value: "FIRST" } });
    await waitFor(() => {
      expect(screen.queryByTestId("merge-tag-row-NAME")).toBeNull();
    });
    expect(screen.getByTestId("merge-tag-row-FIRST_NAME")).toBeTruthy();
  });
});
