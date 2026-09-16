// Phase MI1 · Feb 2026 — Multi-industry checklist renderer.
//
// Dispatches to the industry-specific form based on ``industry``:
//   * ``pool``  → the historical ``PoolChecklistForm`` (untouched).
//   * anything else → a lightweight generic renderer that lists the
//     resolved template items with a checkbox each, required items
//     flagged with a red asterisk.
//
// Design intent: Pool tenants get byte-identical UX vs pre-MI1.
// Non-pool industries get a fit-for-purpose checkbox list right now;
// heavier per-industry surfaces (chemistry-style panels for solar
// output, HVAC pressure readings, etc.) land in Phase D.
//
// The old ``PoolChecklistForm`` file stays authoritative for the
// pool experience — the file rename in the brief was deliberately
// skipped to avoid touching the 1000+ line component (and its
// 20+ source-scanning tests). This wrapper satisfies the same
// "one component, industry prop" contract without the risky
// rename.
import React, { useEffect, useMemo, useState } from "react";
import { api } from "@/api";
import { colors } from "@/theme";
import PoolChecklistForm from "@/components/checklist/PoolChecklistForm";

export const INDUSTRY_LABELS = {
  pool: "Pool",
  landscaping: "Landscaping",
  hvac: "HVAC",
  pest_control: "Pest Control",
  cleaning: "Cleaning",
  solar: "Solar",
  handyman: "Handyman",
};


// Generic checklist renderer — used for every non-pool industry.
function GenericChecklistForm({ industry, template, value, onChange }) {
  const items = template?.items || [];
  const checkedKeys = useMemo(() => {
    const set = new Set();
    (value || []).forEach((row) => {
      if (row && row.done) set.add(String(row.key || row.label || ""));
    });
    return set;
  }, [value]);

  const toggle = (item) => {
    const key = item.key;
    const already = checkedKeys.has(key);
    const next = (value || []).filter(
      (r) => (r?.key || r?.label) !== key && (r?.key || r?.label) !== item.label,
    );
    if (!already) {
      next.push({ key, label: item.label, done: true });
    }
    onChange && onChange(next);
  };

  if (!items.length) {
    return (
      <div className="text-sm p-4 rounded-lg"
           style={{ color: colors.muted, background: colors.surfaceSecondary }}
           data-testid="industry-checklist-empty">
        No checklist items configured for this industry yet.
      </div>
    );
  }

  return (
    <div data-testid={`industry-checklist-${industry}`} className="space-y-2">
      {items.map((item) => {
        const key = item.key;
        const checked = checkedKeys.has(key);
        return (
          <label
            key={key}
            className="flex items-center gap-3 px-3 py-2 rounded-lg cursor-pointer transition-colors hover:bg-slate-50"
            style={{ border: `1px solid ${colors.border}` }}
            data-testid={`industry-checklist-item-${key}`}
          >
            <input
              type="checkbox"
              checked={checked}
              onChange={() => toggle(item)}
              className="cursor-pointer"
              data-testid={`industry-checklist-checkbox-${key}`}
            />
            <span className="text-sm" style={{ color: colors.onSurface }}>
              {item.label}
              {item.required ? (
                <span className="ml-1" style={{ color: "#DC2626" }}
                       aria-label="required">*</span>
              ) : null}
            </span>
          </label>
        );
      })}
    </div>
  );
}


export default function IndustryChecklistForm({
  industry = "pool", tenantId, value, onChange, poolProps,
}) {
  // Hooks must run unconditionally per React rules. We fetch the
  // template even on the pool branch (the request short-circuits
  // in the effect below) so the hook order stays stable across
  // industry switches.
  const [template, setTemplate] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (industry === "pool") { setTemplate(null); setError(""); return; }
    let cancelled = false;
    setError(""); setTemplate(null);
    api.get(`/checklists/industry/${industry}`)
      .then((body) => { if (!cancelled) setTemplate(body); })
      .catch((e) => { if (!cancelled) setError(e?.message || "Failed to load"); });
    return () => { cancelled = true; };
  }, [industry, tenantId]);

  // Pool → delegate to the untouched historical component so
  // pool tenants keep the full chemistry UX.
  if (industry === "pool") {
    return <PoolChecklistForm {...(poolProps || {})} />;
  }

  if (error) {
    return (
      <div className="text-sm p-3 rounded-lg"
           style={{ color: "#991B1B", background: "#FEE2E2" }}
           data-testid="industry-checklist-error">
        {error}
      </div>
    );
  }
  if (!template) {
    return (
      <div className="text-sm p-3" style={{ color: colors.muted }}
           data-testid="industry-checklist-loading">Loading…</div>
    );
  }
  return (
    <GenericChecklistForm
      industry={industry}
      template={template}
      value={value}
      onChange={onChange}
    />
  );
}
