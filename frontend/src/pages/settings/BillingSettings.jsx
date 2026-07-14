/**
 * Phase 20A.2 · Billing Settings — auto-invoice on service-report submit.
 */
import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, Save, Receipt } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

export default function BillingSettings() {
  const nav = useNavigate();
  const [cfg, setCfg] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState("");

  useEffect(() => {
    api.get("/settings/billing")
      .then((r) => { setCfg(r); setLoading(false); })
      .catch((e) => { setToast(e.message); setLoading(false); });
  }, []);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(""), 3000);
    return () => clearTimeout(t);
  }, [toast]);

  const save = async () => {
    setSaving(true);
    try {
      const r = await api.put("/settings/billing", {
        auto_invoice_on_submit: !!cfg.auto_invoice_on_submit,
      });
      setCfg(r);
      setToast("Settings saved");
    } catch (e) { setToast(e.message); }
    finally { setSaving(false); }
  };

  if (loading) return (
    <div className="p-8 text-sm" style={{ color: colors.muted }}>Loading…</div>
  );

  return (
    <div className="p-4 md:p-8 max-w-3xl mx-auto" data-testid="billing-settings-page">
      <div className="flex items-center gap-3 mb-6">
        <button onClick={() => nav(-1)}
                className="p-2 rounded-lg hover:brightness-95"
                style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
                data-testid="billing-back-btn">
          <ArrowLeft size={16} />
        </button>
        <div>
          <h1 className="text-2xl md:text-3xl font-bold" style={{ color: colors.onSurface }}>
            Billing Settings
          </h1>
          <p className="text-xs mt-0.5" style={{ color: colors.muted }}>
            Automatic invoicing behavior when a technician submits a service report.
          </p>
        </div>
      </div>

      <div className="rounded-2xl p-6 mb-4"
           style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
           data-testid="billing-auto-invoice-card">
        <label className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-3">
            <Receipt size={20} style={{ color: colors.brand }}/>
            <div>
              <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>
                Auto-invoice on service report submit
              </div>
              <div className="text-xs mt-0.5" style={{ color: colors.muted }}>
                When a tech submits a report, automatically generate a draft invoice
                for the job. Skips non-billable jobs and zero-price line items.
                Applies pending referral credits (Phase 19).
              </div>
            </div>
          </div>
          <button onClick={() => setCfg({ ...cfg, auto_invoice_on_submit: !cfg.auto_invoice_on_submit })}
                  className="w-11 h-6 rounded-full relative transition ml-3 shrink-0"
                  style={{ backgroundColor: cfg.auto_invoice_on_submit ? colors.brand : colors.surfaceTertiary }}
                  data-testid="auto-invoice-toggle">
            <span className="absolute top-0.5 w-5 h-5 rounded-full bg-white transition-all shadow"
                  style={{ left: cfg.auto_invoice_on_submit ? 22 : 2 }} />
          </button>
        </label>

        <div className="flex justify-end items-center pt-4"
             style={{ borderTop: `1px solid ${colors.border}` }}>
          <button onClick={save} disabled={saving}
                  className="flex items-center gap-1.5 px-4 py-2 text-sm font-semibold rounded-lg disabled:opacity-60"
                  style={{ backgroundColor: colors.brand, color: "#fff" }}
                  data-testid="billing-save-btn">
            <Save size={13} /> {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>

      {toast && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 px-4 py-2.5 rounded-xl text-sm font-semibold shadow-lg"
             style={{ backgroundColor: colors.onSurface, color: "#fff" }}
             data-testid="billing-toast">
          {toast}
        </div>
      )}
    </div>
  );
}
