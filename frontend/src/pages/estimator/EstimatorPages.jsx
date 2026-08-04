/**
 * Phase 21 · Field Estimator — web admin surfaces.
 * List + new + detail + rate catalog editor, all in one file (4 exports).
 */
import React, { useEffect, useState, useCallback } from "react";
import { mustConfirm } from "@/components/ui/confirm-dialog";
import { useNavigate, useParams } from "react-router-dom";
import { Sparkles, Plus, Trash2, Send, Download, ArrowLeft, Wrench, ChevronRight, CheckCircle2, AlertCircle } from "lucide-react";
import { api } from "@/api";
import { colors, brandGradientCss } from "@/theme";

const STATUS_TONE = {
  draft:     { bg: "#FEF3C7", fg: "#92400E" },
  generated: { bg: "#DBEAFE", fg: "#1E40AF" },
  edited:    { bg: "#E9D5FF", fg: "#6B21A8" },
  converted: { bg: "#DCFCE7", fg: "#166534" },
  sent:      { bg: "#DCFCE7", fg: "#166534" },
  expired:   { bg: "#FEE2E2", fg: "#991B1B" },
};

/* ─── LIST ──────────────────────────────────────────────────────────── */
export default function EstimatorList() {
  const nav = useNavigate();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("");

  const load = async () => {
    setLoading(true);
    try {
      const r = await api.get(
        `/estimator/estimates${filter ? `?status=${filter}` : ""}`);
      setRows(r.items || []);
    } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, [filter]); // eslint-disable-line react-hooks/exhaustive-deps -- Phase 41.3 mount-only + explicit param deps

  return (
    <div className="max-w-6xl mx-auto p-4 md:p-6" data-testid="estimator-list">
      <div className="flex items-center gap-3 mb-6">
        <div className="flex-1">
          <h1 className="text-2xl font-bold flex items-center gap-2"
              style={{ color: colors.onSurface }}>
            <Wrench size={22} style={{ color: colors.brand }} />
            Field Estimator
          </h1>
          <p className="text-xs" style={{ color: colors.muted }}>
            AI-powered on-the-spot estimates from photos + scope.
            Convert to a formal quote in 1 tap.
          </p>
        </div>
        <button onClick={() => nav("/admin/estimator/rates")}
                className="px-3 py-2 text-sm font-bold rounded-xl"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}`,
                          color: colors.onSurface }}
                data-testid="estimator-rates-btn">
          Rate catalog
        </button>
        <button onClick={() => nav("/admin/estimator/new")}
                className="px-4 py-2 text-sm font-bold rounded-xl flex items-center gap-2"
                style={{ background: brandGradientCss, color: "#fff" }}
                data-testid="estimator-new-btn">
          <Plus size={14} /> New estimate
        </button>
      </div>

      <div className="flex gap-2 mb-4 flex-wrap">
        {["", "draft", "generated", "edited", "converted", "sent"].map((s) => (
          <button key={s || "all"} onClick={() => setFilter(s)}
                  className="px-3 py-1.5 text-xs font-semibold rounded-full"
                  style={{
                    backgroundColor: filter === s ? colors.brand : colors.surface,
                    color: filter === s ? "#fff" : colors.onSurface,
                    border: `1px solid ${filter === s ? colors.brand : colors.border}`,
                  }}
                  data-testid={`est-filter-${s || "all"}`}>
            {s || "All"}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="p-8 text-center text-sm" style={{ color: colors.muted }}>
          Loading…
        </div>
      ) : rows.length === 0 ? (
        <div className="rounded-2xl p-10 text-center"
             style={{ backgroundColor: colors.surface,
                      border: `1px dashed ${colors.border}`,
                      color: colors.muted }}>
          No estimates yet. Tap "New estimate" to get started.
        </div>
      ) : (
        <div className="rounded-2xl overflow-hidden"
             style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}>
          {rows.map((r, i) => {
            const tone = STATUS_TONE[r.status] || STATUS_TONE.draft;
            return (
              <div key={r.id}
                   onClick={() => nav(`/admin/estimator/${r.id}`)}
                   className="p-4 cursor-pointer flex items-center gap-3"
                   style={{ borderTop: i ? `1px solid ${colors.border}` : "none" }}
                   data-testid={`est-row-${r.id}`}>
                <div className="flex-1 min-w-0">
                  <div className="font-bold" style={{ color: colors.onSurface }}>
                    {r.title}
                  </div>
                  <div className="text-xs" style={{ color: colors.muted }}>
                    {r.service_type} · {(r.created_at || "").slice(0, 10)}
                    {r.address ? ` · ${r.address}` : ""}
                  </div>
                </div>
                <div className="text-right">
                  <div className="font-bold" style={{ color: colors.onSurface }}>
                    ${(r.total || 0).toFixed(2)}
                  </div>
                  <span className="text-[10px] px-2 py-0.5 rounded-full font-bold"
                        style={{ backgroundColor: tone.bg, color: tone.fg }}>
                    {r.status}
                  </span>
                </div>
                <ChevronRight size={16} style={{ color: colors.muted }} />
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

/* ─── NEW ───────────────────────────────────────────────────────────── */
export function EstimatorNew() {
  const nav = useNavigate();
  const [customers, setCustomers] = useState([]);
  const [form, setForm] = useState({
    title: "", service_type: "pool", customer_id: "",
    address: "", description: "",
  });
  const [photos, setPhotos] = useState([{ url: "" }]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    api.get("/customers").then((r) =>
      setCustomers(Array.isArray(r) ? r : (r.items || []))).catch(() => {});
  }, []);

  const submit = async () => {
    setErr("");
    if (!form.title || !form.description) {
      setErr("Title and scope description are required."); return;
    }
    setBusy(true);
    try {
      const filteredPhotos = photos.filter((p) => (p.url || "").trim());
      const r = await api.post("/estimator/estimates", {
        ...form, photos: filteredPhotos,
      });
      const eid = r.estimate_id;
      // Kick off AI generation
      await api.post(`/estimator/estimates/${eid}/generate`, null, 180000);
      nav(`/admin/estimator/${eid}`);
    } catch (e) {
      setErr(e.message || "Failed");
    } finally { setBusy(false); }
  };

  return (
    <div className="max-w-3xl mx-auto p-4 md:p-6" data-testid="estimator-new">
      <div className="flex items-center gap-3 mb-6">
        <button onClick={() => nav("/admin/estimator")}
                className="p-2 rounded-lg"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}>
          <ArrowLeft size={16} />
        </button>
        <h1 className="text-2xl font-bold flex items-center gap-2"
            style={{ color: colors.onSurface }}>
          <Sparkles size={22} style={{ color: colors.brand }} />
          New estimate
        </h1>
      </div>

      {err && (
        <div className="mb-4 p-3 rounded-xl text-sm"
             style={{ backgroundColor: "#FEE2E2", color: "#991B1B" }}
             data-testid="estimator-new-error">{err}</div>
      )}

      <div className="rounded-2xl p-5 space-y-4"
           style={{ backgroundColor: colors.surface,
                    border: `1px solid ${colors.border}` }}>
        {[
          ["title", "Title *", "text"],
          ["address", "Address", "text"],
          ["description", "Scope description *", "textarea"],
        ].map(([k, l, tp]) => (
          <label key={k} className="block">
            <div className="text-xs font-bold mb-1"
                 style={{ color: colors.muted }}>{l}</div>
            {tp === "textarea" ? (
              <textarea rows={4} value={form[k]}
                onChange={(e) => setForm({ ...form, [k]: e.target.value })}
                className="w-full p-2 rounded-lg text-sm"
                style={{ backgroundColor: colors.background,
                          border: `1px solid ${colors.border}` }}
                data-testid={`estnew-${k}`} />
            ) : (
              <input value={form[k]}
                onChange={(e) => setForm({ ...form, [k]: e.target.value })}
                className="w-full p-2 rounded-lg text-sm"
                style={{ backgroundColor: colors.background,
                          border: `1px solid ${colors.border}` }}
                data-testid={`estnew-${k}`} />
            )}
          </label>
        ))}

        <div className="grid grid-cols-2 gap-3">
          <label className="block">
            <div className="text-xs font-bold mb-1"
                 style={{ color: colors.muted }}>Service type</div>
            <select value={form.service_type}
              onChange={(e) => setForm({ ...form, service_type: e.target.value })}
              className="w-full p-2 rounded-lg text-sm"
              style={{ backgroundColor: colors.background,
                        border: `1px solid ${colors.border}` }}
              data-testid="estnew-service-type">
              {["pool", "landscape", "hardscape", "repair", "other"].map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </label>
          <label className="block">
            <div className="text-xs font-bold mb-1"
                 style={{ color: colors.muted }}>Customer (optional)</div>
            <select value={form.customer_id}
              onChange={(e) => setForm({ ...form, customer_id: e.target.value })}
              className="w-full p-2 rounded-lg text-sm"
              style={{ backgroundColor: colors.background,
                        border: `1px solid ${colors.border}` }}
              data-testid="estnew-customer">
              <option value="">— None —</option>
              {customers.slice(0, 200).map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
          </label>
        </div>

        <div>
          <div className="text-xs font-bold mb-1"
               style={{ color: colors.muted }}>Photo URLs (up to 10)</div>
          {photos.map((p, i) => (
            <div key={i} className="flex gap-2 mb-2">
              <input value={p.url} placeholder="https://…"
                onChange={(e) => {
                  const next = [...photos];
                  next[i] = { url: e.target.value };
                  setPhotos(next);
                }}
                className="flex-1 p-2 rounded-lg text-sm"
                style={{ backgroundColor: colors.background,
                          border: `1px solid ${colors.border}` }}
                data-testid={`estnew-photo-${i}`} />
              <button onClick={() => setPhotos(photos.filter((_, j) => j !== i))}
                      className="p-2 rounded"
                      style={{ color: "#DC2626" }}>
                <Trash2 size={14} />
              </button>
            </div>
          ))}
          {photos.length < 10 && (
            <button onClick={() => setPhotos([...photos, { url: "" }])}
                    className="text-xs font-bold px-3 py-1 rounded"
                    style={{ color: colors.brand }}
                    data-testid="estnew-add-photo">
              + Add photo URL
            </button>
          )}
        </div>

        <button onClick={submit} disabled={busy}
                className="w-full py-3 text-sm font-bold rounded-xl disabled:opacity-50 flex items-center justify-center gap-2"
                style={{ background: brandGradientCss, color: "#fff" }}
                data-testid="estnew-submit">
          <Sparkles size={16} />
          {busy ? "Generating estimate (AI vision)…" : "Generate estimate"}
        </button>
      </div>
    </div>
  );
}

/* ─── DETAIL ────────────────────────────────────────────────────────── */
export function EstimatorDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const [e, setE] = useState(null);
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState("");
  const [showSend, setShowSend] = useState(false);
  const [emails, setEmails] = useState("");

  const load = useCallback(async () => {
    const r = await api.get(`/estimator/estimates/${id}`);
    setE(r);
  }, [id]);
  useEffect(() => { load(); }, [load]);

  if (!e) return (
    <div className="p-6 text-sm" style={{ color: colors.muted }}>Loading…</div>
  );

  const updateItem = async (item, patch) => {
    const next = e.line_items.map((li) => li.id === item.id ? { ...li, ...patch } : li);
    setE({ ...e, line_items: next });
    await api.patch(`/estimator/estimates/${id}`, { line_items: next });
    await load();
  };
  const removeItem = async (item) => {
    await api.del(`/estimator/estimates/${id}/line-items/${item.id}`);
    await load();
  };
  const addUpsell = async (u) => {
    await api.post(`/estimator/estimates/${id}/add-line-item`, {
      description: u.title, quantity: 1, unit: "ea",
      unit_price: u.estimated_add_price, category: "misc",
    });
    await load();
    setMsg(`Added "${u.title}" to estimate.`);
    setTimeout(() => setMsg(""), 2500);
  };
  const convert = async () => {
    setBusy("convert");
    try {
      const r = await api.post(`/estimator/estimates/${id}/convert-to-quote`);
      setMsg(`Converted to quote #${r.quote_id.slice(0, 8)}.`);
      await load();
    } catch (err) {
      setMsg(err.message || "Convert failed");
    } finally { setBusy(""); }
  };
  const downloadPdf = async () => {
    const base = process.env.REACT_APP_BACKEND_URL;
    const url = `${base}/api/estimator/estimates/${id}/pdf.file`;
    const token = localStorage.getItem("token") || "";
    const t = localStorage.getItem("tenant_slug") || "";
    const r = await fetch(url, {
      headers: { Authorization: `Bearer ${token}`, "X-Tenant-Slug": t },
    });
    const blob = await r.blob();
    const dl = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = dl; a.download = `estimate-${id.slice(0, 8)}.pdf`; a.click();
    URL.revokeObjectURL(dl);
  };
  const sendEmail = async () => {
    setBusy("send");
    try {
      const to = emails.split(",").map((s) => s.trim()).filter(Boolean);
      const r = await api.post(`/estimator/estimates/${id}/send-to-customer`, {
        recipient_emails: to });
      setMsg(r.sent ? `Sent to ${r.to.join(", ")}` : `Not sent: ${r.reason}`);
      setShowSend(false);
      await load();
    } finally { setBusy(""); }
  };

  const tone = STATUS_TONE[e.status] || STATUS_TONE.draft;

  return (
    <div className="max-w-6xl mx-auto p-4 md:p-6" data-testid="estimator-detail">
      <div className="flex items-center gap-3 mb-4 flex-wrap">
        <button onClick={() => nav("/admin/estimator")}
                className="p-2 rounded-lg"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}>
          <ArrowLeft size={16} />
        </button>
        <div className="flex-1 min-w-0">
          <h1 className="text-2xl font-bold" style={{ color: colors.onSurface }}>
            {e.title}
          </h1>
          <div className="text-xs mt-1 flex items-center gap-2 flex-wrap">
            <span className="px-2 py-0.5 rounded-full font-bold text-[10px]"
                  style={{ backgroundColor: tone.bg, color: tone.fg }}>
              {e.status}
            </span>
            <span style={{ color: colors.muted }}>
              {e.service_type} · {e.address || "no address"}
            </span>
            {e.mocked && (
              <span className="px-2 py-0.5 rounded-full font-bold text-[10px]"
                    style={{ backgroundColor: "#FEF3C7", color: "#92400E" }}>
                MOCK MODE
              </span>
            )}
          </div>
        </div>
        <button onClick={downloadPdf} disabled={!!busy}
                className="px-3 py-2 text-sm font-bold rounded-xl flex items-center gap-1"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}`,
                          color: colors.onSurface }}
                data-testid="estdet-pdf">
          <Download size={14} /> PDF
        </button>
        <button onClick={() => setShowSend(true)} disabled={!!busy}
                className="px-3 py-2 text-sm font-bold rounded-xl flex items-center gap-1"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}`,
                          color: colors.onSurface }}
                data-testid="estdet-send">
          <Send size={14} /> Email
        </button>
        <button onClick={convert} disabled={busy === "convert" || e.status === "converted"}
                className="px-4 py-2 text-sm font-bold rounded-xl flex items-center gap-1 disabled:opacity-50"
                style={{ background: brandGradientCss, color: "#fff" }}
                data-testid="estdet-convert">
          <CheckCircle2 size={14} />
          {e.status === "converted" ? "Converted"
            : busy === "convert" ? "Converting…" : "Convert to Quote"}
        </button>
      </div>

      {msg && (
        <div className="mb-4 p-3 rounded-xl text-sm"
             style={{ backgroundColor: "#EFF6FF", color: "#1E40AF",
                      border: "1px solid #BFDBFE" }}
             data-testid="estdet-msg">{msg}</div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 rounded-2xl overflow-hidden"
             style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}>
          <table className="w-full text-sm">
            <thead style={{ backgroundColor: "#F1F5F9" }}>
              <tr className="text-left">
                <th className="p-2">Description</th>
                <th className="p-2 w-16">Qty</th>
                <th className="p-2 w-20">Unit</th>
                <th className="p-2 w-24">Unit $</th>
                <th className="p-2 w-24 text-right">Total</th>
                <th className="p-2 w-8"></th>
              </tr>
            </thead>
            <tbody>
              {(e.line_items || []).map((li) => (
                <tr key={li.id} data-testid={`estdet-item-${li.id}`}
                    style={{ borderTop: `1px solid ${colors.border}` }}>
                  <td className="p-2">
                    <div style={{ color: colors.onSurface }}>
                      {li.description}
                    </div>
                    {li.unit_price_source === "ai_estimate" && (
                      <div className="text-[9px] mt-1 flex items-center gap-1"
                           style={{ color: "#92400E" }}>
                        <AlertCircle size={10} />
                        AI estimate — adjust for your market
                        {li.confidence != null &&
                          ` · conf ${(li.confidence * 100).toFixed(0)}%`}
                      </div>
                    )}
                    {li.unit_price_source === "tenant_rate" && (
                      <div className="text-[9px] mt-1"
                           style={{ color: "#166534" }}>
                        ✓ From your rate catalog
                      </div>
                    )}
                  </td>
                  <td className="p-2">
                    <input type="number" value={li.quantity}
                      onChange={(ev) => updateItem(li,
                        { quantity: parseFloat(ev.target.value) || 0 })}
                      className="w-14 p-1 rounded text-xs"
                      style={{ backgroundColor: colors.background,
                                border: `1px solid ${colors.border}` }} />
                  </td>
                  <td className="p-2 text-xs" style={{ color: colors.muted }}>
                    {li.unit}
                  </td>
                  <td className="p-2">
                    <input type="number" step="0.01" value={li.unit_price}
                      onChange={(ev) => updateItem(li,
                        { unit_price: parseFloat(ev.target.value) || 0 })}
                      className="w-20 p-1 rounded text-xs"
                      style={{ backgroundColor: colors.background,
                                border: `1px solid ${colors.border}` }} />
                  </td>
                  <td className="p-2 text-right font-bold"
                      style={{ color: colors.onSurface }}>
                    ${(li.extended_price || 0).toFixed(2)}
                  </td>
                  <td className="p-2">
                    <button onClick={() => removeItem(li)}
                            style={{ color: "#DC2626" }}
                            data-testid={`estdet-remove-${li.id}`}>
                      <Trash2 size={12} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {(e.line_items || []).length === 0 && (
            <div className="p-8 text-center text-sm"
                 style={{ color: colors.muted }}>
              No line items yet.
            </div>
          )}
        </div>

        <div className="rounded-2xl p-4"
             style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}>
          <h3 className="font-bold mb-2" style={{ color: colors.onSurface }}>
            Totals
          </h3>
          {[
            ["Subtotal", e.subtotal],
            [`Markup (${(e.markup_pct || 0).toFixed(1)}%)`, e.markup_amount],
            [`Tax (${(e.tax_rate_pct || 0).toFixed(1)}%)`, e.tax_amount],
          ].map(([l, v]) => (
            <div key={l} className="flex justify-between text-sm py-1"
                 style={{ color: colors.onSurface }}>
              <span style={{ color: colors.muted }}>{l}</span>
              <span>${(v || 0).toFixed(2)}</span>
            </div>
          ))}
          <div className="flex justify-between font-bold text-lg pt-2 mt-2"
               style={{ color: colors.onSurface,
                        borderTop: `2px solid ${colors.onSurface}` }}
               data-testid="estdet-total">
            <span>Total</span>
            <span>${(e.total || 0).toFixed(2)}</span>
          </div>

          <h3 className="font-bold mt-6 mb-2 flex items-center gap-2"
              style={{ color: colors.onSurface }}>
            <Sparkles size={14} style={{ color: colors.brand }} />
            Suggested add-ons
          </h3>
          {(e.upsells || []).length === 0 ? (
            <div className="text-xs" style={{ color: colors.muted }}>
              No upsells suggested.
            </div>
          ) : (
            e.upsells.map((u) => (
              <div key={u.id} className="p-3 rounded-lg mb-2"
                   style={{ backgroundColor: colors.background,
                            border: `1px solid ${colors.border}` }}
                   data-testid={`estdet-upsell-${u.id}`}>
                <div className="flex items-center justify-between">
                  <div className="font-bold text-sm"
                       style={{ color: colors.onSurface }}>
                    {u.title}
                  </div>
                  <div className="font-bold text-sm"
                       style={{ color: "#059669" }}>
                    +${(u.estimated_add_price || 0).toFixed(0)}
                  </div>
                </div>
                <div className="text-xs mt-1"
                     style={{ color: colors.muted }}>{u.description}</div>
                <button onClick={() => addUpsell(u)}
                        className="mt-2 text-xs font-bold"
                        style={{ color: colors.brand }}
                        data-testid={`estdet-upsell-add-${u.id}`}>
                  + Add to estimate
                </button>
              </div>
            ))
          )}
        </div>
      </div>

      {showSend && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4"
             style={{ backgroundColor: "rgba(0,0,0,0.5)" }}>
          <div className="rounded-2xl p-6 max-w-md w-full"
               style={{ backgroundColor: colors.surface }}
               data-testid="estdet-send-modal">
            <h2 className="text-lg font-bold mb-4">Email estimate</h2>
            <label className="block mb-3">
              <div className="text-xs font-bold mb-1"
                   style={{ color: colors.muted }}>
                Recipient emails (comma-separated)
              </div>
              <input value={emails} onChange={(ev) => setEmails(ev.target.value)}
                className="w-full p-2 rounded-lg text-sm"
                style={{ backgroundColor: colors.background,
                          border: `1px solid ${colors.border}` }}
                data-testid="estdet-send-to" />
            </label>
            <div className="flex gap-2">
              <button onClick={() => setShowSend(false)}
                      className="flex-1 py-2 text-sm font-bold rounded-xl"
                      style={{ backgroundColor: colors.background,
                                border: `1px solid ${colors.border}`,
                                color: colors.onSurface }}>
                Cancel
              </button>
              <button onClick={sendEmail} disabled={busy === "send" || !emails.trim()}
                      className="flex-1 py-2 text-sm font-bold rounded-xl disabled:opacity-50"
                      style={{ background: brandGradientCss, color: "#fff" }}
                      data-testid="estdet-send-submit">
                {busy === "send" ? "Sending…" : "Send"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ─── RATE CATALOG ──────────────────────────────────────────────────── */
export function EstimatorRates() {
  const nav = useNavigate();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");

  const load = async () => {
    setLoading(true);
    try {
      const r = await api.get("/estimator/rate-catalog");
      setItems(r.items || []);
    } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const save = async () => {
    setSaving(true);
    try {
      await api.post("/estimator/rate-catalog/replace-all", {
        items: items.map(({ code, description, category, unit, default_price }) =>
          ({ code, description, category, unit, default_price })),
      });
      setMsg("Saved."); setTimeout(() => setMsg(""), 2000);
    } finally { setSaving(false); }
  };

  const reset = async () => {
    if (!(await mustConfirm({ title: "Reset to starter catalog?", description: "Custom edits will be lost.", tone: "danger" }))) return;
    setSaving(true);
    try {
      const r = await api.post("/estimator/rate-catalog/reset-defaults");
      setItems(r.items || []);
      setMsg("Reset to defaults."); setTimeout(() => setMsg(""), 2000);
    } finally { setSaving(false); }
  };

  return (
    <div className="max-w-5xl mx-auto p-4 md:p-6" data-testid="estimator-rates">
      <div className="flex items-center gap-3 mb-6">
        <button onClick={() => nav("/admin/estimator")}
                className="p-2 rounded-lg"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}>
          <ArrowLeft size={16} />
        </button>
        <div className="flex-1">
          <h1 className="text-2xl font-bold"
              style={{ color: colors.onSurface }}>Rate catalog</h1>
          <p className="text-xs" style={{ color: colors.muted }}>
            Prices from this catalog are used whenever an item's <code>code</code>
            matches. AI estimates cover the rest.
          </p>
        </div>
        <button onClick={reset} disabled={saving}
                className="px-3 py-2 text-sm font-bold rounded-xl"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}`,
                          color: colors.onSurface }}
                data-testid="rates-reset">
          Reset to defaults
        </button>
        <button onClick={save} disabled={saving}
                className="px-4 py-2 text-sm font-bold rounded-xl"
                style={{ background: brandGradientCss, color: "#fff" }}
                data-testid="rates-save">
          {saving ? "Saving…" : "Save changes"}
        </button>
      </div>

      {msg && (
        <div className="mb-4 p-3 rounded-xl text-sm"
             style={{ backgroundColor: "#DCFCE7", color: "#166534" }}>{msg}</div>
      )}

      {loading ? (
        <div className="p-8 text-center text-sm"
             style={{ color: colors.muted }}>Loading…</div>
      ) : (
        <div className="rounded-2xl overflow-hidden"
             style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}>
          <table className="w-full text-sm">
            <thead style={{ backgroundColor: "#F1F5F9" }}>
              <tr className="text-left">
                <th className="p-2">Code</th>
                <th className="p-2">Description</th>
                <th className="p-2 w-24">Category</th>
                <th className="p-2 w-20">Unit</th>
                <th className="p-2 w-24">Price</th>
                <th className="p-2 w-8"></th>
              </tr>
            </thead>
            <tbody>
              {items.map((it, i) => (
                <tr key={i} data-testid={`rate-row-${i}`}
                    style={{ borderTop: `1px solid ${colors.border}` }}>
                  {["code", "description"].map((k) => (
                    <td key={k} className="p-1">
                      <input value={it[k] || ""}
                        onChange={(ev) => {
                          const next = [...items];
                          next[i] = { ...it, [k]: ev.target.value };
                          setItems(next);
                        }}
                        className="w-full p-1 rounded text-xs"
                        style={{ backgroundColor: colors.background,
                                  border: `1px solid ${colors.border}` }} />
                    </td>
                  ))}
                  <td className="p-1">
                    <select value={it.category}
                      onChange={(ev) => {
                        const next = [...items];
                        next[i] = { ...it, category: ev.target.value };
                        setItems(next);
                      }}
                      className="w-full p-1 rounded text-xs"
                      style={{ backgroundColor: colors.background,
                                border: `1px solid ${colors.border}` }}>
                      {["labor", "material", "equipment", "permit", "misc"].map((c) => (
                        <option key={c} value={c}>{c}</option>
                      ))}
                    </select>
                  </td>
                  <td className="p-1">
                    <select value={it.unit}
                      onChange={(ev) => {
                        const next = [...items];
                        next[i] = { ...it, unit: ev.target.value };
                        setItems(next);
                      }}
                      className="w-full p-1 rounded text-xs"
                      style={{ backgroundColor: colors.background,
                                border: `1px solid ${colors.border}` }}>
                      {["hr", "sqft", "linft", "ea", "lb", "gal", "ton", "yd"].map((u) => (
                        <option key={u} value={u}>{u}</option>
                      ))}
                    </select>
                  </td>
                  <td className="p-1">
                    <input type="number" step="0.01" value={it.default_price}
                      onChange={(ev) => {
                        const next = [...items];
                        next[i] = { ...it, default_price:
                          parseFloat(ev.target.value) || 0 };
                        setItems(next);
                      }}
                      className="w-full p-1 rounded text-xs"
                      style={{ backgroundColor: colors.background,
                                border: `1px solid ${colors.border}` }} />
                  </td>
                  <td className="p-1">
                    <button onClick={() =>
                      setItems(items.filter((_, j) => j !== i))}
                            style={{ color: "#DC2626" }}>
                      <Trash2 size={12} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="p-3">
            <button onClick={() => setItems([...items, {
              code: "", description: "", category: "misc",
              unit: "ea", default_price: 0,
            }])}
                    className="text-xs font-bold"
                    style={{ color: colors.brand }}
                    data-testid="rates-add-row">
              + Add row
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
