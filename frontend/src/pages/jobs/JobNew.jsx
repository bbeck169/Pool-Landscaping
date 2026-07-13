import React, { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ArrowLeft, Repeat, Sparkles } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import {
  PageHeader,
  Button,
  TextInput,
  Toast,
  Chip,
} from "@/components/ui-kit";

const CADENCES = [
  { k: "one_time", label: "One-time" },
  { k: "weekly", label: "Weekly" },
  { k: "biweekly", label: "Bi-weekly" },
  { k: "monthly", label: "Monthly" },
];

export default function JobNew() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const preselectedCustomer = params.get("customer_id") || "";

  const [customers, setCustomers] = useState([]);
  const [techs, setTechs] = useState([]);
  const [items, setItems] = useState([]);
  const [toast, setToast] = useState(null);
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState(null);

  const [form, setForm] = useState({
    customer_id: preselectedCustomer,
    title: "",
    service_type: "Pool Cleaning",
    technician_id: "",
    scheduled_date: "",
    arrival_window: "",
    notes: "",
    cadence: "one_time",
    price: 0,
  });

  useEffect(() => {
    api.get("/customers").then(setCustomers).catch(() => {});
    api.get("/technicians").then(setTechs).catch(() => {});
    api.get("/items").then(setItems).catch(() => {});
  }, []);

  const services = useMemo(
    () => Array.from(new Set(items.map((i) => i.category).concat(["Pool Cleaning", "Repair", "Chemical Delivery", "Landscape"]))),
    [items]
  );

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  useEffect(() => {
    if (!form.scheduled_date || form.cadence === "one_time") {
      setPreview(null);
      return;
    }
    api
      .post("/jobs/recurrence-preview", {
        start_date: form.scheduled_date,
        cadence: form.cadence,
        count: 4,
      })
      .then(setPreview)
      .catch(() => setPreview(null));
  }, [form.scheduled_date, form.cadence]);

  const submit = async (e) => {
    e.preventDefault();
    if (!form.customer_id) {
      setToast({ tone: "error", message: "Pick a customer" });
      return;
    }
    if (!form.title.trim()) {
      setToast({ tone: "error", message: "Job title required" });
      return;
    }
    setBusy(true);
    try {
      const payload = {
        title: form.title,
        customer_id: form.customer_id,
        service_type: form.service_type,
        technician_id: form.technician_id || null,
        scheduled_date: form.scheduled_date || null,
        notes: form.notes,
        price: Number(form.price) || 0,
        status: "scheduled",
      };
      const first = await api.post("/jobs", payload);
      // If recurring, create the follow-up visits from the preview.
      if (preview && preview.dates?.length > 1) {
        for (const d of preview.dates.slice(1)) {
          await api.post("/jobs", { ...payload, scheduled_date: d });
        }
      }
      setToast({ tone: "success", message: "Job created" });
      setTimeout(() => navigate(`/jobs/${first.id}`), 400);
    } catch (err) {
      setToast({ tone: "error", message: err.message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-6" data-testid="job-new-page">
      <button
        onClick={() => navigate(-1)}
        className="flex items-center gap-1 text-sm font-semibold mb-4"
        style={{ color: colors.muted }}
      >
        <ArrowLeft size={14} /> Back
      </button>
      <PageHeader title="New Job" subtitle="Assign, schedule, or set up a recurring series." />

      <form onSubmit={submit} data-testid="job-form">
        <div
          className="rounded-2xl p-5 space-y-4 mb-4"
          style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
        >
          <div>
            <label className="text-xs font-semibold tracking-wide mb-1 block" style={{ color: colors.onSurfaceSecondary }}>
              CUSTOMER *
            </label>
            <select
              value={form.customer_id}
              onChange={set("customer_id")}
              className="w-full px-3.5 py-2.5 rounded-lg outline-none text-sm focus:ring-2"
              style={{
                backgroundColor: colors.surface,
                color: colors.onSurface,
                border: `1px solid ${colors.border}`,
              }}
              data-testid="jf-customer"
            >
              <option value="">Choose a customer…</option>
              {customers.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>
          <TextInput label="TITLE *" value={form.title} onChange={set("title")} testid="jf-title" />
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="text-xs font-semibold tracking-wide mb-1 block" style={{ color: colors.onSurfaceSecondary }}>
                SERVICE TYPE
              </label>
              <select
                value={form.service_type}
                onChange={set("service_type")}
                className="w-full px-3.5 py-2.5 rounded-lg outline-none text-sm focus:ring-2"
                style={{
                  backgroundColor: colors.surface,
                  color: colors.onSurface,
                  border: `1px solid ${colors.border}`,
                }}
                data-testid="jf-service"
              >
                {services.map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs font-semibold tracking-wide mb-1 block" style={{ color: colors.onSurfaceSecondary }}>
                TECHNICIAN
              </label>
              <select
                value={form.technician_id}
                onChange={set("technician_id")}
                className="w-full px-3.5 py-2.5 rounded-lg outline-none text-sm focus:ring-2"
                style={{
                  backgroundColor: colors.surface,
                  color: colors.onSurface,
                  border: `1px solid ${colors.border}`,
                }}
                data-testid="jf-tech"
              >
                <option value="">Unassigned</option>
                {techs.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <TextInput
              label="SCHEDULED DATE"
              type="date"
              value={form.scheduled_date}
              onChange={set("scheduled_date")}
              testid="jf-date"
            />
            <TextInput
              label="ARRIVAL WINDOW"
              placeholder="e.g. 8-10 am"
              value={form.arrival_window}
              onChange={set("arrival_window")}
              testid="jf-window"
            />
          </div>
          <TextInput
            label="PRICE"
            type="number"
            step="0.01"
            value={form.price}
            onChange={set("price")}
            testid="jf-price"
          />
          <div>
            <label className="text-xs font-semibold tracking-wide mb-1 block" style={{ color: colors.onSurfaceSecondary }}>
              NOTES
            </label>
            <textarea
              rows={3}
              value={form.notes}
              onChange={set("notes")}
              className="w-full px-3.5 py-2.5 rounded-lg outline-none text-sm focus:ring-2"
              style={{
                backgroundColor: colors.surface,
                color: colors.onSurface,
                border: `1px solid ${colors.border}`,
              }}
              data-testid="jf-notes"
            />
          </div>
        </div>

        {/* Recurrence card */}
        <div
          className="rounded-2xl p-5 mb-4"
          style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
        >
          <div className="flex items-center gap-2 mb-3">
            <Repeat size={16} color={colors.brand} />
            <span className="font-semibold" style={{ color: colors.onSurface }}>
              Recurrence
            </span>
          </div>
          <div className="flex flex-wrap gap-2 mb-3">
            {CADENCES.map((c) => (
              <button
                key={c.k}
                type="button"
                onClick={() => setForm((f) => ({ ...f, cadence: c.k }))}
                className="text-xs font-semibold px-3 py-1.5 rounded-full"
                style={{
                  backgroundColor: form.cadence === c.k ? colors.brandTertiary : colors.surfaceSecondary,
                  color: form.cadence === c.k ? colors.onBrandTertiary : colors.onSurfaceSecondary,
                  border: `1px solid ${form.cadence === c.k ? colors.brandTertiary : colors.border}`,
                }}
                data-testid={`jf-cadence-${c.k}`}
              >
                {c.label}
              </button>
            ))}
          </div>
          {preview ? (
            <div data-testid="jf-preview">
              <div className="text-xs uppercase font-semibold mb-1" style={{ color: colors.muted }}>
                Next {preview.count} visits
              </div>
              <div className="flex flex-wrap gap-1.5">
                {preview.dates.map((d) => (
                  <Chip key={d} label={d} tone="brand" testid={`jf-preview-${d}`} />
                ))}
              </div>
            </div>
          ) : (
            <p className="text-xs" style={{ color: colors.muted }}>
              {form.cadence === "one_time"
                ? "Single visit only."
                : "Pick a scheduled date to preview upcoming visits."}
            </p>
          )}
        </div>

        <div className="flex gap-2 justify-end pb-8">
          <Button variant="ghost" onClick={(e) => { e.preventDefault(); navigate(-1); }}>
            Cancel
          </Button>
          <Button type="submit" disabled={busy} testid="jf-submit">
            {busy ? "Creating…" : "Create job"}
          </Button>
        </div>
      </form>

      <Toast toast={toast} onClose={() => setToast(null)} />
    </div>
  );
}
