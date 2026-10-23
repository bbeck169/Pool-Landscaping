/**
 * TD-invoice-list-bulk-send · Feb-2026
 * ============================================================
 *
 * Vitest coverage for the FE delta:
 *   * BulkSendInvoicesModal — confirm step / results step / API
 *     call / status chip rendering across all status buckets.
 *   * InvoicesList toolbar — Send Invoice button present + wires
 *     to the modal.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import fs from "node:fs";
import path from "node:path";
import {
  render, screen, cleanup, waitFor, fireEvent,
} from "@testing-library/react";


const { apiPostSpy } = vi.hoisted(() => ({ apiPostSpy: vi.fn() }));


vi.mock("@/api", () => ({
  api: { get: vi.fn(), post: (...a) => apiPostSpy(...a) },
}));


vi.mock("@/theme", () => ({
  colors: {
    surface: "#FFF", surfaceSecondary: "#F4F4F5",
    border: "#E4E4E7", divider: "#E4E4E7", muted: "#71717A",
    onSurface: "#0A0A0A", onSurfaceSecondary: "#52525B",
  },
  money: (n) => `$${Number(n || 0).toFixed(2)}`,
}));


vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));


import BulkSendInvoicesModal from
  "@/components/invoices/BulkSendInvoicesModal";


function _mount(opts = {}) {
  const defaults = {
    open: true,
    invoiceIds: ["inv-1", "inv-2"],
    onClose: vi.fn(),
    onComplete: vi.fn(),
  };
  const props = { ...defaults, ...opts };
  const utils = render(<BulkSendInvoicesModal {...props} />);
  return { ...utils, props };
}


// ═════════════════════════════════════════════════════════════
// 1. Modal — confirm step
// ═════════════════════════════════════════════════════════════
describe("BulkSendInvoicesModal · confirm step", () => {
  beforeEach(() => { apiPostSpy.mockReset(); });
  afterEach(() => cleanup());

  it("does not render when open=false", () => {
    _mount({ open: false });
    expect(screen.queryByTestId("bulk-send-modal")).toBeFalsy();
  });

  it("renders confirm copy with the selection count (singular)", () => {
    _mount({ invoiceIds: ["only-one"] });
    expect(screen.getByTestId("bulk-send-confirm-step").textContent)
      .toContain("1 selected customer");
    expect(
      screen.getByTestId("bulk-send-confirm-btn").textContent,
    ).toContain("Send to 1 customer");
  });

  it("renders confirm copy with the selection count (plural)", () => {
    _mount({ invoiceIds: ["a", "b", "c"] });
    expect(screen.getByTestId("bulk-send-confirm-step").textContent)
      .toContain("3 selected customers");
    expect(
      screen.getByTestId("bulk-send-confirm-btn").textContent,
    ).toContain("Send to 3 customers");
  });

  it("confirm button fires POST /invoices/bulk-send with the ids", async () => {
    apiPostSpy.mockResolvedValue({
      summary: {
        requested: 2, sent_both: 2,
        sent_email_only: 0, sent_sms_only: 0,
        skipped_already_paid: 0, skipped_draft: 0,
        skipped_no_contact: 0, skipped_recent_send: 0,
        skipped_not_found: 0, errored: 0,
      },
      results: [
        { invoice_id: "inv-1", status: "sent_both",
          email_to: "a@a.com", sms_to: "+15550000001" },
        { invoice_id: "inv-2", status: "sent_both",
          email_to: "b@b.com", sms_to: "+15550000002" },
      ],
      request_id: "req-abc",
    });
    _mount({ invoiceIds: ["inv-1", "inv-2"] });
    fireEvent.click(screen.getByTestId("bulk-send-confirm-btn"));
    await waitFor(() => expect(apiPostSpy).toHaveBeenCalledWith(
      "/invoices/bulk-send",
      { invoice_ids: ["inv-1", "inv-2"] },
    ));
  });
});


// ═════════════════════════════════════════════════════════════
// 2. Modal — results step
// ═════════════════════════════════════════════════════════════
describe("BulkSendInvoicesModal · results step", () => {
  beforeEach(() => { apiPostSpy.mockReset(); });
  afterEach(() => cleanup());

  async function _confirmAndWait(resp) {
    apiPostSpy.mockResolvedValue(resp);
    _mount({ invoiceIds: resp.results.map((r) => r.invoice_id) });
    fireEvent.click(screen.getByTestId("bulk-send-confirm-btn"));
    await waitFor(() => expect(
      screen.getByTestId("bulk-send-results-step")).toBeTruthy());
  }

  it("renders per-invoice status chips for all states", async () => {
    await _confirmAndWait({
      summary: {
        requested: 5, sent_both: 1, sent_email_only: 1,
        sent_sms_only: 0, skipped_already_paid: 1,
        skipped_draft: 1, skipped_no_contact: 1,
        skipped_recent_send: 0, skipped_not_found: 0, errored: 0,
      },
      results: [
        { invoice_id: "ok-both", status: "sent_both",
          email_to: "a@a.com", sms_to: "+1" },
        { invoice_id: "ok-email", status: "sent_email_only",
          email_to: "b@b.com", sms_to: null },
        { invoice_id: "paid", status: "skipped_already_paid" },
        { invoice_id: "draft", status: "skipped_draft" },
        { invoice_id: "no-contact", status: "skipped_no_contact" },
      ],
      request_id: "req-x",
    });
    expect(screen.getByTestId("bulk-send-status-sent_both"))
      .toBeTruthy();
    expect(screen.getByTestId("bulk-send-status-sent_email_only"))
      .toBeTruthy();
    expect(screen.getByTestId("bulk-send-status-skipped_already_paid"))
      .toBeTruthy();
    expect(screen.getByTestId("bulk-send-status-skipped_draft"))
      .toBeTruthy();
    expect(screen.getByTestId("bulk-send-status-skipped_no_contact"))
      .toBeTruthy();
  });

  it("summary chips render only non-zero buckets", async () => {
    await _confirmAndWait({
      summary: {
        requested: 2, sent_both: 2,
        sent_email_only: 0, sent_sms_only: 0,
        skipped_already_paid: 0, skipped_draft: 0,
        skipped_no_contact: 0, skipped_recent_send: 0,
        skipped_not_found: 0, errored: 0,
      },
      results: [
        { invoice_id: "a", status: "sent_both" },
        { invoice_id: "b", status: "sent_both" },
      ],
      request_id: "r",
    });
    const chips = screen.getByTestId("bulk-send-summary-chips");
    expect(chips.textContent).toContain("2 sent (both)");
    // Zero buckets should NOT appear.
    expect(chips.textContent).not.toContain("email only");
    expect(chips.textContent).not.toContain("not-found");
  });

  it("shows error detail in the detail column for errored rows", async () => {
    await _confirmAndWait({
      summary: {
        requested: 1, sent_both: 0, sent_email_only: 0,
        sent_sms_only: 0, skipped_already_paid: 0,
        skipped_draft: 0, skipped_no_contact: 0,
        skipped_recent_send: 0, skipped_not_found: 0, errored: 1,
      },
      results: [
        { invoice_id: "bad", status: "error",
          error: "email:no-recipient, sms:failed" },
      ],
      request_id: "r",
    });
    const row = screen.getByTestId("bulk-send-row-bad");
    expect(row.textContent).toContain("email:no-recipient");
    expect(screen.getByTestId("bulk-send-status-error"))
      .toBeTruthy();
  });

  it("Done button closes the modal (calls onClose)", async () => {
    apiPostSpy.mockResolvedValue({
      summary: {
        requested: 1, sent_both: 1, sent_email_only: 0,
        sent_sms_only: 0, skipped_already_paid: 0,
        skipped_draft: 0, skipped_no_contact: 0,
        skipped_recent_send: 0, skipped_not_found: 0, errored: 0,
      },
      results: [{ invoice_id: "x", status: "sent_both" }],
      request_id: "r",
    });
    const closeSpy = vi.fn();
    render(<BulkSendInvoicesModal
      open={true} invoiceIds={["x"]}
      onClose={closeSpy} onComplete={vi.fn()} />);
    fireEvent.click(screen.getByTestId("bulk-send-confirm-btn"));
    await waitFor(() => screen.getByTestId("bulk-send-results-step"));
    fireEvent.click(screen.getByTestId("bulk-send-done"));
    expect(closeSpy).toHaveBeenCalled();
  });
});


// ═════════════════════════════════════════════════════════════
// 3. InvoicesList toolbar — static-source wire-up
// ═════════════════════════════════════════════════════════════
describe("InvoicesList · toolbar wires bulk-send", () => {
  const SRC = fs.readFileSync(
    path.resolve(process.cwd(),
      "src/pages/invoices/InvoicesList.jsx"),
    "utf-8",
  );

  it("imports BulkSendInvoicesModal", () => {
    expect(SRC).toMatch(
      /import\s+BulkSendInvoicesModal\s+from\s+"@\/components\/invoices\/BulkSendInvoicesModal"/);
  });

  it("declares bulkSendOpen state", () => {
    expect(SRC).toMatch(
      /const\s+\[bulkSendOpen,\s*setBulkSendOpen\]\s*=\s*useState\(false\)/);
  });

  it("renders Send Invoice toolbar button with the correct testid", () => {
    expect(SRC).toMatch(/data-testid="bulk-send-button"/);
    expect(SRC).toMatch(/Send Invoice \(\{selectedCount\}\)/);
  });

  it("Send Invoice button disables when selectedCount=0", () => {
    // Mirrors the Apply Credit button's disable guard.
    const idx = SRC.indexOf('data-testid="bulk-send-button"');
    expect(idx).toBeGreaterThan(-1);
    const slice = SRC.slice(idx - 500, idx + 50);
    expect(slice).toMatch(/selectedCount\s*===\s*0/);
  });

  it("mounts <BulkSendInvoicesModal/> and wires its onClose", () => {
    expect(SRC).toMatch(/<BulkSendInvoicesModal[\s\S]{0,300}invoiceIds=\{Array\.from\(selected\)\}/);
    expect(SRC).toMatch(/setBulkSendOpen\(false\)[\s\S]{0,200}clearSelection\(\)[\s\S]{0,100}loadRows\(\)/);
  });
});
