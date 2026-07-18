/**
 * Phase 56.20 — Admin settings for auto end-of-visit customer email.
 * Small admin-only page that toggles the tenant-level feature flag,
 * sets the Google review CTA link, and renders a live HTML preview
 * built from the tenant's most recent submitted service report.
 */
import React, { useEffect, useState } from "react";
import { Mail, Eye, CheckCircle2, AlertTriangle } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

export default function AutoVisitEmailSettings() {
  const [settings, setSettings] = useState(null);
  const [preview, setPreview] = useState(null);
  const [saving, setSaving] = useState(false);
  const [savedFlash, setSavedFlash] = useState(null);
  const [previewErr, setPreviewErr] = useState(null);

  useEffect(() => {
    api.get("/settings/auto-visit-email").then(setSettings).catch(() => setSettings({}));
  }, []);

  const save = async () => {
    setSaving(true);
    try {
      await api.put("/settings/auto-visit-email", settings);
      setSavedFlash({ ok: true, msg: "Saved ✓" });
    } catch (e) { setSavedFlash({ ok: false, msg: e.message }); }
    finally { setSaving(false); setTimeout(() => setSavedFlash(null), 3000); }
  };

  const doPreview = async () => {
    setPreviewErr(null); setPreview(null);
    try {
      const r = await api.post("/settings/auto-visit-email/preview", {});
      setPreview(r);
    } catch (e) {
      setPreviewErr(e.message || "Preview failed");
    }
  };

  if (!settings) return null;

  return (
    <div className="max-w-3xl mx-auto p-4 md:p-6" data-testid="auto-email-settings-page">
      <div className="flex items-center gap-3 mb-6">
        <Mail size={22} style={{ color: colors.brand }} />
        <div>
          <h1 className="text-2xl font-bold" style={{ color: colors.onSurface }}>
            Auto End-of-Visit Customer Emails
          </h1>
          <p className="text-xs" style={{ color: colors.muted }}>
            When a tech submits a service report, automatically email the customer a redacted summary of the visit.
          </p>
        </div>
      </div>

      <div className="rounded-2xl p-6 space-y-4"
           style={{ backgroundColor: colors.surface,
                    border: `1px solid ${colors.border}` }}>
        <label className="flex items-start gap-3 cursor-pointer">
          <input type="checkbox" checked={!!settings.enabled}
                 onChange={(e) => setSettings({...settings, enabled: e.target.checked})}
                 className="mt-1"
                 data-testid="auto-email-enabled" />
          <div>
            <div className="font-semibold" style={{ color: colors.onSurface }}>
              Enable auto end-of-visit emails
            </div>
            <div className="text-xs" style={{ color: colors.muted }}>
              Off by default. Turn on once you've previewed the layout.
            </div>
          </div>
        </label>

        <label className="flex items-start gap-3 cursor-pointer">
          <input type="checkbox" checked={!!settings.include_reviews_cta}
                 onChange={(e) => setSettings({...settings, include_reviews_cta: e.target.checked})}
                 className="mt-1"
                 data-testid="auto-email-reviews-cta" />
          <div>
            <div className="font-semibold" style={{ color: colors.onSurface }}>
              Include "Leave us a review" CTA
            </div>
            <div className="text-xs" style={{ color: colors.muted }}>
              Only shown when the Google review link below is set.
            </div>
          </div>
        </label>

        <label className="block">
          <span className="text-xs font-bold uppercase tracking-wider"
                style={{ color: colors.muted }}>Google review link</span>
          <input value={settings.google_review_link || ""}
                 onChange={(e) => setSettings({...settings, google_review_link: e.target.value})}
                 placeholder="https://g.page/r/…"
                 className="mt-1 w-full rounded-lg px-3 py-2"
                 style={{ backgroundColor: colors.background,
                          border: `1px solid ${colors.border}`,
                          color: colors.onSurface }}
                 data-testid="auto-email-review-link" />
        </label>

        <label className="block">
          <span className="text-xs font-bold uppercase tracking-wider"
                style={{ color: colors.muted }}>Custom footer text (optional)</span>
          <textarea value={settings.footer_text || ""}
                     onChange={(e) => setSettings({...settings, footer_text: e.target.value})}
                     rows={3}
                     placeholder="Family-owned since 2003 • Licensed & insured"
                     className="mt-1 w-full rounded-lg px-3 py-2"
                     style={{ backgroundColor: colors.background,
                              border: `1px solid ${colors.border}`,
                              color: colors.onSurface }}
                     data-testid="auto-email-footer" />
        </label>

        <div className="flex items-center gap-3">
          <button onClick={save} disabled={saving}
                  className="px-4 py-2 rounded-xl font-bold"
                  style={{ backgroundColor: colors.brand, color: "#fff", opacity: saving ? 0.5 : 1 }}
                  data-testid="auto-email-save">
            {saving ? "Saving…" : "Save"}
          </button>
          <button onClick={doPreview}
                  className="px-4 py-2 rounded-xl font-bold flex items-center gap-1"
                  style={{ backgroundColor: colors.surface, color: colors.brand,
                            border: `1px solid ${colors.brand}` }}
                  data-testid="auto-email-preview-btn">
            <Eye size={14} /> Preview email
          </button>
          {savedFlash ? (
            <span className="text-sm flex items-center gap-1"
                  style={{ color: savedFlash.ok ? "#166534" : "#991B1B" }}>
              {savedFlash.ok ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}
              {savedFlash.msg}
            </span>
          ) : null}
        </div>
      </div>

      {previewErr ? (
        <div className="mt-4 rounded-xl p-3 text-sm"
             style={{ backgroundColor: "#FEE2E2", color: "#991B1B" }}
             data-testid="auto-email-preview-error">
          {previewErr === "Not Found" || previewErr.includes("404")
            ? "No submitted service report yet — submit one first, then preview."
            : previewErr}
        </div>
      ) : null}

      {preview ? (
        <div className="mt-4 rounded-2xl p-4"
             style={{ backgroundColor: colors.surface,
                       border: `1px solid ${colors.border}` }}
             data-testid="auto-email-preview">
          <div className="flex items-center gap-2 mb-3">
            <Eye size={14} style={{ color: colors.brand }} />
            <div className="text-xs font-bold uppercase tracking-wider"
                 style={{ color: colors.muted }}>Preview</div>
          </div>
          <div className="text-sm mb-2" style={{ color: colors.onSurface }}>
            <strong>Subject:</strong> {preview.subject}
          </div>
          <div className="rounded-lg p-3 mt-2 max-h-[500px] overflow-auto"
               style={{ backgroundColor: "#fff",
                        border: `1px solid ${colors.border}` }}
               dangerouslySetInnerHTML={{__html: preview.html}} />
        </div>
      ) : null}
    </div>
  );
}
