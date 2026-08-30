import React, { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ArrowLeft, Plus, X } from "lucide-react";
import { api } from "@/api";
import { colors, money } from "@/theme";
import { PageHeader, Button, TextInput, Toast } from "@/components/ui-kit";
import CustomerCombobox from "@/components/customers/CustomerCombobox";
import CategoryPicker from "@/components/income/CategoryPicker";

/** Combined New form for both quotes and invoices — same data model, different `doc_type`. */
export default function QuoteInvoiceNew({ docType = "quote" }) {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const preselect = params.get("customer_id") || "";
  const [customers, setCustomers] = useState([]);
  const [items, setItems] = useState([]);
  const [toast, setToast] = useState(null);
  const [busy, setBusy] = useState(false);
  // Feb-2026 · Invoice inline edit sprint — per-row error state so
  // the save-blocking category errors from the backend can be
  // rendered inline on the offending row instead of a page-level toast.
  const [rowErrors, setRowErrors] = useState({});

  const [form, setForm] = useState({
    customer_id: preselect,
    title: docType === "invoice" ? "Invoice" : "Estimate",
    doc_type: docType,
    tax_rate: 0,
    notes: "",
    terms: "",
    due_date: "",
    // Feb-2026 · Invoice inline edit sprint — category field on new
    // rows is empty so the operator must actively pick one via the
    // inline CategoryPicker. Backend validate_line_item_categories
    // rejects blanks with a friendly ``category_required`` shape.
    line_items: [{ description: "", quantity: 1, unit_price: 0, category: "", pricebook_writeback: false }],
  });
  const [termsDefault, setTermsDefault] = useState("");

  useEffect(() => {
    api.get("/customers?is_active=true").then(setCustomers).catch(() => {});
    api.get("/items").then(setItems).catch(() => {});
    api.get("/settings/terms").then((r) => {
      const def = docType === "invoice" ? r.default_invoice_terms : r.default_quote_terms;
      setTermsDefault(def || "");
      setForm((f) => (f.terms ? f : { ...f, terms: def || "" }));
    }).catch(() => {});
  }, [docType]);

  const totals = useMemo(() => {
    const subtotal = form.line_items.reduce(
      (sum, li) => sum + (Number(li.quantity) || 0) * (Number(li.unit_price) || 0),
      0
    );
    const tax = subtotal * (Number(form.tax_rate) || 0) / 100;
    return { subtotal, tax, total: subtotal + tax };
  }, [form.line_items, form.tax_rate]);

  const setField = (k) => (e) =>
    setForm((f) => ({ ...f, [k]: e.target?.value ?? e }));

  const setLine = (i, k, v) =>
    setForm((f) => ({
      ...f,
      line_items: f.line_items.map((li, idx) => (idx === i ? { ...li, [k]: v } : li)),
    }));

  const patchLine = (i, patch) =>
    setForm((f) => ({
      ...f,
      line_items: f.line_items.map((li, idx) => (idx === i ? { ...li, ...patch } : li)),
    }));

  const addLine = () =>
    setForm((f) => ({
      ...f,
      line_items: [...f.line_items, { description: "", quantity: 1, unit_price: 0, category: "", pricebook_writeback: false }],
    }));

  const removeLine = (i) =>
    setForm((f) => ({
      ...f,
      line_items: f.line_items.filter((_, idx) => idx !== i),
    }));

  const submit = async (e) => {
    e.preventDefault();
    if (!form.customer_id) {
      setToast({ tone: "error", message: "Pick a customer" });
      return;
    }
    // Clear stale row errors — the retry might have fixed the offender.
    setRowErrors({});
    setBusy(true);
    try {
      const payload = {
        customer_id: form.customer_id,
        title: form.title || (docType === "invoice" ? "Invoice" : "Estimate"),
        doc_type: form.doc_type,
        tax_rate: Number(form.tax_rate) || 0,
        due_date: form.due_date || undefined,
        notes: form.notes,
        terms: form.terms,
        line_items: form.line_items
          .filter((li) => (li.description || "").trim())
          .map((li) => ({
            description: li.description,
            quantity: Number(li.quantity) || 0,
            unit_price: Number(li.unit_price) || 0,
            category: li.category || "",
            item_id: li.item_id || li.pricebook_item_id || undefined,
            pricebook_item_id: li.pricebook_item_id || undefined,
            // Feb-2026 · Invoice inline edit sprint — writeback flag
            // is opt-in per line. Backend processes AFTER save.
            pricebook_writeback: !!li.pricebook_writeback,
          })),
      };
      const saved = await api.post("/quotes", payload);
      setToast({ tone: "success", message: `${docType === "invoice" ? "Invoice" : "Quote"} created` });
      setTimeout(
        () => navigate(docType === "invoice" ? `/invoices/${saved.id}` : `/quotes/${saved.id}`),
        400
      );
    } catch (err) {
      // Feb-2026 · Invoice inline edit sprint — parse structured
      // category error and surface INLINE on the offending row
      // instead of a blocking page toast. Save button stays enabled
      // so the operator can fix + retry without a scroll.
      const detail = err?.data?.detail || {};
      const code = detail?.error_code || detail?.error;
      const idx = typeof detail?.line_index === "number" ? detail.line_index : null;
      if (idx !== null && (code === "archived_category"
                            || code === "category_invalid"
                            || code === "category_required")) {
        setRowErrors((prev) => ({
          ...prev,
          [idx]: {
            reason: code === "category_required" ? "category_required" : "archived_category",
            attempted: detail?.attempted_category || form.line_items[idx]?.category,
            message: detail?.message || err.message,
          },
        }));
        setToast({ tone: "error",
                    message: code === "category_required"
                      ? "Category is required on every line. Fix highlighted rows."
                      : `Category '${detail?.attempted_category || ""}' is archived. Pick an active one on the highlighted row.` });
      } else {
        setToast({ tone: "error", message: err.message });
      }
    } finally {
      setBusy(false);
    }
  };

  const priceBook = items.filter((i) => i.category !== "Chemical");

  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-6" data-testid={`${docType}-new-page`}>
      <button
        onClick={() => navigate(-1)}
        className="flex items-center gap-1 text-sm font-semibold mb-4"
        style={{ color: colors.muted }}
      >
        <ArrowLeft size={14} /> Back
      </button>
      <PageHeader title={docType === "invoice" ? "New Invoice" : "New Quote"} />

      <form onSubmit={submit} data-testid={`${docType}-form`}>
        <div
          className="rounded-2xl p-5 space-y-4 mb-4"
          style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
        >
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="text-xs font-semibold tracking-wide mb-1 block" style={{ color: colors.onSurfaceSecondary }}>
                CUSTOMER *
              </label>
              <CustomerCombobox
                value={form.customer_id}
                onChange={(cid) => setForm((f) => ({ ...f, customer_id: cid }))}
                customers={customers}
                testid="qf-customer"
              />
            </div>
            <TextInput label="TITLE" value={form.title} onChange={setField("title")} testid="qf-title" />
            <TextInput
              label="TAX RATE (%)"
              type="number"
              step="0.01"
              value={form.tax_rate}
              onChange={setField("tax_rate")}
              testid="qf-tax"
            />
            {docType === "invoice" ? (
              <TextInput
                label="DUE DATE"
                type="date"
                value={form.due_date}
                onChange={setField("due_date")}
                testid="qf-due"
              />
            ) : null}
          </div>
        </div>

        {/* Line items */}
        <div
          className="rounded-2xl p-5 mb-4"
          style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
        >
          <div className="text-xs font-semibold tracking-wide mb-3" style={{ color: colors.onSurfaceSecondary }}>
            LINE ITEMS
          </div>
          <div className="space-y-3" data-testid="qf-line-items">
            {form.line_items.map((li, i) => {
              const rowErr = rowErrors[i];
              const pricebookDefault = li._pricebook_unit_price;
              const priceOverridden = pricebookDefault != null
                && Math.abs(Number(li.unit_price || 0) - Number(pricebookDefault || 0)) > 0.005;
              return (
                <div
                  key={i}
                  className="rounded-xl p-3"
                  style={{
                    background: rowErr ? "#FEF2F2" : colors.surfaceSecondary,
                    border: `1px solid ${rowErr ? "#FCA5A5" : colors.border}`,
                  }}
                  data-testid={`qf-line-${i}`}
                >
                  {/* Top row: description + qty + price + remove */}
                  <div className="grid grid-cols-12 gap-2 items-start">
                    <div className="col-span-12 md:col-span-6">
                      <label className="text-[10px] uppercase tracking-wider font-semibold block mb-1"
                              style={{ color: colors.muted }}>
                        DESCRIPTION
                      </label>
                      <input
                        list={`items-datalist-${i}`}
                        value={li.description}
                        onChange={(e) => {
                          const chosen = priceBook.find((it) => it.name === e.target.value);
                          if (chosen) {
                            setForm((f) => ({
                              ...f,
                              line_items: f.line_items.map((x, idx) =>
                                idx === i
                                  ? { ...x, description: chosen.name,
                                      unit_price: chosen.unit_price || 0,
                                      category: chosen.category || x.category || "",
                                      pricebook_item_id: chosen.id,
                                      item_id: chosen.id,
                                      _item_type: (chosen.item_type || "product").toLowerCase(),
                                      _pricebook_unit_price: Number(chosen.unit_price || 0) }
                                  : x
                              ),
                            }));
                          } else {
                            setLine(i, "description", e.target.value);
                          }
                        }}
                        placeholder="Item / description"
                        className="w-full px-3 py-2 text-sm rounded-lg outline-none focus:ring-2"
                        style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
                        data-testid={`qf-line-${i}-desc`}
                      />
                      <datalist id={`items-datalist-${i}`}>
                        {priceBook.map((it) => (
                          <option key={it.id} value={it.name} />
                        ))}
                      </datalist>
                    </div>
                    <div className="col-span-4 md:col-span-2">
                      <label className="text-[10px] uppercase tracking-wider font-semibold block mb-1"
                              style={{ color: colors.muted }}>
                        QTY
                      </label>
                      <input
                        type="number"
                        min="0"
                        step="0.01"
                        value={li.quantity}
                        onChange={(e) => setLine(i, "quantity", e.target.value)}
                        placeholder="Qty"
                        className="w-full px-3 py-2 text-sm rounded-lg outline-none focus:ring-2"
                        style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
                        data-testid={`qf-line-${i}-qty`}
                      />
                    </div>
                    <div className="col-span-6 md:col-span-3">
                      <label className="text-[10px] uppercase tracking-wider font-semibold block mb-1"
                              style={{ color: colors.muted }}>
                        UNIT PRICE
                      </label>
                      {/* Feb-2026 · Invoice inline edit sprint — price
                          field is ALWAYS editable. Pricebook value is
                          a prefill default, not a wall. Non-blocking
                          "custom price" hint surfaces when the value
                          diverges from the pricebook default. */}
                      <input
                        type="number"
                        min="0"
                        step="0.01"
                        value={li.unit_price}
                        onChange={(e) => setLine(i, "unit_price", e.target.value)}
                        placeholder="Unit $"
                        className="w-full px-3 py-2 text-sm rounded-lg outline-none focus:ring-2"
                        style={{
                          backgroundColor: colors.surface,
                          border: `1px solid ${priceOverridden ? "#F59E0B" : colors.border}`,
                        }}
                        data-testid={`qf-line-${i}-price`}
                      />
                      {priceOverridden ? (
                        <div
                          className="text-[11px] italic mt-1"
                          style={{ color: "#B45309" }}
                          data-testid={`qf-line-${i}-price-custom`}
                        >
                          custom price — pricebook shows {money(pricebookDefault)}
                        </div>
                      ) : null}
                    </div>
                    <div className="col-span-2 md:col-span-1 flex md:justify-end">
                      <button
                        type="button"
                        onClick={() => removeLine(i)}
                        className="opacity-70 hover:opacity-100 pt-6"
                        style={{ color: colors.error }}
                        data-testid={`qf-line-${i}-remove`}
                        aria-label={`Remove line ${i + 1}`}
                      >
                        <X size={16} />
                      </button>
                    </div>
                  </div>
                  {/* Bottom row: category picker + writeback checkbox */}
                  <div className="grid grid-cols-12 gap-2 items-start mt-2">
                    <div className="col-span-12 md:col-span-6">
                      <label className="text-[10px] uppercase tracking-wider font-semibold block mb-1"
                              style={{ color: colors.muted }}>
                        CATEGORY *
                      </label>
                      <CategoryPicker
                        value={li.category}
                        onChange={(v) => {
                          patchLine(i, { category: v });
                          setRowErrors((prev) => {
                            if (!prev[i]) return prev;
                            const next = { ...prev };
                            delete next[i];
                            return next;
                          });
                        }}
                        required
                        source="income"
                        placeholder="Choose category…"
                        testid={`qf-line-${i}-cat`}
                        invalidReason={rowErr?.reason || null}
                        autoFocus={!!rowErr}
                      />
                    </div>
                    <div className="col-span-12 md:col-span-6 pt-5">
                      <label
                        className="inline-flex items-center gap-2 text-xs cursor-pointer select-none"
                        data-testid={`qf-line-${i}-writeback-label`}
                        style={{ color: colors.onSurface }}
                      >
                        <input
                          type="checkbox"
                          checked={!!li.pricebook_writeback}
                          onChange={(e) => setLine(i, "pricebook_writeback", e.target.checked)}
                          data-testid={`qf-line-${i}-writeback`}
                        />
                        <span>
                          {li.item_id || li.pricebook_item_id
                            ? "Also save this to the pricebook"
                            : "Also add this to the pricebook"}
                        </span>
                      </label>
                    </div>
                  </div>
                  {rowErr ? (
                    <div
                      className="mt-2 text-xs font-semibold"
                      style={{ color: "#7F1D1D" }}
                      data-testid={`qf-line-${i}-row-error`}
                    >
                      {rowErr.reason === "category_required"
                        ? "Category required on this line."
                        : `Category '${rowErr.attempted || ""}' is archived. Choose an active category or create a new one.`}
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
          <div className="mt-3">
            <Button variant="ghost" onClick={(e) => { e.preventDefault(); addLine(); }} testid="qf-add-line">
              <Plus size={14} /> Add line
            </Button>
          </div>

          {/* Totals */}
          <div className="mt-5 pt-4 grid grid-cols-2 gap-2 text-sm ml-auto max-w-xs" style={{ borderTop: `1px solid ${colors.divider}` }}>
            <span style={{ color: colors.muted }}>Subtotal</span>
            <span className="text-right" style={{ color: colors.onSurface }} data-testid="qf-subtotal">
              {money(totals.subtotal)}
            </span>
            <span style={{ color: colors.muted }}>Tax ({form.tax_rate}%)</span>
            <span className="text-right" style={{ color: colors.onSurface }}>{money(totals.tax)}</span>
            <span className="font-semibold" style={{ color: colors.onSurface }}>Total</span>
            <span className="text-right font-bold" style={{ color: colors.brand }} data-testid="qf-total">
              {money(totals.total)}
            </span>
          </div>
        </div>

        <div
          className="rounded-2xl p-5 mb-4"
          style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
        >
          <label className="text-xs font-semibold tracking-wide mb-1 block" style={{ color: colors.onSurfaceSecondary }}>
            NOTES
          </label>
          <textarea
            rows={3}
            value={form.notes}
            onChange={setField("notes")}
            className="w-full px-3 py-2 text-sm rounded-lg outline-none focus:ring-2"
            style={{ backgroundColor: colors.surface, color: colors.onSurface, border: `1px solid ${colors.border}` }}
            data-testid="qf-notes"
          />
        </div>

        <div
          className="rounded-2xl p-5 mb-4"
          style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
        >
          <div className="flex items-center justify-between mb-1">
            <label className="text-xs font-semibold tracking-wide block" style={{ color: colors.onSurfaceSecondary }}>
              TERMS &amp; CONDITIONS
            </label>
            {termsDefault && form.terms !== termsDefault ? (
              <button type="button" onClick={() => setForm((f) => ({ ...f, terms: termsDefault }))}
                      className="text-xs font-semibold hover:underline"
                      style={{ color: colors.brand }}
                      data-testid="qf-terms-reset">
                Reset to default
              </button>
            ) : null}
          </div>
          <textarea
            rows={5}
            value={form.terms}
            onChange={setField("terms")}
            placeholder="Legal terms shown at the bottom of the document and PDF."
            className="w-full px-3 py-2 text-sm rounded-lg outline-none focus:ring-2"
            style={{ backgroundColor: colors.surface, color: colors.onSurface, border: `1px solid ${colors.border}` }}
            data-testid="qf-terms"
          />
        </div>

        <div className="flex justify-end gap-2 pb-8">
          <Button variant="ghost" onClick={(e) => { e.preventDefault(); navigate(-1); }}>Cancel</Button>
          <Button type="submit" disabled={busy} testid="qf-submit">
            {busy ? "Creating…" : `Create ${docType}`}
          </Button>
        </div>
      </form>
      <Toast toast={toast} onClose={() => setToast(null)} />
    </div>
  );
}
