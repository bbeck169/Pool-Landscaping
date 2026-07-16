import React, { useEffect, useState } from "react";
import { mustConfirm } from "@/components/ui/confirm-dialog";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, Save, RotateCcw } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

function Card({ children, className = "", testId }) {
  return (
    <div
      className={`rounded-2xl ${className}`}
      style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      data-testid={testId}
    >
      {children}
    </div>
  );
}

function Toast({ msg, onDone }) {
  useEffect(() => {
    if (!msg) return;
    const t = setTimeout(onDone, 3000);
    return () => clearTimeout(t);
  }, [msg, onDone]);
  if (!msg) return null;
  return (
    <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 px-4 py-2.5 rounded-xl text-sm font-semibold shadow-lg"
         style={{ backgroundColor: colors.onSurface, color: "#fff" }}
         data-testid="terms-toast">
      {msg}
    </div>
  );
}

export default function TermsSettings() {
  const nav = useNavigate();
  const [form, setForm] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [toast, setToast] = useState("");

  const load = () => {
    setLoading(true);
    api.get("/settings/terms")
      .then((r) => { setForm(r); setLoading(false); })
      .catch((e) => { setToast(e.message); setLoading(false); });
  };
  useEffect(load, []);

  const save = async () => {
    setSaving(true);
    try {
      const r = await api.put("/settings/terms", form);
      setForm(r);
      setToast("Defaults saved");
    } catch (e) { setToast(e.message); }
    finally { setSaving(false); }
  };

  const reset = async () => {
    if (!(await mustConfirm({ title: "Reset to defaults?", description: "Reset both defaults to the built-in AquaTerra text?", tone: "danger" }))) return;
    setResetting(true);
    try {
      const r = await api.post("/settings/terms/reset", {});
      setForm(r);
      setToast("Reset to defaults");
    } catch (e) { setToast(e.message); }
    finally { setResetting(false); }
  };

  if (loading) return <div className="p-8 text-sm" style={{ color: colors.muted }}>Loading…</div>;

  return (
    <div className="p-4 md:p-8 max-w-4xl mx-auto" data-testid="terms-settings-page">
      <div className="flex items-center gap-3 mb-6">
        <button onClick={() => nav(-1)}
                className="p-2 rounded-lg hover:brightness-95"
                style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
                data-testid="back-btn">
          <ArrowLeft size={16} />
        </button>
        <div>
          <h1 className="text-2xl md:text-3xl font-bold" style={{ color: colors.onSurface }}>
            Terms &amp; Conditions
          </h1>
          <p className="text-xs mt-0.5" style={{ color: colors.muted }}>
            Default legal text pre-filled on every new estimate and invoice. You can override per-document at any time.
          </p>
        </div>
      </div>

      <Card className="p-6 mb-4">
        <label className="block mb-5">
          <div className="text-sm font-semibold mb-1.5" style={{ color: colors.onSurface }}>
            Default Estimate / Quote Terms
          </div>
          <textarea
            rows={6}
            value={form.default_quote_terms || ""}
            onChange={(e) => setForm({ ...form, default_quote_terms: e.target.value })}
            className="w-full px-3 py-2 text-sm rounded-lg outline-none focus:ring-2"
            style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
            data-testid="quote-terms-input"
          />
        </label>

        <label className="block">
          <div className="text-sm font-semibold mb-1.5" style={{ color: colors.onSurface }}>
            Default Invoice Terms
          </div>
          <textarea
            rows={6}
            value={form.default_invoice_terms || ""}
            onChange={(e) => setForm({ ...form, default_invoice_terms: e.target.value })}
            className="w-full px-3 py-2 text-sm rounded-lg outline-none focus:ring-2"
            style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
            data-testid="invoice-terms-input"
          />
        </label>

        <div className="mt-5 flex flex-wrap items-center justify-between gap-3 pt-4"
             style={{ borderTop: `1px solid ${colors.border}` }}>
          <div className="text-xs" style={{ color: colors.muted }}>
            Applied automatically when a new quote or invoice is created without a `terms` value.
          </div>
          <div className="flex gap-2">
            <button onClick={reset} disabled={resetting}
                    className="flex items-center gap-1.5 px-3 py-2 text-sm font-semibold rounded-lg disabled:opacity-60"
                    style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                    data-testid="terms-reset">
              <RotateCcw size={13} /> {resetting ? "Resetting…" : "Reset to defaults"}
            </button>
            <button onClick={save} disabled={saving}
                    className="flex items-center gap-1.5 px-4 py-2 text-sm font-semibold rounded-lg disabled:opacity-60"
                    style={{ backgroundColor: colors.brand, color: "#fff" }}
                    data-testid="terms-save">
              <Save size={13} /> {saving ? "Saving…" : "Save"}
            </button>
          </div>
        </div>
      </Card>

      <Toast msg={toast} onDone={() => setToast("")} />
    </div>
  );
}
