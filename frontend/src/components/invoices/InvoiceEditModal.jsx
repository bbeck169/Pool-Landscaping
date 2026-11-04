/**
 * Invoice Edit Modal · Feb-2026 — admin-only PATCH form for invoices.
 *
 * Covers all editable fields, live subtotal preview (visual only —
 * backend recomputes), status-gated warnings (sent / paid / void),
 * money-change warning about Stripe payment-link regeneration.
 */
import React, { useMemo, useRef, useState } from "react";
import { X, Plus, Trash2, AlertTriangle } from "lucide-react";
import { colors, money } from "@/theme";
import { Button, TextInput } from "@/components/ui-kit";
import { api } from "@/api";
import { useAuth } from "@/auth";
import CategoryPicker from "@/components/income/CategoryPicker";
// Phase P16.1 · Feb-2026 — Master Service combobox drop-in on the
// per-line description field so the invoice inline edit modal
// shares the pricebook auto-fill path with the K71 quotes editor.
// The modal's ``category`` column is an INCOME category (a
// distinct taxonomy from ``service_categories``), so we skip
// category auto-fill here — only ``unit_price`` is stamped from
// the picked master service.
import MasterServiceCombobox from "@/components/services/MasterServiceCombobox";
import EditLockConfirmDialog from "@/components/documents/EditLockConfirmDialog";
import StatusReversionWarningDialog from "@/components/invoices/StatusReversionWarningDialog";

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

export default function InvoiceEditModal({ invoice, signInfo, onClose, onSaved }) {
  // TD-paid-invoice-admin-edit-unblock · Feb-2026 — admin + super_admin
  // bypass on the line-item ``quantity`` / ``unit_price`` ``readOnly``
  // gate for paid invoices.  Pre-ticket both inputs were hard-locked
  // on paid status, making the BE's existing ack / typed-proof
  // acceptance paths unreachable via this modal — admins who needed
  // a line-item price correction were forced to void-and-reissue.
  //
  // Unlock lets the admin type a new value; Save still routes
  // through the existing <EditLockConfirmDialog> which arms the
  // ``acknowledged_lock_bypass`` flag + the typed invoice-number
  // proof, so the BE gate (``routers/invoice_edit.py`` paths 1 + 2)
  // is unchanged.  Manager / owner keep the existing lock (matches
  // ``_require_staff``'s narrower role widening — those roles are
  // bounded to category-only / date-only edits server-side).
  //
  // ``useAuth()`` returns ``null`` when rendered without an
  // ``<AuthProvider>`` (test harness).  Safer default = treat as
  // non-admin so no silent unlock in an un-authed context.
  const _auth = useAuth();
  const _role = (_auth && _auth.user && _auth.user.role) || "";
  const isAdmin = _role === "admin" || _role === "super_admin";

  const status = String(invoice?.status || "draft").toLowerCase();
  const terminal = status === "void" || status === "cancelled";
  const sent = status === "sent";
  const accepted = status === "accepted";
  const paid = status === "paid";
  // Feb-2026 · Editable Sent Docs · Phase 1 — the modal now gates
  // save on a shared confirmation dialog for any locked status
  // (sent | accepted | paid). ``isStripePaid`` triggers the Stripe-
  // ledger warning; ``isSigned`` triggers the signature-invalidation
  // warning. Both stack when both conditions hold.
  const isLocked = sent || accepted || paid;
  const isStripePaid = paid && Boolean(
    invoice?.payment_intent_id
    || invoice?.charge_id
    || invoice?.stripe_payment_intent_id
    || invoice?.payment_url,
  );
  const isSigned = Boolean(
    signInfo?.signed
    || String(invoice?.signature_status || "").toLowerCase() === "signed",
  );

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
    // TD-paid-invoice-admin-edit-title-field · Feb-2026 — top-level
    // invoice display title.  Mirrors ``Quote.title`` from
    // ``backend/models.py``; renders as the invoice page header in
    // ``QuoteInvoiceDetail.jsx``.  Editable at all times (not paid-
    // gated); BE whitelists it in ``_EDITABLE_FIELDS`` +
    // ``_METADATA_ONLY_TOP_FIELDS`` so a title-only edit on a paid
    // invoice rides the β bypass with zero friction.
    title: invoice?.title || "",
    reason: "",
  }));

  // Feb-2026 · Editable Sent Docs · Phase 1 — shared confirm-dialog
  // toggle. Any Save on a locked status routes through this dialog
  // before firing the PATCH. (The legacy inline "acknowledgement
  // checkbox" flow was retired in the same phase.)
  const [confirmOpen, setConfirmOpen] = useState(false);
  // TD-paid-invoice-admin-edit-unblock · Feb-2026 — one additional
  // pre-save confirm stacked AFTER <EditLockConfirmDialog>:
  //   * <StatusReversionWarningDialog> fires when a paid invoice's
  //     recomputed total exceeds ``amount_paid`` (the BE's
  //     ``remaining_balance = max(total - amount_paid, 0)`` formula
  //     flips status from ``paid`` back to ``partial`` on save).
  //
  // NOTE · Feb-2026 operator reversal — <CategoryEditConfirmDialog>
  // was introduced in ``5ab10f247`` and reverted here ("need to
  // make sure I can edit categories descriptions titles on all
  // paid invoices with no block").  Category edits on paid
  // invoices now fire with zero friction; the retroactive revenue-
  // by-category drift remains traceable via
  // ``db.invoice_edit_history`` only (operator-accepted silent
  // drift — see TECH_DEBT reversal note).
  //
  // Each pre-save ack is tracked on a ref so ``submit()`` can
  // re-enter the pipeline after each dialog without re-prompting.
  const [reversionOpen, setReversionOpen] = useState(false);
  const _acked = useRef({
    editLock: false, statusReversion: false,
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // Feb-2026 · invoice-category hard-block removal (parent SHA
  // ec88141ea + FE SHA 222350ab9) — ``rowErrors`` state was the
  // red-row-highlight + inline red-text handler for the backend's
  // ``category_required`` / ``archived_category`` 400s on
  // ``PATCH /quotes/{id}``.  The backend now soft-passes those two
  // codes (``strict=False`` on ``validate_line_item_categories`` +
  // ``validate_line_item_k71_categories``), so the branch is dead
  // and removed.  Any non-category save error still surfaces via
  // the shared ``error`` setter in the catch below.

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  // Feb-2026 β — operator metadata-only paid bypass. Mirror of the
  // BE ``_is_metadata_only_diff`` helper at
  // ``routers/invoice_edit.py``. When ``paid`` AND the diff touches
  // only metadata fields, we skip BOTH the ack flag AND the
  // confirm dialog so admins can relabel line items without any
  // friction. ``item_id``/``pricebook_item_id`` ride in the
  // metadata set so a pricebook re-link stays no-ack.
  const _METADATA_LINE_KEYS = new Set([
    "category", "income_category_id",
    "service_category", "service_category_id",
    "description", "long_description",
    "item_id", "pricebook_item_id",
  ]);
  const _isMetadataOnlyLineDiff = (origItems, newItems) => {
    const o = origItems || []; const n = newItems || [];
    if (o.length !== n.length) return false;
    for (let i = 0; i < n.length; i++) {
      const newLi = n[i] || {}; const oldLi = o[i] || {};
      const keys = new Set([
        ...Object.keys(newLi), ...Object.keys(oldLi),
      ]);
      for (const k of keys) {
        if (k === "id" || k === "pricebook_writeback") continue;
        const av = oldLi[k]; const bv = newLi[k];
        const normalize = (x) => (
          k === "quantity" || k === "unit_price" || k === "tax_rate"
        ) ? Number(x || 0) : (x ?? "");
        if (normalize(av) !== normalize(bv)
             && !_METADATA_LINE_KEYS.has(k)) {
          return false;
        }
      }
    }
    return true;
  };
  const isPaidMetadataOnlyDiff = paid && _isMetadataOnlyLineDiff(
    invoice?.line_items || [], form.line_items,
  ) && Number(form.tax_rate || 0)
       === Number(invoice?.tax_rate || 0)
    && Number(form.discount_amount || 0)
       === Number(invoice?.discount_amount || 0);

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

  // TD-paid-invoice-admin-edit-unblock · Feb-2026 — pre-save predicate
  // for the status-reversion warning.
  //
  // ``totalExceedsPaid``: true iff ``status === "paid"``, a money
  // field actually changed, and the recomputed total exceeds the
  // recorded ``amount_paid``.  Drives the status-reversion warning.
  //
  // NOTE · ``categoryDiffOnPaid`` predicate was removed in the
  // Feb-2026 operator reversal (see state block above).  Category
  // edits on paid invoices now bypass every FE confirm.
  const totalExceedsPaid = useMemo(() => {
    if (!paid) return false;
    // Reversion warning only when a money-affecting field actually
    // moves (line-item qty / unit_price / tax_rate, top-level
    // tax_rate / discount_amount / discount_type) AND the
    // recomputed total exceeds amount_paid.  The pre-ticket
    // ``moneyChangedList`` based on ``itemsEqual`` treats ANY
    // line-item touch (including a description-only metadata
    // edit) as a money change, which would over-trigger this
    // dialog on the β bypass path.  Scope the check to actual
    // money-moving fields.
    const o = invoice?.line_items || [];
    const n = form.line_items || [];
    let lineMoneyMoved = o.length !== n.length;
    if (!lineMoneyMoved) {
      for (let i = 0; i < n.length; i += 1) {
        const oldLi = o[i] || {}; const newLi = n[i] || {};
        if (Number(oldLi.quantity || 0) !== Number(newLi.quantity || 0)
            || Number(oldLi.unit_price || 0) !== Number(newLi.unit_price || 0)
            || Number(oldLi.tax_rate || 0) !== Number(newLi.tax_rate || 0)) {
          lineMoneyMoved = true;
          break;
        }
      }
    }
    const topMoneyMoved = (
      Number(invoice?.discount_amount || 0)
        !== Number(form.discount_amount || 0)
      || (invoice?.discount_type || "fixed")
        !== (form.discount_type || "fixed")
      || Number(invoice?.tax_rate || 0)
        !== Number(form.tax_rate || 0)
    );
    if (!lineMoneyMoved && !topMoneyMoved) return false;
    const paidAmt = Number(invoice?.amount_paid || 0);
    const newTotal = Number(totals?.total || 0);
    return newTotal > paidAmt;
  }, [paid, invoice, totals, form]);

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
  // Feb-2026 · Editable Sent Docs · Phase 1 — the legacy sent-only
  // acknowledgement checkbox has been replaced by the shared
  // ``EditLockConfirmDialog``, which fires at Save-time for any
  // locked status (sent | accepted | paid). ``canSave`` therefore
  // no longer depends on the ``confirmSent`` checkbox; the dialog
  // provides the friction instead.
  const canSave = !terminal && !busy;

  const doSubmit = async () => {
    setBusy(true);
    setError("");
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
      // Feb-2026 · Editable Sent Docs · Phase 1 — never send the
      // invoice_number field; the input is disabled and the backend
      // treats invoice_number as immutable once assigned.
      delete payload.invoice_number;
      // Feb-2026 · Editable Sent Docs · Phase 1 — attach the ack
      // flag whenever the doc is locked. Legacy fields are still
      // populated for back-compat with older backend builds.
      // Feb-2026 β — SKIP the ack flag entirely on the paid
      // metadata-only path so the BE's new metadata-only short-
      // circuit fires.
      if (isLocked && !isPaidMetadataOnlyDiff) {
        payload.acknowledged_lock_bypass = true;
        if (sent) payload.confirm_edit_sent = true;
        if (paid) {
          payload.confirm_edit_paid_invoice_number =
            invoice?.invoice_number || "";
        }
      }
      const res = await api.patch(`/quotes/${invoice.id}`, payload);
      onSaved?.(res);
    } catch (e) {
      // Feb-2026 · invoice-category hard-block removal (parent SHA
      // ec88141ea + FE SHA 222350ab9) — the ``category_required``
      // / ``archived_category`` / ``category_invalid`` branch that
      // used to live here (setRowErrors + "Category is required on
      // every line. Fix the highlighted row.") is removed because
      // the backend now soft-passes those codes on
      // ``PATCH /quotes/{id}``.  Any surviving non-category save
      // failure still falls through to the legacy-code handler
      // below (invoice_number_conflict, requires_confirmation,
      // generic Error.message).
      const legacyCode = e?.data?.detail?.error || e?.data?.error;
      const msg = legacyCode === "invoice_number_conflict"
        ? "That invoice number is already in use. Pick a different one."
        : legacyCode === "requires_confirmation"
        ? "This invoice was sent — please acknowledge the confirmation dialog."
        : e?.message || "Save failed. Please try again.";
      setError(msg);
    } finally {
      setBusy(false);
    }
  };

  const submit = () => {
    if (!canSave) return;
    // TD-paid-invoice-admin-edit-unblock · Feb-2026 — chained
    // pre-save pipeline.  Each confirm, once accepted, flips its
    // ack flag on ``_acked.current`` and re-enters this function
    // so the next gate can evaluate.  Gates in fixed order:
    //   1. EditLockConfirmDialog   — shipped Phase-1 ack.
    //   2. StatusReversionWarning  — paid invoice's new total
    //                                 exceeds amount_paid.
    //   3. doSubmit().
    //
    // NOTE · The Feb-2026 ``5ab10f247`` ship introduced a third
    // gate (``<CategoryEditConfirmDialog>``) between 2 and 3.  It
    // was reverted in the operator reversal that landed this
    // commit — category edits on paid invoices now flow to
    // doSubmit() without any FE confirm.
    if (isLocked && !isPaidMetadataOnlyDiff
        && !_acked.current.editLock) {
      setConfirmOpen(true);
      return;
    }
    if (totalExceedsPaid && !_acked.current.statusReversion) {
      setReversionOpen(true);
      return;
    }
    doSubmit();
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
              <div className="flex items-start gap-2">
                <AlertTriangle size={16} />
                <span>
                  This invoice has been sent to the customer. You'll be
                  asked to confirm before your changes are saved.
                </span>
              </div>
            </div>
          ) : null}
          {accepted && !terminal ? (
            <div
              className="rounded-xl p-3 text-sm"
              style={{ background: "#FEF3C7", color: "#78350F",
                        border: "1px solid #FCD34D" }}
              data-testid="invoice-edit-banner-accepted"
            >
              <div className="flex items-start gap-2">
                <AlertTriangle size={16} />
                <span>
                  This invoice has been accepted by the customer. You'll be
                  asked to confirm before your changes are saved.
                </span>
              </div>
            </div>
          ) : null}
          {paid && !terminal ? (
            <div
              className="rounded-xl p-3 text-sm"
              style={{ background: "#FEE2E2", color: "#7F1D1D",
                        border: "1px solid #FCA5A5" }}
              data-testid="invoice-edit-banner-paid"
            >
              <div className="flex items-start gap-2">
                <AlertTriangle size={16} />
                <span>
                  This invoice has been PAID. Editing it does <b>not</b>{" "}
                  auto-refund or reconcile the Stripe ledger — you're on the
                  hook for any manual refund / adjustment. You'll be asked
                  to confirm before saving.
                </span>
              </div>
            </div>
          ) : null}
          {isSigned && !terminal ? (
            <div
              className="rounded-xl p-3 text-sm"
              style={{ background: "#FEF3C7", color: "#78350F",
                        border: "1px solid #FCD34D" }}
              data-testid="invoice-edit-banner-signed"
            >
              <div className="flex items-start gap-2">
                <AlertTriangle size={16} />
                <span>
                  This document has been signed by the customer. Saving edits
                  will invalidate the signature — the customer will need to
                  re-sign.
                </span>
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

          {/* TD-paid-invoice-admin-edit-title-field · Feb-2026 —
              top-level invoice display title (mirrors Quote.title
              in backend/models.py).  Editable at all times for
              admin+super_admin; BE whitelists it in
              _METADATA_ONLY_TOP_FIELDS so a title-only edit on a
              paid invoice rides the β bypass with zero FE friction. */}
          <TextInput
            label="Title"
            value={form.title}
            onChange={(e) => set("title", e.target.value)}
            testid="invoice-edit-title-input"
            placeholder="e.g. Pool opening — 123 Main St"
          />

          {/* Customer + Invoice number */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <TextInput
              label="Customer ID"
              value={form.customer_id}
              onChange={(e) => set("customer_id", e.target.value)}
              testid="invoice-edit-customer-id"
            />
            <TextInput
              label="Invoice Number (locked)"
              value={form.invoice_number}
              readOnly
              disabled
              title="Locked — cannot be changed after send."
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
                    return (
                    <tr key={i} data-testid={`invoice-edit-line-${i}`}
                        style={{ borderTop: `1px solid ${colors.border}` }}>
                      <td className="px-2 py-1">
                        {/* Phase P16.1 · Feb-2026 — Master Service
                             combobox in place of the raw description
                             input.  Pick auto-fills ``unit_price``
                             (dollars) via ``patchItem``.  The
                             modal's ``category`` field is an
                             INCOME category — a distinct taxonomy
                             from ``service_categories`` — so we
                             intentionally skip category auto-fill
                             here to avoid stamping a mismatched
                             id into the wrong bucket. */}
                        <MasterServiceCombobox
                          value={li.description || ""}
                          defaultPriceHint={
                            Number(li.unit_price) > 0
                              ? Number(li.unit_price) : null
                          }
                          onChange={({ name, default_price }) => {
                            const patch = { description: name };
                            if (Number.isFinite(default_price)
                                && default_price != null) {
                              patch.unit_price = Number(default_price);
                            }
                            patchItem(i, patch);
                          }}
                          placeholder="Search or add a service…"
                          testid={`invoice-edit-line-${i}-desc`}
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
                        {/* Feb-2026 · invoice-category hard-block
                             removal (parent SHA ec88141ea + FE SHA
                             222350ab9) — the inline red
                             ``invoice-edit-line-${i}-row-error``
                             div used to live here. Removed because
                             the backend no longer returns
                             ``category_required`` /
                             ``archived_category`` 400s. Yellow
                             soft-warning chips still render via
                             the CategoryPicker's own ``required``
                             prop. */}
                      </td>
                      <td className="px-2 py-1">
                        <CategoryPicker
                          value={li.category}
                          onChange={(v) => patchItem(i, { category: v })}
                          required
                          testid={`invoice-edit-line-${i}-cat`}
                          placeholder="Choose…"
                        />
                      </td>
                      <td className="px-2 py-1 text-right">
                        <input
                          type="number" step="0.01"
                          className="w-full px-2 py-1 text-sm rounded text-right"
                          style={{
                            background: paid && !isAdmin ? "#F3F4F6" : colors.surface,
                            border: `1px solid ${colors.border}`,
                            cursor: paid && !isAdmin ? "not-allowed" : "text",
                          }}
                          value={li.quantity}
                          onChange={(e) => patchItem(i, { quantity: e.target.value })}
                          readOnly={paid && !isAdmin}
                          aria-readonly={paid && !isAdmin ? "true" : undefined}
                          data-testid={`invoice-edit-line-${i}-qty`}
                        />
                      </td>
                      <td className="px-2 py-1 text-right">
                        <input
                          type="number" step="0.01"
                          className="w-full px-2 py-1 text-sm rounded text-right"
                          style={{
                            background: paid && !isAdmin ? "#F3F4F6" : colors.surface,
                            border: `1px solid ${colors.border}`,
                            cursor: paid && !isAdmin ? "not-allowed" : "text",
                          }}
                          value={li.unit_price}
                          onChange={(e) => patchItem(i, { unit_price: e.target.value })}
                          readOnly={paid && !isAdmin}
                          aria-readonly={paid && !isAdmin ? "true" : undefined}
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
      {/* Feb-2026 · Editable Sent Docs · Phase 1 — shared confirm
          dialog. Renders on top of the modal when Save is clicked
          against a locked (sent | accepted | paid) status. */}
      <EditLockConfirmDialog
        open={confirmOpen}
        onCancel={() => { if (!busy) setConfirmOpen(false); }}
        onConfirm={() => {
          // TD-paid-invoice-admin-edit-unblock · Feb-2026 — ack
          // the Phase-1 gate and re-enter the pipeline so the two
          // new pre-save confirms (status-reversion + category)
          // can evaluate.  doSubmit() still runs inside ``submit``
          // once every gate has either passed or been acked.
          setConfirmOpen(false);
          _acked.current = { ..._acked.current, editLock: true };
          submit();
        }}
        isStripePaid={isStripePaid}
        isSigned={isSigned}
        busy={busy}
        status={status}
      />
      {/* TD-paid-invoice-admin-edit-unblock · Feb-2026 — status
          reversion warning when a paid invoice's new total would
          push remaining_balance above $0 on save. */}
      <StatusReversionWarningDialog
        open={reversionOpen}
        onCancel={() => { if (!busy) setReversionOpen(false); }}
        onConfirm={() => {
          setReversionOpen(false);
          _acked.current = { ..._acked.current, statusReversion: true };
          submit();
        }}
        amountPaid={Number(invoice?.amount_paid || 0)}
        newTotal={Number(totals?.total || 0)}
        busy={busy}
      />
      {/* NOTE · Feb-2026 operator reversal — <CategoryEditConfirmDialog>
          mount was removed here.  Category edits on paid invoices
          now flow with zero friction; the pre-ticket retroactive
          revenue-by-category drift is captured via
          ``db.invoice_edit_history`` only (silent audit trail). */}
    </div>
  );
}
