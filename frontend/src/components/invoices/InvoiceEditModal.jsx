/**
 * Invoice Edit Modal · Feb-2026 — admin-only PATCH form for invoices.
 *
 * Covers all editable fields, live subtotal preview (visual only —
 * backend recomputes), status-gated warnings (sent / paid / void),
 * money-change warning about Stripe payment-link regeneration.
 */
import React, { useMemo, useState } from "react";
import { X, Plus, Trash2, AlertTriangle } from "lucide-react";
import { colors, money } from "@/theme";
import { Button, TextInput } from "@/components/ui-kit";
import { api } from "@/api";
import CategoryPicker from "@/components/income/CategoryPicker";

const MONEY_FIELDS = new Set([
  "line_items", "discount_amount", "discount_type", "tax_rate", "currency",
]);

/** Deep-ish equality good enough for line item comparison — every
 *  row is a shallow object of primitives. */
function itemsEqual(a, b) {
  if (!Array.isArray(a) || !Array.isArray(b)) return a === b;
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i += 1) {
    const x = a[i] || {}, y = b[i] || {};
    if ((x.description || "") !== (y.description || "")) return false;
    if (Number(x.quantity || 0) !== Number(y.quantity || 0)) return false;
    if (Number(x.unit_price || 0) !== Number(y.unit_price || 0)) return false;
    if (Number(x.tax_rate || 0) !== Number(y.tax_rate || 0)) return false;
  }
  return true;
}

/** Return the list of money-affecting fields the user actually changed. */
function moneyFieldsChanged(before, form) {
  const changed = new Set();
  if (!itemsEqual(before.line_items || [], form.line_items || [])) {
    changed.add("line_items");
  }
  if (Number(before.discount_amount || 0) !== Number(form.discount_amount || 0)) {
    changed.add("discount_amount");
  }
  if ((before.discount_type || "fixed") !== (form.discount_type || "fixed")) {
    changed.add("discount_type");
  }
  if (Number(before.tax_rate || 0) !== Number(form.tax_rate || 0)) {
    changed.add("tax_rate");
  }
  if ((before.currency || "USD") !== (form.currency || "USD")) {
    changed.add("currency");
  }
  return [...changed].filter((f) => MONEY_FIELDS.has(f));
}

const EMPTY_ITEM = () => ({
  description: "", quantity: 1, unit_price: 0, tax_rate: 0, category: "",
  pricebook_writeback: false,
});

export default function InvoiceEditModal({ invoice, onClose, onSaved }) {
  const status = String(invoice?.status || "draft").toLowerCase();
  const terminal = status === "void" || status === "cancelled";
  const sent = status === "sent";
  const paid = status === "paid";

  const [form, setForm] = useState(() => ({
    customer_id: invoice?.customer_id || "",
    line_items: (invoice?.line_items || []).map((li) => ({
      description: li.description || "",
      quantity: Number(li.quantity || 0),
      unit_price: Number(li.unit_price || 0),
      tax_rate: Number(li.tax_rate || 0),
      category: li.category || "",  // Feb-2026 · income category enforcement
      item_id: li.item_id || li.pricebook_item_id || null,
      pricebook_item_id: li.pricebook_item_id || null,
      pricebook_writeback: false,
    })),
    discount_amount: Number(invoice?.discount_amount || 0),
    discount_type: invoice?.discount_type || "fixed",
    promo_code: invoice?.promo_code || "",
    tax_rate: Number(invoice?.tax_rate || 0),
    due_date: invoice?.due_date || "",
    notes: invoice?.notes || "",
    memo: invoice?.memo || "",
    private_notes: invoice?.private_notes || "",
    terms: invoice?.terms || "",
    currency: invoice?.currency || "USD",
    invoice_number: invoice?.invoice_number || "",
    reason: "",
  }));

  const [confirmSent, setConfirmSent] = useState(false);
  const [paidNumberInput, setPaidNumberInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // Feb-2026 · Invoice inline edit sprint — per-row error state so
  // backend category errors surface inline on the offending row.
  const [rowErrors, setRowErrors] = useState({});

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  // ── Live totals (visual preview only) ────────────────────────
  const totals = useMemo(() => {
    const subtotal = (form.line_items || []).reduce(
      (s, li) => s + (Number(li.quantity) || 0) * (Number(li.unit_price) || 0), 0,
    );
    const disc = form.discount_type === "percent"
      ? subtotal * (Number(form.discount_amount) || 0) / 100
      : Number(form.discount_amount) || 0;
    const discounted = Math.max(subtotal - disc, 0);
    const tax = discounted * (Number(form.tax_rate) || 0) / 100;
    return {
      subtotal: subtotal.toFixed(2),
      discount: disc.toFixed(2),
      tax: tax.toFixed(2),
      total: (discounted + tax).toFixed(2),
    };
  }, [form.line_items, form.discount_amount, form.discount_type, form.tax_rate]);

  const moneyChangedList = useMemo(
    () => moneyFieldsChanged(invoice || {}, form),
    [invoice, form],
  );
  // Feb-2026 · Option A revert — the invoice pay-link is a Stripe
  // Checkout Session (not Lumino), so the "regenerate link" warning
  // now reflects Stripe. Kept behind the same money-change guard.
  const showPayLinkWarning =
    moneyChangedList.length > 0 && Boolean(invoice?.payment_url);

  // ── Line item editor helpers ─────────────────────────────────
  const patchItem = (idx, patch) => setForm((f) => ({
    ...f,
    line_items: f.line_items.map((li, i) => i === idx ? { ...li, ...patch } : li),
  }));
  const removeItem = (idx) => setForm((f) => ({
    ...f, line_items: f.line_items.filter((_, i) => i !== idx),
  }));
  const addItem = () => setForm((f) => ({
    ...f, line_items: [...(f.line_items || []), EMPTY_ITEM()],
  }));

  // ── Gate whether Save is allowed ─────────────────────────────
  const paidNumberOk = !paid || paidNumberInput === (invoice?.invoice_number || "");
  const sentOk = !sent || confirmSent;
  // Feb-2026 · Invoice inline edit sprint — save button stays
  // enabled even when a line lacks a category; the operator fixes
  // the row inline after the server error surfaces the issue.
  const canSave = !terminal && sentOk && paidNumberOk && !busy;

  const submit = async () => {
    if (!canSave) return;
    setBusy(true);
    setError("");
    setRowErrors({});
    try {
      const payload = { ...form };
      // Coerce numeric strings back to numbers for the backend.
      payload.tax_rate = Number(payload.tax_rate) || 0;
      payload.discount_amount = Number(payload.discount_amount) || 0;
      payload.line_items = (payload.line_items || []).map((li) => ({
        description: (li.description || "").trim(),
        quantity: Number(li.quantity) || 0,
        unit_price: Number(li.unit_price) || 0,
        tax_rate: Number(li.tax_rate) || 0,
        category: li.category || "",
        // Feb-2026 · Invoice inline edit sprint — carry the FK +
        // writeback flag through to the backend so the writeback
        // helper can either update or create the pricebook row.
        item_id: li.item_id || undefined,
        pricebook_item_id: li.pricebook_item_id || undefined,
        pricebook_writeback: !!li.pricebook_writeback,
      }));
      if (sent) payload.confirm_edit_sent = true;
      if (paid) payload.confirm_edit_paid_invoice_number = paidNumberInput;
      const res = await api.patch(`/quotes/${invoice.id}`, payload);
      onSaved?.(res);
    } catch (e) {
      // Feb-2026 · Invoice inline edit sprint — parse structured
      // category error and surface INLINE on the offending row.
      const detail = e?.data?.detail || {};
      const code = detail?.error_code || detail?.error;
      const idx = typeof detail?.line_index === "number" ? detail.line_index : null;
      if (idx !== null && (code === "archived_category"
                            || code === "category_invalid"
                            || code === "category_required")) {
        setRowErrors({
          [idx]: {
            reason: code === "category_required" ? "category_required" : "archived_category",
            attempted: detail?.attempted_category || form.line_items[idx]?.category,
          },
        });
        setError(code === "category_required"
          ? "Category is required on every line. Fix the highlighted row."
          : `Category '${detail?.attempted_category || ""}' is archived. Choose an active category on the highlighted row.`);
      } else {
        const legacyCode = e?.data?.detail?.error || e?.data?.error;
        const msg = legacyCode === "invoice_number_conflict"
          ? "That invoice number is already in use. Pick a different one."
          : legacyCode === "requires_confirmation"
          ? "This invoice was sent — please tick the acknowledgement above."
          : e?.message || "Save failed. Please try again.";
        setError(msg);
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: "rgba(0,0,0,0.55)" }}
      onClick={onClose}
      data-testid="invoice-edit-modal-backdrop"
    >
      <div
        className="w-full max-w-3xl rounded-2xl overflow-hidden shadow-2xl"
        style={{ backgroundColor: colors.surface }}
        onClick={(e) => e.stopPropagation()}
        data-testid="invoice-edit-modal"
      >
        <header
          className="px-5 py-3 flex items-center justify-between"
          style={{ borderBottom: `1px solid ${colors.border}` }}
        >
          <div className="text-base font-bold" style={{ color: colors.onSurface }}>
            Edit invoice · {invoice?.invoice_number || invoice?.id}
          </div>
          <button
            onClick={onClose}
            className="text-xl leading-none px-1"
            style={{ color: colors.muted }}
            data-testid="invoice-edit-close"
          ><X size={18} /></button>
        </header>

        <div className="px-5 py-4 max-h-[75vh] overflow-y-auto space-y-4">
          {/* Status-gated warning banners */}
          {terminal ? (
            <div
              className="rounded-xl p-3 text-sm flex items-start gap-2"
              style={{ background: "#FEE2E2", color: "#7F1D1D",
                        border: "1px solid #FCA5A5" }}
              data-testid="invoice-edit-banner-terminal"
            >
              <AlertTriangle size={16} />
              This invoice is {status} and cannot be edited.
            </div>
          ) : null}
          {sent && !terminal ? (
            <div
              className="rounded-xl p-3 text-sm"
              style={{ background: "#FEF3C7", color: "#78350F",
                        border: "1px solid #FCD34D" }}
              data-testid="invoice-edit-banner-sent"
            >
              <div className="flex items-start gap-2 mb-2">
                <AlertTriangle size={16} />
                <span>
                  This invoice has been sent to the customer. Editing may
                  cause confusion if they've already reviewed it. Continue?
                </span>
              </div>
              <label className="flex items-center gap-2 mt-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={confirmSent}
                  onChange={(e) => setConfirmSent(e.target.checked)}
                  data-testid="invoice-edit-confirm-sent"
                />
                <span className="text-sm font-semibold">
                  I understand and want to continue.
                </span>
              </label>
            </div>
          ) : null}
          {paid && !terminal ? (
            <div
              className="rounded-xl p-3 text-sm"
              style={{ background: "#FEE2E2", color: "#7F1D1D",
                        border: "1px solid #FCA5A5" }}
              data-testid="invoice-edit-banner-paid"
            >
              <div className="flex items-start gap-2 mb-2">
                <AlertTriangle size={16} />
                <span>
                  This invoice has been PAID. Editing it can break your
                  accounting audit trail. Only proceed if you know what
                  you're doing.
                </span>
              </div>
              <div className="mt-2">
                <label
                  className="text-xs uppercase tracking-wide font-semibold block mb-1"
                  style={{ color: "#7F1D1D" }}
                >
                  Type the invoice number to confirm:
                  <span className="font-mono ml-1">{invoice?.invoice_number}</span>
                </label>
                <input
                  type="text"
                  className="w-full px-3 py-2 rounded-lg outline-none text-sm"
                  style={{ background: "#fff", border: "1px solid #FCA5A5",
                            color: colors.onSurface }}
                  value={paidNumberInput}
                  onChange={(e) => setPaidNumberInput(e.target.value)}
                  data-testid="invoice-edit-paid-number-input"
                  placeholder={invoice?.invoice_number || ""}
                />
              </div>
            </div>
          ) : null}

          {showPayLinkWarning ? (
            <div
              className="rounded-xl p-3 text-xs"
              style={{ background: "#DBEAFE", color: "#1E3A8A",
                        border: "1px solid #93C5FD" }}
              data-testid="invoice-edit-paylink-warning"
            >
              Note: this change will invalidate the current Stripe payment
              link and generate a new one. The old link URL will stop working.
            </div>
          ) : null}

          {/* Customer + Invoice number */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <TextInput
              label="Customer ID"
              value={form.customer_id}
              onChange={(e) => set("customer_id", e.target.value)}
              testid="invoice-edit-customer-id"
            />
            <TextInput
              label="Invoice Number"
              value={form.invoice_number}
              onChange={(e) => set("invoice_number", e.target.value)}
              testid="invoice-edit-invoice-number"
            />
          </div>

          {/* Line items table */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <div
                className="text-xs uppercase font-semibold"
                style={{ color: colors.muted }}
              >Line items</div>
              <button
                onClick={addItem}
                type="button"
                className="text-xs font-semibold flex items-center gap-1"
                style={{ color: colors.brand }}
                data-testid="invoice-edit-add-line"
              >
                <Plus size={12} /> Add line
              </button>
            </div>
            <div className="rounded-xl overflow-hidden"
                  style={{ border: `1px solid ${colors.border}` }}>
              <table className="w-full text-sm">
                <thead style={{ background: colors.surfaceSecondary }}>
                  <tr>
                    <th className="text-left px-2 py-1 font-semibold">Description</th>
                    <th className="w-32 text-left px-2 py-1 font-semibold">Category *</th>
                    <th className="w-20 text-right px-2 py-1 font-semibold">Qty</th>
                    <th className="w-28 text-right px-2 py-1 font-semibold">Unit price</th>
                    <th className="w-24 text-right px-2 py-1 font-semibold">Line total</th>
                    <th className="w-8 px-2 py-1" />
                  </tr>
                </thead>
                <tbody data-testid="invoice-edit-line-items">
                  {(form.line_items || []).map((li, i) => {
                    const rowErr = rowErrors[i];
                    return (
                    <tr key={i} data-testid={`invoice-edit-line-${i}`}
                        style={{ borderTop: `1px solid ${colors.border}`,
                                  background: rowErr ? "#FEF2F2" : undefined }}>
                      <td className="px-2 py-1">
                        <input
                          className="w-full px-2 py-1 text-sm rounded"
                          style={{ background: colors.surface,
                                    border: `1px solid ${colors.border}` }}
                          value={li.description}
                          onChange={(e) => patchItem(i, { description: e.target.value })}
                          data-testid={`invoice-edit-line-${i}-desc`}
                        />
                        <label
                          className="inline-flex items-center gap-1.5 mt-1 text-[11px] cursor-pointer select-none"
                          style={{ color: colors.onSurfaceSecondary }}
                          data-testid={`invoice-edit-line-${i}-writeback-label`}
                        >
                          <input
                            type="checkbox"
                            checked={!!li.pricebook_writeback}
                            onChange={(e) => patchItem(i, { pricebook_writeback: e.target.checked })}
                            data-testid={`invoice-edit-line-${i}-writeback`}
                          />
                          <span>
                            {li.item_id || li.pricebook_item_id
                              ? "Also save to pricebook"
                              : "Also add to pricebook"}
                          </span>
                        </label>
                        {rowErr ? (
                          <div className="text-[11px] font-semibold mt-1"
                                style={{ color: "#7F1D1D" }}
                                data-testid={`invoice-edit-line-${i}-row-error`}>
                            {rowErr.reason === "category_required"
                              ? "Category required on this line."
                              : `Category '${rowErr.attempted || ""}' is archived — pick an active one.`}
                          </div>
                        ) : null}
                      </td>
                      <td className="px-2 py-1">
                        <CategoryPicker
                          value={li.category}
                          onChange={(v) => {
                            patchItem(i, { category: v });
                            setRowErrors((prev) => {
                              if (!prev[i]) return prev;
                              const next = { ...prev };
                              delete next[i];
                              return next;
                            });
                          }}
                          required
                          testid={`invoice-edit-line-${i}-cat`}
                          placeholder="Choose…"
                          invalidReason={rowErr?.reason || null}
                          autoFocus={!!rowErr}
                        />
                      </td>
                      <td className="px-2 py-1 text-right">
                        <input
                          type="number" step="0.01"
                          className="w-full px-2 py-1 text-sm rounded text-right"
                          style={{ background: colors.surface,
                                    border: `1px solid ${colors.border}` }}
                          value={li.quantity}
                          onChange={(e) => patchItem(i, { quantity: e.target.value })}
                          data-testid={`invoice-edit-line-${i}-qty`}
                        />
                      </td>
                      <td className="px-2 py-1 text-right">
                        <input
                          type="number" step="0.01"
                          className="w-full px-2 py-1 text-sm rounded text-right"
                          style={{ background: colors.surface,
                                    border: `1px solid ${colors.border}` }}
                          value={li.unit_price}
                          onChange={(e) => patchItem(i, { unit_price: e.target.value })}
                          data-testid={`invoice-edit-line-${i}-price`}
                        />
                      </td>
                      <td className="px-2 py-1 text-right font-semibold"
                          data-testid={`invoice-edit-line-${i}-subtotal`}>
                        {money((Number(li.quantity) || 0) * (Number(li.unit_price) || 0))}
                      </td>
                      <td className="px-2 py-1 text-right">
                        <button
                          type="button"
                          onClick={() => removeItem(i)}
                          data-testid={`invoice-edit-line-${i}-remove`}
                          style={{ color: colors.error }}
                        ><Trash2 size={14} /></button>
                      </td>
                    </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {/* Discount / promo / tax / currency */}
          <div className="grid grid-cols-1 sm:grid-cols-4 gap-3">
            <div>
              <label className="text-xs uppercase font-semibold block mb-1"
                     style={{ color: colors.muted }}>Discount</label>
              <input
                type="number" step="0.01"
                className="w-full px-3 py-2 text-sm rounded-lg"
                style={{ background: colors.surface,
                          border: `1px solid ${colors.border}` }}
                value={form.discount_amount}
                onChange={(e) => set("discount_amount", e.target.value)}
                data-testid="invoice-edit-discount-amount"
              />
            </div>
            <div>
              <label className="text-xs uppercase font-semibold block mb-1"
                     style={{ color: colors.muted }}>Discount type</label>
              <select
                className="w-full px-3 py-2 text-sm rounded-lg"
                style={{ background: colors.surface,
                          border: `1px solid ${colors.border}` }}
                value={form.discount_type}
                onChange={(e) => set("discount_type", e.target.value)}
                data-testid="invoice-edit-discount-type"
              >
                <option value="fixed">Fixed ($)</option>
                <option value="percent">Percent (%)</option>
              </select>
            </div>
            <TextInput
              label="Promo code"
              value={form.promo_code}
              onChange={(e) => set("promo_code", e.target.value)}
              testid="invoice-edit-promo-code"
            />
            <TextInput
              label="Currency"
              value={form.currency}
              onChange={(e) => set("currency", e.target.value.toUpperCase())}
              testid="invoice-edit-currency"
            />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="text-xs uppercase font-semibold block mb-1"
                     style={{ color: colors.muted }}>Tax rate (%)</label>
              <input
                type="number" step="0.01"
                className="w-full px-3 py-2 text-sm rounded-lg"
                style={{ background: colors.surface,
                          border: `1px solid ${colors.border}` }}
                value={form.tax_rate}
                onChange={(e) => set("tax_rate", e.target.value)}
                data-testid="invoice-edit-tax-rate"
              />
            </div>
            <TextInput
              label="Due date"
              type="date"
              value={form.due_date || ""}
              onChange={(e) => set("due_date", e.target.value)}
              testid="invoice-edit-due-date"
            />
          </div>

          <div>
            <label className="text-xs uppercase font-semibold block mb-1"
                    style={{ color: colors.muted }}>Notes (customer-visible)</label>
            <textarea
              className="w-full px-3 py-2 text-sm rounded-lg"
              style={{ background: colors.surface,
                        border: `1px solid ${colors.border}` }}
              value={form.notes}
              onChange={(e) => set("notes", e.target.value)}
              rows={2}
              data-testid="invoice-edit-notes"
            />
          </div>
          <div>
            <label className="text-xs uppercase font-semibold block mb-1"
                    style={{ color: colors.muted }}>Memo</label>
            <textarea
              className="w-full px-3 py-2 text-sm rounded-lg"
              style={{ background: colors.surface,
                        border: `1px solid ${colors.border}` }}
              value={form.memo}
              onChange={(e) => set("memo", e.target.value)}
              rows={2}
              data-testid="invoice-edit-memo"
            />
          </div>
          <div>
            <label className="text-xs uppercase font-semibold block mb-1"
                    style={{ color: colors.muted }}>Private notes (internal)</label>
            <textarea
              className="w-full px-3 py-2 text-sm rounded-lg"
              style={{ background: colors.surface,
                        border: `1px solid ${colors.border}` }}
              value={form.private_notes}
              onChange={(e) => set("private_notes", e.target.value)}
              rows={2}
              data-testid="invoice-edit-private-notes"
            />
          </div>
          <div>
            <label className="text-xs uppercase font-semibold block mb-1"
                    style={{ color: colors.muted }}>Terms</label>
            <textarea
              className="w-full px-3 py-2 text-sm rounded-lg"
              style={{ background: colors.surface,
                        border: `1px solid ${colors.border}` }}
              value={form.terms}
              onChange={(e) => set("terms", e.target.value)}
              rows={2}
              data-testid="invoice-edit-terms"
            />
          </div>
          <div>
            <label className="text-xs uppercase font-semibold block mb-1"
                    style={{ color: colors.muted }}>
              Reason for edit (for audit log)
            </label>
            <input
              className="w-full px-3 py-2 text-sm rounded-lg"
              style={{ background: colors.surface,
                        border: `1px solid ${colors.border}` }}
              value={form.reason}
              onChange={(e) => set("reason", e.target.value)}
              data-testid="invoice-edit-reason"
              placeholder="e.g., Customer requested additional service"
            />
          </div>

          {/* Live totals preview */}
          <div
            className="rounded-xl p-3 text-sm"
            style={{ background: colors.surfaceSecondary,
                      border: `1px solid ${colors.border}` }}
            data-testid="invoice-edit-totals"
          >
            <div className="flex justify-between">
              <span style={{ color: colors.muted }}>Subtotal</span>
              <span className="font-mono" data-testid="invoice-edit-subtotal-value">
                {money(totals.subtotal)}
              </span>
            </div>
            <div className="flex justify-between">
              <span style={{ color: colors.muted }}>Discount</span>
              <span className="font-mono" data-testid="invoice-edit-discount-value">
                −{money(totals.discount)}
              </span>
            </div>
            <div className="flex justify-between">
              <span style={{ color: colors.muted }}>Tax</span>
              <span className="font-mono" data-testid="invoice-edit-tax-value">
                {money(totals.tax)}
              </span>
            </div>
            <div
              className="flex justify-between mt-1 pt-1 font-bold"
              style={{ borderTop: `1px solid ${colors.border}` }}
            >
              <span>Total (preview)</span>
              <span className="font-mono" data-testid="invoice-edit-total-value">
                {money(totals.total)}
              </span>
            </div>
            <div className="text-xs mt-1" style={{ color: colors.muted }}>
              Server recomputes on save — this is a visual guide.
            </div>
          </div>

          {error ? (
            <div
              className="rounded-xl p-3 text-sm"
              style={{ background: "#FEE2E2", color: "#7F1D1D",
                        border: "1px solid #FCA5A5" }}
              data-testid="invoice-edit-error"
            >{error}</div>
          ) : null}
        </div>

        <footer
          className="px-5 py-3 flex justify-end gap-2"
          style={{ borderTop: `1px solid ${colors.border}`,
                    background: colors.surfaceSecondary }}
        >
          <Button variant="ghost" onClick={onClose} testid="invoice-edit-cancel">
            Cancel
          </Button>
          <Button
            onClick={submit}
            disabled={!canSave}
            testid="invoice-edit-save"
          >
            {busy ? "Saving…" : "Save changes"}
          </Button>
        </footer>
      </div>
    </div>
  );
}
