/**
 * Feb-2026 · CustomerFilterBar
 * ─────────────────────────────────────────────────────────────────
 * Shared customer-search filter widget for list pages (Invoices,
 * Quotes, Estimates, Payments ledger). Reuses the shipped
 * ``<CustomerCombobox>`` under the hood and applies the role gate
 * per Item-2 spec.
 *
 * Behaviour:
 *   • Only renders for callers whose role ∈ {admin, super_admin,
 *     manager}. Everyone else sees nothing (existing list layout
 *     preserved verbatim).
 *   • Fetches customers via ``/customers?is_active=true`` on mount.
 *     Kept local (single-fire useEffect) — list pages don't already
 *     own a customer roster.
 *   • Renders a "Clear" chip when a filter is applied.
 *   • Parent owns URL persistence — passes ``value`` from the
 *     querystring and receives the new id via ``onChange``.
 *
 * Props
 * -----
 *   value      (string|null) — currently-selected customer id.
 *   onChange   (fn)          — called with the new customer id
 *                              (null = cleared).
 *   testId     (string)      — combobox trigger testid; the "Clear"
 *                              button becomes ``{testId}-clear``.
 *   label      (string?)     — small header shown above the picker.
 */
import React from "react";
import { X as XIcon } from "lucide-react";
import { useAuth } from "@/auth";
import { api } from "@/api";
import { colors } from "@/theme";
import CustomerCombobox from "@/components/customers/CustomerCombobox";


const _PRIVILEGED_ROLES = new Set(["admin", "super_admin", "manager"]);


export default function CustomerFilterBar({
  value,
  onChange,
  testId,
  label = "Customer",
}) {
  const { user } = useAuth();
  const role = String((user || {}).role || "").toLowerCase();
  const allowed = _PRIVILEGED_ROLES.has(role);

  const [customers, setCustomers] = React.useState([]);
  const [loading, setLoading] = React.useState(false);

  React.useEffect(() => {
    if (!allowed) return;
    let cancelled = false;
    setLoading(true);
    api.get("/customers?is_active=true")
      .then((rows) => {
        if (cancelled) return;
        setCustomers(Array.isArray(rows) ? rows : []);
      })
      .catch(() => { if (!cancelled) setCustomers([]); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [allowed]);

  if (!allowed) return null;

  return (
    <div className="flex items-center gap-2 flex-wrap"
         data-testid={`${testId}-bar`}>
      <div className="text-xs font-semibold" style={{ color: colors.muted }}>
        {label}
      </div>
      <div className="min-w-[220px]">
        <CustomerCombobox
          value={value || ""}
          onChange={(id) => onChange(id || null)}
          customers={customers}
          testid={testId}
          placeholder={loading ? "Loading customers…" : "All customers"}
          disabled={loading}
        />
      </div>
      {value ? (
        <button
          type="button"
          onClick={() => onChange(null)}
          className="inline-flex items-center gap-1 text-xs font-semibold px-2 py-1 rounded-full"
          style={{
            backgroundColor: "#DBEAFE",
            color: "#1E40AF",
            border: "1px solid #93C5FD",
          }}
          data-testid={`${testId}-clear`}
          aria-label="Clear customer filter"
        >
          Clear <XIcon size={11} />
        </button>
      ) : null}
    </div>
  );
}
