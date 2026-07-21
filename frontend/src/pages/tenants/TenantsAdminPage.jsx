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
