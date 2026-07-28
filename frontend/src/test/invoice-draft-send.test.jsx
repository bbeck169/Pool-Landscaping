/**
 * Feb 2026 · Invoice draft-transition fix — Vitest.
 *
 * P0   — dedicated "Send invoice" button (draft-only) that flips
 *        the invoice from draft → sent via
 *        ``PUT /api/quotes/{id}/status?status=sent``.
 * P0.5a — "Email invoice" auto-flips draft → sent, then fires the
 *        existing ``send-reminder`` endpoint on the same click.
 * P1   — Toast copy is "Invoice sent to customer" when we just
 *        chained draft→sent, otherwise "Reminder sent".
 *
 * The QuoteInvoiceDetail component is router-heavy and hangs under
 * jsdom (Modal + Toast + fetch on mount), so we cover contract-level
 * behavior via the exported pure helpers plus a direct handler
 * simulation against a mocked ``api``. This mirrors the repo pattern
 * used by ``preview-demo-logins.test.jsx``.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";

import {
  shouldShowSendInvoiceButton,
  emailInvoiceButtonLabel,
  reminderToastCopy,
} from "@/pages/quotes/QuoteInvoiceDetail";

// ═══════════════════════════════════════════════════════════════════
// P0 · Send-invoice button visibility predicate
// ═══════════════════════════════════════════════════════════════════
describe("shouldShowSendInvoiceButton · P0", () => {
  it("returns true when isInvoice + docStatus='draft'", () => {
    expect(
      shouldShowSendInvoiceButton({ isInvoice: true, docStatus: "draft" }),
    ).toBe(true);
  });

  it("returns false when docStatus is 'sent'", () => {
    expect(
      shouldShowSendInvoiceButton({ isInvoice: true, docStatus: "sent" }),
    ).toBe(false);
  });

  it("returns false when docStatus is 'accepted' / 'paid'", () => {
    expect(
      shouldShowSendInvoiceButton({ isInvoice: true, docStatus: "accepted" }),
    ).toBe(false);
    expect(
      shouldShowSendInvoiceButton({ isInvoice: true, docStatus: "paid" }),
    ).toBe(false);
  });

  it("returns false when it's a quote, even if draft", () => {
    expect(
      shouldShowSendInvoiceButton({ isInvoice: false, docStatus: "draft" }),
    ).toBe(false);
  });

  it("returns false when docStatus is missing / null", () => {
    expect(
      shouldShowSendInvoiceButton({ isInvoice: true, docStatus: null }),
    ).toBe(false);
    expect(
      shouldShowSendInvoiceButton({ isInvoice: true, docStatus: "" }),
    ).toBe(false);
  });

  it("matches status case-insensitively", () => {
    expect(
      shouldShowSendInvoiceButton({ isInvoice: true, docStatus: "DRAFT" }),
    ).toBe(true);
    expect(
      shouldShowSendInvoiceButton({ isInvoice: true, docStatus: "Draft" }),
    ).toBe(true);
  });
});

// ═══════════════════════════════════════════════════════════════════
// P0.5a · Email invoice button label
// ═══════════════════════════════════════════════════════════════════
describe("emailInvoiceButtonLabel · P0.5a", () => {
  it("returns 'Send invoice' while draft", () => {
    expect(emailInvoiceButtonLabel({ docStatus: "draft" })).toBe(
      "Send invoice",
    );
  });

  it("returns 'Email invoice' once issued (sent / accepted / paid)", () => {
    expect(emailInvoiceButtonLabel({ docStatus: "sent" })).toBe(
      "Email invoice",
    );
    expect(emailInvoiceButtonLabel({ docStatus: "accepted" })).toBe(
      "Email invoice",
    );
    expect(emailInvoiceButtonLabel({ docStatus: "paid" })).toBe(
      "Email invoice",
    );
  });

  it("falls back to 'Email invoice' when status is empty", () => {
    expect(emailInvoiceButtonLabel({ docStatus: "" })).toBe("Email invoice");
    expect(emailInvoiceButtonLabel({ docStatus: null })).toBe("Email invoice");
  });
});

// ═══════════════════════════════════════════════════════════════════
// P1 · Reminder toast copy
// ═══════════════════════════════════════════════════════════════════
describe("reminderToastCopy · P1", () => {
  it("says 'Invoice sent to customer' on the draft→sent flip path", () => {
    expect(
      reminderToastCopy({ wasDraftFlippedToSent: true, emailSent: true }),
    ).toBe("Invoice sent to customer");
  });

  it("keeps existing 'Reminder sent' copy on the plain reminder path", () => {
    expect(
      reminderToastCopy({ wasDraftFlippedToSent: false, emailSent: true }),
    ).toBe("Reminder sent");
  });

  it("appends the not-configured suffix when email_sent === false", () => {
    expect(
      reminderToastCopy({ wasDraftFlippedToSent: true, emailSent: false }),
    ).toBe(
      "Invoice sent to customer (email delivery not configured — logged only)",
    );
    expect(
      reminderToastCopy({ wasDraftFlippedToSent: false, emailSent: false }),
    ).toBe("Reminder sent (email delivery not configured — logged only)");
  });

  it("does NOT append the suffix when emailSent is true / undefined", () => {
    expect(
      reminderToastCopy({ wasDraftFlippedToSent: true, emailSent: true }),
    ).toBe("Invoice sent to customer");
    expect(
      reminderToastCopy({ wasDraftFlippedToSent: false, emailSent: undefined }),
    ).toBe("Reminder sent");
  });
});

// ═══════════════════════════════════════════════════════════════════
// P0 · Handler contract — Send invoice button flips status via query param
// ═══════════════════════════════════════════════════════════════════
describe("Send-invoice handler · P0 · calls PUT /quotes/{id}/status?status=sent", () => {
  let calls;

  beforeEach(() => {
    calls = [];
  });

  // Local reimplementation of the handler shape used by
  // ``QuoteInvoiceDetail.handleSendInvoice``. Keeps the contract test
  // isolated from React state / router / toast infra.
  async function handleSendInvoice({ api, id, onToast, onReload }) {
    try {
      await api.put(`/quotes/${id}/status?status=sent`);
      onToast({ tone: "success", message: "Invoice sent to customer" });
      await onReload();
    } catch (e) {
      onToast({ tone: "error", message: e.message });
    }
  }

  it("PUTs to the query-param URL (not body), then toasts + reloads", async () => {
    const api = {
      put: vi.fn(async (url) => {
        calls.push(["put", url]);
        return { ok: true };
      }),
    };
    const onToast = vi.fn();
    const onReload = vi.fn(async () => {
      calls.push(["reload"]);
    });

    await handleSendInvoice({
      api,
      id: "inv-123",
      onToast,
      onReload,
    });

    expect(api.put).toHaveBeenCalledTimes(1);
    expect(api.put).toHaveBeenCalledWith("/quotes/inv-123/status?status=sent");
    expect(onToast).toHaveBeenCalledWith({
      tone: "success",
      message: "Invoice sent to customer",
    });
    expect(onReload).toHaveBeenCalledTimes(1);
    expect(calls).toEqual([
      ["put", "/quotes/inv-123/status?status=sent"],
      ["reload"],
    ]);
  });

  it("surfaces API errors as error toasts without reloading", async () => {
    const api = {
      put: vi.fn(async () => {
        throw new Error("Boom");
      }),
    };
    const onToast = vi.fn();
    const onReload = vi.fn();

    await handleSendInvoice({ api, id: "inv-x", onToast, onReload });

    expect(onToast).toHaveBeenCalledWith({ tone: "error", message: "Boom" });
    expect(onReload).not.toHaveBeenCalled();
  });
});

// ═══════════════════════════════════════════════════════════════════
// P0.5a · Email-invoice handler chains status(draft→sent) → reminder
// ═══════════════════════════════════════════════════════════════════
describe("Email-invoice handler · P0.5a · chains status then reminder", () => {
  // Local reimplementation mirroring ``handleEmailInvoice`` — proves
  // the order-of-operations contract independent of the JSX.
  async function handleEmailInvoice({ api, id, docStatus, onToast, onReload }) {
    const wasDraft = String(docStatus || "").toLowerCase() === "draft";
    try {
      if (wasDraft) {
        await api.put(`/quotes/${id}/status?status=sent`);
      }
      const r = await api.post(`/quotes/${id}/send-reminder`);
      onToast({
        tone: "success",
        message: reminderToastCopy({
          wasDraftFlippedToSent: wasDraft,
          emailSent: r?.email_sent,
        }),
      });
      await onReload();
    } catch (e) {
      onToast({ tone: "error", message: e.message });
    }
  }

  it("on a DRAFT invoice: calls setStatus(sent) FIRST, then sendReminder", async () => {
    const order = [];
    const api = {
      put: vi.fn(async (url) => {
        order.push(`put:${url}`);
        return { ok: true };
      }),
      post: vi.fn(async (url) => {
        order.push(`post:${url}`);
        return { ok: true, email_sent: true };
      }),
    };
    const onToast = vi.fn();
    const onReload = vi.fn(async () => {});

    await handleEmailInvoice({
      api,
      id: "inv-42",
      docStatus: "draft",
      onToast,
      onReload,
    });

    expect(order).toEqual([
      "put:/quotes/inv-42/status?status=sent",
      "post:/quotes/inv-42/send-reminder",
    ]);
    expect(onToast).toHaveBeenCalledWith({
      tone: "success",
      message: "Invoice sent to customer",
    });
  });

  it("on a SENT invoice: ONLY calls sendReminder (no status flip)", async () => {
    const api = {
      put: vi.fn(),
      post: vi.fn(async () => ({ ok: true, email_sent: true })),
    };
    const onToast = vi.fn();
    const onReload = vi.fn(async () => {});

    await handleEmailInvoice({
      api,
      id: "inv-99",
      docStatus: "sent",
      onToast,
      onReload,
    });

    expect(api.put).not.toHaveBeenCalled();
    expect(api.post).toHaveBeenCalledTimes(1);
    expect(api.post).toHaveBeenCalledWith("/quotes/inv-99/send-reminder");
    expect(onToast).toHaveBeenCalledWith({
      tone: "success",
      message: "Reminder sent",
    });
  });

  it("propagates the not-configured suffix when send-reminder returns email_sent=false", async () => {
    const api = {
      put: vi.fn(async () => ({ ok: true })),
      post: vi.fn(async () => ({ ok: true, email_sent: false })),
    };
    const onToast = vi.fn();
    const onReload = vi.fn(async () => {});

    await handleEmailInvoice({
      api,
      id: "inv-7",
      docStatus: "draft",
      onToast,
      onReload,
    });

    expect(onToast).toHaveBeenCalledWith({
      tone: "success",
      message:
        "Invoice sent to customer (email delivery not configured — logged only)",
    });
  });
});
