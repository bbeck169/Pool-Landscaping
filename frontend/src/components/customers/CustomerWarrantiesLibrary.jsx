/**
 * Phase Feb-2026 — Customer Warranties admin section.
 *
 * Card-per-warranty list + Add / Edit modal. Reuses the same shape
 * conventions as CustomerEquipmentLibrary: sonner-free confirm via
 * window.confirm, inline modal, testid map called out in the phase
 * memo.
 *
 * Linked-entity semantics (see memory/FEATURE_WARRANTY_CONTRACTS.md):
 *   linked_type ∈ {"none","install","equipment"}
 *   linked_id must reference a same-tenant job (service_type contains
 *   "install") or a same-tenant customer_equipment row.
 */
import React, {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import { Pencil, Plus, ShieldCheck, Trash2 } from "lucide-react";
import { api } from "@/api";

const c = {
  border: "#E2E8F0",
  muted: "#64748B",
  surface: "#F8FAFC",
  onSurface: "#0F172A",
  brand: "#0EA5E9",
  danger: "#DC2626",
};

const EMPTY_FORM = {
  plan_id: "",
  start_date: "",
  custom_end_date: "",
  notes: "",
  price_override: "",
  linked_type: "none",
  linked_id: "",
};

function canEditRole(user) {
  const role = (user?.role || "").toLowerCase();
  return role === "admin" || role === "super_admin";
}

// ─── Add / Edit modal ─────────────────────────────────────────────
function WarrantyFormModal({
  open, initial, plans, customerId,
  onSubmit, onClose,
}) {
  const [form, setForm] = useState(EMPTY_FORM);
  const [linkOptions, setLinkOptions] = useState([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!open) return;
    setErr("");
    if (initial) {
      setForm({
        plan_id: initial.plan_id || "",
        start_date: initial.start_date || "",
        custom_end_date: initial.custom_end_date || "",
        notes: initial.notes || "",
        price_override: initial.price_paid != null ? String(initial.price_paid) : "",
        linked_type: initial.linked_type || "none",
        linked_id: initial.linked_id || "",
      });
    } else {
      setForm(EMPTY_FORM);
    }
  }, [open, initial]);

  // Load dependent link-options whenever linked_type changes.
  useEffect(() => {
    if (!open) return;
    if (form.linked_type === "none" || !form.linked_type) {
      setLinkOptions([]);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const r = await api.get(
          `/customers/${encodeURIComponent(customerId)}/warranties/link-options?type=${form.linked_type}`
        );
        if (!cancelled) setLinkOptions(r.options || []);
      } catch (e) {
        if (!cancelled) setLinkOptions([]);
      }
    })();
    return () => { cancelled = true; };
  }, [open, form.linked_type, customerId]);

  if (!open) return null;
  const isEdit = Boolean(initial);
  const update = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const submit = async () => {
    setBusy(true); setErr("");
    try {
      if (!isEdit && !form.plan_id) throw new Error("Plan is required");
      if (!isEdit && !form.start_date) throw new Error("Start date is required");
      const payload = {
        notes: form.notes || null,
        custom_end_date: form.custom_end_date || null,
        linked_type: form.linked_type || "none",
        linked_id: form.linked_type === "none" ? null : (form.linked_id || null),
      };
      if (!isEdit) {
        payload.plan_id = form.plan_id;
        payload.customer_id = customerId;
        payload.start_date = form.start_date;
        if (form.price_override !== "") {
          payload.price_override = Number(form.price_override);
        }
      }
      await onSubmit(payload);
      onClose();
    } catch (e) {
      setErr(e?.message || "Save failed");
    } finally { setBusy(false); }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: "rgba(15,23,42,0.55)" }}
      onClick={onClose}
      data-testid="warranty-form-modal"
    >
      <div
        className="w-full max-w-lg rounded-xl overflow-hidden shadow-2xl"
        style={{ background: "#fff" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          className="px-4 py-3 flex items-center justify-between"
          style={{ borderBottom: `1px solid ${c.border}` }}
        >
          <div className="text-sm font-bold" style={{ color: c.onSurface }}>
            {isEdit ? "Edit Warranty" : "Add Warranty"}
          </div>
          <button
            type="button" onClick={onClose}
            style={{ background: "transparent", border: 0, cursor: "pointer", color: c.muted, fontSize: 20 }}
            data-testid="warranty-form-close"
          >×</button>
        </div>

        <div className="p-4 space-y-3 text-sm" style={{ color: c.onSurface }}>
          {err ? (
            <div
              className="text-xs px-2 py-1 rounded"
              style={{ background: "#FEE2E2", color: "#991B1B" }}
              data-testid="warranty-form-error"
            >{err}</div>
          ) : null}

          {!isEdit ? (
            <div>
              <label className="text-xs font-semibold" style={{ color: c.muted }}>
                Plan (Contract Name) *
              </label>
              <select
                value={form.plan_id}
                onChange={(e) => update("plan_id", e.target.value)}
                className="w-full mt-1 px-3 py-2 rounded-md text-sm"
                style={{ border: `1px solid ${c.border}`, background: "#fff" }}
                data-testid="warranty-contract-name-input"
              >
                <option value="">— Select plan —</option>
                {plans.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} ({p.duration_months}mo)
                  </option>
                ))}
              </select>
            </div>
          ) : (
            <div>
              <div className="text-xs font-semibold" style={{ color: c.muted }}>
                Plan
              </div>
              <div className="text-sm" data-testid="warranty-contract-name-input">
                {initial?.plan_name_snapshot || "—"}
              </div>
            </div>
          )}

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-semibold" style={{ color: c.muted }}>
                Coverage start {isEdit ? "" : "*"}
              </label>
              <input
                type="date" value={form.start_date} disabled={isEdit}
                onChange={(e) => update("start_date", e.target.value)}
                className="w-full mt-1 px-3 py-2 rounded-md text-sm"
                style={{ border: `1px solid ${c.border}`, background: isEdit ? c.surface : "#fff" }}
                data-testid="warranty-coverage-start-input"
              />
            </div>
            <div>
              <label className="text-xs font-semibold" style={{ color: c.muted }}>
                Coverage end (override)
              </label>
              <input
                type="date" value={form.custom_end_date}
                onChange={(e) => update("custom_end_date", e.target.value)}
                className="w-full mt-1 px-3 py-2 rounded-md text-sm"
                style={{ border: `1px solid ${c.border}` }}
                data-testid="warranty-coverage-end-input"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-semibold" style={{ color: c.muted }}>
                Linked to
              </label>
              <select
                value={form.linked_type}
                onChange={(e) => {
                  update("linked_type", e.target.value);
                  update("linked_id", "");
                }}
                className="w-full mt-1 px-3 py-2 rounded-md text-sm"
                style={{ border: `1px solid ${c.border}`, background: "#fff" }}
                data-testid="warranty-linked-type-select"
              >
                <option value="none">None</option>
                <option value="install">Install Job</option>
                <option value="equipment">Equipment</option>
              </select>
            </div>
            <div>
              <label className="text-xs font-semibold" style={{ color: c.muted }}>
                {form.linked_type === "install" ? "Install job" : form.linked_type === "equipment" ? "Equipment unit" : "—"}
              </label>
              <select
                value={form.linked_id}
                onChange={(e) => update("linked_id", e.target.value)}
                disabled={form.linked_type === "none"}
                className="w-full mt-1 px-3 py-2 rounded-md text-sm"
                style={{
                  border: `1px solid ${c.border}`,
                  background: form.linked_type === "none" ? c.surface : "#fff",
                }}
                data-testid="warranty-linked-id-select"
              >
                <option value="">— Select —</option>
                {linkOptions.map((o) => {
                  const label = form.linked_type === "install"
                    ? `${o.title || o.service_type} · ${o.service_date || ""}`
                    : `${o.equipment_type || "Equipment"}${o.brand ? " · " + o.brand : ""}${o.model ? " " + o.model : ""}${o.serial_number ? " · SN " + o.serial_number : ""}`;
                  return <option key={o.id} value={o.id}>{label}</option>;
                })}
              </select>
            </div>
          </div>

          <div>
            <label className="text-xs font-semibold" style={{ color: c.muted }}>Notes</label>
            <textarea
              value={form.notes} rows={2}
              onChange={(e) => update("notes", e.target.value)}
              className="w-full mt-1 px-3 py-2 rounded-md text-sm"
              style={{ border: `1px solid ${c.border}` }}
              data-testid="warranty-notes-input"
            />
          </div>
        </div>

        <div
          className="px-4 py-3 flex justify-end gap-2"
          style={{ borderTop: `1px solid ${c.border}`, background: c.surface }}
        >
          <button
            type="button" onClick={onClose}
            className="text-xs font-bold px-3 py-1.5 rounded-md"
            style={{ background: "transparent", border: `1px solid ${c.border}`, cursor: "pointer" }}
            data-testid="warranty-form-cancel"
          >Cancel</button>
          <button
            type="button" onClick={submit} disabled={busy}
            className="text-xs font-bold px-3 py-1.5 rounded-md"
            style={{ background: c.brand, color: "#fff", border: 0, cursor: busy ? "wait" : "pointer", opacity: busy ? 0.6 : 1 }}
            data-testid="warranty-form-submit"
          >{busy ? "Saving…" : isEdit ? "Save" : "Add"}</button>
        </div>
      </div>
    </div>
  );
}


// ─── Warranty card ─────────────────────────────────────────────────
function WarrantyCard({ w, i, canEdit, onEdit, onDelete }) {
  return (
    <div
      className="rounded-lg p-3"
      style={{ border: `1px solid ${c.border}`, background: "#fff" }}
      data-testid={`warranty-card-${i}`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-bold" style={{ color: c.onSurface }}>
            <ShieldCheck size={14} color={c.brand} />
            <span data-testid={`warranty-card-name-${i}`}>{w.plan_name_snapshot || "Warranty"}</span>
          </div>
          <div className="mt-1 text-xs" style={{ color: c.muted }}>
            <span data-testid={`warranty-card-window-${i}`}>
              {w.start_date} → {w.end_date}
            </span>
            {w.status ? (
              <span
                className="ml-2 uppercase text-[10px] px-1 py-0.5 rounded"
                style={{ background: c.surface, border: `1px solid ${c.border}` }}
              >{w.status}</span>
            ) : null}
          </div>
          {w.linked_summary ? (
            <div
              className="mt-2 text-xs px-2 py-1 rounded"
              style={{ background: c.surface, border: `1px solid ${c.border}` }}
              data-testid={`warranty-card-link-${i}`}
            >
              <span className="font-semibold">Linked {w.linked_summary.type}:</span> {w.linked_summary.label}
            </div>
          ) : null}
          {w.notes ? (
            <div
              className="mt-2 text-xs" style={{ color: c.onSurface, whiteSpace: "pre-wrap" }}
              data-testid={`warranty-card-notes-${i}`}
            >{w.notes}</div>
          ) : null}
        </div>
        {canEdit ? (
          <div className="flex items-center gap-1 shrink-0">
            <button
              type="button" onClick={() => onEdit(w)}
              className="inline-flex items-center gap-1 text-[11px] font-bold px-2 py-1 rounded-md"
              style={{ background: c.surface, border: `1px solid ${c.border}`, color: c.onSurface, cursor: "pointer" }}
              data-testid={`warranty-card-edit-${i}`}
            ><Pencil size={11} /> Edit</button>
            <button
              type="button" onClick={() => onDelete(w)}
              className="inline-flex items-center gap-1 text-[11px] font-bold px-2 py-1 rounded-md"
              style={{ background: "#FEE2E2", color: c.danger, border: `1px solid #FCA5A5`, cursor: "pointer" }}
              data-testid={`warranty-card-delete-${i}`}
            ><Trash2 size={11} /> Cancel</button>
          </div>
        ) : null}
      </div>
    </div>
  );
}


// ─── Root ─────────────────────────────────────────────────────────
export default function CustomerWarrantiesLibrary({ customerId, currentUser }) {
  const [state, setState] = useState({ items: [], loading: true, error: "" });
  const [plans, setPlans] = useState([]);
  const [modal, setModal] = useState({ open: false, initial: null });
  const canEdit = useMemo(() => canEditRole(currentUser), [currentUser]);

  const load = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: "" }));
    try {
      const res = await api.get(`/customers/${encodeURIComponent(customerId)}/warranties`);
      setState({ items: res.items || [], loading: false, error: "" });
    } catch (e) {
      setState((s) => ({ ...s, loading: false, error: e?.message || "Failed to load warranties" }));
    }
  }, [customerId]);

  const loadPlans = useCallback(async () => {
    try {
      const r = await api.get(`/warranties/plans`);
      setPlans(r.items || []);
    } catch { setPlans([]); }
  }, []);

  useEffect(() => { load(); loadPlans(); }, [load, loadPlans]);

  const submitForm = useCallback(async (payload) => {
    if (modal.initial) {
      await api.patch(`/warranties/contracts/${modal.initial.id}`, payload);
    } else {
      await api.post(`/warranties/contracts`, payload);
    }
    await load();
  }, [modal.initial, load]);

  const cancel = useCallback(async (w) => {
    if (!window.confirm(`Cancel warranty "${w.plan_name_snapshot || ""}"?`)) return;
    try {
      await api.post(`/warranties/contracts/${w.id}/cancel`, { reason: "cancelled from customer profile" });
      await load();
    } catch (e) {
      setState((s) => ({ ...s, error: e?.message || "Cancel failed" }));
    }
  }, [load]);

  return (
    <div className="space-y-3" data-testid="customer-warranties-section">
      <div className="flex items-center justify-between">
        <div className="text-sm" style={{ color: c.muted }}>
          One card per warranty contract. Admins can add / edit / cancel; customers are read-only in the portal.
        </div>
        {canEdit ? (
          <button
            type="button" onClick={() => setModal({ open: true, initial: null })}
            className="inline-flex items-center gap-1 text-xs font-bold px-3 py-1.5 rounded-md"
            style={{ background: c.brand, color: "#fff", border: 0, cursor: "pointer" }}
            data-testid="warranty-add-btn"
          ><Plus size={12} /> Add Warranty</button>
        ) : null}
      </div>

      {state.loading ? (
        <div className="text-sm" style={{ color: c.muted }} data-testid="warranty-loading">Loading…</div>
      ) : state.error ? (
        <div className="text-sm" style={{ color: c.danger }} data-testid="warranty-error">{state.error}</div>
      ) : state.items.length === 0 ? (
        <div
          className="text-sm p-4 rounded-lg text-center"
          style={{ color: c.muted, background: c.surface, border: `1px dashed ${c.border}` }}
          data-testid="warranty-empty"
        >No warranties recorded yet.</div>
      ) : (
        <div className="space-y-2" data-testid="warranty-list">
          {state.items.map((w, i) => (
            <WarrantyCard
              key={w.id} w={w} i={i} canEdit={canEdit}
              onEdit={(x) => setModal({ open: true, initial: x })}
              onDelete={cancel}
            />
          ))}
        </div>
      )}

      <WarrantyFormModal
        open={modal.open} initial={modal.initial}
        plans={plans} customerId={customerId}
        onSubmit={submitForm}
        onClose={() => setModal({ open: false, initial: null })}
      />
    </div>
  );
}
