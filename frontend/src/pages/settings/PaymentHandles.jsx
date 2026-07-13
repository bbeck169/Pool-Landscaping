import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, Save, MessageCircle } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import { PageHeader, Button, TextInput, Toast, Chip } from "@/components/ui-kit";

export default function PaymentHandlesSettings() {
  const navigate = useNavigate();
  const [form, setForm] = useState({
    venmo: "",
    zelle: "",
    cashapp: "",
    paypal: "",
    automatic_invoice_texting: false,
  });
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState(null);

  useEffect(() => {
    api
      .get("/settings/payment-handles")
      .then((d) =>
        setForm({
          venmo: d.venmo || "",
          zelle: d.zelle || "",
          cashapp: d.cashapp || "",
          paypal: d.paypal || "",
          automatic_invoice_texting: !!d.automatic_invoice_texting,
        })
      )
      .catch(() => {});
  }, []);

  const set = (k) => (e) => {
    const v = e.target?.type === "checkbox" ? e.target.checked : e.target?.value;
    setForm((f) => ({ ...f, [k]: v }));
  };

  const save = async (e) => {
    e?.preventDefault?.();
    setBusy(true);
    try {
      await api.put("/settings/payment-handles", form);
      setToast({ tone: "success", message: "Saved" });
    } catch (err) {
      setToast({ tone: "error", message: err.message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-6" data-testid="payment-handles-page">
      <button onClick={() => navigate(-1)} className="flex items-center gap-1 text-sm font-semibold mb-4" style={{ color: colors.muted }}>
        <ArrowLeft size={14} /> Back
      </button>
      <PageHeader
        title="Payment Handles"
        subtitle="Alternate ways customers can pay you — appear next to Stripe on invoice emails/SMS."
      />

      <form onSubmit={save}>
        <div
          className="rounded-2xl p-5 space-y-4 mb-4"
          style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
        >
          <TextInput label="VENMO HANDLE" placeholder="@your-venmo" value={form.venmo} onChange={set("venmo")} testid="ph-venmo" />
          <TextInput label="ZELLE (phone or email)" value={form.zelle} onChange={set("zelle")} testid="ph-zelle" />
          <TextInput label="CASH APP HANDLE" placeholder="$YourCashApp" value={form.cashapp} onChange={set("cashapp")} testid="ph-cashapp" />
          <TextInput label="PAYPAL (email or paypal.me)" value={form.paypal} onChange={set("paypal")} testid="ph-paypal" />
        </div>

        <div
          className="rounded-2xl p-5 mb-4"
          style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
        >
          <div className="flex items-start gap-3">
            <div className="w-9 h-9 rounded-xl flex items-center justify-center" style={{ backgroundColor: colors.brandTertiary, color: colors.brand }}>
              <MessageCircle size={18} />
            </div>
            <div className="flex-1">
              <div className="font-semibold" style={{ color: colors.onSurface }}>Automatic Invoice Texting</div>
              <p className="text-sm mt-0.5" style={{ color: colors.muted }}>
                When a new invoice is created, auto-send an SMS with the payment link.
                Uses Twilio — falls back to a no-op if Twilio env vars are unset.
              </p>
              <label className="mt-3 inline-flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={form.automatic_invoice_texting}
                  onChange={set("automatic_invoice_texting")}
                  data-testid="ph-auto-sms"
                />
                Enable automatic invoice texting
              </label>
              <div className="mt-2">
                {form.automatic_invoice_texting ? (
                  <Chip label="Auto-SMS ON" tone="success" />
                ) : (
                  <Chip label="Auto-SMS OFF" tone="neutral" />
                )}
              </div>
            </div>
          </div>
        </div>

        <div className="flex justify-end pb-8">
          <Button type="submit" disabled={busy} testid="ph-save">
            <Save size={14} /> {busy ? "Saving…" : "Save settings"}
          </Button>
        </div>
      </form>

      <Toast toast={toast} onClose={() => setToast(null)} />
    </div>
  );
}
