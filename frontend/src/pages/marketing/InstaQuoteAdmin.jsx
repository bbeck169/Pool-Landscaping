import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowLeft, Copy, Plus, Trash2, ExternalLink, Check, X,
  ClipboardList, Palette, Settings, ListChecks,
} from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { toast } from "sonner";

const UNITS = ["visit", "month", "sqft", "gallon", "job"];
const DEFAULT_SERVICES = [
  { name: "Weekly Pool Service", description: "Chem + skim + brush + brush",
    base_price_cents: 12500, unit: "visit", min_qty: 1, max_qty: 12 },
];
const DEFAULT_FREQ = [
  { label: "Weekly", multiplier: 1.0 },
  { label: "Bi-Weekly", multiplier: 0.55 },
];

function fmt$(cents) {
  return `$${(Number(cents || 0) / 100).toFixed(2)}`;
}

// ─── Live public preview (embedded) ─────────────────────────────────────

function PublicPreview({ cfg }) {
  const [selections, setSelections] = useState({});
  const [contact, setContact] = useState({ name: "", email: "" });

  const priceBreakdown = useMemo(() => {
    const services = cfg?.services || [];
    const addOns = cfg?.add_ons || [];
    const freqs = cfg?.frequencies || [];
    let total = 0;
    const rows = [];
    for (const s of services) {
      const sel = selections[s.id];
      if (!sel || !sel.qty) continue;
      const qty = Math.max(s.min_qty || 0, Math.min(s.max_qty || 999, Number(sel.qty)));
      const freq = freqs.find((f) => f.id === sel.frequency_id) || {};
      const mult = Number(freq.multiplier || 1);
      let addonsSum = 0;
      const addonRows = [];
      for (const aid of sel.add_on_ids || []) {
        const a = addOns.find((x) => x.id === aid);
        if (!a) continue;
        addonRows.push({ name: a.name, cents: a.price_cents });
        addonsSum += a.price_cents;
      }
      const line = Math.round((s.base_price_cents * qty + addonsSum) * mult);
      total += line;
      rows.push({ label: s.name, freq: freq.label, qty, line, addons: addonRows });
    }
    return { rows, total };
  }, [cfg, selections]);

  const setSel = (sid, patch) => setSelections((s) => ({
    ...s, [sid]: { ...(s[sid] || {}), ...patch },
  }));
  const toggleAddOn = (sid, aid) => {
    const cur = selections[sid]?.add_on_ids || [];
    setSel(sid, {
      add_on_ids: cur.includes(aid) ? cur.filter((x) => x !== aid) : [...cur, aid],
    });
  };

  return (
    <div className="rounded-2xl p-5"
          style={{
            backgroundColor: colors.surface,
            borderTop: `4px solid ${cfg.brand_color || "#0284C7"}`,
            border: `1px solid ${colors.border}`,
          }}
          data-testid="iq-preview">
      <div className="flex items-center gap-3 mb-2">
        {cfg.logo_url && <img src={cfg.logo_url} alt="" className="h-6" />}
        <h3 className="text-xl font-bold">
          {cfg.headline || "Get an instant quote."}
        </h3>
      </div>
      {cfg.subheadline && (
        <p className="text-sm mb-3" style={{ color: colors.muted }}>
          {cfg.subheadline}
        </p>
      )}

      <div className="space-y-3">
        {(cfg.services || []).map((s) => (
          <div key={s.id}
                className="rounded-lg p-3"
                style={{ backgroundColor: colors.surfaceSecondary,
                          border: `1px solid ${colors.border}` }}>
            <div className="flex items-center justify-between mb-1">
              <div>
                <div className="font-semibold text-sm">{s.name}</div>
                <div className="text-xs" style={{ color: colors.muted }}>
                  {s.description} · {fmt$(s.base_price_cents)}/{s.unit}
                </div>
              </div>
              <Input type="number"
                      className="w-20 text-right"
                      value={selections[s.id]?.qty || ""}
                      min={s.min_qty} max={s.max_qty}
                      onChange={(e) => setSel(s.id, { qty: e.target.value })}
                      placeholder="0" />
            </div>
            <div className="flex flex-wrap gap-1 mt-2">
              {(cfg.frequencies || []).map((f) => (
                <button key={f.id}
                        onClick={() => setSel(s.id, { frequency_id: f.id })}
                        className="text-xs px-2 py-1 rounded-full border"
                        style={{
                          backgroundColor: selections[s.id]?.frequency_id === f.id
                            ? cfg.brand_color : "transparent",
                          color: selections[s.id]?.frequency_id === f.id
                            ? "#fff" : colors.onSurface,
                          borderColor: colors.border,
                        }}>
                  {f.label}
                </button>
              ))}
            </div>
            {(cfg.add_ons || []).length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1">
                {(cfg.add_ons || []).map((a) => {
                  const on = (selections[s.id]?.add_on_ids || []).includes(a.id);
                  return (
                    <button key={a.id}
                            onClick={() => toggleAddOn(s.id, a.id)}
                            className="text-xs px-2 py-1 rounded border"
                            style={{
                              borderColor: on ? cfg.brand_color : colors.border,
                              backgroundColor: on ? cfg.brand_color + "15" : "transparent",
                            }}>
                      + {a.name} ({fmt$(a.price_cents)})
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        ))}
      </div>

      {priceBreakdown.rows.length > 0 && (
        <div className="mt-4 p-3 rounded-lg"
              style={{ backgroundColor: colors.surfaceSecondary }}>
          {priceBreakdown.rows.map((r, i) => (
            <div key={i} className="text-xs flex justify-between">
              <span>{r.label} × {r.qty} · {r.freq}</span>
              <span className="font-semibold">{fmt$(r.line)}</span>
            </div>
          ))}
          <div className="flex justify-between mt-2 pt-2 border-t font-bold"
                style={{ borderColor: colors.border }}>
            <span>Total</span>
            <span style={{ color: cfg.brand_color }}>
              {fmt$(priceBreakdown.total)}
            </span>
          </div>
        </div>
      )}

      <div className="mt-4 pt-3 border-t space-y-2"
            style={{ borderColor: colors.border }}>
        {cfg.collect_fields?.name !== false && (
          <Input placeholder="Your name" value={contact.name}
                  onChange={(e) => setContact({ ...contact, name: e.target.value })} />
        )}
        {cfg.collect_fields?.email !== false && (
          <Input placeholder="Email" value={contact.email}
                  onChange={(e) => setContact({ ...contact, email: e.target.value })} />
        )}
        <button className="w-full py-2 rounded-lg font-semibold text-white"
                style={{ backgroundColor: cfg.brand_color }}
                disabled>
          Submit (preview only)
        </button>
      </div>
    </div>
  );
}

// ─── Builder ──────────────────────────────────────────────────────────

function Builder({ cfg, onChange, onSave }) {
  const set = (patch) => onChange({ ...cfg, ...patch });
  const addService = () => set({
    services: [...(cfg.services || []),
                 { name: "New service", base_price_cents: 5000,
                   unit: "visit", min_qty: 1, max_qty: 12 }],
  });
  const patchList = (key, i, patch) => {
    const list = [...(cfg[key] || [])];
    list[i] = { ...list[i], ...patch };
    set({ [key]: list });
  };
  const removeAt = (key, i) => {
    const list = [...(cfg[key] || [])];
    list.splice(i, 1);
    set({ [key]: list });
  };

  return (
    <div className="rounded-2xl p-5 space-y-4"
          style={{ backgroundColor: colors.surface,
                    border: `1px solid ${colors.border}` }}>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div>
          <Label>Slug (URL)</Label>
          <Input value={cfg.slug || ""}
                  onChange={(e) => set({ slug: e.target.value })}
                  disabled={!!cfg.id}
                  placeholder="e.g. aquaterra-pools"
                  data-testid="iq-slug" />
        </div>
        <div>
          <Label>Brand color</Label>
          <Input type="color" value={cfg.brand_color || "#0284C7"}
                  onChange={(e) => set({ brand_color: e.target.value })} />
        </div>
        <div className="md:col-span-2">
          <Label>Headline</Label>
          <Input value={cfg.headline || ""}
                  onChange={(e) => set({ headline: e.target.value })}
                  data-testid="iq-headline" />
        </div>
        <div className="md:col-span-2">
          <Label>Sub-headline</Label>
          <Input value={cfg.subheadline || ""}
                  onChange={(e) => set({ subheadline: e.target.value })} />
        </div>
        <div>
          <Label>Logo URL</Label>
          <Input value={cfg.logo_url || ""}
                  onChange={(e) => set({ logo_url: e.target.value })} />
        </div>
        <div>
          <Label>Success redirect URL (optional)</Label>
          <Input value={cfg.success_redirect_url || ""}
                  onChange={(e) => set({ success_redirect_url: e.target.value })} />
        </div>
      </div>

      <div>
        <div className="flex items-center justify-between">
          <h3 className="font-semibold text-sm">Services</h3>
          <Button variant="outline" size="sm" onClick={addService}
                    data-testid="iq-add-service">
            <Plus className="w-3 h-3 mr-1" /> Add service
          </Button>
        </div>
        <div className="space-y-2 mt-2">
          {(cfg.services || []).map((s, i) => (
            <div key={i} className="rounded-lg p-2 grid grid-cols-12 gap-1 items-center"
                  style={{ backgroundColor: colors.surfaceSecondary,
                            border: `1px solid ${colors.border}` }}>
              <Input className="col-span-4" value={s.name}
                      onChange={(e) => patchList("services", i, { name: e.target.value })}
                      placeholder="Service name" />
              <Input className="col-span-2" type="number"
                      value={s.base_price_cents} min={0}
                      onChange={(e) => patchList("services", i,
                          { base_price_cents: Number(e.target.value) })}
                      placeholder="cents" />
              <select className="col-span-2 border rounded p-2 text-sm"
                      value={s.unit || "visit"}
                      onChange={(e) => patchList("services", i, { unit: e.target.value })}>
                {UNITS.map((u) => <option key={u}>{u}</option>)}
              </select>
              <Input className="col-span-1" type="number" min={0}
                      value={s.min_qty}
                      onChange={(e) => patchList("services", i,
                          { min_qty: Number(e.target.value) })}
                      placeholder="min" />
              <Input className="col-span-2" type="number" min={1}
                      value={s.max_qty}
                      onChange={(e) => patchList("services", i,
                          { max_qty: Number(e.target.value) })}
                      placeholder="max" />
              <button className="col-span-1 text-red-500 p-1"
                       onClick={() => removeAt("services", i)}>
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          ))}
        </div>
      </div>

      <div>
        <div className="flex items-center justify-between">
          <h3 className="font-semibold text-sm">Add-ons</h3>
          <Button variant="outline" size="sm"
                    onClick={() => set({ add_ons: [...(cfg.add_ons || []),
                      { name: "New add-on", price_cents: 2500 }] })}>
            <Plus className="w-3 h-3 mr-1" /> Add
          </Button>
        </div>
        <div className="space-y-2 mt-2">
          {(cfg.add_ons || []).map((a, i) => (
            <div key={i} className="rounded-lg p-2 grid grid-cols-12 gap-1"
                  style={{ backgroundColor: colors.surfaceSecondary,
                            border: `1px solid ${colors.border}` }}>
              <Input className="col-span-7" value={a.name}
                      onChange={(e) => patchList("add_ons", i, { name: e.target.value })} />
              <Input className="col-span-4" type="number" value={a.price_cents}
                      onChange={(e) => patchList("add_ons", i,
                          { price_cents: Number(e.target.value) })} />
              <button className="col-span-1 text-red-500 p-1"
                       onClick={() => removeAt("add_ons", i)}>
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          ))}
        </div>
      </div>

      <div>
        <div className="flex items-center justify-between">
          <h3 className="font-semibold text-sm">Frequencies</h3>
          <Button variant="outline" size="sm"
                    onClick={() => set({ frequencies: [...(cfg.frequencies || []),
                      { label: "One-time", multiplier: 1.0 }] })}>
            <Plus className="w-3 h-3 mr-1" /> Add
          </Button>
        </div>
        <div className="space-y-2 mt-2">
          {(cfg.frequencies || []).map((f, i) => (
            <div key={i} className="rounded-lg p-2 grid grid-cols-12 gap-1"
                  style={{ backgroundColor: colors.surfaceSecondary,
                            border: `1px solid ${colors.border}` }}>
              <Input className="col-span-7" value={f.label}
                      onChange={(e) => patchList("frequencies", i, { label: e.target.value })} />
              <Input className="col-span-4" type="number" step="0.05" value={f.multiplier}
                      onChange={(e) => patchList("frequencies", i,
                          { multiplier: Number(e.target.value) })} />
              <button className="col-span-1 text-red-500 p-1"
                       onClick={() => removeAt("frequencies", i)}>
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          ))}
        </div>
      </div>

      <div>
        <h3 className="font-semibold text-sm mb-1">Collect fields</h3>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
          {["name", "email", "phone", "address", "notes"].map((k) => (
            <label key={k} className="flex items-center gap-2 text-sm">
              <Switch
                  checked={cfg.collect_fields?.[k] !== false}
                  onCheckedChange={(v) => set({
                    collect_fields: { ...(cfg.collect_fields || {}), [k]: v }
                  })}
              />
              {k}
            </label>
          ))}
        </div>
      </div>

      <div>
        <Label>Thank-you HTML</Label>
        <Textarea value={cfg.thank_you_html || ""} rows={2}
                    onChange={(e) => set({ thank_you_html: e.target.value })} />
      </div>

      <Button onClick={onSave} data-testid="iq-save">
        <Check className="w-4 h-4 mr-1" /> Save changes
      </Button>
    </div>
  );
}

// ─── Submissions ──────────────────────────────────────────────────────

function SubmissionsList({ refresh }) {
  const [subs, setSubs] = useState([]);
  const [sel, setSel] = useState(null);
  const load = useCallback(async () => {
    const r = await api.get("/instaquote/submissions?limit=100")
      .catch(() => ({ submissions: [] }));
    setSubs(r.submissions || []);
  }, []);
  useEffect(() => { load(); }, [load, refresh]);

  const convert = async (id) => {
    try {
      const r = await api.post(`/instaquote/submissions/${id}/convert`);
      toast.success(`Converted → deal ${r.deal_id?.slice(0, 6)}…`);
      setSel(null); load();
    } catch (e) {
      toast.error(e?.message || "Convert failed");
    }
  };
  const dismiss = async (id) => {
    try {
      await api.post(`/instaquote/submissions/${id}/dismiss`, { note: "" });
      toast.success("Dismissed");
      setSel(null); load();
    } catch (e) {
      toast.error(e?.message || "Dismiss failed");
    }
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4"
          data-testid="iq-submissions">
      <div className="rounded-2xl p-4"
            style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}>
        <h3 className="font-semibold mb-2">Recent submissions</h3>
        {subs.length === 0 && (
          <div className="text-sm text-center py-6"
                style={{ color: colors.muted }}>
            No submissions yet.
          </div>
        )}
        <div className="space-y-1">
          {subs.map((s) => (
            <button key={s.id}
                    onClick={() => setSel(s)}
                    className="w-full text-left rounded-lg p-2 text-sm hover:brightness-95"
                    style={{
                      backgroundColor: sel?.id === s.id
                        ? colors.surfaceSecondary : "transparent",
                      border: `1px solid ${colors.border}`,
                    }}
                    data-testid={`iq-sub-${s.id}`}>
              <div className="flex items-center justify-between">
                <div className="font-semibold truncate">
                  {s.contact?.name || s.contact?.email || "(anonymous)"}
                </div>
                <div className="flex items-center gap-1">
                  {Number(s.contact_history_count || 0) > 1 && (
                    <Badge
                      className="bg-amber-500 hover:bg-amber-600 text-white text-[10px]"
                      data-testid={`iq-returning-badge-${s.id}`}
                      title="This contact has submitted before"
                    >
                      Returning ×{s.contact_history_count}
                    </Badge>
                  )}
                  <Badge variant="outline">{s.status}</Badge>
                </div>
              </div>
              <div className="text-xs" style={{ color: colors.muted }}>
                {fmt$(s.computed_total_cents)} · {s.submitted_at?.slice(0, 16)}
              </div>
            </button>
          ))}
        </div>
      </div>

      <div className="rounded-2xl p-4"
            style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}>
        {!sel && (
          <div className="text-sm text-center py-8"
                style={{ color: colors.muted }}>
            Pick a submission to inspect / convert.
          </div>
        )}
        {sel && (
          <div className="text-sm space-y-2">
            <div className="flex items-center justify-between">
              <h3 className="font-semibold">Submission · {sel.status}</h3>
              <Badge variant="outline">{fmt$(sel.computed_total_cents)}</Badge>
            </div>
            <div>
              <div className="font-semibold">{sel.contact?.name}</div>
              <div style={{ color: colors.muted }}>{sel.contact?.email}</div>
              <div style={{ color: colors.muted }}>{sel.contact?.phone}</div>
              {sel.contact?.notes && (
                <div className="italic mt-1">"{sel.contact.notes}"</div>
              )}
            </div>
            <div className="space-y-1">
              {(sel.computed_breakdown_json || []).map((b, i) => (
                <div key={i} className="rounded p-2"
                      style={{ backgroundColor: colors.surfaceSecondary }}>
                  <div className="flex justify-between">
                    <span>{b.service_name} × {b.qty} · {b.frequency_label}</span>
                    <span className="font-semibold">{fmt$(b.line_total_cents)}</span>
                  </div>
                  {(b.add_ons || []).map((a) => (
                    <div key={a.id} className="text-xs"
                          style={{ color: colors.muted }}>
                      + {a.name} ({fmt$(a.price_cents)})
                    </div>
                  ))}
                </div>
              ))}
            </div>
            {sel.status === "new" && (
              <div className="flex gap-2 pt-2">
                <Button onClick={() => convert(sel.id)}
                          data-testid="iq-convert">
                  <Check className="w-3 h-3 mr-1" /> Convert
                </Button>
                <Button variant="outline"
                          onClick={() => dismiss(sel.id)}
                          data-testid="iq-dismiss">
                  <X className="w-3 h-3 mr-1" /> Dismiss
                </Button>
              </div>
            )}
            {sel.status === "converted" && (
              <div className="text-xs" style={{ color: colors.muted }}>
                Deal: <code>{sel.converted_deal_id}</code> · Estimate:{" "}
                <code>{sel.converted_estimate_id}</code>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Page shell ───────────────────────────────────────────────────────

export default function InstaQuoteAdminPage() {
  const nav = useNavigate();
  const [configs, setConfigs] = useState([]);
  const [cfg, setCfg] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const load = useCallback(async () => {
    const r = await api.get("/instaquote/configs").catch(() => ({ configs: [] }));
    setConfigs(r.configs || []);
    if (r.configs?.length && !cfg) setCfg(r.configs[0]);
  }, [cfg]);
  useEffect(() => { load(); }, [load]);

  const newConfig = () => {
    setCfg({
      slug: `quote-${Math.floor(Math.random() * 100000).toString(36)}`,
      headline: "Get an instant quote.",
      subheadline: "Custom pool + landscape service in under a minute.",
      brand_color: "#0284C7",
      services: DEFAULT_SERVICES,
      add_ons: [],
      frequencies: DEFAULT_FREQ,
      rules: [],
      collect_fields: { name: true, email: true, phone: true },
      thank_you_html: "Thanks — we'll be in touch shortly.",
      active: false,
    });
  };

  const save = async () => {
    try {
      if (cfg.id) {
        const patch = { ...cfg };
        delete patch.slug; delete patch.id; delete patch.tenant_id;
        delete patch.created_at; delete patch.updated_at; delete patch.active;
        const r = await api.patch(`/instaquote/configs/${cfg.id}`, patch);
        setCfg(r);
        toast.success("Saved");
      } else {
        const r = await api.post("/instaquote/configs", cfg);
        setCfg(r);
        toast.success("Created");
      }
      load();
    } catch (e) {
      toast.error(e?.message || "Save failed");
    }
  };

  const activate = async () => {
    if (!cfg?.id) return;
    try {
      await api.post(`/instaquote/configs/${cfg.id}/activate`);
      toast.success("Activated");
      load();
    } catch (e) {
      toast.error(e?.message || "Activate failed");
    }
  };

  const publicUrl = cfg?.slug
    ? `${window.location.origin}/quote/${cfg.slug}` : "";

  return (
    <div className="p-4 md:p-8 max-w-7xl mx-auto space-y-4"
          data-testid="instaquote-admin">
      <div className="flex items-center gap-3 mb-4">
        <button onClick={() => nav(-1)}
                className="p-2 rounded-lg hover:brightness-95"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}>
          <ArrowLeft size={16} />
        </button>
        <div className="flex-1">
          <h1 className="text-2xl md:text-3xl font-bold"
              style={{ color: colors.onSurface }}>
            InstaQuote
          </h1>
          <p className="text-xs mt-0.5" style={{ color: colors.muted }}>
            Public self-quote portal. One active config per tenant.
          </p>
        </div>
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        <select className="border rounded p-2 text-sm"
                value={cfg?.id || "new"}
                onChange={(e) => {
                  const v = e.target.value;
                  if (v === "new") newConfig();
                  else setCfg(configs.find((c) => c.id === v));
                }}
                data-testid="iq-config-select">
          <option value="new">+ New config</option>
          {configs.map((c) => (
            <option key={c.id} value={c.id}>
              {c.slug} {c.active ? "(active)" : ""}
            </option>
          ))}
        </select>
        {cfg?.id && (
          <>
            <Badge variant="outline">
              {cfg.active ? "Active" : "Draft"}
            </Badge>
            {!cfg.active && (
              <Button variant="outline" size="sm" onClick={activate}
                        data-testid="iq-activate">
                Activate
              </Button>
            )}
            {publicUrl && (
              <button onClick={() => {
                        navigator.clipboard.writeText(publicUrl);
                        toast.success("Public URL copied");
                      }}
                      className="text-xs px-2 py-1 rounded border flex items-center gap-1"
                      data-testid="iq-copy-url">
                <Copy className="w-3 h-3" /> {publicUrl}
              </button>
            )}
            {cfg.active && publicUrl && (
              <a href={publicUrl} target="_blank" rel="noreferrer"
                  className="text-xs px-2 py-1 rounded border flex items-center gap-1">
                <ExternalLink className="w-3 h-3" /> Open
              </a>
            )}
          </>
        )}
      </div>

      {cfg && (
        <Tabs defaultValue="builder">
          <TabsList>
            <TabsTrigger value="builder" data-testid="iq-tab-builder">
              <Palette className="w-3 h-3 mr-1" /> Builder
            </TabsTrigger>
            <TabsTrigger value="submissions"
                          onClick={() => setRefreshKey((n) => n + 1)}
                          data-testid="iq-tab-submissions">
              <ListChecks className="w-3 h-3 mr-1" /> Submissions
            </TabsTrigger>
          </TabsList>
          <TabsContent value="builder" className="mt-4">
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <Builder cfg={cfg} onChange={setCfg} onSave={save} />
              <div>
                <div className="text-xs mb-2 font-semibold"
                      style={{ color: colors.muted }}>
                  Live preview (of what customers see)
                </div>
                <PublicPreview cfg={cfg} />
              </div>
            </div>
          </TabsContent>
          <TabsContent value="submissions" className="mt-4">
            <SubmissionsList refresh={refreshKey} />
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
}
