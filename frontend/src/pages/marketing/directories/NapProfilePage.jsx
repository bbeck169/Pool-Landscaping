/**
 * Directories · NAP Profile editor (D2 · Feb 2026)
 * -----------------------------------------------------------------
 * Backend contract:
 *   GET   /api/directories/nap-profile           → full profile doc
 *   PATCH /api/directories/nap-profile           → { profile, stale_submissions_flipped }
 *   POST  /api/directories/nap-profile/validate  → { ok, issues:[{field,code,detail}],
 *                                                     geocode_status, geocode_detail, nap_hash }
 */
import React, { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowLeft, Save, ShieldCheck, CircleCheck, TriangleAlert, MapPin,
} from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api";
import { colors } from "@/theme";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";

const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
const DAY_LABELS = { mon: "Mon", tue: "Tue", wed: "Wed", thu: "Thu",
                       fri: "Fri", sat: "Sat", sun: "Sun" };
const CATEGORIES = ["pool_service", "pool_repair", "pool_construction",
                     "landscaping", "landscape_maintenance", "hardscape",
                     "irrigation", "lawn_care"];
const EMP_RANGES = ["1", "2-5", "6-10", "11-25", "26-50", "51-100", "100+"];
const SOCIALS = ["facebook", "instagram", "linkedin", "tiktok", "youtube", "x"];

function IssueBadge({ code }) {
  const label = {
    required: "Required",
    bad_url:  "Bad URL",
    unparseable: "Cannot parse",
    not_geocodable: "Not geocodable",
  }[code] || code;
  return <Badge className="bg-red-500 text-white text-[10px] ml-1">{label}</Badge>;
}

export default function NapProfilePage() {
  const nav = useNavigate();
  const [p, setP] = useState(null);
  const [saving, setSaving] = useState(false);
  const [validating, setValidating] = useState(false);
  const [validation, setValidation] = useState(null);

  const load = useCallback(async () => {
    try {
      const doc = await api.get("/directories/nap-profile");
      setP(doc);
    } catch (e) {
      toast.error(e?.message || "Failed to load profile");
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const set = (patch) => setP((cur) => ({ ...cur, ...patch }));
  const setAddr = (patch) => setP((cur) => ({
    ...cur, address: { ...(cur?.address || {}), ...patch }
  }));
  const setHours = (day, patch) => setP((cur) => ({
    ...cur,
    hours: { ...(cur?.hours || {}),
              [day]: { ...(cur?.hours?.[day] || {}), ...patch } }
  }));
  const setSocial = (key, val) => setP((cur) => ({
    ...cur,
    social_urls: { ...(cur?.social_urls || {}), [key]: val }
  }));

  const validate = async () => {
    setValidating(true);
    try {
      const r = await api.post("/directories/nap-profile/validate", {});
      setValidation(r);
      if (r.ok) {
        toast.success("Profile is valid.");
      } else {
        toast.error(`${r.issues.length} issue${r.issues.length === 1 ? "" : "s"} found.`);
      }
    } catch (e) {
      toast.error(e?.message || "Validation failed");
    }
    setValidating(false);
  };

  const save = async () => {
    setSaving(true);
    try {
      const patch = { ...p };
      // Server owns these — don't send back.
      delete patch.id; delete patch.tenant_id; delete patch.nap_hash;
      delete patch.created_at; delete patch.updated_at; delete patch.updated_by;
      delete patch.phone_e164;
      const r = await api.patch("/directories/nap-profile", patch);
      setP(r.profile);
      const flipped = Number(r.stale_submissions_flipped || 0);
      if (flipped > 0) {
        toast.success(
          `Saved. ${flipped} previously-submitted director${flipped === 1 ? "y" : "ies"} flipped to Needs Update.`,
          { duration: 6000 }
        );
      } else {
        toast.success("Profile saved.");
      }
    } catch (e) {
      toast.error(e?.message || "Save failed");
    }
    setSaving(false);
  };

  if (!p) {
    return (
      <div className="p-8 text-sm" style={{ color: colors.muted }}>
        Loading NAP profile…
      </div>
    );
  }

  const issuesByField = (validation?.issues || []).reduce((acc, iss) => {
    acc[iss.field] = iss; return acc;
  }, {});
  const napHashShort = (p.nap_hash || "").slice(0, 10);

  return (
    <div className="p-4 md:p-8 max-w-4xl mx-auto space-y-4"
          data-testid="nap-profile-page">
      <div className="flex items-center gap-3 mb-2">
        <button onClick={() => nav(-1)}
                className="p-2 rounded-lg hover:brightness-95"
                style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
          <ArrowLeft size={16} />
        </button>
        <div className="flex-1">
          <h1 className="text-2xl md:text-3xl font-bold" style={{ color: colors.onSurface }}>
            <MapPin className="inline w-5 h-5 mr-1" /> NAP Profile
          </h1>
          <p className="text-xs mt-0.5" style={{ color: colors.muted }}>
            Name / Address / Phone — the single source of truth every directory reads from.
          </p>
        </div>
        {napHashShort ? (
          <span className="text-[10px] font-mono px-2 py-1 rounded"
                 style={{ backgroundColor: colors.surfaceSecondary, color: colors.muted }}
                 title="Current NAP hash (short prefix)"
                 data-testid="nap-hash-chip">
            hash · {napHashShort}
          </span>
        ) : null}
        <Button variant="outline" onClick={validate} disabled={validating}
                  data-testid="nap-validate-btn">
          <ShieldCheck className="w-4 h-4 mr-1" />
          {validating ? "Validating…" : "Validate"}
        </Button>
        <Button onClick={save} disabled={saving} data-testid="nap-save-btn">
          <Save className="w-4 h-4 mr-1" /> {saving ? "Saving…" : "Save"}
        </Button>
      </div>

      {validation && !validation.ok && (
        <div className="rounded-xl p-3 text-sm"
              style={{ backgroundColor: "#fef3c7", border: "1px solid #f59e0b", color: "#78350f" }}
              data-testid="nap-issues-banner">
          <TriangleAlert className="inline w-4 h-4 mr-1" />
          {validation.issues.length} issue(s) found. See highlighted fields below.
        </div>
      )}
      {validation?.ok && (
        <div className="rounded-xl p-3 text-sm"
              style={{ backgroundColor: "#d1fae5", border: "1px solid #10b981", color: "#065f46" }}>
          <CircleCheck className="inline w-4 h-4 mr-1" />
          Profile validated. Geocode status: <b>{validation.geocode_status}</b>
          {validation.geocode_detail ? ` — ${validation.geocode_detail}` : ""}
        </div>
      )}
      {validation && validation.geocode_status === "skipped" && (
        <div className="rounded-xl p-3 text-xs"
              style={{ backgroundColor: colors.surfaceSecondary, color: colors.muted }}>
          Geocoding is skipped because <code>GOOGLE_API_KEY</code> is not configured in this environment.
          Non-geocode validation still runs.
        </div>
      )}

      {/* Business Identity */}
      <Section title="Business Identity">
        <Row label="Business name" issue={issuesByField["business_name"]}>
          <Input value={p.business_name || ""}
                  onChange={(e) => set({ business_name: e.target.value })}
                  data-testid="nap-name" />
        </Row>
        <Row label="DBA names (comma-separated)">
          <Input value={(p.dba_names || []).join(", ")}
                  onChange={(e) => set({ dba_names: e.target.value.split(",").map(x => x.trim()).filter(Boolean) })} />
        </Row>
      </Section>

      {/* Address */}
      <Section title="Address">
        <Row label="Line 1" issue={issuesByField["address.line1"]}>
          <Input value={p.address?.line1 || ""} onChange={(e) => setAddr({ line1: e.target.value })} />
        </Row>
        <Row label="Line 2">
          <Input value={p.address?.line2 || ""} onChange={(e) => setAddr({ line2: e.target.value })} />
        </Row>
        <div className="grid grid-cols-3 gap-2">
          <Row label="City" issue={issuesByField["address.city"]}>
            <Input value={p.address?.city || ""} onChange={(e) => setAddr({ city: e.target.value })} />
          </Row>
          <Row label="State" issue={issuesByField["address.state"]}>
            <Input value={p.address?.state || ""} onChange={(e) => setAddr({ state: e.target.value.toUpperCase() })} />
          </Row>
          <Row label="Postal code" issue={issuesByField["address.postal_code"]}>
            <Input value={p.address?.postal_code || ""} onChange={(e) => setAddr({ postal_code: e.target.value })} />
          </Row>
        </div>
      </Section>

      {/* Contact */}
      <Section title="Contact">
        <div className="grid grid-cols-2 gap-2">
          <Row label={`Phone${p.phone_e164 ? ` · ${p.phone_e164}` : ""}`} issue={issuesByField["phone"]}>
            <Input value={p.phone || ""} onChange={(e) => set({ phone: e.target.value })} />
          </Row>
          <Row label="Email">
            <Input value={p.email || ""} onChange={(e) => set({ email: e.target.value })} />
          </Row>
        </div>
        <Row label="Alt phones (comma-separated)">
          <Input value={(p.alt_phones || []).join(", ")}
                  onChange={(e) => set({ alt_phones: e.target.value.split(",").map(x => x.trim()).filter(Boolean) })} />
        </Row>
      </Section>

      {/* Website + socials */}
      <Section title="Website & Socials">
        <Row label="Website" issue={issuesByField["website"]}>
          <Input value={p.website || ""} onChange={(e) => set({ website: e.target.value })} placeholder="https://..." />
        </Row>
        <div className="grid grid-cols-2 gap-2">
          {SOCIALS.map((k) => (
            <Row key={k} label={k} issue={issuesByField[`social_urls.${k}`]}>
              <Input value={p.social_urls?.[k] || ""}
                      onChange={(e) => setSocial(k, e.target.value)}
                      placeholder="https://..." />
            </Row>
          ))}
        </div>
      </Section>

      {/* Hours */}
      <Section title="Hours">
        <div className="grid grid-cols-1 gap-1 text-sm">
          {DAYS.map((d) => {
            const h = p.hours?.[d] || {};
            return (
              <div key={d} className="grid grid-cols-[60px_1fr_1fr_120px] gap-2 items-center">
                <span style={{ color: colors.muted }}>{DAY_LABELS[d]}</span>
                <Input type="time" value={h.open || ""}
                        onChange={(e) => setHours(d, { open: e.target.value })}
                        disabled={h.closed} />
                <Input type="time" value={h.close || ""}
                        onChange={(e) => setHours(d, { close: e.target.value })}
                        disabled={h.closed} />
                <label className="text-xs flex items-center gap-1" style={{ color: colors.muted }}>
                  <input type="checkbox" checked={Boolean(h.closed)}
                          onChange={(e) => setHours(d, { closed: e.target.checked })} />
                  Closed
                </label>
              </div>
            );
          })}
        </div>
      </Section>

      {/* Categories & service area */}
      <Section title="Business categories">
        <div className="flex flex-wrap gap-1">
          {CATEGORIES.map((c) => {
            const on = (p.business_categories || []).includes(c);
            return (
              <button key={c}
                       type="button"
                       onClick={() => set({
                         business_categories: on
                           ? p.business_categories.filter((x) => x !== c)
                           : [...(p.business_categories || []), c]
                       })}
                       className="text-xs px-2 py-1 rounded-full border"
                       style={{
                         backgroundColor: on ? colors.brand : "transparent",
                         color: on ? "#fff" : colors.onSurface,
                         borderColor: colors.border,
                       }}>
                {c.replace(/_/g, " ")}
              </button>
            );
          })}
        </div>
      </Section>

      <Section title="Company info">
        <div className="grid grid-cols-2 gap-2">
          <Row label="Founded year">
            <Input type="number" value={p.founded_year || ""}
                    onChange={(e) => set({ founded_year: e.target.value ? Number(e.target.value) : null })} />
          </Row>
          <Row label="Employee count range">
            <select className="border rounded p-2 text-sm w-full"
                    value={p.employee_count_range || ""}
                    onChange={(e) => set({ employee_count_range: e.target.value })}>
              <option value="">—</option>
              {EMP_RANGES.map((r) => <option key={r}>{r}</option>)}
            </select>
          </Row>
        </div>
      </Section>

      <Section title="Brand assets">
        <Row label="Logo URL"><Input value={p.logo_url || ""} onChange={(e) => set({ logo_url: e.target.value })} /></Row>
        <Row label="Cover photo URL"><Input value={p.cover_photo_url || ""} onChange={(e) => set({ cover_photo_url: e.target.value })} /></Row>
        <Row label="Gallery photo URLs (comma-separated)">
          <Input value={(p.gallery_photo_urls || []).join(", ")}
                  onChange={(e) => set({ gallery_photo_urls: e.target.value.split(",").map(x => x.trim()).filter(Boolean) })} />
        </Row>
      </Section>

      <Section title="Descriptions">
        <Row label="Tagline"><Input value={p.tagline || ""} onChange={(e) => set({ tagline: e.target.value })} /></Row>
        <Row label="Short description">
          <Textarea value={p.description_short || ""} rows={2}
                     onChange={(e) => set({ description_short: e.target.value })} />
        </Row>
        <Row label="Long description">
          <Textarea value={p.description_long || ""} rows={4}
                     onChange={(e) => set({ description_long: e.target.value })} />
        </Row>
      </Section>

      <div className="flex justify-end">
        <Button onClick={save} disabled={saving} data-testid="nap-save-btn-2">
          <Save className="w-4 h-4 mr-1" /> {saving ? "Saving…" : "Save changes"}
        </Button>
      </div>
    </div>
  );
}

function Section({ title, children }) {
  return (
    <div className="rounded-2xl p-4"
          style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
      <h2 className="text-sm font-bold mb-2" style={{ color: colors.onSurface }}>{title}</h2>
      <div className="space-y-2">{children}</div>
    </div>
  );
}

function Row({ label, issue, children }) {
  return (
    <div>
      <Label className="text-xs" style={{ color: colors.muted }}>
        {label} {issue ? <IssueBadge code={issue.code} /> : null}
      </Label>
      {children}
      {issue?.detail ? (
        <div className="text-[10px] mt-0.5" style={{ color: "#b91c1c" }}>{issue.detail}</div>
      ) : null}
    </div>
  );
}
