import React from "react";
import { toast } from "sonner";
import { api } from "@/api";
import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/ui/confirm-dialog";
import { formatCurrency } from "./formatters";

/**
 * Phase R1.b · Feb-2026 — one-tap "Send reminder" button for
 * unpaid invoice rows.
 *
 * Flow:
 *   1. Click → global ``useConfirm`` modal opens with the
 *      customer + invoice + balance in the description.
 *   2. Confirm → ``POST /api/quotes/{id}/send-reminder``. Server
 *      dispatches in-app + SMS + email via the existing
 *      ``send_invoice_reminder_email`` pipeline, bumps
 *      ``reminder_count``, and writes an ``invoice_reminder_sent``
 *      audit event (see routers/quotes.py::send_reminder).
 *   3. Success → toast("Reminder sent"), ``onSent(inv)`` so the
 *      parent can bump the row's ``reminder_count`` locally
 *      without a full re-fetch.
 *   4. Failure → toast.error with the server message.
 *
 * Role gate: the server-side route requires admin; the button
 * itself is still rendered so non-admin see the same UI and get
 * a clean 401/403 toast on click. Parents that want to hide the
 * action entirely can pass ``visible={false}``.
 */
export function UnpaidInvoiceReminderButton({
  invoice,
  onSent,
  size = "sm",
  testid,
}) {
  const confirm = useConfirm();
  const [busy, setBusy] = React.useState(false);
  const tid = testid || `send-reminder-${invoice?.id}`;

  const balance = React.useMemo(() => {
    const total = Number(invoice?.total || 0);
    const paid = Number(invoice?.amount_paid || 0);
    return Math.max(0, total - paid);
  }, [invoice]);

  const label = invoice?.title || `Invoice #${invoice?.invoice_number || invoice?.id}`;
  const customer = invoice?.customer_name || "this customer";

  const onClick = async () => {
    if (!invoice?.id || busy) return;
    const ok = await confirm({
      title: `Send payment reminder to ${customer}?`,
      description: `${label} · Balance ${formatCurrency(balance)}. `
        + "The customer will receive an in-app notification, SMS "
        + "(if opted in), and an email.",
      confirmText: "Send reminder",
      cancelText: "Cancel",
    });
    if (!ok) return;
    setBusy(true);
    try {
      const r = await api.post(`/quotes/${invoice.id}/send-reminder`);
      toast.success(
        r?.email_sent
          ? "Reminder sent — email + in-app dispatched"
          : "Reminder queued — email pending",
      );
      if (onSent) onSent({ ...invoice, ...r });
    } catch (e) {
      const msg = e?.response?.data?.detail || e?.message || "Failed to send reminder";
      toast.error(msg);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Button
      variant="outline"
      size={size}
      onClick={onClick}
      disabled={!invoice?.id || busy}
      data-testid={tid}
    >
      {busy ? "Sending…" : "Send reminder"}
    </Button>
  );
}

export default UnpaidInvoiceReminderButton;
