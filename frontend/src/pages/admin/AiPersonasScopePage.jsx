/**
 * Task RR Phase 2 · Feb 2026 — AI Employees data-scope + active
 * toggle admin page (revised scope · Task RR/SS Phase 2).
 *
 * What this page does
 * -------------------
 * Lists every persona (admin + customer audience) and exposes:
 *   • Row-level scope toggle — flip ``read_access_scope`` between
 *     ``customer_scoped`` (safe default) and ``tenant_all`` (grants
 *     the LLM tenant-wide data reads). Flipping UP to ``tenant_all``
 *     requires a confirmation modal AND super_admin role (backend-
 *     enforced 403 for non-super_admin).
 *   • Row-level active toggle — turn the persona on/off (any admin).
 *   • Bulk-select + bulk actions — bulk-activate, bulk-deactivate,
 *     bulk set-scope. Uses shared ``BulkSelectToolkit``.
 *   • Optimistic UI with revert-on-failure across all mutations.
 *
 * Skew column — deliberately omitted. The concept doesn't exist
 * server-side yet; an inline info banner explains the gap.
 *
 * API contract (unchanged from Phase 1):
 *   GET   /api/admin/ai-personas-scope
 *   PATCH /api/ai-employees/{eid}   {read_access_scope? , active?}
 */
import React, { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { ShieldCheck, Users, Info, Camera } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import {
  useBulkSelect,
  BulkSelectAll,
  BulkSelectRow,
  BulkActionBar,
  BulkConfirmModal,
} from "@/components/bulk-select/BulkSelectToolkit";
import PersonaAvatar from "@/components/personas/PersonaAvatar";
import PersonaAvatarUploadModal from "@/components/personas/PersonaAvatarUploadModal";

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
  // F2e · avatar upload modal target — null when closed.
  const [avatarTarget, setAvatarTarget] = useState(null);
  const [confirmFor, setConfirmFor] = useState(null);    // persona row awaiting scope-elevation confirm
  const [saving, setSaving] = useState(null);              // persona id currently mutating
  const [me, setMe] = useState(null);                        // current user (for super_admin gate)
  const [bulkConfirm, setBulkConfirm] = useState(null);    // {kind, targetIds, nextScope?, nextActive?}
  const [bulkBusy, setBulkBusy] = useState(false);

  const load = () => {
    setErr(null);
    api.get("/admin/ai-personas-scope")
      .then((r) => setItems(r?.items || []))
      .catch((e) => { setItems([]); setErr(e?.message || "Failed to load"); });
  };
  useEffect(() => {
    api.get("/auth/me").then(setMe).catch(() => setMe(null));
    load();
  }, []);

  const isSuperAdmin = (me?.role || "") === "super_admin";
  const visibleIds = useMemo(() => (items || []).map((r) => r.id), [items]);
  const bulk = useBulkSelect(visibleIds);

  /* ─── single-row mutations ─── */
  async function flipScope(row, nextScope) {
    setSaving(row.id);
    // Optimistic update.
    const prev = items;
    setItems((cur) => (cur || []).map(
      (r) => (r.id === row.id ? { ...r, read_access_scope: nextScope } : r),
    ));
    try {
      await api.patch(`/ai-employees/${row.id}`, { read_access_scope: nextScope });
      toast.success(`${row.name} · scope is now ${scopeLabel(nextScope)}`);
    } catch (e) {
      setItems(prev);        // revert
      const detail = e?.response?.data?.detail || e?.message || "Update failed";
      toast.error(detail);
    } finally {
      setSaving(null);
      setConfirmFor(null);
    }
  }

  async function flipActive(row, nextActive) {
    setSaving(row.id);
    const prev = items;
    setItems((cur) => (cur || []).map(
      (r) => (r.id === row.id ? { ...r, active: nextActive } : r),
    ));
    try {
      await api.patch(`/ai-employees/${row.id}`, { active: nextActive });
      toast.success(`${row.name} is now ${nextActive ? "active" : "off"}`);
    } catch (e) {
      setItems(prev);
      const detail = e?.response?.data?.detail || e?.message || "Update failed";
      toast.error(detail);
    } finally {
      setSaving(null);
    }
  }

  /* ─── bulk mutations ─── */
  async function runBulk({ kind, targetIds, nextScope, nextActive }) {
    setBulkBusy(true);
    const prev = items;
    // Optimistic bulk update.
    setItems((cur) => (cur || []).map((r) => {
      if (!targetIds.includes(r.id)) return r;
      if (kind === "scope") return { ...r, read_access_scope: nextScope };
      if (kind === "active") return { ...r, active: nextActive };
      return r;
    }));
    const patch = kind === "scope"
      ? { read_access_scope: nextScope }
      : { active: nextActive };
    const failures = [];
    // Sequential; the persona set is tiny (≤12 rows) so no need for parallel.
    for (const eid of targetIds) {
      try {
        await api.patch(`/ai-employees/${eid}`, patch);
      } catch (e) {
        failures.push({ id: eid, err: e?.response?.data?.detail || e?.message });
      }
    }
    setBulkBusy(false);
    setBulkConfirm(null);
    bulk.clear();
    if (failures.length === 0) {
      toast.success(`${targetIds.length} persona(s) updated`);
    } else {
      // Full revert on any failure — the bulk operation is not
      // atomic server-side, but from a UX standpoint we prefer
      // "all or nothing" so admins re-check what happened.
      setItems(prev);
      const firstErr = failures[0]?.err || "unknown";
      toast.error(
        `${failures.length}/${targetIds.length} update(s) failed — ${firstErr}`,
      );
    }
    load();      // authoritative refresh
  }

  const bulkActions = [
    {
      key: "activate",
      label: "Activate",
      tone: "primary",
      onClick: () => setBulkConfirm({
        kind: "active", targetIds: Array.from(bulk.selected), nextActive: true,
      }),
    },
    {
      key: "deactivate",
      label: "Deactivate",
      tone: "primary",
      onClick: () => setBulkConfirm({
        kind: "active", targetIds: Array.from(bulk.selected), nextActive: false,
      }),
    },
    {
      key: "set-scope",
      label: "Set scope",
      tone: "primary",
      dropdown: [
        { value: "customer_scoped", label: "Own customer only (safe)" },
        {
          value: "tenant_all",
          label: `Tenant-wide${!isSuperAdmin ? " · super_admin only" : ""}`,
        },
      ],
      onClick: (nextScope) => {
        if (nextScope === "tenant_all" && !isSuperAdmin) {
          toast.error("Only super_admin can grant tenant-wide access.");
          return;
        }
        setBulkConfirm({
          kind: "scope", targetIds: Array.from(bulk.selected), nextScope,
        });
      },
    },
  ];

  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-6"
          data-testid="ai-personas-scope-page">
      <div className="mb-5">
        <h1 className="text-2xl md:text-3xl font-bold"
            style={{ color: colors.onSurface }}>
          <ShieldCheck size={20} className="inline mr-2" />
          AI Employee data access + activation
        </h1>
        <p className="text-xs mt-1" style={{ color: colors.muted }}>
          Controls what customer data each AI Employee can read via the
          read-only tool registry. Default:&nbsp;
          <strong>Own customer only</strong> (safest).
          Flipping to <strong>Tenant-wide</strong> requires super_admin
          confirmation.
        </p>
      </div>

      {/* Skew-not-supported inline banner (Task RR/SS Phase 2 revised scope). */}
      <div className="rounded-2xl p-4 mb-4 text-sm flex items-start gap-2"
            style={{ backgroundColor: "#eff6ff",
                      border: "1px solid #bfdbfe",
                      color: "#1e40af" }}
            data-testid="ai-personas-skew-banner">
        <Info size={16} className="mt-0.5 flex-shrink-0" />
        <span>
          <strong>Per-persona skew is not yet supported server-side.</strong>{" "}
          Follow-up phase. This page controls scope + activation only.
        </span>
      </div>

      {err && (
        <div className="rounded-2xl p-4 mb-4 text-sm"
              style={{ backgroundColor: "#fef2f2",
                        border: "1px solid #fecaca",
                        color: "#991b1b" }}
              data-testid="ai-personas-error">
          {err}
        </div>
      )}

      <div className="rounded-2xl overflow-hidden"
            style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}>
        <div className="grid grid-cols-12 gap-2 px-4 py-3 text-xs uppercase tracking-wide items-center"
              style={{ backgroundColor: colors.surfaceSecondary,
                        color: colors.muted,
                        borderBottom: `1px solid ${colors.border}` }}>
          <div className="col-span-1">
            <BulkSelectAll
              checked={bulk.allVisibleSelected}
              indeterminate={bulk.indeterminate}
              onChange={bulk.toggleAll}
              label="Select all personas"
            />
          </div>
          <div className="col-span-3">Persona</div>
          <div className="col-span-2">Audience</div>
          <div className="col-span-3">Current scope</div>
          <div className="col-span-2">Active</div>
          <div className="col-span-1 text-right">Scope</div>
        </div>
        {items === null && (
          <div className="py-10 text-center text-sm"
                style={{ color: colors.muted }}
                data-testid="ai-personas-loading">
            Loading…
          </div>
        )}
        {items && items.length === 0 && (
          <div className="py-10 text-center text-sm"
                style={{ color: colors.muted }}
                data-testid="ai-personas-empty">
            No AI Employees seeded yet.
          </div>
        )}
        {(items || []).map((row) => {
          const scope = row.read_access_scope || "customer_scoped";
          const isActive = row.active !== false;
          const isChecked = bulk.selected.has(row.id);
          return (
            <div key={row.id}
                  data-testid={`ai-persona-row-${row.key}`}
                  className="grid grid-cols-12 gap-2 px-4 py-3 items-center text-sm"
                  style={{ borderBottom: `1px solid ${colors.border}`,
                            color: colors.onSurface }}>
              <div className="col-span-1">
                <BulkSelectRow id={row.id}
                                checked={isChecked}
                                onChange={() => bulk.toggleOne(row.id)}
                                label={`Select ${row.name}`} />
              </div>
              <div className="col-span-3 flex items-center gap-2">
                <div className="relative">
                  <PersonaAvatar persona={row} size={40} />
                  <button
                    type="button"
                    onClick={() => setAvatarTarget(row)}
                    title="Upload custom avatar"
                    aria-label={`Upload custom avatar for ${row.name}`}
                    data-testid={`persona-avatar-upload-${row.key}`}
                    className="absolute -bottom-1 -right-1 w-5 h-5 rounded-full flex items-center justify-center bg-white shadow border border-zinc-200 text-zinc-700 hover:bg-zinc-50"
                  >
                    <Camera size={10} />
                  </button>
                </div>
                <div>
                  <div className="font-semibold">{row.name}</div>
                  <div className="text-xs" style={{ color: colors.muted }}>
                    {row.role} · <code>{row.key}</code>
                  </div>
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
              <div className="col-span-2">
                <label className="inline-flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={isActive}
                    disabled={saving === row.id}
                    onChange={(e) => flipActive(row, e.target.checked)}
                    data-testid={`ai-persona-active-toggle-${row.key}`}
                    className="cursor-pointer"
                  />
                  <span className="text-xs" style={{ color: colors.muted }}>
                    {isActive ? "On" : "Off"}
                  </span>
                </label>
              </div>
              <div className="col-span-1 text-right">
                {scope === "customer_scoped" ? (
                  <button
                    onClick={() => {
                      if (!isSuperAdmin) {
                        toast.error("Only super_admin can grant tenant-wide access.");
                        return;
                      }
                      setConfirmFor(row);
                    }}
                    disabled={saving === row.id || !isSuperAdmin}
                    title={!isSuperAdmin ? "Only super_admin can grant tenant-wide access" : ""}
                    data-testid={`ai-persona-scope-toggle-btn-${row.key}`}
                    className="px-2.5 py-1 rounded-lg text-xs font-semibold hover:brightness-95 disabled:opacity-50 disabled:cursor-not-allowed"
                    style={{ backgroundColor: "#0284c7",
                              color: "#fff" }}>
                    Grant…
                  </button>
                ) : (
                  <button
                    onClick={() => flipScope(row, "customer_scoped")}
                    disabled={saving === row.id}
                    data-testid={`ai-persona-scope-toggle-btn-${row.key}`}
                    className="px-2.5 py-1 rounded-lg text-xs font-semibold hover:brightness-95 disabled:opacity-50"
                    style={{ backgroundColor: colors.surfaceSecondary,
                              border: `1px solid ${colors.border}`,
                              color: colors.onSurface }}>
                    Revert
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Bulk action bar (rendered by the shared toolkit — hides itself when 0 selected) */}
      <BulkActionBar
        selectedCount={bulk.selectedCount}
        actions={bulkActions}
        onClear={bulk.clear}
      />

      {/* Bulk confirm modal */}
      {bulkConfirm && (
        <BulkConfirmModal
          open={true}
          onClose={() => setBulkConfirm(null)}
          onConfirm={() => runBulk(bulkConfirm)}
          title={
            bulkConfirm.kind === "scope"
              ? `Set ${bulkConfirm.targetIds.length} persona(s) to ${scopeLabel(bulkConfirm.nextScope)}?`
              : `${bulkConfirm.nextActive ? "Activate" : "Deactivate"} ${bulkConfirm.targetIds.length} persona(s)?`
          }
          description={
            bulkConfirm.kind === "scope" && bulkConfirm.nextScope === "tenant_all"
              ? "Grants tenant-wide read access to every selected persona. Only super_admin can perform this — non-super_admin rows will 403."
              : "This affects all currently-selected personas."
          }
          confirmLabel={bulkBusy ? "Applying…" : "Confirm"}
          testidRoot="ai-personas-bulk-confirm"
          busy={bulkBusy}
        />
      )}

      {/* Single-row grant-tenant-wide confirm (kept from Phase 1) */}
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
              <button onClick={() => flipScope(confirmFor, "tenant_all")}
                       disabled={saving === confirmFor.id}
                       data-testid="ai-persona-scope-confirm-submit"
                       className="px-4 py-2 rounded-lg text-sm font-semibold text-white disabled:opacity-50"
                       style={{ backgroundColor: "#d97706" }}>
                Grant tenant-wide access
              </button>
            </div>
          </div>
        </div>
      )}
      {avatarTarget ? (
        <PersonaAvatarUploadModal
          persona={avatarTarget}
          onClose={() => setAvatarTarget(null)}
          onSaved={(next) => {
            // Optimistic patch of the visible row.
            setItems((prev) => (prev || []).map((r) =>
              r.key === next.key ? { ...r, avatar_url: next.avatar_url } : r,
            ));
          }}
        />
      ) : null}
    </div>
  );
}
