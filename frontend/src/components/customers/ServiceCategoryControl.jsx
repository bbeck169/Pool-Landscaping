/**
 * P2 #6 · Feb-2026 · ServiceCategoryControl
 *
 * Admin-only compact dropdown rendered on the CustomerDetail
 * identity header.  Mirrors the sibling ActivationControl / VIP
 * toggle UX: inline control, optimistic update + revert on error,
 * toast on success / failure.
 *
 * PATCHes ``/customers/{cid}/service-category`` with the new value
 * (``null`` for "Not set").  The backend emits
 * ``customer.service_category_changed`` audit log row on every
 * transition — see routers/customers.py::patch_customer_service_category.
 */
import React, { useState } from "react";
import { toast } from "sonner";
import { api } from "@/api";
import { useAuth } from "@/auth";


const _OPTIONS = [
  { value: "", label: "Not set" },
  { value: "pool", label: "Pool" },
  { value: "landscaping", label: "Landscaping" },
  { value: "both", label: "Both" },
];


export function ServiceCategoryControl({ customer, onOptimisticSet }) {
  const { user } = useAuth() || {};
  const isAdmin = ["admin", "super_admin"].includes(user?.role);
  const [saving, setSaving] = useState(false);
  // Current value for the <select>.  Empty string sentinel → "Not set".
  const current = (customer?.service_category || "");

  if (!isAdmin || !customer?.id) return null;

  const handleChange = async (e) => {
    const next = e.target.value || null;
    const prev = customer.service_category || null;
    if (next === prev) return;
    onOptimisticSet?.(next);
    setSaving(true);
    try {
      await api.patch(
        `/customers/${customer.id}/service-category`,
        { service_category: next },
      );
      toast.success(
        next ? `Service category set to ${next}` : "Service category cleared",
      );
    } catch (err) {
      onOptimisticSet?.(prev);
      toast.error("Failed to update service category");
    } finally {
      setSaving(false);
    }
  };

  return (
    <label
      className="inline-flex items-center gap-1.5 px-2 py-1 rounded-full text-xs font-semibold uppercase tracking-wider"
      style={{
        backgroundColor: current ? "#DBEAFE" : "#1E293B",
        color: current ? "#1E3A8A" : "#CBD5E1",
        border: `1px solid ${current ? "#60A5FA" : "#334155"}`,
      }}
      data-testid="customer-service-category-control"
    >
      <span className="opacity-80">Category:</span>
      <select
        value={current}
        onChange={handleChange}
        disabled={saving}
        data-testid="customer-service-category-select"
        className="bg-transparent border-0 text-xs font-semibold uppercase tracking-wider focus:outline-none"
        style={{ color: "inherit" }}
      >
        {_OPTIONS.map((o) => (
          <option
            key={o.value || "unset"}
            value={o.value}
            style={{ color: "#0F172A", background: "#FFFFFF" }}
          >
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}

export default ServiceCategoryControl;
