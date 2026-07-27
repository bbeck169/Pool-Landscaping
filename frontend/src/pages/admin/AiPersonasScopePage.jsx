/**
 * Task RR Phase 2 · Feb 2026 — AI Employees read_access_scope toggle.
 *
 * Lists every persona (admin + customer audience) and lets a
 * super_admin flip ``read_access_scope`` between
 * ``customer_scoped`` (safe default) and ``tenant_all`` (grants
 * the LLM tenant-wide data reads). Flipping UP to ``tenant_all``
 * requires a confirmation modal that spells out the consequences.
 * Flipping DOWN to ``customer_scoped`` is one click, no confirm.
 *
 * Backend gate: PATCH ``/ai-employees/{eid}`` refuses to set
 * ``tenant_all`` unless the caller is super_admin (Task RR).
 *
 * API:
 *   GET  /api/admin/ai-personas-scope
 *   PATCH /api/ai-employees/{eid}   {read_access_scope}
 */
import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { ShieldCheck, Users } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

function scopeLabel(scope) {
  return scope === "tenant_all" ? "Tenant-wide" : "Own customer only";
}
function scopeClass(scope) {
  return scope === "tenant_all"
    ? "text-amber-800 bg-amber-50 border-amber-200"
    : "text-emerald-700 bg-emerald-50 border-emerald-200";
}

export default function AiPersonasScopePage() {
  const [items, setItems] = useState(null);
  const [err, setErr] = useState(null);
  const [confirmFor, setConfirmFor] = useState(null);    // persona row awaiting confirm
  const [saving, setSaving] = useState(null);              // persona id currently mutating

  const load = () => {
    setErr(null);
    api.get("/admin/ai-personas-scope")
      .then((r) => setItems(r?.items || []))
      .catch((e) => { setItems([]); setErr(e?.message || "Failed to load"); });
  };
  useEffect(load, []);

  async function flip(row, nextScope) {
    setSaving(row.id);
    try {
      await api.patch(`/ai-employees/${row.id}`, { read_access_scope: nextScope });
      toast.success(`${row.name} · scope is now ${scopeLabel(nextScope)}`);
      load();
    } catch (e) {
      const detail = e?.response?.data?.detail || e?.message || "Update failed";
      toast.error(detail);
    } finally {
      setSaving(null);
      setConfirmFor(null);
    }
  }

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-6"
          data-testid="ai-personas-scope-page">
      <div className="mb-5">
        <h1 className="text-2xl md:text-3xl font-bold"
            style={{ color: colors.onSurface }}>
          <ShieldCheck size={20} className="inline mr-2" />
          AI Employee data access scope
        </h1>
        <p className="text-xs mt-1" style={{ color: colors.muted }}>
          Controls what customer data each AI Employee can read via the
          read-only tool registry. Default:&nbsp;
          <strong>Own customer only</strong> (safest).
          Flipping to <strong>Tenant-wide</strong> requires super_admin
          confirmation.
        </p>
      </div>

      {err && (
        <div className="rounded-2xl p-4 mb-4 text-sm"
              style={{ backgroundColor: "#fef2f2",
                        border: "1px solid #fecaca",
                        color: "#991b1b" }}>
          {err}
        </div>
      )}

      <div className="rounded-2xl overflow-hidden"
            style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}>
        <div className="grid grid-cols-12 gap-2 px-4 py-3 text-xs uppercase tracking-wide"
              style={{ backgroundColor: colors.surfaceSecondary,
                        color: colors.muted,
                        borderBottom: `1px solid ${colors.border}` }}>
          <div className="col-span-1">Icon</div>
          <div className="col-span-3">Persona</div>
          <div className="col-span-2">Audience</div>
          <div className="col-span-3">Current scope</div>
          <div className="col-span-3">Action</div>
        </div>
        {items === null && (
          <div className="py-10 text-center text-sm"
                style={{ color: colors.muted }}>
            Loading…
          </div>
        )}
        {items && items.length === 0 && (
          <div className="py-10 text-center text-sm"
                style={{ color: colors.muted }}>
            No AI Employees seeded yet.
          </div>
        )}
        {(items || []).map((row) => {
          const scope = row.read_access_scope || "customer_scoped";
          return (
            <div key={row.id}
                  data-testid={`ai-persona-row-${row.key}`}
                  className="grid grid-cols-12 gap-2 px-4 py-3 items-center text-sm"
                  style={{ borderBottom: `1px solid ${colors.border}`,
                            color: colors.onSurface }}>
              <div className="col-span-1 text-2xl">{row.avatar_emoji || "🤖"}</div>
              <div className="col-span-3">
                <div className="font-semibold">{row.name}</div>
                <div className="text-xs" style={{ color: colors.muted }}>
                  {row.role} · <code>{row.key}</code>
                </div>
              </div>
              <div className="col-span-2 text-xs" style={{ color: colors.muted }}>
                <Users size={12} className="inline mr-1" />
                {row.audience === "customer" ? "Customer-facing" : "Internal"}
              </div>
              <div className="col-span-3"
                    data-testid={`ai-persona-scope-${row.key}`}>
                <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs border ${scopeClass(scope)}`}>
                  {scopeLabel(scope)}
                </span>
              </div>
              <div className="col-span-3">
                {scope === "customer_scoped" ? (
                  <button
                    onClick={() => setConfirmFor(row)}
                    disabled={saving === row.id}
                    data-testid={`ai-persona-scope-toggle-btn-${row.key}`}
                    className="px-3 py-1.5 rounded-lg text-xs font-semibold hover:brightness-95"
                    style={{ backgroundColor: "#0284c7",
                              color: "#fff" }}>
                    Grant tenant-wide…
                  </button>
                ) : (
                  <button
                    onClick={() => flip(row, "customer_scoped")}
                    disabled={saving === row.id}
                    data-testid={`ai-persona-scope-toggle-btn-${row.key}`}
                    className="px-3 py-1.5 rounded-lg text-xs font-semibold hover:brightness-95"
                    style={{ backgroundColor: colors.surfaceSecondary,
                              border: `1px solid ${colors.border}`,
                              color: colors.onSurface }}>
                    Revert to own-customer
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {confirmFor && (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4"
              data-testid="ai-persona-scope-confirm-modal">
          <div className="max-w-md w-full rounded-2xl p-6"
                style={{ backgroundColor: colors.surface }}>
            <h2 className="text-lg font-bold mb-2"
                style={{ color: colors.onSurface }}>
              Grant {confirmFor.name} full-tenant read access?
            </h2>
            <p className="text-sm mb-4" style={{ color: colors.muted }}>
              This lets the persona see <strong>all customers'</strong>{" "}
              invoices, schedules, and billing data via read-only tool
              calls. It cannot write / mutate anything, but the LLM's
              responses will be able to reference other customers.
              Confirm your action.
            </p>
            <p className="text-xs mb-4" style={{ color: colors.muted }}>
              Only super_admin can perform this action. Regular admins
              will see a 403 from the backend.
            </p>
            <div className="flex items-center justify-end gap-2">
              <button onClick={() => setConfirmFor(null)}
                       className="px-4 py-2 rounded-lg text-sm"
                       style={{ color: colors.onSurface }}>
                Cancel
              </button>
              <button onClick={() => flip(confirmFor, "tenant_all")}
                       disabled={saving === confirmFor.id}
                       data-testid="ai-persona-scope-confirm-submit"
                       className="px-4 py-2 rounded-lg text-sm font-semibold text-white"
                       style={{ backgroundColor: "#d97706" }}>
                Grant tenant-wide access
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
