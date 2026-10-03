import React, { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ArrowLeft, Plus, X } from "lucide-react";
import { api } from "@/api";
import { useAuth } from "@/auth";
import { colors, money } from "@/theme";
import { PageHeader, Button, TextInput, Toast } from "@/components/ui-kit";
// Phase 2 B2 · Feb-2026 — swap CustomerCombobox for the unified
// QuoteRecipientPicker so quotes/invoices can be addressed to a
// Lead OR Customer. Keep CustomerCombobox mounted on OTHER pages
// (New Job, Recurring Jobs, warranty scopes, etc.) — this swap is
// scoped to the quote/invoice create flow only.
import QuoteRecipientPicker from "@/components/quotes/QuoteRecipientPicker";
import CategoryPicker, {
  loadCategories as _loadServiceCats,
} from "@/components/income/CategoryPicker";
// Phase P16.1.1 · Feb-2026 — Master Service combobox drop-in for the
// create-flow line-items editor.  P16.1 wired the combobox into the
// K71 detail-edit surface (``K71LineItemsEditor`` used by
// ``QuoteInvoiceDetail.jsx``) but the create page mounted at
// ``/quotes/new`` and ``/invoices/new`` had its own inline editor
// still using ``<input list="items-datalist">``; this import closes
// that gap on both estimate and invoice create paths.
// Phase PRICEBOOK-UNIFY · Feb-2026 — MasterServiceCombobox import
// removed (was the master-services catalog picker). The line-
// item search now runs through the shared ``PricebookItemPicker``
// component so every admin surface (Estimator, K71, this page)
// hits the same ``/api/items`` endpoint. Retaining
// ``_loadServiceCats`` from CategoryPicker below since we still
// need it for service_category_id resolution on pick.
// Phase PRICEBOOK-UNIFY · Feb-2026 — shared standalone pricebook
// picker. Replaces the ``MasterServiceCombobox`` on quote /
// invoice line items so all admin surfaces search the same
// pricebook catalog.
import PricebookItemPicker from "@/components/pricebook/PricebookItemPicker";

/** Combined New form for both quotes and invoices — same data model, different `doc_type`. */
export default function QuoteInvoiceNew({ docType = "quote" }) {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  // Phase 2 B2 · Feb-2026 — accept both legacy ``?customer_id=``
  // AND the new ``?recipient_type=&recipient_id=`` pair.
  const preselectCustomerId = params.get("customer_id") || "";
  const preselectRecipientType = params.get("recipient_type") || "";
  const preselectRecipientId = params.get("recipient_id") || "";
  // Phase A2 · Feb-2026 · Proactive Intelligence — chemistry-upsell
  // deep-link prefill. When ``source=intelligence_alert`` the alerts
  // page has passed the recommended action slug via ``service_type``
  // and the originating alert id via ``alert_id``. We seed a
  // human-friendly title + note so the operator sees the context on
  // arrival; the description + line-items remain empty for the
  // operator to shape. No server-side "quote-from-alert" endpoint
  // exists yet — this is a pure client prefill (see Phase A2 spec).
  const preServiceType = params.get("service_type") || "";
  const preAlertId     = params.get("alert_id") || "";
  const preSource      = params.get("source") || "";
  const _presetTitle = () => {
    if (preSource === "intelligence_alert" && preServiceType) {
      const human = preServiceType.replace(/_/g, " ")
        .replace(/\b\w/g, (c) => c.toUpperCase());
      return `${human} — upsell quote`;
    }
    return docType === "invoice" ? "Invoice" : "Estimate";
  };
  const _presetNote = () => {
    if (preSource === "intelligence_alert" && preServiceType) {
      const human = preServiceType.replace(/_/g, " ");
      const src = preAlertId
        ? `intelligence alert ${preAlertId}`
        : "an intelligence alert";
      return `Recommended after ${src}: ${human}.`;
    }
    return "";
  };
  const [customers, setCustomers] = useState([]);
  const [toast, setToast] = useState(null);
  const [busy, setBusy] = useState(false);
  // Feb-2026 · Invoice inline edit sprint — per-row error state so
  // the save-blocking category errors from the backend can be
  // rendered inline on the offending row instead of a page-level toast.
  const [rowErrors, setRowErrors] = useState({});
  // Task H0 · Feb-2026 — Historical Invoice Date Backfill.
  // Admin-only optional ``created_at`` override on quote/invoice
  // create. The section renders only when ``canBackfill`` is
  // truthy; a blank input falls through to the server's default
  // ``now()`` stamp so the non-admin / no-override path is
  // completely unchanged.  The role predicate mirrors the backend
  // allowlist verbatim (``services.quotes.date_override``
  // ``_DEFAULT_ADMIN_ALLOWLIST``) — future drift on either side
  // trips vitest at ``task-h0-backfill-date-ui.test.jsx``.
  const { user } = useAuth();
  const canBackfill = ["admin", "super_admin", "owner"].includes(
    (user?.role || "").toLowerCase()
  );
  const [backfillDate, setBackfillDate] = useState("");

  // Phase 2 B2 · Feb-2026 — hybrid recipient state. Honor the new
  // {recipient_type,recipient_id} URL pair; fall back to the legacy
  // ``?customer_id=`` for Customer-only preselects.
  const _initialRecipient = (() => {
    if (preselectRecipientType && preselectRecipientId) {
      return {
        type: preselectRecipientType.toLowerCase() === "lead"
          ? "lead" : "customer",
        id: preselectRecipientId,
        name: "",
      };
    }
    if (preselectCustomerId) {
      return { type: "customer", id: preselectCustomerId, name: "" };
    }
    return null;
  })();
  const [recipient, setRecipient] = useState(_initialRecipient);
  const [form, setForm] = useState({
    customer_id: preselectCustomerId,
    title: _presetTitle(),
    doc_type: docType,
    tax_rate: 0,
    notes: _presetNote(),
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
    api.get("/customers?is_active=true").then((rows) => {
      setCustomers(rows);
      // Phase 2 B2 · Feb-2026 — once customers load, hydrate the
      // picker's display name if a legacy ``?customer_id=`` URL
      // preselect was in play and we only have the id so far.
      setRecipient((prev) => {
        if (!prev || prev.name || prev.type !== "customer") return prev;
        const hit = (rows || []).find((c) => c.id === prev.id);
        return hit ? { ...prev, name: hit.name || "" } : prev;
      });
    }).catch(() => {});
    // Phase P16.1.1 · Feb-2026 — the legacy ``/items`` datalist
    // fetch was retired when the description field flipped to
    // ``MasterServiceCombobox``, which pulls active rows from
    // ``/services/active`` on demand.
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
    // Phase 2 B2 · Feb-2026 — recipient MAY be a Customer OR a Lead.
    // Prefer the picker's ``recipient`` state; fall back to the
    // legacy ``form.customer_id`` for compatibility with any flows
    // that write only the customer_id field.
    const _effectiveRecipient = recipient
      || (form.customer_id
            ? { type: "customer", id: form.customer_id, name: "" }
            : null);
    if (!_effectiveRecipient || !_effectiveRecipient.id) {
      setToast({ tone: "error", message: "Pick a customer or lead" });
      return;
    }
    // Clear stale row errors — the retry might have fixed the offender.
    setRowErrors({});
    setBusy(true);
    try {
      // Phase 2 B2 · Feb-2026 — hybrid payload.
      //   • Customer recipient → send BOTH customer_id (legacy) AND
      //     {recipient_type:"customer", recipient_id}.
      //   • Lead recipient     → omit customer_id entirely and send
      //     {recipient_type:"lead", recipient_id}. Backend B1 will
      //     NOT auto-promote the lead to a customer.
      const _isLeadRecipient = _effectiveRecipient.type === "lead";
      const payload = {
        ...(_isLeadRecipient ? {} : { customer_id: _effectiveRecipient.id }),
        recipient_type: _effectiveRecipient.type,
        recipient_id: _effectiveRecipient.id,
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
      // Task H0 · Feb-2026 — admin-only historical-date backfill.
      // Include ``created_at`` ONLY when the operator is an admin
      // AND typed a date; otherwise omit the key entirely so the
      // server-side ``resolve_date_override`` short-circuits on
      // ``None`` and stamps ``now()``.  Sending an empty string
      // would trigger a Pydantic 422 (invalid datetime) — hence
      // the conditional-key pattern rather than `|| undefined`.
      if (canBackfill && backfillDate) {
        payload.created_at = new Date(backfillDate).toISOString();
      }
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

  // Phase P16.1.1 · Feb-2026 — the legacy pricebook ``<datalist>``
  // for the description field was replaced by the
  // ``MasterServiceCombobox`` above, which pulls active rows from
  // ``/services/active`` on demand.

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
                RECIPIENT *
              </label>
              {/* Phase 2 B2 · Feb-2026 — unified Customer/Lead
                  picker. Keeps ``form.customer_id`` wired for
                  Customer picks so legacy inline reads continue
                  to resolve; blanks it on Lead picks so the
                  backend contract maps cleanly. */}
              <QuoteRecipientPicker
                value={recipient}
                onChange={(next) => {
                  setRecipient(next);
                  setForm((f) => ({
                    ...f,
                    customer_id: next?.type === "customer" ? next.id : "",
                  }));
                }}
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
                      {/* Phase P16.1.1 · Feb-2026 — Master Service
                          combobox in place of the raw ``description``
                          input + datalist.  Mirrors the K71
                          drop-in in ``K71LineItemsEditor.jsx``.  A
                          pick auto-fills ``unit_price`` (dollars) +
                          ``category`` (name, the shape this page
                          ships to ``POST /quotes``) + resolves the
                          category NAME to a
                          ``service_category_id`` for K71-parity in
                          the create payload.  Free-typing still
                          saves the raw string — backward-compatible
                          with legacy pricebook items that never
                          lived in ``services``. */}
                      {/* Phase PRICEBOOK-UNIFY · Feb-2026 —
                          swapped the master-services catalog
                          picker (`MasterServiceCombobox`) for the
                          shared ``PricebookItemPicker`` so quotes
                          / invoices search the SAME pricebook
                          catalog as Estimator + K71. On pick we
                          auto-fill ``description`` +
                          ``unit_price``; category / service-
                          category-id resolution downstream still
                          runs identically (rehydrated below). */}
                      <PricebookItemPicker
                        value={li.description}
                        onChange={(text) => setLine(i, "description", text)}
                        onSelect={(item) => {
                          setForm((f) => ({
                            ...f,
                            line_items: f.line_items.map((x, idx) => {
                              if (idx !== i) return x;
                              const next = { ...x };
                              next.description = item.name
                                                    || item.description
                                                    || x.description;
                              const raw = Number(item.unit_price);
                              if (Number.isFinite(raw)) {
                                next.unit_price = raw;
                                next._pricebook_unit_price = raw;
                              }
                              // Preserve K71-parity: propagate the
                              // pricebook item's ``category`` label
                              // + its id for downstream refs.
                              if (item.category) next.category = item.category;
                              if (item.id) {
                                next.item_id = item.id;
                                next.pricebook_item_id = item.id;
                              }
                              if (item.service_category_id) {
                                next.service_category_id = item.service_category_id;
                              }
                              return next;
                            }),
                          }));
                          // Resolve service-category NAME → id via
                          // the same cache the legacy picker used
                          // — keeps every downstream K71-parity
                          // read path working.
                          const cat = item.category
                                       || item.service_category_name;
                          if (cat && !item.service_category_id) {
                            _loadServiceCats("service").then((cats) => {
                              const match = (cats || []).find(
                                (c) => String(c.name || "").toLowerCase()
                                  === String(cat).toLowerCase(),
                              );
                              if (!match?.id) return;
                              setForm((f) => ({
                                ...f,
                                line_items: f.line_items.map((x, idx) =>
                                  idx === i
                                    ? { ...x, service_category_id: match.id }
                                    : x,
                                ),
                              }));
                            });
                          }
                        }}
                        placeholder="Search pricebook or type a one-off name…"
                        testidPrefix={`qf-line-${i}-picker`}
                        inputTestid={`qf-line-${i}-desc-input`}
                      />
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

        {/*
          Task H0 · Feb-2026 — admin-only Backfill Date section.
          Zero visual change for techs / customers / no-override
          flows: the collapsible ``<details>`` is only mounted when
          ``canBackfill`` is truthy AND stays collapsed by default
          (``open`` is intentionally omitted).  Blank input →
          payload omits ``created_at`` → server stamps ``now()``.
          See ``services/quotes/date_override.py`` for the paired
          backend contract + validation.
        */}
        {canBackfill ? (
          <div
            className="rounded-2xl p-5 mb-4"
            style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
            data-testid="backfill-date-section"
          >
            <details>
              <summary
                className="text-xs font-semibold tracking-wide cursor-pointer select-none"
                style={{ color: colors.onSurfaceSecondary }}
                data-testid="backfill-date-summary"
              >
                BACKFILL DATE (admin)
              </summary>
              <div className="mt-3">
                <label
                  className="text-xs font-semibold tracking-wide mb-1 block"
                  style={{ color: colors.onSurfaceSecondary }}
                >
                  {docType === "invoice" ? "INVOICE DATE" : "ESTIMATE DATE"}
                </label>
                <input
                  type="date"
                  value={backfillDate}
                  onChange={(e) => setBackfillDate(e.target.value)}
                  className="w-full px-3 py-2 text-sm rounded-lg outline-none focus:ring-2"
                  style={{
                    backgroundColor: colors.surface,
                    color: colors.onSurface,
                    border: `1px solid ${colors.border}`,
                  }}
                  data-testid="backfill-date-input"
                />
                <p className="text-xs mt-2" style={{ color: colors.muted }}>
                  Leave blank to use today. Only used when importing historical {docType === "invoice" ? "invoices" : "estimates"}.
                </p>
              </div>
            </details>
          </div>
        ) : null}

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
