import React, { useEffect, useState } from "react";
import { api } from "@/api";
import { colors, brandGradientCss } from "@/theme";
import { Plus, Check, Ban, Save } from 'lucide-react';
import AddressAutocomplete from "@/components/AddressAutocomplete";

const Card = ({ children, className = "", testId }) => (
  <div className={"rounded-2xl " + className}
       style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
       data-testid={testId}>{children}</div>
);

const emptyForm = {
  name: "", slug: "", brand_primary: "#0284C7", brand_secondary: "#16A34A",
  custom_domain: "", plan_tier: "free",
};

export default function TenantsAdminPage() {
  const [rows, setRows] = useState([]);
  const [form, setForm] = useState(emptyForm);
  const [editingId, setEditingId] = useState(null);
  const [creating, setCreating] = useState(false);
  const [toast, setToast] = useState("");
  const [error, setError] = useState("");

  const load = () => api.get("/tenants").then(setRows).catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);

  const showToast = (t) => { setToast(t); setTimeout(() => setToast(""), 2600); };

  const startCreate = () => { setEditingId(null); setForm(emptyForm); setCreating(true); };
  const startEdit = (t) => {
    setCreating(false); setEditingId(t.id);
    setForm({ ...emptyForm, ...t, custom_domain: t.custom_domain || "" });
  };
  const cancel = () => { setCreating(false); setEditingId(null); setError(""); };

  const submit = async () => {
    setError("");
    try {
      if (creating) {
        await api.post("/tenants", { ...form, custom_domain: form.custom_domain || null });
        showToast("Tenant created");
      } else if (editingId) {
        const { name, brand_primary, brand_secondary, custom_domain, plan_tier } = form;
        await api.request(`/tenants/${editingId}`, {
          method: "PATCH",
          body: JSON.stringify({ name, brand_primary, brand_secondary,
                                 custom_domain: custom_domain || null, plan_tier }),
        });
        showToast("Tenant updated");
      }
      cancel(); load();
    } catch (e) { setError(e.message || "Failed"); }
  };

  const toggleActive = async (t) => {
    await api.request(`/tenants/${t.id}`, {
      method: "PATCH",
      body: JSON.stringify({ active: !t.active }),
    });
    showToast(t.active ? "Deactivated" : "Reactivated");
    load();
  };

  return (
    <div className="p-4 md:p-8 max-w-6xl mx-auto" data-testid="tenants-admin-page">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-3xl font-bold" style={{ color: colors.onSurface }}>Tenants</h1>
          <p className="text-sm mt-1" style={{ color: colors.muted }}>
            Super-admin tools — create tenants, edit branding + plan, deactivate.
          </p>
        </div>
        <button onClick={startCreate}
                className="flex items-center gap-1 px-4 py-2 rounded-xl text-sm font-bold text-white"
                style={{ background: brandGradientCss }}
                data-testid="tenants-new-btn"><Plus size={14}/> New tenant</button>
      </div>

      {(creating || editingId) && (
        <Card className="p-5 mb-6" testId="tenants-form">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <Input label="NAME" value={form.name} onChange={(v) => setForm({ ...form, name: v })} testId="tf-name" />
            <Input label="SLUG (lowercase, digits, hyphens)" value={form.slug}
                   onChange={(v) => setForm({ ...form, slug: v })} disabled={!!editingId} testId="tf-slug" />
            <Input label="BRAND PRIMARY" value={form.brand_primary}
                   onChange={(v) => setForm({ ...form, brand_primary: v })} testId="tf-primary" />
            <Input label="BRAND SECONDARY" value={form.brand_secondary}
                   onChange={(v) => setForm({ ...form, brand_secondary: v })} testId="tf-secondary" />
            <Input label="CUSTOM DOMAIN (optional)" value={form.custom_domain}
                   onChange={(v) => setForm({ ...form, custom_domain: v })} testId="tf-domain" />
            <div>
              <label className="text-xs font-bold tracking-wide mb-1 block" style={{ color: colors.muted }}>PLAN TIER</label>
              <select value={form.plan_tier} onChange={(e) => setForm({ ...form, plan_tier: e.target.value })}
                      className="w-full px-3 py-2 rounded-lg text-sm outline-none"
                      style={{ border: `1px solid ${colors.border}`, backgroundColor: colors.surface, color: colors.onSurface }}
                      data-testid="tf-plan">
                {["free", "pro", "enterprise"].map((p) => <option key={p}>{p}</option>)}
              </select>
            </div>
          </div>
          {error && <div className="mt-3 text-sm" style={{ color: colors.error }}>{error}</div>}
          <div className="flex gap-2 mt-4">
            <button onClick={submit}
                    className="flex items-center gap-1 px-4 py-2 rounded-xl text-sm font-bold text-white"
                    style={{ background: brandGradientCss }}
                    data-testid="tf-submit">
              <Save size={14} /> {creating ? "Create" : "Save"}
            </button>
            <button onClick={cancel}
                    className="px-4 py-2 rounded-xl text-sm font-semibold"
                    style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface }}
                    data-testid="tf-cancel">Cancel</button>
          </div>
        </Card>
      )}

      <Card className="overflow-hidden" testId="tenants-table">
        <div className="grid grid-cols-12 gap-2 px-4 py-2 text-xs font-bold uppercase tracking-wide"
             style={{ color: colors.muted, backgroundColor: colors.surfaceSecondary, borderBottom: `1px solid ${colors.border}` }}>
          <div className="col-span-3">Name</div>
          <div className="col-span-2">Slug</div>
          <div className="col-span-2">Plan</div>
          <div className="col-span-3">Custom domain</div>
          <div className="col-span-1">Active</div>
          <div className="col-span-1 text-right">Actions</div>
        </div>
        {rows.map((t) => (
          <div key={t.id} className="grid grid-cols-12 gap-2 px-4 py-3 text-sm"
               style={{ borderBottom: `1px solid ${colors.border}`, color: colors.onSurface }}
               data-testid={`tenant-row-${t.id}`}>
            <div className="col-span-3 font-semibold">{t.name}</div>
            <div className="col-span-2 font-mono text-xs" style={{ color: colors.muted }}>{t.slug}</div>
            <div className="col-span-2 uppercase text-xs font-bold" style={{ color: colors.brand }}>{t.plan_tier}</div>
            <div className="col-span-3 text-xs" style={{ color: colors.muted }}>{t.custom_domain || "—"}</div>
            <div className="col-span-1">
              {t.active ? <Check size={14} style={{ color: "#16A34A" }} /> : <Ban size={14} style={{ color: "#DC2626" }} />}
            </div>
            <div className="col-span-1 flex justify-end gap-1">
              <button onClick={() => startEdit(t)} data-testid={`tenant-edit-${t.id}`}
                      className="px-2 py-1 rounded text-xs font-semibold"
                      style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface }}>
                Edit
              </button>
              <button onClick={() => toggleActive(t)} data-testid={`tenant-toggle-${t.id}`}
                      className="px-2 py-1 rounded text-xs font-semibold"
                      style={{ backgroundColor: t.active ? "#FEE2E2" : "#DCFCE7",
                               color: t.active ? "#991B1B" : "#166534" }}>
                {t.active ? "Deactivate" : "Reactivate"}
              </button>
            </div>
          </div>
        ))}
        {rows.length === 0 && <div className="p-6 text-center text-sm" style={{ color: colors.muted }}>No tenants.</div>}
      </Card>

      {toast && (
        <div className="fixed bottom-6 right-6 z-50 px-4 py-2 rounded-xl text-sm text-white shadow-lg"
             style={{ backgroundColor: colors.onSurface }}
             data-testid="tenants-toast">{toast}</div>
      )}
    </div>
  );
}

function Input({ label, value, onChange, testId, disabled }) {
  return (
    <label className="block">
      <div className="text-xs font-bold tracking-wide mb-1" style={{ color: colors.muted }}>{label}</div>
      <input value={value || ""} onChange={(e) => onChange(e.target.value)} disabled={disabled}
             className="w-full px-3 py-2 rounded-lg text-sm outline-none"
             style={{ border: `1px solid ${colors.border}`, backgroundColor: colors.surface, color: colors.onSurface,
                      opacity: disabled ? 0.6 : 1 }}
             data-testid={testId} />
    </label>
  );
}

/* ═══════════ /settings/tenant ═════════════════════════════════════════════ */
export function TenantBrandSettings() {
  const [tenant, setTenant] = useState(null);
  const [primary, setPrimary] = useState("#0284C7");
  const [secondary, setSecondary] = useState("#16A34A");
  const [logoUrl, setLogoUrl] = useState("");
  const [toast, setToast] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    api.get("/tenants/current").then((t) => {
      setTenant(t);
      setPrimary(t.brand_primary || "#0284C7");
      setSecondary(t.brand_secondary || "#16A34A");
    }).catch((e) => setError(e.message));
  }, []);

  const save = async () => {
    setError("");
    try {
      const r = await api.request("/tenants/mine/brand", {
        method: "PATCH",
        body: JSON.stringify({ brand_primary: primary, brand_secondary: secondary,
                               logo_url: logoUrl || null }),
      });
      setTenant(r);
      setToast("Brand saved"); setTimeout(() => setToast(""), 2500);
    } catch (e) { setError(e.message || "Failed"); }
  };

  if (!tenant) return <div className="p-8 text-sm" style={{ color: colors.muted }}>Loading…</div>;

  return (
    <div className="p-4 md:p-8 max-w-3xl mx-auto" data-testid="tenant-brand-settings">
      <h1 className="text-3xl font-bold mb-1" style={{ color: colors.onSurface }}>Tenant Brand</h1>
      <p className="text-sm mb-6" style={{ color: colors.muted }}>
        Customize the brand colors + logo for <b>{tenant.name}</b>. To rename or change plan tier, contact your super-admin.
      </p>

      <Card className="p-5" testId="brand-editor">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Input label="PRIMARY COLOR" value={primary} onChange={setPrimary} testId="brand-primary" />
          <Input label="SECONDARY COLOR" value={secondary} onChange={setSecondary} testId="brand-secondary" />
        </div>
        <div className="mt-4">
          <Input label="LOGO URL (optional)" value={logoUrl} onChange={setLogoUrl} testId="brand-logo" />
        </div>

        <div className="mt-6 p-6 rounded-xl text-white text-center"
             style={{ background: `linear-gradient(135deg, ${primary} 0%, ${secondary} 100%)` }}
             data-testid="brand-preview">
          <div className="text-lg font-bold">{tenant.name}</div>
          <div className="text-xs opacity-90 mt-1">Brand preview — gradient will apply across public forms + emails.</div>
        </div>

        {error && <div className="mt-3 text-sm" style={{ color: colors.error }}>{error}</div>}
        <div className="mt-4 flex gap-2">
          <button onClick={save}
                  className="flex items-center gap-1 px-4 py-2 rounded-xl text-sm font-bold text-white"
                  style={{ background: brandGradientCss }}
                  data-testid="brand-save"><Save size={14} /> Save brand</button>
        </div>
      </Card>

      {toast && (
        <div className="fixed bottom-6 right-6 z-50 px-4 py-2 rounded-xl text-sm text-white shadow-lg"
             style={{ backgroundColor: colors.onSurface }}
             data-testid="brand-toast">{toast}</div>
      )}

      {/* Feb-2026 · HQ Location — super-admin only. The rest of the
          page above is admin-visible, so we self-gate this card. */}
      <HqLocationCard />
      {/* Feb-2026 · Slice 6 · Google Review URL — super-admin only. */}
      <GoogleReviewUrlCard />
      {/* Feb-2026 · Slice GH0 · Website Widget config — super-admin only. */}
      <WidgetConfigCard />
    </div>
  );
}


/* ═══════════ Slice GH0 · Website Widget config ═════════════════════════ */
function WidgetConfigCard() {
  const [me, setMe] = useState(null);
  const [cfg, setCfg] = useState(null);
  const [domainsText, setDomainsText] = useState("");
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    api.get("/auth/me").then(setMe).catch(() => {});
    api.get("/tenants/mine/widget-config")
      .then((r) => {
        setCfg(r);
        setDomainsText((r.widget_allowed_domains || []).join("\n"));
      })
      .catch(() => {});
  }, []);

  if (!me || me.role !== "super_admin" || !cfg) return null;

  const copy = () => {
    try { navigator.clipboard?.writeText(cfg.public_widget_key); }
    catch { /* graceful — some browsers block clipboard */ }
    setToast("Key copied");
    setTimeout(() => setToast(""), 2000);
  };

  const regenerate = async () => {
    if (!window.confirm("Rotate the widget key? Existing widget embeds using the old key will stop working until you update them.")) return;
    setBusy(true); setError("");
    try {
      const r = await api.post(
        "/tenants/mine/widget-config/regenerate-key", {},
      );
      setCfg((c) => ({ ...c, public_widget_key: r.public_widget_key }));
      setToast("New key generated");
      setTimeout(() => setToast(""), 2000);
    } catch (e) { setError(e?.message || "Regenerate failed"); }
    finally { setBusy(false); }
  };

  const save = async () => {
    setBusy(true); setError("");
    try {
      const domains = domainsText
        .split(/[\n,]/)
        .map((s) => s.trim())
        .filter(Boolean);
      const r = await api.patch(
        "/tenants/mine/widget-config/domains",
        { widget_allowed_domains: domains },
      );
      setCfg((c) => ({ ...c, widget_allowed_domains: r.widget_allowed_domains }));
      setDomainsText((r.widget_allowed_domains || []).join("\n"));
      setToast("Allowed domains saved");
      setTimeout(() => setToast(""), 2000);
    } catch (e) { setError(e?.message || "Save failed"); }
    finally { setBusy(false); }
  };

  return (
    <Card className="p-5 mt-6" testId="tenant-widget-card">
      <h2 className="text-lg font-bold mb-1" style={{ color: colors.onSurface }}>
        Website Widget
      </h2>
      <p className="text-sm mb-4" style={{ color: colors.muted }}>
        The public key identifies your widget on customer sites (like a
        Stripe publishable key — safe to expose). Widgets only load on
        the exact domains you list below.
      </p>

      <div className="mb-4">
        <div className="text-[10px] font-bold uppercase tracking-wider mb-1"
             style={{ color: colors.muted }}>
          Public widget key
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <code className="px-3 py-2 rounded-lg text-sm font-mono flex-1 min-w-0 break-all"
                style={{ backgroundColor: colors.surfaceSecondary,
                         color: colors.onSurface,
                         border: `1px solid ${colors.border}` }}
                data-testid="tenant-widget-key">
            {cfg.public_widget_key}
          </code>
          <button onClick={copy}
                  className="px-3 py-2 rounded-lg text-xs font-semibold"
                  style={{ backgroundColor: colors.surfaceSecondary,
                           color: colors.onSurface,
                           border: `1px solid ${colors.border}` }}
                  data-testid="tenant-widget-key-copy">
            Copy
          </button>
          <button onClick={regenerate} disabled={busy}
                  className="px-3 py-2 rounded-lg text-xs font-semibold disabled:opacity-50"
                  style={{ backgroundColor: colors.surfaceSecondary,
                           color: colors.error,
                           border: `1px solid ${colors.border}` }}
                  data-testid="tenant-widget-key-regenerate-btn">
            Regenerate
          </button>
        </div>
      </div>

      <div>
        <div className="text-[10px] font-bold uppercase tracking-wider mb-1"
             style={{ color: colors.muted }}>
          Allowed domains (one per line)
        </div>
        <textarea rows={4} value={domainsText}
                  onChange={(e) => setDomainsText(e.target.value)}
                  placeholder="www.example.com&#10;shop.example.com"
                  className="w-full px-3 py-2 rounded-lg text-sm outline-none font-mono"
                  style={{ backgroundColor: colors.surface,
                           color: colors.onSurface,
                           border: `1px solid ${colors.border}` }}
                  data-testid="tenant-widget-domains-input" />
        <div className="text-[10px] mt-1" style={{ color: colors.muted }}>
          Widgets refuse to load anywhere else. Add
          <b> {window.location.host} </b>for local dev.
        </div>
      </div>

      {error && <div className="mt-3 text-sm" style={{ color: colors.error }}>{error}</div>}
      {toast && <div className="mt-2 text-sm" style={{ color: colors.brand }}>{toast}</div>}

      <div className="mt-4 flex justify-end">
        <button onClick={save} disabled={busy}
                className="inline-flex items-center gap-1 px-4 py-2 rounded-xl text-sm font-bold text-white disabled:opacity-50"
                style={{ background: brandGradientCss }}
                data-testid="tenant-widget-config-save-btn">
          <Save size={14} /> {busy ? "Saving…" : "Save allowed domains"}
        </button>
      </div>

      {/* Feb-2026 · Slice G3 — auto-generated embed snippet with
          copy-to-clipboard + live preview iframe + denied-requests
          ring buffer. Everything below is admin-visible. */}
      <WidgetEmbedSnippetSection publicKey={cfg.public_widget_key} />
      <WidgetDeniedRequestsSection />
    </Card>
  );
}


/* ═══════════ Slice G3 · Embed snippet + live preview ═══════════════════ */
function WidgetEmbedSnippetSection({ publicKey }) {
  const [copied, setCopied] = useState(false);
  const [previewNonce, setPreviewNonce] = useState(0);
  const publicUrl = window.location.origin;
  const snippet =
    `<script async defer\n  src="${publicUrl}/widget/chat.js"\n  data-widget-key="${publicKey}"></script>`;

  const copySnippet = () => {
    try { navigator.clipboard?.writeText(snippet); } catch { /* graceful */ }
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="mt-6 pt-5" style={{ borderTop: `1px solid ${colors.border}` }}>
      <h3 className="text-sm font-bold mb-1" style={{ color: colors.onSurface }}>
        Embed snippet
      </h3>
      <p className="text-xs mb-3" style={{ color: colors.muted }}>
        Paste this into your marketing site's HTML. The chat bubble appears
        automatically once the page loads.
      </p>
      <pre className="text-xs font-mono p-3 rounded-lg overflow-x-auto"
           style={{ backgroundColor: colors.surfaceSecondary,
                    border: `1px solid ${colors.border}`,
                    color: colors.onSurface }}
           data-testid="widget-embed-snippet-code">
{snippet}
      </pre>
      <div className="flex items-center gap-2 mt-2">
        <button onClick={copySnippet}
                className="px-3 py-1.5 rounded-lg text-xs font-semibold"
                style={{ backgroundColor: colors.surfaceSecondary,
                         color: colors.onSurface,
                         border: `1px solid ${colors.border}` }}
                data-testid="widget-embed-copy-btn">
          {copied ? "Copied ✓" : "Copy to clipboard"}
        </button>
        <button onClick={() => setPreviewNonce((n) => n + 1)}
                className="px-3 py-1.5 rounded-lg text-xs font-semibold"
                style={{ backgroundColor: colors.surfaceSecondary,
                         color: colors.onSurface,
                         border: `1px solid ${colors.border}` }}
                data-testid="widget-embed-preview-refresh-btn">
          Refresh preview
        </button>
      </div>

      <div className="mt-4">
        <div className="text-[10px] font-bold uppercase tracking-wider mb-2"
             style={{ color: colors.muted }}>
          Live preview
        </div>
        <iframe
          key={previewNonce}
          src={`/widget-demo?key=${encodeURIComponent(publicKey)}&t=${previewNonce}`}
          title="Widget live preview"
          data-testid="widget-embed-preview-iframe"
          style={{
            width: "100%",
            height: "480px",
            border: `1px solid ${colors.border}`,
            borderRadius: "12px",
            background: "#fff",
          }}
        />
      </div>
    </div>
  );
}


/* ═══════════ Slice G3 · Denied-requests ring buffer viewer ═════════════ */
function WidgetDeniedRequestsSection() {
  const [rows, setRows] = useState([]);
  const [expanded, setExpanded] = useState(false);
  const [loading, setLoading] = useState(false);

  const refresh = () => {
    setLoading(true);
    api.get("/tenants/mine/widget-config/denied-requests")
      .then((r) => setRows(r.denied || []))
      .catch(() => setRows([]))
      .finally(() => setLoading(false));
  };
  useEffect(() => { refresh(); }, []);

  if (!rows.length && !loading) {
    return (
      <div className="mt-6 pt-5" style={{ borderTop: `1px solid ${colors.border}` }}>
        <h3 className="text-sm font-bold mb-1" style={{ color: colors.onSurface }}
            data-testid="widget-denied-requests-heading">
          Recent denied requests
        </h3>
        <p className="text-xs" style={{ color: colors.muted }}
           data-testid="widget-denied-requests-empty">
          No rejections in memory. Any widget request that fails
          origin/key checks will appear here (up to 50, cleared on
          backend restart).
        </p>
      </div>
    );
  }

  const visible = expanded ? rows : rows.slice(0, 10);

  const reasonPill = (r) => {
    const map = {
      foreign_origin: { bg: "#FEE2E2", fg: "#991B1B", label: "foreign origin" },
      no_origin: { bg: "#FEF3C7", fg: "#854D0E", label: "no origin/referer" },
      invalid_key: { bg: "#EDE9FE", fg: "#5B21B6", label: "invalid key" },
      missing_key: { bg: "#F3F4F6", fg: "#374151", label: "missing key" },
      empty_allowlist: { bg: "#DBEAFE", fg: "#1E3A8A", label: "empty allowlist" },
    };
    const c = map[r] || { bg: "#F3F4F6", fg: "#374151", label: r };
    return (
      <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold"
            style={{ backgroundColor: c.bg, color: c.fg }}>
        {c.label}
      </span>
    );
  };

  return (
    <div className="mt-6 pt-5" style={{ borderTop: `1px solid ${colors.border}` }}>
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-bold" style={{ color: colors.onSurface }}
            data-testid="widget-denied-requests-heading">
          Recent denied requests ({rows.length})
        </h3>
        <button onClick={refresh}
                className="text-xs font-semibold px-2 py-1 rounded-lg"
                style={{ color: colors.brand,
                         border: `1px solid ${colors.border}` }}
                data-testid="widget-denied-refresh-btn">
          Refresh
        </button>
      </div>
      <div className="rounded-lg overflow-hidden"
           style={{ border: `1px solid ${colors.border}` }}
           data-testid="widget-denied-requests-list">
        {visible.map((row, idx) => (
          <div key={row.at + idx}
               data-testid={`widget-denied-request-row-${idx}`}
               className="px-3 py-2 flex items-center gap-3 text-xs"
               style={{
                 borderBottom: idx < visible.length - 1 ? `1px solid ${colors.border}` : undefined,
                 backgroundColor: idx % 2 ? colors.surfaceSecondary : "transparent",
               }}>
            <div className="whitespace-nowrap" style={{ color: colors.muted, minWidth: 90 }}>
              {row.at.slice(11, 19)}
            </div>
            <div>{reasonPill(row.reason)}</div>
            <div className="truncate flex-1" style={{ color: colors.onSurface }}>
              {row.origin || row.referer || row.x_forwarded_origin || "—"}
            </div>
            <div className="hidden sm:block whitespace-nowrap"
                 style={{ color: colors.muted }}>
              {row.path}
            </div>
          </div>
        ))}
      </div>
      {rows.length > 10 && (
        <button onClick={() => setExpanded((v) => !v)}
                className="mt-2 text-xs font-semibold"
                style={{ color: colors.brand }}
                data-testid="widget-denied-expand-btn">
          {expanded ? "Show only 10" : `Show all ${rows.length}`}
        </button>
      )}
    </div>
  );
}

function HqLocationCard() {
  const [me, setMe] = useState(null);
  const [existing, setExisting] = useState(null);
  const [address, setAddress] = useState("");
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    api.get("/auth/me").then(setMe).catch(() => setMe({}));
  }, []);

  const isSuper = me && me.role === "super_admin";

  useEffect(() => {
    if (!isSuper) return;
    api.get("/tenants/mine/geocode").then((r) => {
      setExisting(r);
      setAddress(r?.hq_address || "");
    }).catch(() => setExisting({}));
  }, [isSuper]);

  if (!me) return null;
  if (!isSuper) return null;

  const saveAddress = async (addr) => {
    setError("");
    setBusy(true);
    try {
      const r = await api.request("/tenants/mine/geocode", {
        method: "PATCH",
        body: JSON.stringify({ address: addr }),
      });
      setExisting(r);
      // Invalidate the module-level tenant-location cache so the
      // weather widget re-fetches without a full page reload.
      try {
        const { invalidateTenantLocation } = await import("@/hooks/useTenantLocation");
        invalidateTenantLocation();
      } catch { /* ignore */ }
      setToast("HQ location saved");
      setTimeout(() => setToast(""), 2500);
    } catch (e) {
      setError(e.message || "Failed to save");
    } finally {
      setBusy(false);
    }
  };

  const onSaveClick = () => {
    const trimmed = (address || "").trim();
    if (!trimmed || trimmed.length < 3) return;
    saveAddress(trimmed);
  };

  // Feb-2026 · Google Places Autocomplete on the HQ input. When the
  // user picks a suggestion we auto-save immediately using the
  // Google-normalised formatted string — no need to click "Save".
  // Raw text is still honoured via the Save button, so a user who
  // types without picking a suggestion can still submit.
  const onPlaceSelect = (place) => {
    const formatted = place?.formatted || place?.description || address;
    if (formatted) {
      setAddress(formatted);
      saveAddress(formatted);
    }
  };

  return (
    <div className="mt-6" data-testid="tenant-hq-card">
      <div className="rounded-2xl p-5" style={{ background: colors.surface, border: `1px solid ${colors.border}` }}>
        <div className="text-sm font-bold uppercase tracking-wider mb-2" style={{ color: colors.onSurface }}>
          HQ Location
        </div>
        <p className="text-xs mb-4" style={{ color: colors.muted }}>
          Enter your headquarters address. We&apos;ll geocode it once via Google Places and anchor the weather widget + forecast on this location for every user in your tenant. Super-admin only.
        </p>
        <div className="flex flex-col sm:flex-row gap-2 items-stretch">
          <div className="flex-1 min-w-0">
            <AddressAutocomplete
              value={address}
              onChange={setAddress}
              onSelect={onPlaceSelect}
              placeholder="e.g. 10840 W Saddlehorn Rd, Peoria AZ 85383"
              testid="tenant-hq-address"
            />
          </div>
          <button
            onClick={onSaveClick}
            disabled={busy || !address.trim() || address.trim().length < 3}
            className="px-4 py-2 rounded-lg text-sm font-bold text-white shrink-0"
            style={{ background: colors.brand, opacity: busy ? 0.6 : 1 }}
            data-testid="tenant-hq-save-btn"
          >
            {busy ? "Saving…" : "Save"}
          </button>
        </div>
        {existing?.hq_lat != null && existing?.hq_lng != null ? (
          <div className="mt-3 rounded-lg px-3 py-2 text-xs"
                style={{ background: colors.surfaceSecondary, color: colors.onSurfaceSecondary }}
                data-testid="tenant-hq-current">
            <div>
              <span className="font-semibold">Currently stored:</span>{" "}
              {existing.hq_address_formatted || existing.hq_address}
            </div>
            <div className="mt-1 opacity-80">
              lat <b data-testid="tenant-hq-lat">{existing.hq_lat.toFixed(6)}</b>
              {" · "}
              lng <b data-testid="tenant-hq-lng">{existing.hq_lng.toFixed(6)}</b>
              {existing.hq_geocoded_at ? (
                <span className="ml-2 opacity-60">
                  (geocoded {String(existing.hq_geocoded_at).slice(0, 10)})
                </span>
              ) : null}
            </div>
          </div>
        ) : null}
        {error ? (
          <div className="mt-3 text-sm" style={{ color: colors.error }}
                data-testid="tenant-hq-error">{error}</div>
        ) : null}
        {toast ? (
          <div className="fixed bottom-6 right-6 z-50 px-4 py-2 rounded-xl text-sm text-white shadow-lg"
                style={{ backgroundColor: colors.onSurface }}
                data-testid="tenant-hq-toast">{toast}</div>
        ) : null}
      </div>
    </div>
  );
}

// Feb-2026 · Slice 6 — Super-admin only card for the tenant's Google
// review URL.  Backend read is auth-any, but write is 403 for
// anything below super_admin — we self-gate the UI to reduce noise
// on the page for regular admins.
function GoogleReviewUrlCard() {
  const [me, setMe] = React.useState(null);
  const [url, setUrl] = React.useState("");
  const [current, setCurrent] = React.useState(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [toast, setToast] = React.useState("");

  React.useEffect(() => {
    api.get("/auth/me").then(setMe).catch(() => setMe(null));
  }, []);
  const isSuper = me && me.role === "super_admin";
  React.useEffect(() => {
    if (!isSuper) return;
    api
      .get("/tenants/mine/google-review-url")
      .then((r) => {
        setCurrent(r.url);
        setUrl(r.url || "");
      })
      .catch(() => setCurrent(null));
  }, [isSuper]);

  if (!isSuper) return null;

  const save = async () => {
    setBusy(true);
    setError("");
    try {
      const r = await api.patch("/tenants/mine/google-review-url", {
        url: url.trim(),
      });
      setCurrent(r.url);
      setToast("Saved");
      setTimeout(() => setToast(""), 2500);
    } catch (err) {
      // Server 422 messages come through as "Bad request" — surface
      // the raw explanation the router returns so a super-admin
      // knows what shape to paste.
      setError(err?.message || "Save failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="mt-6 rounded-2xl p-6"
      style={{
        backgroundColor: "var(--color-surface)",
        border: "1px solid var(--color-border)",
      }}
      data-testid="tenant-google-review-card"
    >
      <div className="flex items-center gap-2 mb-2">
        <span
          className="inline-flex items-center justify-center w-8 h-8 rounded-lg"
          style={{ backgroundColor: "#FEF3C7", color: "#92400E" }}
        >
          ★
        </span>
        <h2
          className="text-lg font-bold"
          style={{ color: "var(--color-on-surface)" }}
        >
          Google Review URL
        </h2>
      </div>
      <p
        className="text-sm mb-3"
        style={{ color: "var(--color-muted)" }}
      >
        Happy customers (4-5 stars) will be prompted to share on Google.
        Paste the tenant's Google Business review link below. Accepted
        formats: <code className="text-xs">https://g.page/r/…/review</code>,{" "}
        <code className="text-xs">
          https://search.google.com/local/writereview?placeid=…
        </code>
        .
      </p>
      <input
        type="url"
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        placeholder="https://g.page/r/..."
        className="w-full px-3 py-2 rounded-lg text-sm outline-none"
        style={{
          backgroundColor: "var(--color-surface)",
          color: "var(--color-on-surface)",
          border: "1px solid var(--color-border)",
        }}
        data-testid="tenant-google-review-url-input"
      />
      {error ? (
        <div
          className="mt-2 text-sm"
          style={{ color: "var(--color-error)" }}
          data-testid="tenant-google-review-url-error"
        >
          {error}
        </div>
      ) : null}
      <div className="mt-3 flex items-center justify-between gap-2">
        <div className="text-xs" style={{ color: "var(--color-muted)" }}>
          {current ? (
            <>
              Currently saved:{" "}
              <a
                href={current}
                target="_blank"
                rel="noopener noreferrer"
                className="font-semibold"
                style={{ color: "var(--color-brand)" }}
              >
                {current.length > 60
                  ? current.slice(0, 57) + "…"
                  : current}
              </a>
            </>
          ) : (
            "No Google review URL configured yet."
          )}
        </div>
        <button
          onClick={save}
          disabled={busy}
          className="px-4 py-2 rounded-xl text-sm font-bold text-white disabled:opacity-50"
          style={{ background: "var(--color-brand)" }}
          data-testid="tenant-google-review-url-save-btn"
        >
          {busy ? "Saving…" : "Save URL"}
        </button>
      </div>
      {toast ? (
        <div
          className="mt-3 text-xs font-semibold"
          style={{ color: "var(--color-success)" }}
          data-testid="tenant-google-review-url-toast"
        >
          {toast}
        </div>
      ) : null}
    </div>
  );
}

