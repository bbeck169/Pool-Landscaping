/**
 * Phase 10 · Feb 2026 — Admin promo codes page (`/settings/promo-codes`).
 *
 * List + filter + create/edit dialog + soft-delete. Uses only the
 * existing Phase-10 endpoints (POST/GET/PATCH/DELETE /api/promo-codes).
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  Plus, Trash2, Pencil, Search, X as XIcon, Save, Info,
} from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";

const TYPE_LABEL = {
  manual: { label: "Manual", bg: "#EEF2FF", fg: "#3730A3" },
  referral_reward: { label: "Referral", bg: "#DCFCE7", fg: "#166534" },
};
const KIND_LABEL = {
  fixed_credit: "Fixed credit",
  percent_off_invoice: "% off invoice",
  fixed_off_invoice: "Fixed off invoice",
};

function fmtDiscount(row) {
  if (row.discount_kind === "percent_off_invoice") return `${row.percent}%`;
  return `$${((row.amount_cents || 0) / 100).toFixed(2)}`;
}


export default function AdminPromoCodesPage() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState({ type: "", is_active: "" });
  const [editing, setEditing] = useState(null);   // row OR "__new__"

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (filter.type) params.set("type", filter.type);
      if (filter.is_active !== "") params.set("is_active", filter.is_active);
      if (q) params.set("q", q);
      const res = await api.get(`/promo-codes?${params}`);
      setRows(res.promo_codes || []);
    } catch (e) {
      toast.error(e.message || "Failed to load promo codes");
    } finally {
      setLoading(false);
    }
  }, [filter, q]);

  useEffect(() => { load(); }, [load]);

  async function toggleActive(row, next) {
    try {
      const updated = await api.patch(`/promo-codes/${row.id}`, { is_active: next });
      setRows((prev) => prev.map((r) => (r.id === row.id ? { ...r, ...updated } : r)));
    } catch (e) {
      toast.error(e.message || "Toggle failed");
    }
  }

  async function del(row) {
    if (!window.confirm(`Deactivate code ${row.code}?`)) return;
    try {
      await api.del(`/promo-codes/${row.id}`);
      setRows((prev) => prev.filter((r) => r.id !== row.id));
      toast.success("Promo code deactivated");
    } catch (e) {
      toast.error(e.message || "Delete failed");
    }
  }

  return (
    <div className="min-h-screen bg-zinc-50" data-testid="admin-promo-codes-page">
      <div className="bg-white border-b border-zinc-200">
        <div className="max-w-7xl mx-auto px-6 py-6 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-zinc-900">Promo codes</h1>
            <p className="text-sm text-zinc-500 mt-0.5">
              Manual codes + auto-issued referral rewards.
            </p>
          </div>
          <button
            onClick={() => setEditing("__new__")}
            data-testid="admin-promo-new-btn"
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-zinc-900 text-white text-sm hover:bg-zinc-800"
          >
            <Plus className="w-4 h-4" />
            New promo code
          </button>
        </div>
        <div className="max-w-7xl mx-auto px-6 pb-4 flex items-center gap-2">
          <div className="relative flex-1 max-w-md">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-400" />
            <input value={q}
                    onChange={(e) => setQ(e.target.value)}
                    placeholder="Search code…"
                    data-testid="admin-promo-search"
                    className="w-full pl-9 pr-3 py-2 rounded-lg border border-zinc-200 text-sm" />
          </div>
          <select value={filter.type}
                    onChange={(e) => setFilter({ ...filter, type: e.target.value })}
                    data-testid="admin-promo-filter-type"
                    className="px-3 py-2 rounded-lg border border-zinc-200 text-sm bg-white">
            <option value="">All types</option>
            <option value="manual">Manual</option>
            <option value="referral_reward">Referral reward</option>
          </select>
          <select value={filter.is_active}
                    onChange={(e) => setFilter({ ...filter, is_active: e.target.value })}
                    data-testid="admin-promo-filter-active"
                    className="px-3 py-2 rounded-lg border border-zinc-200 text-sm bg-white">
            <option value="">Any state</option>
            <option value="true">Active only</option>
            <option value="false">Inactive only</option>
          </select>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-6 py-6">
        <div className="bg-white rounded-xl border border-zinc-200 overflow-hidden">
          <div className="grid grid-cols-12 gap-2 px-4 py-3 border-b border-zinc-200 bg-zinc-50 text-xs uppercase tracking-wide text-zinc-500">
            <div className="col-span-3">Code</div>
            <div className="col-span-2">Type</div>
            <div className="col-span-2">Discount</div>
            <div className="col-span-2">Uses</div>
            <div className="col-span-2">Expires</div>
            <div className="col-span-1 text-right">Actions</div>
          </div>
          {loading && (
            <div className="py-10 text-center text-sm text-zinc-500">Loading…</div>
          )}
          {!loading && rows.length === 0 && (
            <div className="py-10 text-center text-sm text-zinc-400"
                 data-testid="admin-promo-empty">
              No promo codes yet.
            </div>
          )}
          {!loading && rows.map((r) => {
            const t = TYPE_LABEL[r.type] || TYPE_LABEL.manual;
            return (
              <div key={r.id}
                   data-testid={`admin-promo-row-${r.id}`}
                   className="grid grid-cols-12 gap-2 px-4 py-3 border-b border-zinc-100 items-center hover:bg-zinc-50/70">
                <div className="col-span-3 font-mono text-sm text-zinc-900 truncate">
                  {r.code}
                </div>
                <div className="col-span-2">
                  <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium"
                        style={{ background: t.bg, color: t.fg }}>
                    {t.label}
                  </span>
                </div>
                <div className="col-span-2 text-sm text-zinc-700">{fmtDiscount(r)}</div>
                <div className="col-span-2 text-sm text-zinc-500">
                  {r.uses_count || 0} / {r.max_uses || "—"}
                </div>
                <div className="col-span-2 text-sm text-zinc-500">
                  {r.expires_at ? new Date(r.expires_at).toLocaleDateString() : "—"}
                </div>
                <div className="col-span-1 flex items-center justify-end gap-1">
                  <input type="checkbox" checked={!!r.is_active}
                         onChange={(e) => toggleActive(r, e.target.checked)}
                         data-testid={`admin-promo-active-${r.id}`}
                         className="w-4 h-4" title="Active" />
                  <button onClick={() => setEditing(r)}
                          data-testid={`admin-promo-edit-${r.id}`}
                          className="p-1.5 rounded hover:bg-zinc-100 text-zinc-500 hover:text-zinc-900">
                    <Pencil className="w-3.5 h-3.5" />
                  </button>
                  <button onClick={() => del(r)}
                          data-testid={`admin-promo-delete-${r.id}`}
                          className="p-1.5 rounded hover:bg-red-50 text-zinc-400 hover:text-red-600"
                          title="Deactivate">
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {editing && (
        <PromoDialog
          existing={editing === "__new__" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); load(); }}
        />
      )}
    </div>
  );
}


function PromoDialog({ existing, onClose, onSaved }) {
  const isEdit = !!existing;
  const [form, setForm] = useState(() => ({
    code: existing?.code || "",
    type: existing?.type || "manual",
    discount_kind: existing?.discount_kind || "fixed_credit",
    apply_to: existing?.apply_to || "account_credit",
    amount_cents: existing?.amount_cents || 2500,
    percent: existing?.percent || null,
    max_uses: existing?.max_uses || 1,
    expires_at: existing?.expires_at || "",
    is_active: existing?.is_active !== false,
  }));
  const [saving, setSaving] = useState(false);

  const codeLive = form.code.replace(/[^A-Z0-9]/gi, "").toUpperCase();
  const codeValid = codeLive.length === 0 || (codeLive.length >= 3 && codeLive.length <= 32);
  const canSave = codeValid && !saving && (
    form.discount_kind === "percent_off_invoice"
      ? !!form.percent
      : !!form.amount_cents
  );

  async function submit() {
    setSaving(true);
    try {
      const payload = { ...form, code: codeLive || undefined };
      if (form.discount_kind === "percent_off_invoice") {
        payload.amount_cents = null;
      } else {
        payload.percent = null;
      }
      if (isEdit) {
        // PATCH only accepts a subset — send just the mutable fields.
        await api.patch(`/promo-codes/${existing.id}`, {
          max_uses: form.max_uses,
          expires_at: form.expires_at || null,
          is_active: form.is_active,
          amount_cents: payload.amount_cents,
          percent: payload.percent,
        });
        toast.success("Promo code updated");
      } else {
        await api.post("/promo-codes", payload);
        toast.success("Promo code created");
      }
      onSaved();
    } catch (e) {
      // Structured 409 detail from backend.
      const msg = e.message || "";
      if (/already exists/i.test(msg)) {
        toast.error("A code with that value already exists.");
      } else {
        toast.error(msg || "Save failed");
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open onOpenChange={(o) => (!o && onClose())}>
      <DialogContent className="max-w-lg"
                     data-testid="admin-promo-dialog">
        <DialogHeader>
          <DialogTitle>{isEdit ? "Edit promo code" : "New promo code"}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <Field label="Code" hint={codeValid ? "" : "3–32 chars A-Z 0-9"}>
            <input
              value={form.code}
              onChange={(e) => setForm({ ...form, code: e.target.value })}
              disabled={isEdit}
              data-testid="admin-promo-form-code"
              placeholder={isEdit ? "" : "SUMMER25 — or leave blank to auto-generate"}
              className="w-full px-3 py-2 rounded-lg border border-zinc-200 text-sm font-mono disabled:bg-zinc-50"
            />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Type">
              <select
                value={form.type}
                onChange={(e) => setForm({ ...form, type: e.target.value })}
                disabled={isEdit || form.type === "referral_reward"}
                data-testid="admin-promo-form-type"
                title={form.type === "referral_reward"
                        ? "Referral rewards are auto-created by the watcher"
                        : ""}
                className="w-full px-3 py-2 rounded-lg border border-zinc-200 text-sm bg-white disabled:bg-zinc-50">
                <option value="manual">Manual</option>
                <option value="referral_reward">Referral reward</option>
              </select>
            </Field>
            <Field label="Discount kind">
              <select
                value={form.discount_kind}
                onChange={(e) => setForm({ ...form, discount_kind: e.target.value })}
                disabled={isEdit}
                data-testid="admin-promo-form-kind"
                className="w-full px-3 py-2 rounded-lg border border-zinc-200 text-sm bg-white disabled:bg-zinc-50">
                <option value="fixed_credit">Fixed credit</option>
                <option value="percent_off_invoice">Percent off invoice</option>
                <option value="fixed_off_invoice">Fixed off invoice</option>
              </select>
            </Field>
          </div>
          <div className="grid grid-cols-2 gap-3">
            {form.discount_kind === "percent_off_invoice" ? (
              <Field label="Percent">
                <input type="number" min="1" max="100"
                        value={form.percent || ""}
                        onChange={(e) => setForm({ ...form, percent: parseInt(e.target.value || "0", 10) })}
                        data-testid="admin-promo-form-percent"
                        className="w-full px-3 py-2 rounded-lg border border-zinc-200 text-sm" />
              </Field>
            ) : (
              <Field label="Amount (dollars)">
                <input type="number" min="1"
                        value={form.amount_cents ? form.amount_cents / 100 : ""}
                        onChange={(e) => setForm({ ...form, amount_cents: Math.round(parseFloat(e.target.value || "0") * 100) })}
                        data-testid="admin-promo-form-amount"
                        className="w-full px-3 py-2 rounded-lg border border-zinc-200 text-sm" />
              </Field>
            )}
            <Field label="Apply to">
              <select
                value={form.apply_to}
                onChange={(e) => setForm({ ...form, apply_to: e.target.value })}
                disabled={isEdit}
                data-testid="admin-promo-form-apply"
                className="w-full px-3 py-2 rounded-lg border border-zinc-200 text-sm bg-white disabled:bg-zinc-50">
                <option value="account_credit">Account credit</option>
                <option value="next_invoice">Next invoice</option>
              </select>
            </Field>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Max uses">
              <input type="number" min="1"
                      value={form.max_uses}
                      onChange={(e) => setForm({ ...form, max_uses: parseInt(e.target.value || "1", 10) })}
                      data-testid="admin-promo-form-max"
                      className="w-full px-3 py-2 rounded-lg border border-zinc-200 text-sm" />
            </Field>
            <Field label="Expires (optional)">
              <input type="date"
                      value={form.expires_at ? form.expires_at.slice(0, 10) : ""}
                      onChange={(e) => setForm({ ...form, expires_at: e.target.value || "" })}
                      data-testid="admin-promo-form-expires"
                      className="w-full px-3 py-2 rounded-lg border border-zinc-200 text-sm" />
            </Field>
          </div>
          <label className="inline-flex items-center gap-2 text-sm text-zinc-700">
            <input type="checkbox" checked={!!form.is_active}
                    onChange={(e) => setForm({ ...form, is_active: e.target.checked })}
                    data-testid="admin-promo-form-active"
                    className="w-4 h-4" />
            Active
          </label>
        </div>
        <div className="mt-4 flex items-center justify-end gap-2">
          <button onClick={onClose}
                  className="px-4 py-2 rounded-lg text-sm text-zinc-700 hover:bg-zinc-100">Cancel</button>
          <button onClick={submit}
                  disabled={!canSave}
                  data-testid="admin-promo-form-save"
                  className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-zinc-900 text-white text-sm hover:bg-zinc-800 disabled:opacity-50">
            <Save className="w-4 h-4" />
            {saving ? "Saving…" : (isEdit ? "Save changes" : "Create")}
          </button>
        </div>
      </DialogContent>
    </Dialog>
  );
}


function Field({ label, hint, children }) {
  return (
    <label className="block">
      <div className="text-xs uppercase tracking-wide text-zinc-500 mb-1">
        {label}{" "}
        {hint && <span className="text-red-500 normal-case tracking-normal">— {hint}</span>}
      </div>
      {children}
    </label>
  );
}
