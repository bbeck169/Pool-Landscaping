/**
 * Phase R1.b · Feb-2026 — UnpaidInvoiceReminderButton flow:
 * confirm modal → POST /quotes/{id}/send-reminder → success
 * toast + onSent callback. Failure path surfaces toast.error and
 * leaves the row un-patched.
 */
import React from "react";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("@/api", () => ({ api: { post: vi.fn() } }));
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));
let confirmResult = true;
vi.mock("@/components/ui/confirm-dialog", () => ({
  useConfirm: () => async () => confirmResult,
}));

import { api } from "@/api";
import { toast } from "sonner";
import { UnpaidInvoiceReminderButton } from "@/components/reports/UnpaidInvoiceReminderButton";

const inv = {
  id: "inv-1", invoice_number: "1001",
  customer_id: "c1", customer_name: "Alice",
  total: 500, amount_paid: 0,
};

describe("UnpaidInvoiceReminderButton (R1.b)", () => {
  beforeEach(() => {
    api.post.mockReset();
    toast.success.mockReset();
    toast.error.mockReset();
    confirmResult = true;
  });

  it("confirms → posts → success toast + onSent invoked", async () => {
    api.post.mockResolvedValue({ ok: true, email_sent: true, reminder_count: 1 });
    const onSent = vi.fn();
    render(<UnpaidInvoiceReminderButton invoice={inv} onSent={onSent} />);
    const btn = screen.getByTestId(`send-reminder-${inv.id}`);
    fireEvent.click(btn);
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(`/quotes/${inv.id}/send-reminder`)
    );
    await waitFor(() => expect(toast.success).toHaveBeenCalled());
    expect(onSent).toHaveBeenCalledWith(
      expect.objectContaining({ id: "inv-1", reminder_count: 1, email_sent: true }),
    );
  });

  it("cancel path: no POST, no toast", async () => {
    confirmResult = false;
    render(<UnpaidInvoiceReminderButton invoice={inv} onSent={vi.fn()} />);
    fireEvent.click(screen.getByTestId(`send-reminder-${inv.id}`));
    // yield the event loop so the async confirm can settle
    await new Promise((r) => setTimeout(r, 10));
    expect(api.post).not.toHaveBeenCalled();
    expect(toast.success).not.toHaveBeenCalled();
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("server error → error toast, onSent NOT invoked", async () => {
    api.post.mockRejectedValue(new Error("boom"));
    const onSent = vi.fn();
    render(<UnpaidInvoiceReminderButton invoice={inv} onSent={onSent} />);
    fireEvent.click(screen.getByTestId(`send-reminder-${inv.id}`));
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(onSent).not.toHaveBeenCalled();
  });
});
