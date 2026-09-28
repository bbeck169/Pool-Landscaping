/**
 * MTH-B · Feb-2026 — Override diff panel.
 *
 * Given a category, the ``override_map`` from the backend, the
 * tenant's resolved value, and the platform-default value,
 * renders a per-field diff that expands from an "N overrides"
 * pill click.
 *
 * Design fork (see MTH-B report): the MTH-A backend only exposes
 * whole-category reset (``POST /api/tenant-ai-rules/reset/{category}``),
 * so per-field "↺ Reset this field" would need a new backend
 * endpoint to implement.  We surface a whole-category reset
 * shortcut in the diff panel instead, and label it explicitly so
 * the intent is unambiguous.  The individual card footer already
 * has the full "Reset to Platform Default" button — this panel's
 * shortcut is a duplicate for convenience when the operator is
 * already looking at the diff.
 */
import React, { useState } from "react";
import { toast } from "sonner";
import { ChevronDown, ChevronUp, RotateCcw } from "lucide-react";
import { api } from "@/api";
import { Button } from "@/components/ui-kit";
import RulesReasonModal from "./RulesReasonModal";

function formatValue(v) {
  if (v === null || v === undefined) return "—";
  if (typeof v === "boolean") return v ? "true" : "false";
  if (typeof v === "string") return v.length ? v : "(empty)";
  if (typeof v === "number") return String(v);
  try {
    return JSON.stringify(v, null, 2);
  } catch {
    return String(v);
  }
}

function collectOverrides(category, overrideMap, tenantValue, platformValue) {
  const out = [];
  if (!overrideMap) return out;
  const prefix = `${category}.`;
  // Sub-field overrides.
  Object.entries(overrideMap).forEach(([key, source]) => {
    if (source !== "tenant") return;
    if (!key.startsWith(prefix)) return;
    const sub = key.slice(prefix.length);
    if (!sub) return;
    const tv =
      tenantValue && typeof tenantValue === "object" ? tenantValue[sub] : undefined;
    const pv =
      platformValue && typeof platformValue === "object" ? platformValue[sub] : undefined;
    out.push({ subField: sub, tenantValue: tv, platformValue: pv });
  });
  // Whole-category atomic override (e.g. escalation_rules).
  if (overrideMap[category] === "tenant") {
    out.push({
      subField: "(whole category)",
      tenantValue,
      platformValue,
    });
  }
  return out;
}

export default function OverrideDiff({
  category,
  overrideMap,
  tenantValue,
  platformValue,
  onReset,
  testid = "ai-rules-override-diff",
  readOnly = false,
}) {
  const rows = collectOverrides(
    category,
    overrideMap,
    tenantValue,
    platformValue,
  );
  const [expanded, setExpanded] = useState(false);
  const [resetOpen, setResetOpen] = useState(false);

  if (rows.length === 0) return null;

  const doReset = async (reason) => {
    try {
      await api.post(`/tenant-ai-rules/reset/${category}`, { reason });
      toast.success(`Reset ${category} to platform default.`);
      setResetOpen(false);
      if (onReset) await onReset();
    } catch (e) {
      toast.error(
        `Reset failed: ${e?.data?.detail?.message || e?.message || "unknown"}`,
      );
    }
  };

  return (
    <div className="rounded-lg border" style={{ borderColor: "#E2E8F0" }}>
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center justify-between px-3 py-2 text-xs font-semibold"
        style={{ color: "#334155", background: "#F8FAFC" }}
        data-testid={`${testid}-toggle`}
      >
        <span>
          {rows.length} tenant override{rows.length === 1 ? "" : "s"} in this
          category
        </span>
        {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
      </button>
      {expanded ? (
        <div
          className="p-3 space-y-2 text-xs"
          data-testid={`${testid}-panel`}
        >
          {rows.map((r) => (
            <div
              key={r.subField}
              className="rounded-md border p-2"
              style={{ borderColor: "#E2E8F0", background: "#FEF3C7" }}
              data-testid={`${testid}-row-${r.subField.replace(/[^\w-]/g, "_")}`}
            >
              <div className="font-semibold mb-1" style={{ color: "#92400E" }}>
                {r.subField}
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <div className="text-[10px] font-semibold opacity-60 tracking-wide">
                    PLATFORM DEFAULT
                  </div>
                  <pre className="whitespace-pre-wrap break-words text-[11px] bg-white/60 rounded p-1 mt-0.5">
                    {formatValue(r.platformValue)}
                  </pre>
                </div>
                <div>
                  <div
                    className="text-[10px] font-semibold opacity-60 tracking-wide"
                    style={{ color: "#166534" }}
                  >
                    TENANT VALUE
                  </div>
                  <pre className="whitespace-pre-wrap break-words text-[11px] bg-white rounded p-1 mt-0.5">
                    {formatValue(r.tenantValue)}
                  </pre>
                </div>
              </div>
            </div>
          ))}

          <div className="pt-1 flex items-center justify-end">
            <Button
              variant="ghost"
              onClick={() => setResetOpen(true)}
              disabled={readOnly}
              testid={`${testid}-reset-category`}
              className="text-xs"
            >
              <RotateCcw size={12} />
              Reset entire category
            </Button>
          </div>
          <div
            className="text-[11px] opacity-60"
            data-testid={`${testid}-per-field-note`}
          >
            Per-field revert is not yet supported by the backend — resetting a
            single field routes through a whole-category reset.
          </div>
        </div>
      ) : null}

      <RulesReasonModal
        open={resetOpen}
        onClose={() => setResetOpen(false)}
        title={`Reset "${category}" to platform default`}
        description="This clears every tenant-level override in this category and falls back to the platform-wide settings."
        onConfirm={doReset}
        confirmLabel="Reset Category"
        confirmVariant="danger"
        testidPrefix={`${testid}-reset-reason`}
      />
    </div>
  );
}

export { collectOverrides };
