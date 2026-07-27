/**
 * Phase 34 · Task GG · Feb 2026 — Google Review URL settings screen.
 *
 * Admin-only surface at ``/settings/reviews``. Reads the current
 * ``settings.business_card.google_review_url`` value from
 * ``GET /api/tenants/business-card`` and writes back via
 * ``PATCH /api/tenants/business-card``. Server-side validation
 * (Google Business Profile URL shape) lives in
 * ``routers/tenants.py::update_business_card_v2`` so bad values are
 * rejected at the API layer; the frontend does a mirror check for
 * fast feedback.
 */
import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { ExternalLink, Save, Check, AlertCircle } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import { PageHeader, Button } from "@/components/ui-kit";

const GOOGLE_URL_PREFIXES = [
  "https://g.page/r/",
  "https://www.google.com/maps",
  "https://google.com/maps",
  "https://maps.app.goo.gl/",
  "https://search.google.com/local/writereview",
];

const validateGoogleUrl = (value) => {
  if (!value) return { ok: true, empty: true };
  const v = String(value).trim();
  if (!v.startsWith("https://")) {
    return { ok: false, reason: "Must start with https://" };
  }
  const lower = v.toLowerCase();
  const matched = GOOGLE_URL_PREFIXES.some((p) => lower.startsWith(p));
  if (!matched) {
    return {
      ok: false,
      reason: "Must be a Google Business Profile review link " +
                "(g.page/r/…/review, google.com/maps/…/review, or " +
                "search.google.com/local/writereview)",
    };
  }
  return { ok: true };
};

export default function GoogleReviewSettings() {
  const [value, setValue] = useState("");
  const [initialValue, setInitialValue] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.get("/tenants/business-card")
      .then((card) => {
        const url = card?.google_review_url || "";
        setValue(url);
        setInitialValue(url);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  const validation = validateGoogleUrl(value);
  const isDirty = value !== initialValue;
  const canSave = isDirty && (validation.ok || validation.empty);

  const save = async () => {
    if (!canSave) return;
    setSaving(true);
    try {
      await api.patch("/tenants/business-card", {
        google_review_url: value.trim(),
      });
      setInitialValue(value.trim());
      toast.success("Google review URL saved");
    } catch (e) {
      toast.error(e?.message || "Save failed");
    } finally { setSaving(false); }
  };

  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 py-6 space-y-6"
         data-testid="google-review-settings">
      <PageHeader
        title="Google Review URL"
        subtitle="Where 4-5 star reviewers are sent to post their public review."
      />

      <div className="rounded-2xl p-6 space-y-4"
           style={{ backgroundColor: colors.surface,
                     border: `1px solid ${colors.border}` }}>
        <label htmlFor="grev-url"
               className="block text-sm font-semibold"
               style={{ color: colors.onSurface }}>
          Google Business Profile Review URL
        </label>
        <input
          id="grev-url"
          type="url"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="https://g.page/r/XXXXXXXXX/review"
          className="w-full px-3 py-2.5 rounded-lg text-sm outline-none"
          style={{ border: `1px solid ${!validation.ok && !validation.empty ? "#DC2626" : colors.border}`,
                    background: "#fff", color: colors.onSurface }}
          data-testid="google-review-url-input"
          disabled={loading || saving}
        />
        {!validation.ok && !validation.empty ? (
          <div className="flex items-start gap-2 text-xs"
               style={{ color: "#DC2626" }}
               data-testid="google-review-url-error">
            <AlertCircle size={13} className="flex-shrink-0 mt-0.5" />
            <span>{validation.reason}</span>
          </div>
        ) : null}

        {value && validation.ok && !validation.empty ? (
          <div className="flex items-center gap-2 text-xs"
               style={{ color: "#166534" }}>
            <Check size={13} /> Looks like a valid Google review URL.
          </div>
        ) : null}

        <p className="text-xs mt-2" style={{ color: colors.muted }}>
          Reviewers rating 4 or 5 stars will be prompted to also post on this URL
          (via the customer-facing review submit page). 1-3 star ratings go to
          private admin feedback instead — they are never routed to Google.
        </p>

        <div className="flex items-center gap-2 pt-2">
          <Button
            onClick={save}
            disabled={!canSave || saving || loading}
            testid="google-review-url-save">
            <Save size={14} /> {saving ? "Saving…" : "Save"}
          </Button>
          {value && validation.ok && !validation.empty ? (
            <a
              href={value}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl text-sm font-semibold"
              style={{ border: `1px solid ${colors.border}`,
                        color: colors.onSurface, background: "#fff" }}
              data-testid="google-review-url-test-link"
            >
              <ExternalLink size={13} /> Test link
            </a>
          ) : null}
        </div>
      </div>

      <div className="rounded-2xl p-4 text-xs"
           style={{ backgroundColor: colors.surfaceSecondary,
                     border: `1px solid ${colors.border}`, color: colors.muted }}>
        <div className="font-semibold mb-1"
             style={{ color: colors.onSurface }}>
          How to find your Google review URL
        </div>
        <ol className="list-decimal list-inside space-y-1">
          <li>Sign in to your Google Business Profile.</li>
          <li>Open the "Reviews" tab.</li>
          <li>Click "Share review form" — the URL that copies to your
              clipboard is the correct value to paste here.</li>
        </ol>
      </div>
    </div>
  );
}
