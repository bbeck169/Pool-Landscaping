// TD-seo-phase3 · Oct-2026 — Portal SEO admin tab.
//
// Operator-facing editor for ``tenants.settings.business_card.seo``.
// Consumes the Phase 1 admin endpoints:
//
//   GET  /api/admin/portal-seo/{tenant_id}
//   PATCH /api/admin/portal-seo/{tenant_id}
//
// Both endpoints are role-gated to admin / super_admin / owner on the
// backend (require_admin + explicit tenant-scope). This component
// mirrors that gate client-side: it renders nothing if the current
// user is below admin tier (defense-in-depth; AdminOnly wraps the
// parent page in App.js already).
//
// Scope lock (Phase 0 §7 decision #4):
//   * This tab slots inside the existing ``WebsiteSeoPage``.
//   * NO Track B (external scan) touch — External Scan tab is the
//     default, keeps full byte-identical UX.
//   * NO new npm packages — plain textarea + JSON.parse validation
//     for ``json_ld_overrides``.
import React from "react";
import { toast } from "sonner";
import { Save, RotateCcw } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import { useAuth } from "@/auth";

// Role gate must mirror backend ``require_admin`` (admin + super_admin
// + owner, Phase 34 Task X widening).
const _PORTAL_SEO_ROLES = ["admin", "super_admin", "owner"];

// Twitter card enum must match backend ``_TWITTER_CARD_TYPES`` in
// backend/routers/portal_seo_admin.py:38.
const _TWITTER_CARD_OPTIONS = [
  "summary", "summary_large_image", "app", "player",
];

// Soft hint caps — the BE caps og_description at 400 and
// meta_description_override at 400; crawlers typically truncate
// around 155–160 chars so we surface that as a soft warning.
const _OG_DESC_SOFT_HINT = 160;
const _META_DESC_SOFT_HINT = 160;

function _isValidUrl(v) {
  if (!v) return true;  // empty is allowed (clears override)
  return /^https?:\/\//i.test(String(v).trim());
}

function _tryParseJson(v) {
  // Returns [ok, parsed_or_message]. Empty string → ok, {} default.
  if (!v || !v.trim()) return [true, {}];
  try {
    const p = JSON.parse(v);
    if (p === null || typeof p !== "object" || Array.isArray(p)) {
      return [false, "must be a JSON object"];
    }
    return [true, p];
  } catch (e) {
    return [false, e.message || "invalid JSON"];
  }
}

// _buildPatch: strip empty strings so the BE's ``exclude_none=True``
// does not clobber unset keys (empty-string ≠ null in the BE schema).
// service_areas: comma-or-newline → trimmed non-empty list.
// json_ld_overrides: parsed object (never a string).
export function _buildPatch(form) {
  const out = {};
  const _str = (k) => {
    const v = (form[k] || "").trim();
    if (v) out[k] = v;
  };
  _str("og_title");
  _str("og_description");
  _str("og_image_url");
  _str("twitter_card");
  _str("twitter_site");
  _str("canonical_base_url");
  _str("meta_description_override");
  const areas = String(form.service_areas || "")
    .split(/[\n,]/)
    .map((s) => s.trim())
    .filter(Boolean);
  if (areas.length) out.service_areas = areas;
  if (form.json_ld_overrides && form.json_ld_overrides.trim()) {
    const [ok, parsed] = _tryParseJson(form.json_ld_overrides);
    if (ok && Object.keys(parsed).length) out.json_ld_overrides = parsed;
  }
  return out;
}

function _toForm(resp) {
  // Shape the GET response (which has typed values + arrays/objects)
  // into text-form state the UI can edit.
  const r = resp || {};
  return {
    og_title:                  r.og_title || "",
    og_description:            r.og_description || "",
    og_image_url:              r.og_image_url || "",
    twitter_card:              r.twitter_card || "summary_large_image",
    twitter_site:              r.twitter_site || "",
    canonical_base_url:        r.canonical_base_url || "",
    meta_description_override: r.meta_description_override || "",
    service_areas:             Array.isArray(r.service_areas)
                                   ? r.service_areas.join(", ")
                                   : "",
    json_ld_overrides:         r.json_ld_overrides
                                   && Object.keys(r.json_ld_overrides).length
                                     ? JSON.stringify(r.json_ld_overrides, null, 2)
                                     : "",
  };
}

export default function PortalSeoTab() {
  const { user } = useAuth() || {};
  const role = (user?.role || "").toLowerCase();
  const canEdit = _PORTAL_SEO_ROLES.includes(role);
  const tenantId = user?.tenant_id || "";

  const [loading, setLoading] = React.useState(true);
  const [saving, setSaving] = React.useState(false);
  const [initial, setInitial] = React.useState(null);
  const [form, setForm] = React.useState(_toForm(null));
  const [jsonErr, setJsonErr] = React.useState("");

  const load = React.useCallback(async () => {
    if (!canEdit || !tenantId) { setLoading(false); return; }
    setLoading(true);
    try {
      const r = await api.get(`/admin/portal-seo/${tenantId}`);
      const f = _toForm(r);
      setForm(f);
      setInitial(f);
      setJsonErr("");
    } catch (e) {
      toast.error(`Failed to load SEO settings: ${e.message || e}`);
    } finally {
      setLoading(false);
    }
  }, [canEdit, tenantId]);

  React.useEffect(() => { load(); }, [load]);

  if (!canEdit) {
    // Defense-in-depth; AdminOnly already gates the page.
    return (
      <div className="rounded-xl p-6 text-center text-sm"
           style={{ backgroundColor: colors.surfaceSecondary,
                      border: `1px dashed ${colors.border}`,
                      color: colors.muted }}
           data-testid="portal-seo-denied">
        Admin role required to edit Portal SEO metadata.
      </div>
    );
  }

  const urlErrOg = form.og_image_url && !_isValidUrl(form.og_image_url);
  const urlErrCanonical = form.canonical_base_url && !_isValidUrl(form.canonical_base_url);
  const canSave = !saving && !loading && !jsonErr && !urlErrOg && !urlErrCanonical;

  const onChange = (k) => (e) => {
    const v = e?.target?.value ?? "";
    setForm((f) => ({ ...f, [k]: v }));
    if (k === "json_ld_overrides") setJsonErr("");
  };

  const onJsonBlur = () => {
    const [ok, msg] = _tryParseJson(form.json_ld_overrides);
    setJsonErr(ok ? "" : String(msg));
  };

  const onReset = () => {
    if (initial) {
      setForm(initial);
      setJsonErr("");
    }
  };

  const onSave = async () => {
    if (!canSave) return;
    const [ok, msg] = _tryParseJson(form.json_ld_overrides);
    if (!ok) { setJsonErr(String(msg)); return; }
    const patch = _buildPatch({ ...form, json_ld_overrides: form.json_ld_overrides });
    if (!Object.keys(patch).length) {
      toast.error("No changes to save.");
      return;
    }
    setSaving(true);
    try {
      const r = await api.patch(`/admin/portal-seo/${tenantId}`, patch);
      const f = _toForm(r);
      setForm(f);
      setInitial(f);
      toast.success("Portal SEO saved.");
    } catch (e) {
      toast.error(`Save failed: ${e.message || e}`);
    } finally {
      setSaving(false);
    }
  };

  const fieldStyle = {
    backgroundColor: colors.surfaceSecondary,
    border: `1px solid ${colors.border}`,
    color: colors.onSurface,
  };

  const labelCls = "block text-xs font-semibold mb-1 uppercase tracking-wide";
  const inputCls = "w-full px-3 py-1.5 text-sm rounded-md";
  const taCls = "w-full px-3 py-2 text-sm rounded-md font-mono";

  if (loading) {
    return (
      <div className="rounded-xl p-6 text-sm"
           style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}`,
                      color: colors.muted }}
           data-testid="portal-seo-loading">
        Loading Portal SEO settings…
      </div>
    );
  }

  return (
    <div className="rounded-xl p-4 space-y-4"
         style={{ backgroundColor: colors.surface,
                    border: `1px solid ${colors.border}` }}
         data-testid="portal-seo-tab">
      <div>
        <h2 className="text-base font-semibold" style={{ color: colors.onSurface }}>
          Portal SEO metadata
        </h2>
        <p className="text-xs mt-1" style={{ color: colors.muted }}>
          Open Graph, Twitter, canonical, and JSON-LD overrides for your
          public-facing portal pages (business card, lead form, reviews).
          Blank fields fall back to your business card defaults.
        </p>
      </div>

      <div className="grid md:grid-cols-2 gap-4">
        <div>
          <label className={labelCls} style={{ color: colors.muted }}>
            OG title
          </label>
          <input
            type="text"
            value={form.og_title}
            onChange={onChange("og_title")}
            className={inputCls}
            style={fieldStyle}
            maxLength={200}
            data-testid="portal-seo-og-title"
          />
        </div>

        <div>
          <label className={labelCls} style={{ color: colors.muted }}>
            Twitter card
          </label>
          <select
            value={form.twitter_card}
            onChange={onChange("twitter_card")}
            className={inputCls}
            style={fieldStyle}
            data-testid="portal-seo-twitter-card"
          >
            {_TWITTER_CARD_OPTIONS.map((o) => (
              <option key={o} value={o}>{o}</option>
            ))}
          </select>
        </div>

        <div className="md:col-span-2">
          <label className={labelCls} style={{ color: colors.muted }}>
            OG description
            <span className="ml-2 font-normal normal-case"
                  style={{ color: form.og_description.length > _OG_DESC_SOFT_HINT
                             ? "#B91C1C" : colors.muted }}
                  data-testid="portal-seo-og-desc-counter">
              {form.og_description.length}/{_OG_DESC_SOFT_HINT} (soft)
            </span>
          </label>
          <textarea
            value={form.og_description}
            onChange={onChange("og_description")}
            className={taCls}
            style={{ ...fieldStyle, minHeight: 60 }}
            maxLength={400}
            data-testid="portal-seo-og-desc"
          />
        </div>

        <div>
          <label className={labelCls} style={{ color: colors.muted }}>
            OG image URL
          </label>
          <input
            type="url"
            value={form.og_image_url}
            onChange={onChange("og_image_url")}
            className={inputCls}
            style={{ ...fieldStyle, borderColor: urlErrOg ? "#B91C1C" : colors.border }}
            placeholder="https://…"
            data-testid="portal-seo-og-image-url"
          />
          {urlErrOg ? (
            <div className="text-[10px] mt-1" style={{ color: "#B91C1C" }}
                 data-testid="portal-seo-og-image-url-err">
              must start with http:// or https://
            </div>
          ) : null}
          {form.og_image_url && !urlErrOg ? (
            <img src={form.og_image_url} alt=""
                 className="mt-2 rounded max-h-24 border"
                 style={{ borderColor: colors.border }}
                 data-testid="portal-seo-og-image-preview"
                 onError={(e) => { e.currentTarget.style.display = "none"; }} />
          ) : null}
        </div>

        <div>
          <label className={labelCls} style={{ color: colors.muted }}>
            Twitter @site
          </label>
          <input
            type="text"
            value={form.twitter_site}
            onChange={onChange("twitter_site")}
            className={inputCls}
            style={fieldStyle}
            maxLength={50}
            placeholder="@yourhandle"
            data-testid="portal-seo-twitter-site"
          />
        </div>

        <div className="md:col-span-2">
          <label className={labelCls} style={{ color: colors.muted }}>
            Canonical base URL
          </label>
          <input
            type="url"
            value={form.canonical_base_url}
            onChange={onChange("canonical_base_url")}
            className={inputCls}
            style={{ ...fieldStyle, borderColor: urlErrCanonical ? "#B91C1C" : colors.border }}
            placeholder="https://yourdomain.com"
            data-testid="portal-seo-canonical-base-url"
          />
          {urlErrCanonical ? (
            <div className="text-[10px] mt-1" style={{ color: "#B91C1C" }}
                 data-testid="portal-seo-canonical-base-url-err">
              must start with http:// or https://
            </div>
          ) : null}
        </div>

        <div className="md:col-span-2">
          <label className={labelCls} style={{ color: colors.muted }}>
            Meta description override
            <span className="ml-2 font-normal normal-case"
                  style={{ color: form.meta_description_override.length > _META_DESC_SOFT_HINT
                             ? "#B91C1C" : colors.muted }}
                  data-testid="portal-seo-meta-desc-counter">
              {form.meta_description_override.length}/{_META_DESC_SOFT_HINT} (soft)
            </span>
          </label>
          <textarea
            value={form.meta_description_override}
            onChange={onChange("meta_description_override")}
            className={taCls}
            style={{ ...fieldStyle, minHeight: 60 }}
            maxLength={400}
            data-testid="portal-seo-meta-desc"
          />
        </div>

        <div className="md:col-span-2">
          <label className={labelCls} style={{ color: colors.muted }}>
            Service areas (comma or newline separated, max 50)
          </label>
          <textarea
            value={form.service_areas}
            onChange={onChange("service_areas")}
            className={taCls}
            style={{ ...fieldStyle, minHeight: 50 }}
            placeholder="Austin, TX, Round Rock, Pflugerville"
            data-testid="portal-seo-service-areas"
          />
        </div>

        <div className="md:col-span-2">
          <label className={labelCls} style={{ color: colors.muted }}>
            JSON-LD overrides (merged into schema.org payload)
            {jsonErr ? (
              <span className="ml-2 font-normal normal-case"
                    style={{ color: "#B91C1C" }}
                    data-testid="portal-seo-json-err">
                invalid JSON: {jsonErr}
              </span>
            ) : null}
          </label>
          <textarea
            value={form.json_ld_overrides}
            onChange={onChange("json_ld_overrides")}
            onBlur={onJsonBlur}
            className={taCls}
            style={{
              ...fieldStyle,
              minHeight: 100,
              borderColor: jsonErr ? "#B91C1C" : colors.border,
            }}
            placeholder='{"priceRange": "$$"}'
            data-testid="portal-seo-json-ld"
          />
        </div>
      </div>

      <div className="flex items-center gap-2 pt-2"
           style={{ borderTop: `1px solid ${colors.border}` }}>
        <button
          type="button"
          onClick={onSave}
          disabled={!canSave}
          className="flex items-center gap-1.5 px-3 py-2 rounded-md text-sm font-semibold text-white hover:brightness-95 disabled:opacity-60"
          style={{ backgroundColor: colors.brand }}
          data-testid="portal-seo-save-btn"
        >
          <Save size={13} />
          {saving ? "Saving…" : "Save"}
        </button>
        <button
          type="button"
          onClick={onReset}
          disabled={saving || !initial}
          className="flex items-center gap-1.5 px-3 py-2 rounded-md text-sm font-semibold disabled:opacity-60"
          style={{ backgroundColor: colors.surfaceSecondary,
                     color: colors.onSurface,
                     border: `1px solid ${colors.border}` }}
          data-testid="portal-seo-reset-btn"
        >
          <RotateCcw size={13} />
          Reset to defaults
        </button>
      </div>
    </div>
  );
}
