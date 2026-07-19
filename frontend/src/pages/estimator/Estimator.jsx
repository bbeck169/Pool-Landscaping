import React, { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Plus, FileText, Settings, Copy, Trash2 } from "lucide-react";
import { api } from "@/api";
import { colors, money } from "@/theme";
import {
  PageHeader,
  Button,
  Skeleton,
  Modal,
  TextInput,
  Toast,
  EmptyState,
} from "@/components/ui-kit";
import MediaUploader from "@/components/media/MediaUploader";

// ────── Estimates list ──────
export function EstimatesList() {
  const navigate = useNavigate();
  const [rows, setRows] = useState(null);
  const [settings, setSettings] = useState(null);
  useEffect(() => {
    api.get("/estimates").then(setRows).catch(() => setRows([]));
    api.get("/estimates/settings").then(setSettings).catch(() => setSettings({}));
  }, []);
  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6" data-testid="estimator-list">
      <PageHeader
        title="Estimator"
        subtitle="Build detailed estimates from reusable templates."
        right={
          <>
            <Button variant="ghost" onClick={() => navigate("/estimator/templates")} testid="est-templates">
              <Copy size={14} /> Templates
            </Button>
            <Button variant="ghost" onClick={() => navigate("/estimator/settings")} testid="est-settings">
              <Settings size={14} /> Settings
            </Button>
            <Button onClick={() => navigate("/estimator/new")} testid="est-new">
              <Plus size={16} /> New estimate
            </Button>
          </>
        }
      />
      {rows === null ? (
        <Skeleton style={{ height: 220 }} />
      ) : rows.length === 0 ? (
        <EmptyState icon={FileText} title="No estimates yet" hint="Templates + line items build estimates in seconds." action={<Button onClick={() => navigate("/estimator/new")}>New estimate</Button>} />
      ) : (
        <div className="rounded-2xl overflow-hidden" style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
          <table className="w-full text-sm">
            <thead>
              <tr style={{ backgroundColor: colors.surfaceSecondary }}>
                <th className="text-left px-3 py-2 font-semibold">Title</th>
                <th className="text-left px-3 py-2 font-semibold hidden md:table-cell">Customer</th>
                <th className="text-right px-3 py-2 font-semibold">Total</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} onClick={() => navigate(`/estimator/${r.id}`)} className="cursor-pointer hover:bg-zinc-50" style={{ borderTop: `1px solid ${colors.divider}` }} data-testid={`est-row-${r.id}`}>
                  <td className="px-3 py-3 font-semibold">{r.title}</td>
                  <td className="px-3 py-3 hidden md:table-cell text-sm" style={{ color: colors.onSurfaceSecondary }}>{r.customer_name || "—"}</td>
                  <td className="px-3 py-3 text-right font-semibold">{money(r.total)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ────── Settings ──────
export function EstimatorSettings() {
  const navigate = useNavigate();
  const [form, setForm] = useState({ default_markup: 0, default_tax_rate: 0, currency: "USD", labeling: "Estimate", valid_days: 30 });
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState(null);
  useEffect(() => {
    api.get("/estimates/settings").then((d) => setForm((f) => ({ ...f, ...(d || {}) }))).catch(() => {});
  }, []);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const save = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api.put("/estimates/settings", form);
      setToast({ tone: "success", message: "Saved" });
    } catch (err) {
      setToast({ tone: "error", message: err.message });
    } finally { setBusy(false); }
  };
  return (
    <div className="max-w-2xl mx-auto px-4 sm:px-6 lg:px-8 py-6" data-testid="est-settings-page">
      <button onClick={() => navigate("/estimator")} className="flex items-center gap-1 text-sm font-semibold mb-4" style={{ color: colors.muted }}>
        <ArrowLeft size={14} /> Estimates
      </button>
      <PageHeader title="Estimator Settings" />
      <form onSubmit={save} className="rounded-2xl p-5 space-y-4" style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
        <TextInput label="DEFAULT MARKUP (%)" type="number" step="0.01" value={form.default_markup ?? 0} onChange={set("default_markup")} />
        <TextInput label="DEFAULT TAX RATE (%)" type="number" step="0.01" value={form.default_tax_rate ?? 0} onChange={set("default_tax_rate")} />
        <TextInput label="CURRENCY" value={form.currency || "USD"} onChange={set("currency")} />
        <TextInput label="LABELING" value={form.labeling || "Estimate"} onChange={set("labeling")} />
        <TextInput label="DEFAULT VALID DAYS" type="number" value={form.valid_days ?? 30} onChange={set("valid_days")} />
        <div className="flex justify-end pt-2">
          <Button type="submit" disabled={busy}>{busy ? "Saving…" : "Save"}</Button>
        </div>
      </form>
      <Toast toast={toast} onClose={() => setToast(null)} />
    </div>
  );
}

// ────── Templates ──────
export function EstimatorTemplates() {
  const navigate = useNavigate();
  const [rows, setRows] = useState(null);
  const [addOpen, setAddOpen] = useState(false);
  const [form, setForm] = useState({ name: "", notes: "", markup: 0, line_items: [] });
  const [toast, setToast] = useState(null);

  const load = () => api.get("/estimate-templates").then(setRows).catch(() => setRows([]));
  useEffect(() => { load(); }, []);

  const create = async () => {
    try {
      await api.post("/estimate-templates", form);
      setAddOpen(false);
      setForm({ name: "", notes: "", markup: 0, line_items: [] });
      await load();
    } catch (e) { setToast({ tone: "error", message: e.message }); }
  };
  const del = async (id) => {
    try {
      await api.del(`/estimate-templates/${id}`);
      await load();
    } catch (e) { setToast({ tone: "error", message: e.message }); }
  };
  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-6" data-testid="est-templates-page">
      <button onClick={() => navigate("/estimator")} className="flex items-center gap-1 text-sm font-semibold mb-4" style={{ color: colors.muted }}>
        <ArrowLeft size={14} /> Estimates
      </button>
      <PageHeader title="Estimate Templates" right={<Button onClick={() => setAddOpen(true)}><Plus size={16} /> New template</Button>} />
      {rows === null ? <Skeleton style={{ height: 200 }} /> :
       rows.length === 0 ? <EmptyState icon={Copy} title="No templates yet" hint="Create a template to spin up estimates fast." /> :
       <ul className="space-y-2">
         {rows.map((t) => (
           <li key={t.id} className="flex items-center gap-3 p-4 rounded-xl" style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
             <div className="flex-1">
               <div className="font-semibold">{t.name}</div>
               <div className="text-xs" style={{ color: colors.muted }}>{(t.line_items || []).length} line items · {t.markup || 0}% markup</div>
             </div>
             <button onClick={() => del(t.id)} style={{ color: colors.error }}><Trash2 size={14} /></button>
           </li>
         ))}
       </ul>}

      <Modal open={addOpen} onClose={() => setAddOpen(false)} title="New template"
        footer={<><Button variant="ghost" onClick={() => setAddOpen(false)}>Cancel</Button><Button onClick={create}>Create</Button></>}>
        <div className="space-y-3">
          <TextInput label="NAME" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <TextInput label="MARKUP (%)" type="number" value={form.markup} onChange={(e) => setForm({ ...form, markup: e.target.value })} />
          <div>
            <label className="text-xs font-semibold tracking-wide mb-1 block" style={{ color: colors.onSurfaceSecondary }}>NOTES</label>
            <textarea value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} rows={3}
              className="w-full px-3 py-2 text-sm rounded-lg outline-none focus:ring-2"
              style={{ backgroundColor: colors.surface, color: colors.onSurface, border: `1px solid ${colors.border}` }} />
          </div>
        </div>
      </Modal>
      <Toast toast={toast} onClose={() => setToast(null)} />
    </div>
  );
}

// ────── Editor (New or Existing) ──────
export function EstimatorEditor() {
  const { id } = useParams();
  const navigate = useNavigate();
  const isNew = !id || id === "new";
  const [customers, setCustomers] = useState([]);
  const [form, setForm] = useState({
    customer_id: "",
    title: "New Estimate",
    line_items: [{ description: "", quantity: 1, unit_price: 0 }],
    tax_rate: 0,
    notes: "",
    terms: "",
  });
  const [videos, setVideos] = useState([]);
  const [termsDefault, setTermsDefault] = useState("");
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState(null);

  useEffect(() => {
    api.get("/customers").then(setCustomers).catch(() => {});
    api.get("/settings/terms").then((r) => {
      setTermsDefault(r.default_quote_terms || "");
      setForm((f) => (f.terms ? f : { ...f, terms: r.default_quote_terms || "" }));
    }).catch(() => {});
    if (!isNew) {
      api.get(`/estimates/${id}`).then((d) => {
        setForm({
          customer_id: d.customer_id || "",
          title: d.title || "Estimate",
          line_items: d.line_items || [],
          tax_rate: d.tax_rate || 0,
          notes: d.notes || "",
          terms: d.terms || "",
        });
        setVideos(d.videos || []);
      }).catch(() => {});
    }
  }, [id, isNew]);

  const totals = useMemo(() => {
    const subtotal = form.line_items.reduce((s, li) => s + (Number(li.quantity) || 0) * (Number(li.unit_price) || 0), 0);
    const tax = subtotal * (Number(form.tax_rate) || 0) / 100;
    return { subtotal, tax, total: subtotal + tax };
  }, [form.line_items, form.tax_rate]);

  const setLine = (i, k, v) => setForm((f) => ({ ...f, line_items: f.line_items.map((li, idx) => idx === i ? { ...li, [k]: v } : li) }));
  const addLine = () => setForm((f) => ({ ...f, line_items: [...f.line_items, { description: "", quantity: 1, unit_price: 0 }] }));
  const remove = (i) => setForm((f) => ({ ...f, line_items: f.line_items.filter((_, idx) => idx !== i) }));

  const save = async () => {
    setBusy(true);
    try {
      const payload = { ...form, tax_rate: Number(form.tax_rate) || 0 };
      const saved = isNew ? await api.post("/estimates", payload) : await api.put(`/estimates/${id}`, payload);
      setToast({ tone: "success", message: "Saved" });
      if (isNew) setTimeout(() => navigate(`/estimator/${saved.id}`), 400);
    } catch (e) { setToast({ tone: "error", message: e.message }); }
    finally { setBusy(false); }
  };

  const convertToQuote = async () => {
    try {
      const q = await api.post(`/estimates/${id}/convert`, {});
      setToast({ tone: "success", message: "Converted to quote" });
      setTimeout(() => navigate(`/quotes/${q.id}`), 400);
    } catch (e) { setToast({ tone: "error", message: e.message }); }
  };

  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-6" data-testid="est-editor">
      <button onClick={() => navigate("/estimator")} className="flex items-center gap-1 text-sm font-semibold mb-4" style={{ color: colors.muted }}>
        <ArrowLeft size={14} /> Estimator
      </button>
      <PageHeader title={isNew ? "New estimate" : form.title} right={!isNew ? <Button onClick={convertToQuote}>Convert to quote</Button> : null} />
      <div className="rounded-2xl p-5 space-y-4" style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="text-xs font-semibold tracking-wide mb-1 block" style={{ color: colors.onSurfaceSecondary }}>CUSTOMER</label>
            <select value={form.customer_id} onChange={(e) => setForm({ ...form, customer_id: e.target.value })}
              className="w-full px-3.5 py-2.5 rounded-lg outline-none text-sm focus:ring-2"
              style={{ backgroundColor: colors.surface, color: colors.onSurface, border: `1px solid ${colors.border}` }}>
              <option value="">Choose a customer…</option>
              {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </div>
          <TextInput label="TITLE" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
          <TextInput label="TAX RATE (%)" type="number" step="0.01" value={form.tax_rate} onChange={(e) => setForm({ ...form, tax_rate: e.target.value })} />
        </div>

        <div className="text-xs font-semibold tracking-wide mt-2" style={{ color: colors.onSurfaceSecondary }}>LINE ITEMS</div>
        {form.line_items.map((li, i) => (
          <div key={i} className="grid grid-cols-12 gap-2">
            <input value={li.description} onChange={(e) => setLine(i, "description", e.target.value)} placeholder="Description"
              className="col-span-6 px-3 py-2 text-sm rounded-lg" style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}` }} />
            <input type="number" step="0.01" value={li.quantity} onChange={(e) => setLine(i, "quantity", e.target.value)} placeholder="Qty"
              className="col-span-2 px-3 py-2 text-sm rounded-lg" style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}` }} />
            <input type="number" step="0.01" value={li.unit_price} onChange={(e) => setLine(i, "unit_price", e.target.value)} placeholder="Unit $"
              className="col-span-3 px-3 py-2 text-sm rounded-lg" style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}` }} />
            <button onClick={() => remove(i)} className="col-span-1 pt-2 opacity-70 hover:opacity-100" style={{ color: colors.error }}>×</button>
          </div>
        ))}
        <Button variant="ghost" onClick={addLine}><Plus size={14} /> Add line</Button>

        <div className="mt-4 pt-4 flex justify-end" style={{ borderTop: `1px solid ${colors.divider}` }}>
          <div className="w-56 space-y-1 text-sm">
            <div className="flex justify-between"><span style={{ color: colors.muted }}>Subtotal</span><span>{money(totals.subtotal)}</span></div>
            <div className="flex justify-between"><span style={{ color: colors.muted }}>Tax</span><span>{money(totals.tax)}</span></div>
            <div className="flex justify-between font-bold" style={{ color: colors.brand }}><span>Total</span><span>{money(totals.total)}</span></div>
          </div>
        </div>
      </div>

      <div className="rounded-2xl p-4 mt-3 space-y-2" style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
        <div className="flex items-center justify-between">
          <div className="text-xs font-semibold tracking-wide" style={{ color: colors.onSurfaceSecondary }}>
            TERMS &amp; CONDITIONS
          </div>
          {termsDefault && form.terms !== termsDefault ? (
            <button type="button" onClick={() => setForm((f) => ({ ...f, terms: termsDefault }))}
                    className="text-xs font-semibold hover:underline"
                    style={{ color: colors.brand }}
                    data-testid="est-terms-reset">
              Reset to default
            </button>
          ) : null}
        </div>
        <textarea
          rows={5}
          value={form.terms || ""}
          onChange={(e) => setForm((f) => ({ ...f, terms: e.target.value }))}
          placeholder="Legal terms shown on the estimate and converted quote."
          className="w-full px-3 py-2 text-sm rounded-lg outline-none"
          style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface, border: `1px solid ${colors.border}` }}
          data-testid="est-terms"
        />
      </div>

      <div className="flex justify-end mt-4 pb-8"><Button onClick={save} disabled={busy}>{busy ? "Saving…" : "Save estimate"}</Button></div>

      {!isNew ? (
        <div className="rounded-2xl p-5 mb-8"
             style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
             data-testid="est-media-section">
          <h3 className="text-base font-bold mb-3" style={{ color: colors.onSurface }}>
            Attachments · Videos
          </h3>
          <MediaUploader
            entityKind="estimate"
            entityId={id}
            existingVideos={videos}
            onUploaded={(v) => setVideos((xs) => [...xs, v])}
            onDeleted={(vid) => setVideos((xs) => xs.map((x) => x.id === vid ? { ...x, is_deleted: true } : x))}
            onPatched={(v) => setVideos((xs) => xs.map((x) => x.id === v.id ? { ...x, ...v } : x))}
          />
        </div>
      ) : null}

      <Toast toast={toast} onClose={() => setToast(null)} />
    </div>
  );
}
