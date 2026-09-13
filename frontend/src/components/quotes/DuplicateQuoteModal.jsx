/**
 * DuplicateQuoteModal · Feb-2026 · P0
 *
 * Modal + endpoint wiring for the "Duplicate" toolbar action on a
 * quote detail page.  Fires ``POST /api/quotes/{qid}/duplicate``
 * with:
 *
 *     {
 *       "customer_id": "<uuid — pre-fills to the source quote's
 *                        current customer; admin may reassign>",
 *       "property_id": "<uuid | null — the destination customer's
 *                        active property when the picker exposes one;
 *                        null when the destination has zero on file>"
 *     }
 *
 * On success: fires ``onDuplicated({ quote_id, quote_number })`` and
 * closes.  On failure: fires ``onError(detail)`` and keeps the modal
 * open so the admin can fix the input.
 *
 * See ``/app/memory/FEATURE_QUOTE_DUPLICATE.md`` for the full
 * carry-over / reset field manifest and the property-resolution
 * rules the backend enforces.
 */
import React, { useEffect, useMemo, useState } from "react";
import { Button, Modal } from "@/components/ui-kit";
import { api } from "@/api";
import { colors } from "@/theme";
import { Copy } from "lucide-react";


export default function DuplicateQuoteModal({
  open,
  quoteId,
  sourceCustomerId,
  onClose,
  onDuplicated,
  onError,
}) {
  const [busy, setBusy] = useState(false);
  const [customers, setCustomers] = useState([]);
  const [customerId, setCustomerId] = useState(sourceCustomerId || "");
  const [customerFilter, setCustomerFilter] = useState("");
  const [properties, setProperties] = useState([]);
  const [propertyId, setPropertyId] = useState("");
  const [propsLoading, setPropsLoading] = useState(false);

  // Load the customer roster once when the modal opens.  Uses the
  // same endpoint QuoteInvoiceNew already consumes so the tenant
  // scoping / soft-delete filter stays consistent.
  useEffect(() => {
    if (!open) return;
    api.get("/customers?is_active=true")
      .then((rows) => setCustomers(Array.isArray(rows) ? rows : []))
      .catch(() => setCustomers([]));
  }, [open]);

  // Re-pin the customer selection to the source whenever the modal
  // (re-)opens with a different quote.
  useEffect(() => {
    if (open) setCustomerId(sourceCustomerId || "");
  }, [open, sourceCustomerId]);

  // Fetch the destination customer's active properties whenever the
  // selected customer changes.  Auto-select the first active property
  // when the list is non-empty (matches the create_quote auto-assign
  // behaviour); leave blank when the destination has zero properties
  // (the Duplicate button still submits — the backend accepts
  // ``property_id=null``).
  useEffect(() => {
    if (!open || !customerId) {
      setProperties([]);
      setPropertyId("");
      return;
    }
    setPropsLoading(true);
    api.get(`/customers/${customerId}/properties`)
      .then((rows) => {
        const active = (Array.isArray(rows) ? rows : [])
          .filter((p) => p && p.active !== false);
        setProperties(active);
        setPropertyId(active.length ? active[0].id : "");
      })
      .catch(() => { setProperties([]); setPropertyId(""); })
      .finally(() => setPropsLoading(false));
  }, [open, customerId]);

  const filteredCustomers = useMemo(() => {
    const q = String(customerFilter || "").trim().toLowerCase();
    if (!q) return customers.slice(0, 200);
    return customers.filter((c) => {
      const hay = [
        c?.name, c?.email, c?.phone, c?.customer_number,
      ].filter(Boolean).join(" ").toLowerCase();
      return hay.includes(q);
    }).slice(0, 200);
  }, [customers, customerFilter]);

  const run = async () => {
    if (!customerId) {
      onError?.("Pick a customer before duplicating.");
      return;
    }
    setBusy(true);
    try {
      const body = { customer_id: customerId };
      if (propertyId) body.property_id = propertyId;
      const r = await api.post(`/quotes/${quoteId}/duplicate`, body);
      onDuplicated?.(r);
    } catch (e) {
      // Surface the backend detail verbatim (422 / 404 / 403) so
      // the admin sees the actionable server message.
      const detail = e?.detail || e?.message || "Duplicate failed";
      onError?.(String(detail));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={busy ? undefined : onClose}
      title="Duplicate this quote"
      footer={
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            onClick={onClose}
            disabled={busy}
            testid="duplicate-quote-cancel"
          >
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={run}
            disabled={busy || !customerId}
            testid="duplicate-quote-confirm"
          >
            <Copy size={14} />
            {busy ? " Duplicating…" : " Duplicate"}
          </Button>
        </div>
      }
    >
      <div
        data-testid="duplicate-quote-body"
        style={{
          display: "flex", flexDirection: "column", gap: 14,
          minWidth: 380,
        }}
      >
        <p style={{ fontSize: 13, color: colors.onSurfaceSecondary,
                     margin: 0 }}>
          Creates a new <b>draft</b> quote with the same line items,
          terms and notes.  Signatures, decisions, decline state and
          any sent/paid timestamps are reset.
        </p>

        <label style={{ display: "flex", flexDirection: "column",
                         gap: 6 }}>
          <span style={{ fontSize: 12, fontWeight: 600 }}>
            Customer
          </span>
          <input
            type="text"
            placeholder="Search name, email, phone…"
            value={customerFilter}
            onChange={(e) => setCustomerFilter(e.target.value)}
            data-testid="duplicate-quote-customer-search"
            style={{
              border: `1px solid ${colors.border}`, borderRadius: 6,
              padding: "6px 10px", fontSize: 14,
            }}
          />
          <select
            value={customerId}
            onChange={(e) => setCustomerId(e.target.value)}
            data-testid="duplicate-quote-customer-select"
            style={{
              border: `1px solid ${colors.border}`, borderRadius: 6,
              padding: "6px 10px", fontSize: 14, minHeight: 34,
            }}
          >
            <option value="">— Select customer —</option>
            {filteredCustomers.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name || "(no name)"}
                {c.customer_number ? ` · #${c.customer_number}` : ""}
              </option>
            ))}
          </select>
        </label>

        <label style={{ display: "flex", flexDirection: "column",
                         gap: 6 }}>
          <span style={{ fontSize: 12, fontWeight: 600 }}>
            Property
          </span>
          <select
            value={propertyId}
            onChange={(e) => setPropertyId(e.target.value)}
            data-testid="duplicate-quote-property-select"
            disabled={propsLoading || properties.length === 0}
            style={{
              border: `1px solid ${colors.border}`, borderRadius: 6,
              padding: "6px 10px", fontSize: 14, minHeight: 34,
            }}
          >
            {properties.length === 0 ? (
              <option value="">
                {propsLoading ? "Loading…" : "No properties on file"}
              </option>
            ) : (
              properties.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label || "(unlabelled)"}
                </option>
              ))
            )}
          </select>
          {!propsLoading && properties.length === 0 && customerId ? (
            <span
              data-testid="duplicate-quote-no-properties-hint"
              style={{ fontSize: 12, color: colors.onSurfaceSecondary }}
            >
              This customer has no active properties. The new quote
              will be created without a property pin — you can add one
              from the draft.
            </span>
          ) : null}
        </label>
      </div>
    </Modal>
  );
}
