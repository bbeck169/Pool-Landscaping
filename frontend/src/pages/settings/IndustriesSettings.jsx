/**
 * Phase Feb-2026 · Multi-industry Phase B — Industries settings page.
 *
 * 25-checkbox grid keyed off the shared enum. Auto-save on toggle
 * via ``PATCH /api/tenants/mine/settings`` — no explicit Save button
 * so the UX matches "settings are always in sync". Rejected 422s
 * (invalid_industry, unlikely from checkbox UI but possible on
 * concurrent enum drift) show a red toast; success shows a subtle
 * green "Saved" toast that fades after 1.5s.
 *
 * NO gating behavior lives here — this is Phase B (settings UI only).
 * Phase C will wire the ``useIndustries()`` predicate into feature
 * gates.
 */
import React, { useCallback, useEffect, useState } from "react";
import { Building2, CheckCircle2 } from "lucide-react";
import { colors } from "@/theme";
import { api } from "@/api";
import {
  INDUSTRIES,
  INDUSTRY_LABELS,
} from "@/config/industries";
import { invalidateIndustries } from "@/hooks/useIndustries";

const SUB = "Select all industries your business serves. Feature-gating applies dynamically across the app.";

export default function IndustriesSettings() {
  const [industries, setIndustries] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState({});   // { slug: bool }
  const [toast, setToast] = useState({ kind: "", msg: "" });

  const load = useCallback(async () => {
    try {
      const r = await api.get("/tenants/current");
      setIndustries(Array.isArray(r?.industries) ? r.industries : []);
    } catch {
      setIndustries([]);
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Auto-clear toast after 1.5s (success) / 3s (error).
  useEffect(() => {
    if (!toast.msg) return;
    const t = setTimeout(
      () => setToast({ kind: "", msg: "" }),
      toast.kind === "error" ? 3000 : 1500,
    );
    return () => clearTimeout(t);
  }, [toast]);

  const toggle = useCallback(async (slug, next) => {
    setSaving((s) => ({ ...s, [slug]: true }));
    const optimistic = next
      ? [...industries.filter((x) => x !== slug), slug]
      : industries.filter((x) => x !== slug);
    // Preserve the canonical enum order in the persisted array
    // so the UI never renders the badges in a different order
    // than the settings checkboxes.
    const ordered = INDUSTRIES.filter((s) => optimistic.includes(s));
    setIndustries(ordered);
    try {
      await api.patch("/tenants/mine/settings", { industries: ordered });
      invalidateIndustries();
      setToast({ kind: "success", msg: "Saved" });
    } catch (e) {
      // Roll back on failure.
      setIndustries(industries);
      setToast({
        kind: "error",
        msg: "Failed to save industries. Please refresh and try again.",
      });
    } finally {
      setSaving((s) => {
        const n = { ...s }; delete n[slug]; return n;
      });
    }
  }, [industries]);

  return (
    <div className="space-y-4" data-testid="settings-industries-section">
      <header className="flex items-center gap-2">
        <Building2 size={16} style={{ color: colors.brand }} />
        <h2
          className="text-lg font-bold tracking-tight"
          style={{ color: colors.onSurface }}
          data-testid="settings-industries-title"
        >
          Industries
        </h2>
      </header>
      <p className="text-sm" style={{ color: colors.muted }}>{SUB}</p>

      {loading ? (
        <div
          className="text-sm"
          style={{ color: colors.muted }}
          data-testid="settings-industries-loading"
        >Loading…</div>
      ) : (
        <div
          className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2"
          data-testid="settings-industries-grid"
        >
          {INDUSTRIES.map((slug) => {
            const checked = industries.includes(slug);
            const busy = Boolean(saving[slug]);
            return (
              <label
                key={slug}
                className="flex items-center gap-2 rounded-md px-2 py-1.5 cursor-pointer"
                style={{
                  background: checked ? "rgba(2,132,199,0.06)" : "transparent",
                  border: `1px solid ${checked ? colors.brand : colors.border}`,
                  opacity: busy ? 0.7 : 1,
                }}
              >
                <input
                  type="checkbox"
                  checked={checked}
                  disabled={busy}
                  onChange={(e) => toggle(slug, e.target.checked)}
                  data-testid={`settings-industry-checkbox-${slug}`}
                />
                <span
                  className="text-sm"
                  style={{ color: colors.onSurface }}
                >
                  {INDUSTRY_LABELS[slug]}
                </span>
              </label>
            );
          })}
        </div>
      )}

      {toast.msg ? (
        <div
          role="status"
          className="text-xs px-3 py-1.5 rounded-md inline-flex items-center gap-1"
          style={{
            background: toast.kind === "success"
              ? "rgba(22,163,74,0.10)" : "rgba(220,38,38,0.10)",
            color: toast.kind === "success" ? "#166534" : "#991B1B",
            border: `1px solid ${toast.kind === "success" ? "#86EFAC" : "#FCA5A5"}`,
          }}
          data-testid="settings-industry-save-toast"
        >
          {toast.kind === "success" ? <CheckCircle2 size={11} /> : null}
          {toast.msg}
        </div>
      ) : null}
    </div>
  );
}
