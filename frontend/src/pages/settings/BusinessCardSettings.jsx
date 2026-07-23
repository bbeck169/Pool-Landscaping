// Feb-2026 · Item 6 — Business Card admin editor.
//
// Two-column layout: form on the left, live <BusinessCard /> preview
// on the right. PATCH /api/tenants/business-card persists on Save.
import React from "react";
import { toast } from "sonner";
import { Save, IdCard } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import BusinessCard from "@/components/business-card/BusinessCard";

const FIELDS = [
  { key: "company_name",       label: "Company name",       type: "text" },
  { key: "tagline",            label: "Tagline",            type: "text" },
  { key: "service_area",       label: "Service area",       type: "text",
    placeholder: "e.g. Peoria & Vistancia, Arizona" },
  { key: "phone",              label: "Phone",              type: "tel" },
  { key: "email",              label: "Email",              type: "email" },
  { key: "website_url",        label: "Website URL",        type: "url" },
  { key: "google_review_url",  label: "Google review URL",  type: "url" },
  { key: "logo_url",           label: "Logo URL",           type: "url" },
];

export default function BusinessCardSettingsPage() {
  const [card, setCard] = React.useState(null);
  const [draft, setDraft] = React.useState(null);
  const [saving, setSaving] = React.useState(false);
  const [previewKey, setPreviewKey] = React.useState(0);

  const load = React.useCallback(async () => {
    try {
      const c = await api.get("/tenants/business-card");
      setCard(c); setDraft(c);
    } catch (e) { toast.error(`Failed to load: ${e.message || e}`); }
  }, []);
  React.useEffect(() => { load(); }, [load]);

  const onField = (k, v) => setDraft((d) => ({ ...(d || {}), [k]: v }));

  const save = async () => {
    if (!draft) return;
    setSaving(true);
    try {
      const patch = {};
      for (const f of FIELDS) patch[f.key] = draft[f.key] ?? null;
      patch.gradient_from = draft.gradient_from || "#0EA5E9";
      patch.gradient_to = draft.gradient_to || "#16A34A";
      const fresh = await api.patch("/tenants/business-card", patch);
      setCard(fresh); setDraft(fresh);
      setPreviewKey((k) => k + 1);
      toast.success("Business card saved");
    } catch (e) {
      toast.error(`Save failed: ${e.message || e}`);
    } finally { setSaving(false); }
  };

  if (!draft) {
    return (
      <div className="p-8" data-testid="business-card-settings-page">
        <div className="text-sm" style={{ color: colors.muted }}>Loading…</div>
      </div>
    );
  }

  return (
    <div className="p-4 md:p-8 max-w-6xl mx-auto space-y-4"
         data-testid="business-card-settings-page">
      <div>
        <h1 className="text-2xl md:text-3xl font-bold tracking-tight"
            style={{ color: colors.onSurface }}
            data-testid="business-card-settings-title">
          <IdCard size={20} className="inline mr-2 -mt-0.5"
                    style={{ color: colors.brand }} />
          Business Card
        </h1>
        <p className="text-sm" style={{ color: colors.muted }}>
          Your company's shareable digital business card. This card is what
          customers, techs, and admins see across every profile page.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="rounded-xl p-4 space-y-3"
             style={{ backgroundColor: colors.surface,
                        border: `1px solid ${colors.border}` }}
             data-testid="business-card-settings-form">
          {FIELDS.map((f) => (
            <div key={f.key}>
              <label className="text-[11px] uppercase tracking-wide font-semibold"
                     style={{ color: colors.muted }}>{f.label}</label>
              <input
                type={f.type}
                value={draft[f.key] || ""}
                placeholder={f.placeholder || ""}
                onChange={(e) => onField(f.key, e.target.value)}
                className="mt-1 w-full rounded px-2 py-1.5 text-sm focus:outline-none"
                style={{
                  backgroundColor: colors.surfaceSecondary,
                  color: colors.onSurface,
                  border: `1px solid ${colors.border}`,
                }}
                data-testid={`business-card-settings-input-${f.key}`}
              />
            </div>
          ))}

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-[11px] uppercase tracking-wide font-semibold"
                     style={{ color: colors.muted }}>Gradient from</label>
              <input
                type="color"
                value={draft.gradient_from || "#0EA5E9"}
                onChange={(e) => onField("gradient_from", e.target.value)}
                className="mt-1 w-full h-9 rounded"
                data-testid="business-card-settings-input-gradient_from"
              />
            </div>
            <div>
              <label className="text-[11px] uppercase tracking-wide font-semibold"
                     style={{ color: colors.muted }}>Gradient to</label>
              <input
                type="color"
                value={draft.gradient_to || "#16A34A"}
                onChange={(e) => onField("gradient_to", e.target.value)}
                className="mt-1 w-full h-9 rounded"
                data-testid="business-card-settings-input-gradient_to"
              />
            </div>
          </div>

          <div className="flex items-center gap-2 pt-2">
            <button
              type="button"
              onClick={save}
              disabled={saving}
              className="flex items-center gap-1.5 px-3 py-2 rounded-md text-sm font-semibold text-white hover:brightness-95 disabled:opacity-60"
              style={{ backgroundColor: colors.brand }}
              data-testid="business-card-settings-save-btn"
            >
              <Save size={13} /> {saving ? "Saving…" : "Save"}
            </button>
          </div>
        </div>

        <div data-testid="business-card-settings-preview">
          <div className="text-[11px] uppercase tracking-wide font-semibold mb-1"
               style={{ color: colors.muted }}>Preview</div>
          {/* Force remount after save so the child re-fetches. */}
          <BusinessCard key={previewKey} variant="full" />
        </div>
      </div>
    </div>
  );
}
