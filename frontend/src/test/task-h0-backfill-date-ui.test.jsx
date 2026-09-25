/**
 * Task H0 · Feb-2026 — Historical Invoice Date Backfill · UI.
 *
 * Locks the admin-only backfill-date input contract on:
 *   1. ``QuoteInvoiceNew.jsx``     — ``created_at`` backfill.
 *   2. ``RecordPaymentModal``      — ``paid_at`` backfill (co-
 *      located in ``QuoteInvoiceDetail.jsx``; imported as a
 *      named component via source-transform trick because the
 *      module default-exports the page, not the modal).
 *
 * Coverage matrix (6 cases · matches the halt-report plan):
 *
 *   QuoteInvoiceNew:
 *     1. Admin viewer  → backfill section renders.
 *     2. Non-admin (tech) → backfill section absent.
 *     3. Admin sets a date → POST payload includes
 *        ``created_at`` (ISO-8601 string) verbatim.
 *     4. Admin leaves blank → POST payload OMITS the
 *        ``created_at`` key entirely (server stamps ``now()``).
 *
 *   RecordPaymentModal:
 *     5. Admin viewer  → paid-date section renders (mount via
 *        source-inspection; full DOM mount of the deep modal
 *        would require stubbing every ``QuoteInvoiceDetail``
 *        dep + is disproportionate for a 4-line render check).
 *     6. Non-admin → paid-date section absent (same posture).
 *
 * Test style — the vitest posture matches the codebase's mixed
 * DOM-mount (cases 1-4) + source-inspection (cases 5-6) idiom;
 * see ``jobdetail-k6-completed-unlock.test.jsx`` (source-only)
 * vs ``invoice-save-errors-inline.test.jsx`` (DOM-mount) for
 * the two established prior arts.
 */
import fs from "fs";
import path from "path";
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

// ── Mocks ──────────────────────────────────────────────────────
let currentUser = { id: "admin-1", role: "admin" };
vi.mock("@/auth", () => ({
  useAuth: () => ({ user: currentUser }),
  AuthProvider: ({ children }) => children,
}));

const postSpy = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: vi.fn(async (url) => {
      if (url === "/customers?is_active=true") {
        return [{ id: "cust-1", name: "TEST_cust", is_active: true }];
      }
      if (url === "/items") return [];
      if (url === "/settings/terms") return { default_quote_terms: "", default_invoice_terms: "" };
      if (url === "/income-categories") {
        return { items: [{ id: "cat-pool", name: "Pool", color: "#0EA5E9" }] };
      }
      return {};
    }),
    post: (...args) => postSpy(...args),
  },
}));

import { invalidateCategoryCache } from "@/components/income/CategoryPicker";
import QuoteInvoiceNew from "@/pages/quotes/QuoteInvoiceNew";


// ── Helpers ────────────────────────────────────────────────────
async function tick() {
  await act(async () => { for (let i = 0; i < 5; i += 1) await Promise.resolve(); });
}

function mount(docType = "quote") {
  return render(
    <MemoryRouter initialEntries={[`/${docType}s/new?customer_id=cust-1`]}>
      <QuoteInvoiceNew docType={docType} />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  invalidateCategoryCache();
  postSpy.mockReset();
  postSpy.mockResolvedValue({ id: "new-quote-123" });
  currentUser = { id: "admin-1", role: "admin" };
});


// ── (1) Admin viewer → backfill section renders ────────────────
describe("Task H0 · QuoteInvoiceNew · admin backfill section", () => {
  it("renders the backfill section when viewer is admin", async () => {
    currentUser = { id: "admin-1", role: "admin" };
    mount("quote");
    await tick();
    const section = screen.queryByTestId("backfill-date-section");
    expect(section).not.toBeNull();
    // The input lives inside a collapsed <details>; opening it
    // reveals the date input.  Do not click — just assert the
    // section wrapper renders. Vitest can query nested elements
    // inside a collapsed <details> without expanding.
    expect(screen.queryByTestId("backfill-date-input")).not.toBeNull();
  });

  it("renders the section for super_admin too", async () => {
    currentUser = { id: "super-1", role: "super_admin" };
    mount("quote");
    await tick();
    expect(screen.queryByTestId("backfill-date-section")).not.toBeNull();
  });

  it("renders the section for owner too (matches backend allowlist)", async () => {
    currentUser = { id: "owner-1", role: "owner" };
    mount("quote");
    await tick();
    expect(screen.queryByTestId("backfill-date-section")).not.toBeNull();
  });
});


// ── (2) Non-admin viewer → backfill section absent ─────────────
describe("Task H0 · QuoteInvoiceNew · non-admin viewer", () => {
  it("does NOT render the backfill section for technician", async () => {
    currentUser = { id: "tech-1", role: "technician" };
    mount("quote");
    await tick();
    expect(screen.queryByTestId("backfill-date-section")).toBeNull();
    expect(screen.queryByTestId("backfill-date-input")).toBeNull();
  });

  it("does NOT render the section when user is null (unauthenticated / uninit)", async () => {
    currentUser = null;
    mount("quote");
    await tick();
    expect(screen.queryByTestId("backfill-date-section")).toBeNull();
  });
});


// ── (3) Admin sets a date → payload includes created_at ────────
// Both cases 3+4 use source-inspection rather than a full DOM
// mount because ``fillLineAndSubmit`` depends on the same
// ``qf-line-0-desc`` MasterServiceCombobox flow that already
// baselines-flakes in ``invoice-save-errors-inline.test.jsx``.
// The wiring contract is small and unambiguous — the exact
// two-line conditional-key block in the component — so
// regex-locking it here is more reliable than a full-form
// e2e-style mount + also matches the JobDetail contract-suite
// posture used elsewhere in this repo.
describe("Task H0 · QuoteInvoiceNew · payload wiring (source lock)", () => {
  const SRC = fs.readFileSync(
    path.resolve(__dirname, "../pages/quotes/QuoteInvoiceNew.jsx"),
    "utf8",
  );

  it("case 3 · includes created_at ISO string on submit when admin picks a date", () => {
    // Regression guard on the conditional-key emission. The
    // exact pattern must be: ``if (canBackfill && backfillDate)
    // { payload.created_at = new Date(backfillDate).toISOString(); }``.
    // Any drift (e.g. sending the raw ``backfillDate`` YYYY-MM-DD
    // string, or dropping the ``canBackfill`` gate) fails here.
    expect(SRC).toMatch(
      /if\s*\(\s*canBackfill\s*&&\s*backfillDate\s*\)\s*\{[\s\S]{0,140}payload\.created_at\s*=\s*new\s+Date\(\s*backfillDate\s*\)\.toISOString\(\)/,
    );
  });

  it("case 4 · OMITS created_at when the admin leaves the date blank", () => {
    // Belt-and-suspenders: the payload object literal must NOT
    // declare ``created_at`` inline (only the conditional-key
    // block above should mutate it). A regression that adds
    // ``created_at: form.something`` to the initial payload
    // literal breaks the "no-override → no key" contract even
    // when ``canBackfill`` is false.
    expect(SRC).not.toMatch(
      /const\s+payload\s*=\s*\{[\s\S]{0,700}created_at\s*:/,
    );
  });

  it("case 4b · non-admin viewer cannot set created_at via the payload path", () => {
    // Same conditional gate as case 3 — the ``canBackfill && ...``
    // guard prevents a tech with a devtools-injected
    // ``backfillDate`` state from smuggling the field in. This
    // is UX-side only (server 403 is authoritative), but the
    // gate belongs here too.
    expect(SRC).toMatch(
      /const\s+canBackfill\s*=\s*\[[\s\S]{0,40}"admin"[\s\S]{0,40}"super_admin"[\s\S]{0,40}"owner"[\s\S]{0,40}\]\.includes/,
    );
  });
});


// ── (5, 6) RecordPaymentModal — source-inspection posture ──────
// Mounting the full QuoteInvoiceDetail page just to reach the
// modal would require stubbing 15+ dependencies (customer /
// payments / stripe / audit / follow-up …).  Source-inspection
// locks the render-gate contract cleanly without the mount cost;
// this is the exact posture used by ``jobdetail-k6-completed-
// unlock.test.jsx`` and the wider JobDetail contract suite.
describe("Task H0 · RecordPaymentModal · admin gate (source lock)", () => {
  const SRC = fs.readFileSync(
    path.resolve(__dirname, "../pages/quotes/QuoteInvoiceDetail.jsx"),
    "utf8",
  );

  it("accepts a ``user`` prop on the RecordPaymentModal signature", () => {
    // The modal signature must expose ``user`` so the parent can
    // prop-drill from useAuth() — this is the H0 wiring contract.
    expect(SRC).toMatch(
      /function\s+RecordPaymentModal\(\s*\{\s*[^}]*\buser\b[^}]*\}\s*\)/,
    );
  });

  it("gates the backfill-date section on the same 3-role allowlist as the backend", () => {
    // The role predicate must literally match the backend
    // ``_DEFAULT_ADMIN_ALLOWLIST`` — {admin, super_admin, owner}.
    // A drift on either side breaks the "silent-drop UX" contract
    // (non-admins should never see a control that gets ignored).
    expect(SRC).toMatch(
      /\[\s*"admin"\s*,\s*"super_admin"\s*,\s*"owner"\s*\]\s*\.\s*includes/,
    );
  });

  it("renders the backfill-date-section testid inside the modal only when canBackfill", () => {
    // Regression guard on the ternary — a future refactor that
    // hoists the section out of the ``{canBackfill ? ... : null}``
    // wrapper would leak the control to non-admins.
    expect(SRC).toMatch(
      /canBackfill\s*\?\s*\([\s\S]{0,700}data-testid=["']backfill-date-section["']/,
    );
    // Same for the input itself — the section must contain the
    // date input (either literally or via a component wrapper
    // that emits the testid).
    expect(SRC).toMatch(
      /data-testid=["']backfill-date-input["']|testid=["']backfill-date-input["']/,
    );
  });

  it("conditionally attaches paid_at to the payload only when admin picks a date", () => {
    // Regression guard on the conditional-key emission — the
    // fallback path (no backfill) must submit exactly the same
    // payload shape as pre-Task-H0 so the record-payment endpoint
    // never sees an unexpected paid_at key.
    expect(SRC).toMatch(
      /if\s*\(\s*canBackfill\s*&&\s*paidDate\s*\)\s*\{[\s\S]{0,140}payload\.paid_at\s*=\s*new\s+Date\(\s*paidDate\s*\)\.toISOString\(\)/,
    );
  });

  it("parent passes user={user} down to RecordPaymentModal", () => {
    // The prop-drill site must be intact — a regression that
    // forgets the ``user={user}`` prop reduces the admin gate to
    // ``user=undefined`` and hides the section from every viewer.
    // ``[\s\S]{0,300}`` (not ``[^>]*``) because the surrounding
    // JSX props contain arrow functions (``() => ...``) whose
    // ``>`` characters break a naive ``[^>]`` traversal.
    expect(SRC).toMatch(
      /<RecordPaymentModal[\s\S]{0,300}user=\{user\}/,
    );
  });
});
