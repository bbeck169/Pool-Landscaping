import React, { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ArrowLeft, Plus, X } from "lucide-react";
import { api } from "@/api";
import { colors, money } from "@/theme";
import { PageHeader, Button, TextInput, Toast } from "@/components/ui-kit";

/** Combined New form for both quotes and invoices — same data model, different `doc_type`. */
export default function QuoteInvoiceNew({ docType = "quote" }) {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const preselect = params.get("customer_id") || "";
  const [customers, setCustomers] = useState([]);
  const [items, setItems] = useState([]);
  const [toast, setToast] = useState(null);
  const [busy, setBusy] = useState(false);

  const [form, setForm] = useState({
    customer_id: preselect,
    title: docType === "invoice" ? "Invoice" : "Estimate",
    doc_type: docType,
    tax_rate: 0,
    notes: "",
    terms: "",
    due_date: "",
    line_items: [{ description: "", quantity: 1, unit_price: 0, category: "Pool" }],
  });
  const [termsDefault, setTermsDefault] = useState("");

  useEffect(() => {
    api.get("/customers").then(setCustomers).catch(() => {});
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

  const addLine = () =>
    setForm((f) => ({
      ...f,
      line_items: [...f.line_items, { description: "", quantity: 1, unit_price: 0, category: "Pool" }],
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
            category: li.category || "Pool",
          })),
      };
      const saved = await api.post("/quotes", payload);
      setToast({ tone: "success", message: `${docType === "invoice" ? "Invoice" : "Quote"} created` });
      setTimeout(
        () => navigate(docType === "invoice" ? `/invoices/${saved.id}` : `/quotes/${saved.id}`),
        400
      );
    } catch (err) {
      setToast({ tone: "error", message: err.message });
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
              <select
                value={form.customer_id}
                onChange={setField("customer_id")}
                className="w-full px-3.5 py-2.5 rounded-lg outline-none text-sm focus:ring-2"
                style={{ backgroundColor: colors.surface, color: colors.onSurface, border: `1px solid ${colors.border}` }}
                data-testid="qf-customer"
              >
                <option value="">Choose a customer…</option>
                {customers.map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
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
          <div className="space-y-2" data-testid="qf-line-items">
            {form.line_items.map((li, i) => (
              <div key={i} className="grid grid-cols-12 gap-2 items-start" data-testid={`qf-line-${i}`}>
                <div className="col-span-6">
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
                              ? { ...x, description: chosen.name, unit_price: chosen.unit_price || 0, category: chosen.category || "Pool", pricebook_item_id: chosen.id }
                              : x
                          ),
                        }));
                      } else {
                        setLine(i, "description", e.target.value);
                      }
                    }}
                    placeholder="Item / description"
                    className="w-full px-3 py-2 text-sm rounded-lg outline-none focus:ring-2"
                    style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}` }}
                    data-testid={`qf-line-${i}-desc`}
                  />
                  <datalist id={`items-datalist-${i}`}>
                    {priceBook.map((it) => (
                      <option key={it.id} value={it.name} />
                    ))}
                  </datalist>
                </div>
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  value={li.quantity}
                  onChange={(e) => setLine(i, "quantity", e.target.value)}
                  placeholder="Qty"
                  className="col-span-2 px-3 py-2 text-sm rounded-lg outline-none focus:ring-2"
                  style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}` }}
                  data-testid={`qf-line-${i}-qty`}
                />
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  value={li.unit_price}
                  onChange={(e) => setLine(i, "unit_price", e.target.value)}
                  placeholder="Unit $"
                  className="col-span-3 px-3 py-2 text-sm rounded-lg outline-none focus:ring-2"
                  style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}` }}
                  data-testid={`qf-line-${i}-price`}
                />
                <button
                  type="button"
                  onClick={() => removeLine(i)}
                  className="col-span-1 opacity-70 hover:opacity-100 pt-2"
                  style={{ color: colors.error }}
                  data-testid={`qf-line-${i}-remove`}
                >
                  <X size={16} />
                </button>
              </div>
            ))}
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
