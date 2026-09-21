/**
 * BusinessSettings — Feb-2026.
 *
 * Admin-only settings page bundling company defaults + brand colours
 * + logo upload/remove. Consumed by the queued Theme Refresh phase
 * on Estimates / Quotes / Invoices / customer emails.
 *
 * Routes:
 *   GET    /api/tenants/me/business-settings
 *   PATCH  /api/tenants/me/business-settings
 *   POST   /api/tenants/me/logo   (multipart)
 *   DELETE /api/tenants/me/logo
 *
 * See /app/memory/FEATURE_BUSINESS_SETTINGS.md.
 */
import React from "react";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import { Image as ImageIcon, Trash2, Loader2, Upload } from "lucide-react";
import { api, api_base, TOKEN_KEY } from "@/api";
import { colors } from "@/theme";
import { TimezoneSelect } from "@/components/settings/TimezoneSelect";
import PaymentProvidersCard from "@/components/settings/PaymentProvidersCard";

const HEX_RE = /^#[0-9a-fA-F]{6}$/;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const MAX_LOGO_BYTES = 2 * 1024 * 1024;
const ALLOWED_MIME = new Set([
  "image/png", "image/jpeg", "image/jpg",
  "image/webp", "image/svg+xml",
]);

function toAbsolute(url) {
  if (!url) return null;
  if (url.startsWith("http://") || url.startsWith("https://")
      || url.startsWith("data:")) return url;
  const base = api_base();
  const origin = base.endsWith("/api") ? base.slice(0, -4) : base;
  return `${origin}${url.startsWith("/") ? "" : "/"}${url}`;
}


function _validate(fields) {
  const errs = {};
  if (fields.brand_primary_hex && !HEX_RE.test(fields.brand_primary_hex)) {
    errs.brand_primary_hex = "Use #RRGGBB";
  }
  if (fields.brand_secondary_hex && !HEX_RE.test(fields.brand_secondary_hex)) {
    errs.brand_secondary_hex = "Use #RRGGBB";
  }
  if (fields.email && !EMAIL_RE.test(fields.email)) {
    errs.email = "Invalid email";
  }
  return errs;
}


export default function BusinessSettings() {
  const { t } = useTranslation("common");
  const [loading, setLoading] = React.useState(true);
  const [saving, setSaving] = React.useState(false);
  const [savingTz, setSavingTz] = React.useState(false);
  const [tenantTz, setTenantTz] = React.useState("America/Phoenix");
  const [logoBusy, setLogoBusy] = React.useState(false);
  const [dirty, setDirty] = React.useState(false);
  const [fields, setFields] = React.useState({
    company_display_name: "",
    mailing_address: "",
    phone: "",
    website: "",
    email: "",
    brand_primary_hex: "",
    brand_secondary_hex: "",
    footer_note: "",
    tax_id: "",
    // Feb-2026 · Routing Traffic-Aware phase — bool toggle. Kept in
    // the same fields state so the dirty-tracking + Save gating
    // paths pick it up without a second reducer.
    routing_traffic_aware: false,
  });

  // Feb-2026 · UX Polish Batch B follow-up — Email preview panel state.
  // Fetches ``GET /api/tenants/me/email-preview?template=<n>`` and
  // renders the returned HTML inside an <iframe srcDoc>. Zero PII —
  // the backend uses synthetic stub payloads.
  const [previewTemplate, setPreviewTemplate] = React.useState("");
  const [previewHtml, setPreviewHtml] = React.useState("");
  const [previewLoading, setPreviewLoading] = React.useState(false);

  React.useEffect(() => {
    if (!previewTemplate) {
      setPreviewHtml("");
      return;
    }
    let cancelled = false;
    setPreviewLoading(true);
    setPreviewHtml("");
    api.get(`/tenants/me/email-preview?template=${previewTemplate}`)
      .then((r) => { if (!cancelled) setPreviewHtml(r?.html || ""); })
      .catch(() => { if (!cancelled) setPreviewHtml(""); })
      .finally(() => { if (!cancelled) setPreviewLoading(false); });
    return () => { cancelled = true; };
  }, [previewTemplate]);
  const [effective, setEffective] = React.useState({});
  const [logoUrl, setLogoUrl] = React.useState(null);

  const reload = React.useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.get("/tenants/me/business-settings");
      const stored = r?.stored || {};
      setFields({
        company_display_name: stored.company_display_name || "",
        mailing_address: stored.mailing_address || "",
        phone: stored.phone || "",
        website: stored.website || "",
        email: stored.email || "",
        brand_primary_hex: stored.brand_primary_hex || "",
        brand_secondary_hex: stored.brand_secondary_hex || "",
        footer_note: stored.footer_note || "",
        tax_id: stored.tax_id || "",
        // Feb-2026 · Routing Traffic-Aware phase — coerce the stored
        // bool to a real ``false`` when unset so the toggle isn't
        // ``undefined``.
        routing_traffic_aware: !!(
          stored.routing_traffic_aware ??
          r?.effective?.routing_traffic_aware ??
          false
        ),
      });
      setEffective(r?.effective || {});
      setLogoUrl(stored.logo_url || r?.effective?.logo_url || null);
      setDirty(false);
      // Feb-2026 · Timezone Finalization — the tenant-wide timezone
      // is a separate tenant-settings field owned by the
      // /api/tenants/mine/settings endpoint (not business-settings).
      // We fetch it alongside so both pages surface the picker on the
      // same tenant-wide value.
      try {
        const tenantDoc = await api.get("/tenants/mine/settings");
        setTenantTz(tenantDoc?.timezone || "America/Phoenix");
      } catch {
        // Non-fatal — page still renders with the default TZ shown
        // in the picker; the picker's save path will still work.
      }
    } catch (e) {
      toast.error(e?.message || "Failed to load settings");
    } finally {
      setLoading(false);
    }
  }, []);
  React.useEffect(() => { reload(); }, [reload]);

  const errs = _validate(fields);
  const canSave = dirty && Object.keys(errs).length === 0 && !saving;

  const onChange = (key) => (e) => {
    const v = e?.target?.value ?? "";
    setFields((f) => ({ ...f, [key]: v }));
    setDirty(true);
  };

  const onSave = async () => {
    if (!canSave) return;
    setSaving(true);
    try {
      const patch = {};
      for (const [k, v] of Object.entries(fields)) {
        if (typeof v === "boolean") {
          // Feb-2026 · Routing Traffic-Aware phase — bools ship
          // through as-is; the trim-empty-to-null rule below is
          // string-only.
          patch[k] = v;
        } else {
          patch[k] = v.trim() === "" ? null : v;
        }
      }
      const r = await api.patch("/tenants/me/business-settings", patch);
      setEffective(r?.effective || {});
      setDirty(false);
      toast.success("Business Settings saved");
    } catch (e) {
      toast.error(e?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const onLogoPick = async (e) => {
    const file = e?.target?.files?.[0];
    if (!file) return;
    if (!ALLOWED_MIME.has(file.type)) {
      toast.error("Logo must be PNG / JPEG / WEBP / SVG");
      e.target.value = "";
      return;
    }
    if (file.size > MAX_LOGO_BYTES) {
      toast.error("Logo exceeds 2 MB");
      e.target.value = "";
      return;
    }
    setLogoBusy(true);
    try {
      const fd = new FormData();
      fd.append("logo", file);
      const tok = localStorage.getItem(TOKEN_KEY);
      const r = await fetch(`${api_base()}/tenants/me/logo`, {
        method: "POST",
        headers: tok ? { Authorization: `Bearer ${tok}` } : {},
        body: fd,
      });
      if (!r.ok) throw new Error(await r.text());
      const body = await r.json();
      setLogoUrl(body.logo_url);
      toast.success("Logo uploaded");
    } catch (err) {
      toast.error(err?.message || "Upload failed");
    } finally {
      setLogoBusy(false);
      e.target.value = "";
    }
  };

  const onLogoRemove = async () => {
    if (!window.confirm("Remove the current logo?")) return;
    setLogoBusy(true);
    try {
      await api.del("/tenants/me/logo");
      setLogoUrl(null);
      toast.success("Logo removed");
    } catch (e) {
      toast.error(e?.message || "Remove failed");
    } finally {
      setLogoBusy(false);
    }
  };

  const _primary = fields.brand_primary_hex || effective.brand_primary_hex || "#0B4A6F";
  const _secondary = fields.brand_secondary_hex || effective.brand_secondary_hex || "#F97316";

  return (
    <div className="max-w-5xl mx-auto px-4 py-6"
          data-testid="business-settings-page">
      <div className="mb-6">
        <h1 className="text-2xl md:text-3xl font-bold"
             style={{ color: colors.onSurface }}
             data-testid="business-settings-title">
          Business Settings
        </h1>
        <p className="text-sm mt-1" style={{ color: colors.muted }}>
          Company defaults + brand identity used on Estimates,
          Quotes, Invoices, and customer emails.
        </p>
      </div>

      {loading ? (
        <div className="flex items-center gap-2 py-8"
              data-testid="business-settings-loading">
          <Loader2 className="animate-spin" size={18} />
          <span>Loading…</span>
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* ── Company ─────────────────────────────────────── */}
          <section className="lg:col-span-2 bg-white rounded-lg border p-5"
                    style={{ borderColor: colors.border }}
                    data-testid="business-settings-company-section">
            <h2 className="text-lg font-semibold mb-4">Company</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <Field label="Display name"
                      testid="bs-company-display-name"
                      value={fields.company_display_name}
                      onChange={onChange("company_display_name")}
                      placeholder="Aquaterra Landscaping" />
              <Field label="Phone"
                      testid="bs-phone"
                      value={fields.phone}
                      onChange={onChange("phone")}
                      placeholder="(555) 123-4567" />
              <div className="md:col-span-2">
                <label className="block text-xs font-medium mb-1"
                        style={{ color: colors.muted }}>
                  Mailing address
                </label>
                <textarea
                  className="w-full border rounded px-3 py-2 text-sm"
                  style={{ borderColor: colors.border, minHeight: 68 }}
                  rows={3}
                  value={fields.mailing_address}
                  onChange={onChange("mailing_address")}
                  placeholder={"123 Main St\nAustin, TX 78701"}
                  data-testid="bs-mailing-address"
                />
              </div>
              <Field label="Website"
                      testid="bs-website"
                      value={fields.website}
                      onChange={onChange("website")}
                      placeholder="aquaterra.com" />
              <Field label="Email"
                      testid="bs-email"
                      value={fields.email}
                      onChange={onChange("email")}
                      err={errs.email}
                      placeholder="hello@aquaterra.com" />
              <Field label="Footer note"
                      testid="bs-footer-note"
                      value={fields.footer_note}
                      onChange={onChange("footer_note")}
                      placeholder="Licensed & Insured — Lic #12345" />
              <Field label="Tax ID (invoices only)"
                      testid="bs-tax-id"
                      value={fields.tax_id}
                      onChange={onChange("tax_id")}
                      placeholder="EIN 12-3456789" />
            </div>
            {/* Feb-2026 · Timezone Finalization — timezone picker
                lifted from Billing Settings into a shared
                TimezoneSelect component so both surfaces stay
                option-for-option identical. Saves through the same
                PATCH /api/tenants/mine/settings endpoint the Billing
                Settings picker uses; state lives on the tenant, not
                on business-settings. */}
            <div className="mt-4 pt-4"
                  style={{ borderTop: "1px solid #E5E7EB" }}>
              <TimezoneSelect
                value={tenantTz}
                disabled={savingTz}
                label={t("timezone.label", "Timezone")}
                helperText={t(
                  "timezone.helper_business",
                  "Used to bucket schedule, dashboards, and dispatch times in your local zone.",
                )}
                testid="bs-tenant-timezone-picker"
                onChange={async (e) => {
                  const nextTz = e.target.value;
                  if (savingTz) return;
                  setSavingTz(true);
                  try {
                    const doc = await api.patch("/tenants/mine/settings",
                                                  { timezone: nextTz });
                    const savedTz = doc?.timezone || nextTz;
                    setTenantTz(savedTz);
                    toast.success(t("timezone.saved", "Timezone updated"));
                    // Phase P15 · Feb-2026 — broadcast a tenant-scoped
                    // event so any dashboard / schedule surface that
                    // memoizes a tenant-tz-derived "today" key can
                    // bust its cache and re-render without a full
                    // page reload.  Listeners live in
                    // ``pages/admin/Dashboard.jsx`` and
                    // ``pages/schedule/CalendarSchedule.jsx``.
                    try {
                      window.dispatchEvent(new CustomEvent(
                        "tenant:settings-updated",
                        { detail: { timezone: savedTz } },
                      ));
                    } catch {
                      // ``CustomEvent`` unavailable in jsdom fallback —
                      // ignore.  React state re-render still fires.
                    }
                  } catch (err) {
                    toast.error(err?.message || "Save failed");
                  } finally {
                    setSavingTz(false);
                  }
                }}
              />
            </div>
          </section>

          {/* ── Live preview ────────────────────────────────── */}
          <aside className="bg-white rounded-lg border p-5"
                   style={{ borderColor: colors.border }}
                   data-testid="business-settings-live-preview">
            <h2 className="text-lg font-semibold mb-4">Live preview</h2>
            <div className="rounded-lg overflow-hidden border"
                  style={{ borderColor: colors.border }}>
              <div className="p-4 text-white"
                    style={{ background: _primary }}
                    data-testid="bs-preview-header">
                <div className="text-xs opacity-80">ESTIMATE</div>
                <div className="text-lg font-bold">
                  {fields.company_display_name
                    || effective.company_display_name
                    || "Your Company"}
                </div>
              </div>
              <div className="p-4">
                <button
                  className="px-3 py-1.5 rounded text-white text-sm"
                  style={{ background: _secondary }}
                  type="button"
                  data-testid="bs-preview-cta"
                >
                  Approve Estimate
                </button>
              </div>
            </div>
          </aside>

          {/* ── Branding ────────────────────────────────────── */}
          <section className="lg:col-span-3 bg-white rounded-lg border p-5"
                    style={{ borderColor: colors.border }}
                    data-testid="business-settings-branding-section">
            <h2 className="text-lg font-semibold mb-4">Branding</h2>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              {/* Logo */}
              <div>
                <label className="block text-xs font-medium mb-2"
                        style={{ color: colors.muted }}>
                  Logo
                </label>
                <div className="border rounded-lg p-3 flex items-center gap-3"
                      style={{ borderColor: colors.border, minHeight: 96 }}
                      data-testid="bs-logo-tile">
                  {logoUrl ? (
                    <img
                      src={toAbsolute(logoUrl)}
                      alt="Logo"
                      style={{ maxHeight: 64, maxWidth: 160,
                                 objectFit: "contain" }}
                      data-testid="bs-logo-preview"
                    />
                  ) : (
                    <div className="flex items-center gap-2"
                          style={{ color: colors.muted }}
                          data-testid="bs-logo-empty">
                      <ImageIcon size={20} />
                      <span className="text-sm">No logo uploaded</span>
                    </div>
                  )}
                </div>
                <div className="flex items-center gap-2 mt-2">
                  <label className="inline-flex items-center gap-1 px-3 py-1.5 rounded text-sm cursor-pointer border"
                          style={{ borderColor: colors.border }}
                          data-testid="bs-logo-upload-button">
                    <Upload size={14} />
                    {logoBusy ? "Uploading…" : "Upload"}
                    <input
                      type="file"
                      accept="image/png,image/jpeg,image/webp,image/svg+xml"
                      className="hidden"
                      onChange={onLogoPick}
                      disabled={logoBusy}
                      data-testid="bs-logo-file-input"
                    />
                  </label>
                  {logoUrl ? (
                    <button
                      type="button"
                      onClick={onLogoRemove}
                      disabled={logoBusy}
                      className="inline-flex items-center gap-1 px-3 py-1.5 rounded text-sm border"
                      style={{ borderColor: colors.border, color: "#DC2626" }}
                      data-testid="bs-logo-remove-button"
                    >
                      <Trash2 size={14} />
                      Remove
                    </button>
                  ) : null}
                </div>
                <p className="text-xs mt-1" style={{ color: colors.muted }}>
                  PNG / JPEG / WEBP / SVG · under 2 MB
                </p>
              </div>

              {/* Primary */}
              <ColorField
                label="Primary colour"
                testidPrefix="bs-brand-primary"
                value={fields.brand_primary_hex}
                onChange={onChange("brand_primary_hex")}
                err={errs.brand_primary_hex}
                placeholder="#0B4A6F"
              />

              {/* Secondary */}
              <ColorField
                label="Secondary colour"
                testidPrefix="bs-brand-secondary"
                value={fields.brand_secondary_hex}
                onChange={onChange("brand_secondary_hex")}
                err={errs.brand_secondary_hex}
                placeholder="#F97316"
              />
            </div>
          </section>

          {/* ── Routing ─────────────────────────────────────
              Feb-2026 · Routing Traffic-Aware phase — per-tenant
              opt-in. Default OFF; admin must explicitly enable to
              hit the higher-tier ``TRAFFIC_AWARE`` Google Routes
              API SKU. See /app/memory/FEATURE_ROUTING_TRAFFIC_AWARE.md.
           */}
          <section className="lg:col-span-3 bg-white rounded-lg border p-5"
                    style={{ borderColor: colors.border }}
                    data-testid="business-settings-routing-section">
            <h2 className="text-lg font-semibold mb-4">Routing</h2>
            <label className="flex items-start gap-3 cursor-pointer"
                    data-testid="bs-routing-traffic-aware-row">
              <input
                type="checkbox"
                className="mt-1 h-4 w-4"
                checked={!!fields.routing_traffic_aware}
                onChange={(e) => {
                  setFields((f) => ({
                    ...f,
                    routing_traffic_aware: !!e.target.checked,
                  }));
                  setDirty(true);
                }}
                data-testid="bs-routing-traffic-aware-toggle"
              />
              <div>
                <div className="text-sm font-medium"
                      style={{ color: colors.onSurface }}>
                  Traffic-aware route optimization
                </div>
                <div className="text-xs mt-1"
                      style={{ color: colors.muted }}
                      data-testid="bs-routing-traffic-aware-helper">
                  Uses Google&rsquo;s live traffic data to sequence stops.
                  May incur additional API cost.
                </div>
              </div>
            </label>
          </section>

          {/* ── Email preview ─────────────────────────────────
              Feb-2026 · UX Polish Batch B follow-up — Rendered email
              preview panel. Hits ``GET /api/tenants/me/email-preview``
              which wraps a synthetic stub body in the real
              ``wrap_html_in_shell(...)`` — so admins see the branding
              exactly as customers will, without triggering a real
              send. NO PII in the stub payloads.
           */}
          <section className="lg:col-span-3 bg-white rounded-lg border p-5"
                    style={{ borderColor: colors.border }}
                    data-testid="business-settings-email-preview-section">
            <h2 className="text-lg font-semibold mb-3">Preview email</h2>
            <div className="flex items-center gap-2 mb-3">
              <label htmlFor="bs-email-preview-select" className="text-sm"
                        style={{ color: colors.muted }}>
                Preview email as
              </label>
              <select
                id="bs-email-preview-select"
                data-testid="bs-email-preview-select"
                className="text-sm border rounded px-2 py-1"
                value={previewTemplate}
                onChange={(e) => setPreviewTemplate(e.target.value)}
              >
                <option value="">(choose a template)</option>
                <option value="quote_sent">Quote sent</option>
                <option value="invoice_reminder">Invoice reminder</option>
                <option value="password_reset">Password reset</option>
                <option value="portal_invite">Portal invite</option>
              </select>
            </div>
            {!previewTemplate ? (
              <div className="text-sm" style={{ color: colors.muted }}
                    data-testid="bs-email-preview-empty">
                Choose a template to preview.
              </div>
            ) : previewLoading ? (
              <div className="text-sm" style={{ color: colors.muted }}
                    data-testid="bs-email-preview-loading">
                Loading preview…
              </div>
            ) : previewHtml ? (
              <iframe
                title="Email preview"
                data-testid="bs-email-preview-iframe"
                srcDoc={previewHtml}
                style={{ width: "640px", maxWidth: "100%",
                         minHeight: "500px", border: "1px solid " + colors.border,
                         borderRadius: 6 }}
              />
            ) : (
              <div className="text-sm text-red-600"
                    data-testid="bs-email-preview-error">
                Preview unavailable.
              </div>
            )}
          </section>

          {/* F1.1 · Feb-2026 — tenant currency picker. */}
          <CurrencyCard />

          {/* ── Save bar ────────────────────────────────────── */}
          <PaymentProvidersCard />

          <div className="lg:col-span-3 flex justify-end">
            <button
              type="button"
              onClick={onSave}
              disabled={!canSave}
              className="px-4 py-2 rounded text-white text-sm font-medium"
              style={{
                background: canSave ? colors.brand : "#94A3B8",
                cursor: canSave ? "pointer" : "not-allowed",
              }}
              data-testid="bs-save-button"
            >
              {saving ? "Saving…" : "Save changes"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}


function Field({ label, value, onChange, placeholder, err, testid }) {
  return (
    <div>
      <label className="block text-xs font-medium mb-1"
              style={{ color: colors.muted }}>
        {label}
      </label>
      <input
        type="text"
        className="w-full border rounded px-3 py-2 text-sm"
        style={{ borderColor: err ? "#DC2626" : colors.border }}
        value={value || ""}
        placeholder={placeholder}
        onChange={onChange}
        data-testid={testid}
      />
      {err ? (
        <div className="text-xs mt-1" style={{ color: "#DC2626" }}
              data-testid={`${testid}-error`}>{err}</div>
      ) : null}
    </div>
  );
}


function ColorField({ label, testidPrefix, value, onChange, err, placeholder }) {
  const isValid = !value || HEX_RE.test(value);
  return (
    <div data-testid={`${testidPrefix}-field`}>
      <label className="block text-xs font-medium mb-1"
              style={{ color: colors.muted }}>{label}</label>
      <div className="flex items-center gap-2">
        <input
          type="color"
          value={isValid && value ? value : (placeholder || "#000000")}
          onChange={onChange}
          style={{
            width: 44, height: 34, border: "1px solid #E5E7EB",
            borderRadius: 6, padding: 0, background: "transparent",
          }}
          data-testid={`${testidPrefix}-picker`}
        />
        <input
          type="text"
          className="flex-1 border rounded px-3 py-2 text-sm"
          style={{ borderColor: err ? "#DC2626" : colors.border }}
          value={value || ""}
          onChange={onChange}
          placeholder={placeholder}
          data-testid={`${testidPrefix}-hex`}
        />
        <div
          style={{
            width: 34, height: 34, borderRadius: 6,
            border: "1px solid #E5E7EB",
            background: isValid && value ? value : "#F3F4F6",
          }}
          data-testid={`${testidPrefix}-swatch`}
        />
      </div>
      {err ? (
        <div className="text-xs mt-1" style={{ color: "#DC2626" }}
              data-testid={`${testidPrefix}-error`}>{err}</div>
      ) : null}
    </div>
  );
}



/**
 * F1.1 · Feb-2026 — tenant currency card.
 *
 * Standalone card wired to the new PATCH
 * ``/api/tenants/mine/settings/business`` endpoint (kept separate
 * from the existing ``/tenants/me/business-settings`` surface so
 * we don't have to reshape that route to accept currency mid-cycle).
 *
 * Renders a dropdown of every ISO code the backend whitelist
 * exposes with a native symbol preview next to it. Save is
 * immediate on selection change — no dirty tracker.
 */
export function CurrencyCard() {
  const [state, setState] = React.useState("loading"); // loading | ready | saving | error
  const [current, setCurrent] = React.useState("USD");
  const [supported, setSupported] = React.useState([]);
  // G1.6 · Feb-2026 — full ISO catalog via /api/reference/currencies.
  const [catalog, setCatalog] = React.useState([]);
  const [filter, setFilter] = React.useState("");

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [biz, cat] = await Promise.all([
          api.get("/tenants/mine/settings/business"),
          api.get("/reference/currencies")
             .catch(() => ({ currencies: [] })),
        ]);
        if (cancelled) return;
        setCurrent(biz?.currency || "USD");
        setSupported(biz?.supported_currencies || []);
        setCatalog((cat?.currencies || []).length
          ? cat.currencies
          : (biz?.supported_currencies || []).map(
              (c) => ({ code: c.code, name: c.code, symbol: c.symbol })));
        setState("ready");
      } catch (e) {
        if (cancelled) return;
        setState("error");
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const filteredCatalog = React.useMemo(() => {
    const q = (filter || "").toLowerCase().trim();
    if (!q) return catalog;
    return catalog.filter((c) =>
      c.code.toLowerCase().includes(q) ||
      (c.name || "").toLowerCase().includes(q));
  }, [catalog, filter]);

  const onChange = async (e) => {
    const code = e.target.value;
    setState("saving");
    try {
      const r = await api.patch("/tenants/mine/settings/business",
                                    { currency: code });
      setCurrent(r?.currency || code);
      toast.success(`Currency set to ${code}`);
      setState("ready");
    } catch (err) {
      toast.error(err?.data?.detail?.error === "unsupported_currency"
        ? "Unsupported currency"
        : (err?.message || "Save failed"));
      setState("ready");
    }
  };

  return (
    <section
      className="lg:col-span-3 rounded-lg border p-4"
      style={{ borderColor: colors.border, background: "#FFFFFF" }}
      data-testid="bs-currency-card"
    >
      <div className="flex items-center justify-between mb-3">
        <div>
          <h2 className="text-base font-bold"
              style={{ color: colors.onSurface }}>Currency</h2>
          <p className="text-xs" style={{ color: colors.muted }}>
            Applied to the sales pipeline, reports, and every customer-facing
            proposal / renewal email.
          </p>
        </div>
        {state === "saving" ? (
          <span className="text-xs" style={{ color: colors.muted }}
                 data-testid="bs-currency-saving">Saving…</span>
        ) : null}
      </div>
      {state === "loading" ? (
        <div className="text-xs" style={{ color: colors.muted }}
              data-testid="bs-currency-loading">Loading…</div>
      ) : state === "error" ? (
        <div className="text-xs" style={{ color: "#DC2626" }}
              data-testid="bs-currency-error">Failed to load currency setting.</div>
      ) : (
        <div className="flex flex-col gap-2 max-w-md">
          <input
            type="text"
            placeholder="Search currency (e.g. Japanese Yen, JPY)…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="px-3 py-2 rounded-lg text-sm outline-none"
            style={{ border: `1px solid ${colors.border}`, background: "#FFF" }}
            data-testid="bs-currency-search"
          />
          <div className="flex items-center gap-3">
            <select
              value={current}
              onChange={onChange}
              disabled={state === "saving"}
              size={Math.min(6, Math.max(1, filteredCatalog.length))}
              className="px-3 py-2 rounded-lg text-sm outline-none flex-1"
              style={{ border: `1px solid ${colors.border}`, background: "#FFF" }}
              data-testid="bs-currency-select"
            >
              {filteredCatalog.map((c) => (
                <option key={c.code} value={c.code}
                          data-testid={`bs-currency-option-${c.code}`}>
                  {c.code} — {c.name || c.code} {c.symbol && c.symbol !== c.code ? `(${c.symbol})` : ""}
                </option>
              ))}
            </select>
            <span className="text-2xl" data-testid="bs-currency-symbol">
              {(catalog.find((c) => c.code === current) || {}).symbol
                 || (supported.find((c) => c.code === current) || {}).symbol
                 || "$"}
            </span>
          </div>
        </div>
      )}
    </section>
  );
}
