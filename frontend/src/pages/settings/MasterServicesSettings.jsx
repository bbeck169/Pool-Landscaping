/**
 * Phase P16 · Feb-2026 — Master Services Settings page.
 *
 * Admin surface for the pricebook of "services the business
 * offers" — a flat list of (name, category, default_price)
 * triplets consumed by the Add Recurring Job combobox and (in
 * P16.1) by the Job / Estimate / Invoice line-item editors.
 *
 * Behaviour matrix:
 *   • List always shows active + inactive counts (backend
 *     aggregate); the toggle only affects the visible rows.
 *   • Admin      → full CRUD; Delete opens a two-mode dialog
 *     (Soft-Delete / Permanent Delete, latter needs "DELETE"
 *     typed).
 *   • Manager    → Create / Edit enabled; Delete button
 *     disabled with a tooltip "Admin only" (backend also 403s
 *     managers on DELETE, defence in depth).
 *   • Technician → route already gated at the router level;
 *     unreachable here.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Plus, Pencil, Trash2, X, Search } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api";
import { colors } from "@/theme";
import { usePermissions } from "@/hooks/usePermissions";
import { invalidateMasterServicesCache } from "@/components/services/MasterServiceCombobox";


function fmtMoney(n) {
  const v = Number(n || 0);
  return `$${v.toFixed(2)}`;
}


function ServiceModal({ initial, categories, onClose, onSaved }) {
  const editing = Boolean(initial?.id);
  const [name, setName] = useState(initial?.name || "");
  const [defaultPrice, setDefaultPrice] = useState(
    initial && Number.isFinite(initial.default_price)
      ? String(initial.default_price) : "",
  );
  const [category, setCategory] = useState(initial?.category || "");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const save = useCallback(async () => {
    setErr("");
    const trimmed = (name || "").trim();
    if (!trimmed) { setErr("Name is required."); return; }
    if (!category) { setErr("Category is required."); return; }
    const priceN = Number(defaultPrice);
    if (defaultPrice !== "" && (!Number.isFinite(priceN) || priceN < 0)) {
      setErr("Default price must be a non-negative number.");
      return;
    }
    const payload = {
      name: trimmed,
      default_price: defaultPrice === "" ? 0 : priceN,
      category,
    };
    setBusy(true);
    try {
      const res = editing
        ? await api.patch(`/master-services/${initial.id}`, payload)
        : await api.post("/master-services", payload);
      invalidateMasterServicesCache();
      onSaved?.(res);
    } catch (e) {
      const code = e?.data?.detail?.error || e?.data?.error;
      if (code === "duplicate_name") {
        setErr("A master service with that name already exists.");
      } else if (code === "category_invalid") {
        setErr("Category is not valid for this tenant.");
      } else if (code === "category_required") {
        setErr("Category is required.");
      } else {
        setErr(e?.message || "Save failed.");
      }
    } finally { setBusy(false); }
  }, [name, defaultPrice, category, editing, initial, onSaved]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: "rgba(0,0,0,0.55)" }}
      onClick={onClose}
      data-testid="master-service-modal-backdrop"
    >
      <div
        className="w-full max-w-md rounded-2xl overflow-hidden shadow-2xl"
        style={{ background: colors.surface }}
        onClick={(e) => e.stopPropagation()}
        data-testid="master-service-modal"
      >
        <header
          className="px-5 py-3 flex items-center justify-between"
          style={{ borderBottom: `1px solid ${colors.border}` }}
        >
          <div className="text-base font-bold"
                style={{ color: colors.onSurface }}>
            {editing ? "Edit master service" : "New master service"}
          </div>
          <button onClick={onClose}
                    style={{ color: colors.muted }}
                    data-testid="master-service-modal-close">
            <X size={18} />
          </button>
        </header>
        <div className="px-5 py-4 space-y-3">
          <div>
            <label className="text-xs uppercase font-semibold block mb-1"
                    style={{ color: colors.muted }}>Name *</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoFocus
              className="w-full px-3 py-2 text-sm rounded-lg"
              style={{ background: colors.surface,
                        border: `1px solid ${colors.border}`,
                        color: colors.onSurface }}
              data-testid="master-service-modal-name"
            />
          </div>
          <div>
            <label className="text-xs uppercase font-semibold block mb-1"
                    style={{ color: colors.muted }}>Default Price</label>
            <input
              type="number"
              min="0"
              step="0.01"
              value={defaultPrice}
              onChange={(e) => setDefaultPrice(e.target.value)}
              placeholder="0.00"
              className="w-full px-3 py-2 text-sm rounded-lg"
              style={{ background: colors.surface,
                        border: `1px solid ${colors.border}`,
                        color: colors.onSurface }}
              data-testid="master-service-modal-price"
            />
          </div>
          <div>
            <label className="text-xs uppercase font-semibold block mb-1"
                    style={{ color: colors.muted }}>Category *</label>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="w-full px-3 py-2 text-sm rounded-lg"
              style={{ background: colors.surface,
                        border: `1px solid ${colors.border}`,
                        color: colors.onSurface }}
              data-testid="master-service-modal-category"
            >
              <option value="">— Select category —</option>
              {categories.map((c) => (
                <option key={c.name} value={c.name}>{c.name}</option>
              ))}
            </select>
          </div>
          {err ? (
            <div
              className="text-xs px-2 py-1 rounded"
              style={{ background: "#FEE2E2", color: "#7F1D1D" }}
              data-testid="master-service-modal-error"
            >{err}</div>
          ) : null}
        </div>
        <footer
          className="px-5 py-3 flex items-center justify-end gap-2"
          style={{ borderTop: `1px solid ${colors.border}` }}
        >
          <button
            onClick={onClose}
            disabled={busy}
            className="px-3 py-1.5 text-sm rounded-lg"
            style={{ background: colors.surfaceSecondary,
                      color: colors.onSurface,
                      border: `1px solid ${colors.border}` }}
            data-testid="master-service-modal-cancel"
          >Cancel</button>
          <button
            onClick={save}
            disabled={busy}
            className="px-3 py-1.5 text-sm rounded-lg font-semibold disabled:opacity-60"
            style={{ background: colors.brand, color: "#FFFFFF" }}
            data-testid="master-service-modal-save"
          >{busy ? "Saving…" : (editing ? "Save" : "Add service")}</button>
        </footer>
      </div>
    </div>
  );
}


function DeleteDialog({ target, onClose, onDone }) {
  const [mode, setMode] = useState("soft"); // "soft" | "hard"
  const [confirmInput, setConfirmInput] = useState("");
  const [busy, setBusy] = useState(false);

  const canHardConfirm = confirmInput.trim() === "DELETE";

  const runSoft = useCallback(async () => {
    setBusy(true);
    try {
      await api.del(`/master-services/${target.id}`);
      invalidateMasterServicesCache();
      toast.success(`${target.name} deactivated.`);
      onDone?.();
    } catch (e) {
      toast.error(e?.message || "Delete failed.");
    } finally { setBusy(false); }
  }, [target, onDone]);

  const runHard = useCallback(async () => {
    if (!canHardConfirm) return;
    setBusy(true);
    try {
      await api.del(`/master-services/${target.id}?hard=true`,
                     { confirm: "DELETE" });
      invalidateMasterServicesCache();
      toast.success(`${target.name} permanently deleted.`);
      onDone?.();
    } catch (e) {
      toast.error(e?.message || "Delete failed.");
    } finally { setBusy(false); }
  }, [target, canHardConfirm, onDone]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: "rgba(0,0,0,0.55)" }}
      onClick={onClose}
      data-testid="master-service-delete-modal-backdrop"
    >
      <div
        className="w-full max-w-lg rounded-2xl overflow-hidden shadow-2xl"
        style={{ background: colors.surface }}
        onClick={(e) => e.stopPropagation()}
        data-testid="master-service-delete-modal"
      >
        <header
          className="px-5 py-3 flex items-center justify-between"
          style={{ borderBottom: `1px solid ${colors.border}` }}
        >
          <div className="text-base font-bold"
                style={{ color: colors.onSurface }}>
            Delete master service
          </div>
          <button onClick={onClose}
                    style={{ color: colors.muted }}
                    data-testid="master-service-delete-modal-close">
            <X size={18} />
          </button>
        </header>
        <div className="px-5 py-4 space-y-3 text-sm"
              style={{ color: colors.onSurface }}>
          <p>
            This will hide <strong>{target.name}</strong> from the
            service picker. Recurring jobs referencing it keep their
            price. To permanently remove it and clear audit-log-visible
            traces, choose <em>Permanent Delete</em>.
          </p>
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-1.5 text-xs">
              <input
                type="radio"
                name="delMode"
                checked={mode === "soft"}
                onChange={() => setMode("soft")}
                data-testid="master-service-delete-mode-soft"
              />
              Soft-Delete (deactivate)
            </label>
            <label className="flex items-center gap-1.5 text-xs">
              <input
                type="radio"
                name="delMode"
                checked={mode === "hard"}
                onChange={() => setMode("hard")}
                data-testid="master-service-delete-mode-hard"
              />
              Permanent Delete
            </label>
          </div>
          {mode === "hard" ? (
            <div>
              <label className="text-xs uppercase font-semibold block mb-1"
                      style={{ color: colors.muted }}>
                Type DELETE to confirm
              </label>
              <input
                type="text"
                value={confirmInput}
                onChange={(e) => setConfirmInput(e.target.value)}
                className="w-full px-3 py-2 text-sm rounded-lg"
                style={{ background: colors.surface,
                          border: `1px solid ${colors.border}`,
                          color: colors.onSurface }}
                data-testid="master-service-delete-modal-confirm-input"
              />
            </div>
          ) : null}
        </div>
        <footer
          className="px-5 py-3 flex items-center justify-end gap-2"
          style={{ borderTop: `1px solid ${colors.border}` }}
        >
          <button
            onClick={onClose}
            disabled={busy}
            className="px-3 py-1.5 text-sm rounded-lg"
            style={{ background: colors.surfaceSecondary,
                      color: colors.onSurface,
                      border: `1px solid ${colors.border}` }}
            data-testid="master-service-delete-modal-cancel"
          >Cancel</button>
          {mode === "soft" ? (
            <button
              onClick={runSoft}
              disabled={busy}
              className="px-3 py-1.5 text-sm rounded-lg font-semibold disabled:opacity-60"
              style={{ background: "#B45309", color: "#FFFFFF" }}
              data-testid="master-service-delete-modal-soft-btn"
            >Soft-Delete</button>
          ) : (
            <button
              onClick={runHard}
              disabled={busy || !canHardConfirm}
              className="px-3 py-1.5 text-sm rounded-lg font-semibold disabled:opacity-60"
              style={{ background: colors.error, color: "#FFFFFF" }}
              data-testid="master-service-delete-modal-hard-btn"
            >Permanently Delete</button>
          )}
        </footer>
      </div>
    </div>
  );
}


export default function MasterServicesSettings() {
  const { role, effectiveRole } = usePermissions();
  const actingRole = String(effectiveRole || role || "").toLowerCase();
  const canHardDelete = actingRole === "admin" || actingRole === "super_admin"
    || actingRole === "owner";

  const [items, setItems] = useState([]);
  const [counts, setCounts] = useState({ active: 0, inactive: 0, total: 0 });
  const [categories, setCategories] = useState([]);
  const [showInactive, setShowInactive] = useState(false);
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  const [editing, setEditing] = useState(null);
  const [deleting, setDeleting] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(search.trim()), 250);
    return () => clearTimeout(t);
  }, [search]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const qs = new URLSearchParams();
      if (showInactive) qs.set("include_inactive", "true");
      if (debounced) qs.set("q", debounced);
      const url = `/master-services${qs.toString() ? `?${qs.toString()}` : ""}`;
      const res = await api.get(url);
      setItems(Array.isArray(res?.items) ? res.items : []);
      if (res?.counts && typeof res.counts === "object") {
        setCounts({
          active: Number(res.counts.active || 0),
          inactive: Number(res.counts.inactive || 0),
          total: Number(res.counts.total || 0),
        });
      }
    } catch (e) {
      toast.error(e?.message || "Failed to load master services.");
    } finally { setLoading(false); }
  }, [showInactive, debounced]);

  const loadCategories = useCallback(async () => {
    try {
      const res = await api.get("/master-services/categories");
      setCategories(Array.isArray(res?.items) ? res.items : []);
    } catch { setCategories([]); }
  }, []);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { loadCategories(); }, [loadCategories]);

  const openNew = useCallback(() => setEditing({}), []);
  const openEdit = useCallback((row) => setEditing(row), []);

  const filteredItems = useMemo(() => items, [items]);

  return (
    <div className="max-w-5xl mx-auto p-4"
          data-testid="master-services-settings-page">
      <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
        <div>
          <h1 className="text-2xl font-black"
              style={{ color: colors.onSurface }}>
            Master Services
          </h1>
          <p className="text-sm mt-0.5" style={{ color: colors.muted }}>
            The catalog of services your business offers. Powers the
            searchable "Service" picker on Recurring Jobs.
          </p>
        </div>
        <button
          onClick={openNew}
          className="inline-flex items-center gap-2 px-3 py-2 text-sm font-semibold rounded-lg"
          style={{ background: colors.brand, color: "#FFFFFF" }}
          data-testid="master-services-add-btn"
        >
          <Plus size={14} />
          Add Service
        </button>
      </div>

      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <div className="relative w-full max-w-sm">
          <Search
            size={14}
            className="absolute left-2.5 top-1/2 -translate-y-1/2 pointer-events-none"
            style={{ color: colors.searchIcon }}
          />
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search services…"
            aria-label="Search master services"
            className="w-full text-sm rounded-md py-1.5 pl-8 pr-3"
            style={{ background: colors.surface,
                      color: colors.onSurface,
                      border: `1px solid ${colors.border}` }}
            data-testid="master-services-search"
          />
        </div>
        <div className="flex items-center gap-3">
          <div className="text-xs" style={{ color: colors.muted }}>
            <span data-testid="master-services-count-active">
              Active: {counts.active}
            </span>{" · "}
            <span data-testid="master-services-count-inactive">
              Inactive: {counts.inactive}
            </span>
          </div>
          <label className="flex items-center gap-1.5 text-xs"
                  style={{ color: colors.muted }}>
            <input
              type="checkbox"
              checked={showInactive}
              onChange={(e) => setShowInactive(e.target.checked)}
              data-testid="master-services-show-inactive"
            />
            Show inactive
          </label>
        </div>
      </div>

      <div className="rounded-2xl overflow-hidden"
            style={{ background: colors.surface,
                      border: `1px solid ${colors.border}` }}>
        <table className="w-full text-sm"
                data-testid="master-services-table">
          <thead style={{ background: colors.surfaceSecondary }}>
            <tr>
              <th className="text-left px-3 py-2 font-semibold">Name</th>
              <th className="text-left px-3 py-2 font-semibold">Category</th>
              <th className="text-right px-3 py-2 font-semibold">Default Price</th>
              <th className="text-center px-3 py-2 font-semibold">Status</th>
              <th className="w-28 px-3 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan="5" className="px-3 py-6 text-center text-sm"
                        style={{ color: colors.muted }}>Loading…</td></tr>
            ) : filteredItems.length === 0 ? (
              <tr><td colSpan="5" className="px-3 py-8 text-center text-sm"
                        style={{ color: colors.muted }}
                        data-testid="master-services-empty">
                No master services yet — click "Add Service" to
                create your first one.
              </td></tr>
            ) : filteredItems.map((row) => (
              <tr key={row.id}
                  style={{ borderTop: `1px solid ${colors.border}`,
                            opacity: row.is_active === false ? 0.55 : 1 }}
                  data-testid={`master-services-row-${row.id}`}>
                <td className="px-3 py-2 font-semibold"
                    style={{ color: colors.onSurface }}>{row.name}</td>
                <td className="px-3 py-2" style={{ color: colors.muted }}>
                  {row.category || "—"}
                </td>
                <td className="px-3 py-2 text-right font-mono">
                  {fmtMoney(row.default_price)}
                </td>
                <td className="px-3 py-2 text-center text-xs">
                  {row.is_active === false ? (
                    <span className="px-2 py-0.5 rounded-full"
                          style={{ background: "#FEE2E2", color: "#7F1D1D" }}>
                      Inactive
                    </span>
                  ) : (
                    <span className="px-2 py-0.5 rounded-full"
                          style={{ background: "#DCFCE7", color: "#166534" }}>
                      Active
                    </span>
                  )}
                </td>
                <td className="px-3 py-2 text-right whitespace-nowrap">
                  <button
                    onClick={() => openEdit(row)}
                    className="p-1 mr-1"
                    style={{ color: colors.brand }}
                    title="Edit"
                    data-testid={`master-services-edit-${row.id}`}
                  ><Pencil size={13} /></button>
                  <button
                    onClick={() => canHardDelete && setDeleting(row)}
                    disabled={!canHardDelete}
                    className="p-1"
                    style={{ color: canHardDelete
                      ? colors.error
                      : colors.muted,
                      cursor: canHardDelete ? "pointer" : "not-allowed" }}
                    title={canHardDelete
                      ? "Delete"
                      : "Admin only"}
                    data-testid={`master-services-delete-${row.id}`}
                  ><Trash2 size={13} /></button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {editing ? (
        <ServiceModal
          initial={editing}
          categories={categories}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); load(); }}
        />
      ) : null}
      {deleting ? (
        <DeleteDialog
          target={deleting}
          onClose={() => setDeleting(null)}
          onDone={() => { setDeleting(null); load(); }}
        />
      ) : null}
    </div>
  );
}
