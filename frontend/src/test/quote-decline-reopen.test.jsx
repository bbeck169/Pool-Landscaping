/**
 * Phase 3 B2 · Feb-2026 — Quote lifecycle (Decline / Reopen) FE tests.
 *
 * Covers:
 *   A. Pure helper tests (``QuoteInvoiceDetail`` exports):
 *      • ``canUserDeclineOrReopenQuote`` role gate matrix.
 *      • ``shouldShowDeclineButton`` visibility predicate.
 *      • ``shouldShowReopenButton`` visibility predicate.
 *      • ``shouldShowConvertToInvoiceButton`` NOW hides on
 *        ``docStatus === "declined"`` (new Phase 3 regression).
 *   B. ``QuotesList`` component — lifecycle view filter wiring:
 *      • Default fetch sends ``?view=open`` on mount.
 *      • The 4-option filter control renders all 4 stable testids.
 *      • Clicking a filter option (``converted``) re-fetches with
 *        the right ``view`` querystring param.
 *      • Decline button hidden on a converted row.
 *      • Reopen button visible on a declined row (and only there).
 *      • Role-gated: viewing as a technician hides both.
 *
 * Follows the ``quotes-list-viewed-column.test.jsx`` mount pattern:
 *   • ``@/api`` is vi.mock'd with spies.
 *   • ``@/auth`` is vi.mock'd to inject the signed-in user.
 *   • Component is rendered under ``<MemoryRouter>`` because
 *     ``QuotesList`` uses ``useSearchParams`` + ``useNavigate``.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor, fireEvent, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import {
  canUserDeclineOrReopenQuote,
  shouldShowDeclineButton,
  shouldShowReopenButton,
  shouldShowConvertToInvoiceButton,
} from "@/pages/quotes/QuoteInvoiceDetail";

// ═══════════════════════════════════════════════════════════════════
// A1 · canUserDeclineOrReopenQuote role gate
// ═══════════════════════════════════════════════════════════════════
describe("Phase 3 B2 · canUserDeclineOrReopenQuote role gate", () => {
  it.each([["admin"], ["super_admin"], ["owner"], ["manager"]])(
    "returns true for %s",
    (role) => expect(canUserDeclineOrReopenQuote(role)).toBe(true),
  );
  it.each([["technician"], ["customer"], ["dispatcher"], [""], [null], [undefined]])(
    "returns false for %s",
    (role) => expect(canUserDeclineOrReopenQuote(role)).toBe(false),
  );
  it("is case-insensitive on role input", () => {
    expect(canUserDeclineOrReopenQuote("ADMIN")).toBe(true);
    expect(canUserDeclineOrReopenQuote("Manager")).toBe(true);
  });
});

// ═══════════════════════════════════════════════════════════════════
// A2 · shouldShowDeclineButton
// ═══════════════════════════════════════════════════════════════════
describe("Phase 3 B2 · shouldShowDeclineButton", () => {
  it("true on open-set quote (draft) with admin signed in", () => {
    expect(shouldShowDeclineButton({
      isInvoice: false,
      docStatus: "draft",
      convertedInvoiceId: null,
      canDecline: true,
    })).toBe(true);
  });
  it("true on sent + accepted (both in open-set)", () => {
    expect(shouldShowDeclineButton({
      isInvoice: false, docStatus: "sent",
      convertedInvoiceId: null, canDecline: true,
    })).toBe(true);
    expect(shouldShowDeclineButton({
      isInvoice: false, docStatus: "accepted",
      convertedInvoiceId: null, canDecline: true,
    })).toBe(true);
  });
  it("false on invoice doc_type (button is quote-only)", () => {
    expect(shouldShowDeclineButton({
      isInvoice: true, docStatus: "draft",
      convertedInvoiceId: null, canDecline: true,
    })).toBe(false);
  });
  it("false when already declined", () => {
    expect(shouldShowDeclineButton({
      isInvoice: false, docStatus: "declined",
      convertedInvoiceId: null, canDecline: true,
    })).toBe(false);
  });
  it("false when already converted (converted_invoice_id set)", () => {
    expect(shouldShowDeclineButton({
      isInvoice: false, docStatus: "draft",
      convertedInvoiceId: "inv-123", canDecline: true,
    })).toBe(false);
  });
  it("false when the user is below admin/manager (role gate)", () => {
    expect(shouldShowDeclineButton({
      isInvoice: false, docStatus: "draft",
      convertedInvoiceId: null, canDecline: false,
    })).toBe(false);
  });
  it("false on legacy statuses outside the open-set (approved, expired)", () => {
    expect(shouldShowDeclineButton({
      isInvoice: false, docStatus: "approved",
      convertedInvoiceId: null, canDecline: true,
    })).toBe(false);
    expect(shouldShowDeclineButton({
      isInvoice: false, docStatus: "expired",
      convertedInvoiceId: null, canDecline: true,
    })).toBe(false);
  });
});

// ═══════════════════════════════════════════════════════════════════
// A3 · shouldShowReopenButton
// ═══════════════════════════════════════════════════════════════════
describe("Phase 3 B2 · shouldShowReopenButton", () => {
  it("true on a declined quote with admin signed in", () => {
    expect(shouldShowReopenButton({
      isInvoice: false, docStatus: "declined", canReopen: true,
    })).toBe(true);
  });
  it("false on any non-declined status", () => {
    for (const s of ["draft", "sent", "accepted", "approved", "expired"]) {
      expect(shouldShowReopenButton({
        isInvoice: false, docStatus: s, canReopen: true,
      })).toBe(false);
    }
  });
  it("false on invoice doc_type (button is quote-only)", () => {
    expect(shouldShowReopenButton({
      isInvoice: true, docStatus: "declined", canReopen: true,
    })).toBe(false);
  });
  it("false when the user is below admin/manager (role gate)", () => {
    expect(shouldShowReopenButton({
      isInvoice: false, docStatus: "declined", canReopen: false,
    })).toBe(false);
  });
});

// ═══════════════════════════════════════════════════════════════════
// A4 · shouldShowConvertToInvoiceButton — Phase 3 regression
// (new ``docStatus`` arg hides the button on declined quotes to
// mirror the backend 400 ``quote_declined`` guard).
// ═══════════════════════════════════════════════════════════════════
describe("Phase 3 B2 · shouldShowConvertToInvoiceButton — declined guard", () => {
  it("Phase 1 baseline — true on a plain draft quote (no docStatus arg → defaults safe)", () => {
    expect(shouldShowConvertToInvoiceButton({
      isInvoice: false, convertedInvoiceId: null, canConvert: true,
    })).toBe(true);
  });
  it("Phase 3 · false when docStatus='declined' (mirrors backend quote_declined)", () => {
    expect(shouldShowConvertToInvoiceButton({
      isInvoice: false, convertedInvoiceId: null,
      canConvert: true, docStatus: "declined",
    })).toBe(false);
  });
  it("Phase 3 · true when docStatus='draft' + canConvert", () => {
    expect(shouldShowConvertToInvoiceButton({
      isInvoice: false, convertedInvoiceId: null,
      canConvert: true, docStatus: "draft",
    })).toBe(true);
  });
  it("Phase 3 · remains false when converted (converted+docStatus combo)", () => {
    expect(shouldShowConvertToInvoiceButton({
      isInvoice: false, convertedInvoiceId: "inv-x",
      canConvert: true, docStatus: "draft",
    })).toBe(false);
  });
});

// ═══════════════════════════════════════════════════════════════════
// B · QuotesList — lifecycle view filter + row controls
// ═══════════════════════════════════════════════════════════════════
const apiGet = vi.fn();
const apiPost = vi.fn();
let userMock = { role: "admin", id: "u-1" };

vi.mock("@/api", () => ({
  TOKEN_KEY: "token",
  api: {
    get: (...a) => apiGet(...a),
    post: (...a) => apiPost(...a),
    put: vi.fn(),
    del: vi.fn(),
  },
}));
vi.mock("@/auth", () => ({
  useAuth: () => ({ user: userMock, token: "t" }),
}));

// Stub CustomerFilterBar so its internal /customers fetch doesn't
// pollute ``apiGet`` call-counts; the component still renders a
// pass-through div so the layout above/below is unchanged.
vi.mock("@/components/customers/CustomerFilterBar", () => ({
  default: () => <div data-testid="quotes-filter-customer-stub" />,
}));

const SAMPLE_ROWS = [
  {
    id: "q-draft-1", doc_type: "quote", title: "Pool Install Quote",
    customer_id: "c-1", customer_name: "Alice",
    status: "draft", decision: null,
    total: 1000, converted_invoice_id: null,
  },
  {
    id: "q-sent-1", doc_type: "quote", title: "Patio Reseal",
    customer_id: "c-2", customer_name: "Bob",
    status: "sent", decision: null,
    total: 500, converted_invoice_id: null,
  },
];
const CONVERTED_ROWS = [
  {
    id: "q-conv-1", doc_type: "quote", title: "Spa Repair (converted)",
    customer_id: "c-3", customer_name: "Carol",
    status: "accepted", decision: "approved",
    total: 2000, converted_invoice_id: "inv-conv-1",
  },
];
const DECLINED_ROWS = [
  {
    id: "q-decl-1", doc_type: "quote", title: "Fountain Install",
    customer_id: "c-4", customer_name: "Dan",
    status: "declined", decision: null,
    total: 750, converted_invoice_id: null,
    previous_status: "sent",
  },
];

async function renderList({ initialEntries = ["/quotes"], rows } = {}) {
  const { default: QuotesList } = await import("@/pages/quotes/QuotesList");
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <QuotesList />
    </MemoryRouter>,
  );
}

describe("Phase 3 B2 · QuotesList — lifecycle view filter", () => {
  beforeEach(() => {
    apiGet.mockReset();
    apiPost.mockReset();
    userMock = { role: "admin", id: "u-1" };
  });
  afterEach(() => cleanup());

  it("default fetch on mount sends ?view=open", async () => {
    apiGet.mockResolvedValue(SAMPLE_ROWS);
    await renderList();
    await waitFor(() => {
      const calls = apiGet.mock.calls.map((c) => c[0]);
      expect(calls.some((u) => /view=open/.test(u))).toBe(true);
    });
  });

  it("filter control renders all 4 stable testids", async () => {
    apiGet.mockResolvedValue(SAMPLE_ROWS);
    await renderList();
    await screen.findByTestId("quotes-list-filter");
    // ZZ-A Wave 3-E · Feb-2026 — the ``converted`` lifecycle view
    // was renamed to ``accepted`` (``LIFECYCLE_VIEWS = ["open",
    // "accepted", "declined", "all"]`` at QuotesList.jsx:41; the
    // URL ``?view=converted`` is silently rewritten to
    // ``?view=accepted`` by the component — see QuotesList.jsx:
    // L37-39 + L116 rationale). Flipped the Converted testid
    // assertion to the Accepted replacement.
    expect(screen.getByTestId("quotes-list-filter-open")).toBeTruthy();
    expect(screen.getByTestId("quotes-list-filter-accepted")).toBeTruthy();
    expect(screen.getByTestId("quotes-list-filter-declined")).toBeTruthy();
    expect(screen.getByTestId("quotes-list-filter-all")).toBeTruthy();
  });

  it("clicking the Accepted filter re-fetches with ?view=accepted", async () => {
    // ZZ-A Wave 3-E · Feb-2026 — renamed from "Converted" per the
    // lifecycle view rename (see case above + QuotesList.jsx:41).
    apiGet.mockResolvedValue(SAMPLE_ROWS);
    await renderList();
    await screen.findByTestId("quotes-list-filter-accepted");
    apiGet.mockResolvedValue(CONVERTED_ROWS);
    await act(async () => {
      fireEvent.click(screen.getByTestId("quotes-list-filter-accepted"));
    });
    await waitFor(() => {
      const calls = apiGet.mock.calls.map((c) => c[0]);
      expect(calls.some((u) => /view=accepted/.test(u))).toBe(true);
    });
  });

  it("open view: Decline button renders on an open row, Reopen does NOT", async () => {
    apiGet.mockResolvedValue(SAMPLE_ROWS);
    await renderList();
    await screen.findByTestId("quote-row-q-draft-1");
    expect(screen.getByTestId("quote-row-decline-q-draft-1")).toBeTruthy();
    expect(screen.queryByTestId("quote-row-reopen-q-draft-1")).toBeNull();
  });

  it("converted view: Decline button is hidden on a converted row (Reopen also hidden)", async () => {
    apiGet.mockResolvedValue(CONVERTED_ROWS);
    await renderList({ initialEntries: ["/quotes?view=converted"] });
    await screen.findByTestId("quote-row-q-conv-1");
    expect(screen.queryByTestId("quote-row-decline-q-conv-1")).toBeNull();
    expect(screen.queryByTestId("quote-row-reopen-q-conv-1")).toBeNull();
  });

  it("declined view: Reopen button renders on declined row, Decline does NOT", async () => {
    apiGet.mockResolvedValue(DECLINED_ROWS);
    await renderList({ initialEntries: ["/quotes?view=declined"] });
    await screen.findByTestId("quote-row-q-decl-1");
    expect(screen.getByTestId("quote-row-reopen-q-decl-1")).toBeTruthy();
    expect(screen.queryByTestId("quote-row-decline-q-decl-1")).toBeNull();
  });

  it("role-gated — technician sees neither Decline nor Reopen", async () => {
    userMock = { role: "technician", id: "u-tech" };
    apiGet.mockResolvedValue(SAMPLE_ROWS);
    await renderList();
    await screen.findByTestId("quote-row-q-draft-1");
    expect(screen.queryByTestId("quote-row-decline-q-draft-1")).toBeNull();
    expect(screen.queryByTestId("quote-row-reopen-q-draft-1")).toBeNull();
  });

  // ZZ-A Wave 3-E · obsolete per QUOTES-OPEN-TAB-DECLINE-EXTEND
  // (Feb-2026) — the ``window.confirm`` prompt was removed from
  // the list-row Decline affordance per the DOC-LOCK-POLICY-RELAX
  // "always editable" philosophy (see QuotesList.jsx:240-247
  // "silent decline" rationale: Decline is reversible via Reopen,
  // so a confirm modal is friction for no benefit). The list-row
  // Decline button still exists + still POSTs; it just skips the
  // confirm step. The sibling case "open view: Decline button
  // renders on an open row…" (line ~282) continues to lock the
  // button presence + testid. .skip the confirm-first assertion
  // + the "no POST when dismissed" assertion since both theses
  // are literally impossible to satisfy under silent-decline.
  it.skip("Decline on open row calls confirm() first, then POSTs decline", async () => {
    apiGet.mockResolvedValue(SAMPLE_ROWS);
    apiPost.mockResolvedValue({});
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    await renderList();
    await screen.findByTestId("quote-row-decline-q-draft-1");
    await act(async () => {
      fireEvent.click(screen.getByTestId("quote-row-decline-q-draft-1"));
    });
    expect(confirmSpy).toHaveBeenCalled();
    await waitFor(() => {
      expect(
        apiPost.mock.calls.some(
          ([url]) => url === "/quotes/q-draft-1/decline",
        ),
      ).toBe(true);
    });
    confirmSpy.mockRestore();
  });

  // ZZ-A Wave 3-E · obsolete per QUOTES-OPEN-TAB-DECLINE-EXTEND
  // (Feb-2026) — silent decline shipped; the confirm-dismissal
  // branch is unreachable (see sibling .skip above).
  it.skip("Decline is a no-op (no POST) when confirm() is dismissed", async () => {
    apiGet.mockResolvedValue(SAMPLE_ROWS);
    apiPost.mockResolvedValue({});
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    await renderList();
    await screen.findByTestId("quote-row-decline-q-draft-1");
    await act(async () => {
      fireEvent.click(screen.getByTestId("quote-row-decline-q-draft-1"));
    });
    expect(confirmSpy).toHaveBeenCalled();
    expect(
      apiPost.mock.calls.some(([url]) => /decline$/.test(url)),
    ).toBe(false);
    confirmSpy.mockRestore();
  });
});
