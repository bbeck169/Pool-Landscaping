import React, { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ArrowLeft, Repeat } from 'lucide-react';
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

export default function JobNew({
  initialValues = null,
  renderMode = "page",
  onCreated = null,
  onCancel = null,
} = {}) {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  // Feb-2026 · JobNew is now dual-mode:
  //   • ``renderMode="page"`` (default) — the standalone
  //     /jobs/new route. Reads pre-fills from the URL query
  //     (customer_id / property_id / technician_id /
  //     scheduled_date) so links from /schedule and the new
  //     /jobs/{id} "+ New Scheduled Job" button both work.
  //   • ``renderMode="modal"`` — mounted inside a Dialog by
  //     JobDetail.jsx (and mobile equivalent). Consumes
  //     ``initialValues`` from props, calls ``onCreated`` on
  //     success instead of navigating.
  // Props always beat URL params so a JobDetail modal can
  // enforce customer/property/technician regardless of the
  // active browser URL.
  const iv = initialValues || {};
  const preselectedCustomer =
    iv.customer_id ?? params.get("customer_id") ?? "";
  const preselectedProperty =
    iv.property_id ?? params.get("property_id") ?? "";
  const preselectedTech =
    iv.technician_id ?? params.get("technician_id") ?? "";
  const preselectedDate =
    iv.scheduled_date ?? params.get("scheduled_date") ?? "";

  const [customers, setCustomers] = useState([]);
  const [techs, setTechs] = useState([]);
  const [items, setItems] = useState([]);
  const [toast, setToast] = useState(null);
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState(null);
  // Feb-2026 MP2 UI — property picker step. Loads active properties
  // for the selected customer; when the customer has ≥2 active
  // properties, a valid ``property_id`` is required before submit.
  const [properties, setProperties] = useState([]);
  const [propsLoading, setPropsLoading] = useState(false);

  const [form, setForm] = useState({
    customer_id: preselectedCustomer,
    title: "",
    service_type: "Pool Cleaning",
    technician_id: preselectedTech,
    scheduled_date: preselectedDate,
    arrival_window: "",
    notes: "",
    cadence: "one_time",
    price: 0,
    property_id: preselectedProperty,
  });

  useEffect(() => {
    api.get("/customers").then(setCustomers).catch(() => {});
    api.get("/technicians").then(setTechs).catch(() => {});
    api.get("/items").then(setItems).catch(() => {});
  }, []);

  // Refresh property list whenever the picked customer changes.
  useEffect(() => {
    if (!form.customer_id) { setProperties([]); return; }
    setPropsLoading(true);
    api.get(`/customers/${form.customer_id}/properties`)
      .then((rows) => {
        const active = (rows || []).filter((r) => r.active !== false);
        setProperties(active);
        // Auto-pick when there's exactly one active property so the
        // caller doesn't have to click. Pre-select sort_order=0 for
        // customers with several properties.
        setForm((f) => {
          if (f.property_id) return f;  // preserve user pick
          if (active.length === 1) return { ...f, property_id: active[0].id };
          if (active.length >= 2) {
            const primary = active.find((p) => (p.sort_order ?? 99) === 0) || active[0];
            return { ...f, property_id: primary.id };
          }
          return f;
        });
      })
      .catch(() => setProperties([]))
      .finally(() => setPropsLoading(false));
  }, [form.customer_id]);

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
    // Feb-2026 MP2 UI — property picker enforcement. Backend rejects
    // multi-property customers without an explicit ``property_id``;
    // we surface a friendlier error client-side so the user notices
    // the empty picker before hitting the API.
    if (properties.length >= 2 && !form.property_id) {
      setToast({ tone: "error", message: "Pick a property for this job" });
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
      if (form.property_id) payload.property_id = form.property_id;
      const first = await api.post("/jobs", payload);
      // If recurring, create the follow-up visits from the preview.
      if (preview && preview.dates?.length > 1) {
        for (const d of preview.dates.slice(1)) {
          await api.post("/jobs", { ...payload, scheduled_date: d });
        }
      }
      setToast({ tone: "success", message: "Job created" });
      // Feb-2026 · JobNew modal mode — the parent (JobDetail's
      // "+ New Scheduled Job" flow) supplies ``onCreated`` and
      // owns navigation. Page mode keeps the historical behavior
      // of jumping straight to the new job's detail.
      if (renderMode === "modal" && typeof onCreated === "function") {
        onCreated(first);
      } else {
        setTimeout(() => navigate(`/jobs/${first.id}`), 400);
      }
    } catch (err) {
      setToast({ tone: "error", message: err.message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-6" data-testid="job-new-page">
      {renderMode !== "modal" ? (
        <>
          <button
            onClick={() => navigate(-1)}
            className="flex items-center gap-1 text-sm font-semibold mb-4"
            style={{ color: colors.muted }}
          >
            <ArrowLeft size={14} /> Back
          </button>
          <PageHeader title="New Job" subtitle="Assign, schedule, or set up a recurring series." />
        </>
      ) : null}

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
          {/* Feb-2026 MP2 UI — property picker. Required when the
              customer has ≥2 active properties; hidden entirely when
              the customer has zero (legacy). Auto-fills with the
              sole active property for single-property customers. */}
          {form.customer_id && properties.length > 0 ? (
            <div>
              <label className="text-xs font-semibold tracking-wide mb-1 block" style={{ color: colors.onSurfaceSecondary }}>
                PROPERTY {properties.length >= 2 ? "*" : ""}
              </label>
              <select
                value={form.property_id}
                onChange={set("property_id")}
                className="w-full px-3.5 py-2.5 rounded-lg outline-none text-sm focus:ring-2"
                style={{
                  backgroundColor: colors.surface,
                  color: colors.onSurface,
                  border: `1px solid ${colors.border}`,
                }}
                data-testid="jf-property"
              >
                {properties.length >= 2 ? (
                  <option value="">Choose a property…</option>
                ) : null}
                {properties.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.label} — {p.address?.line1 || ""}
                  </option>
                ))}
              </select>
              {properties.length >= 2 && !form.property_id ? (
                <div className="text-xs mt-1" style={{ color: colors.danger }} data-testid="jf-property-required">
                  This customer has {properties.length} properties — pick one.
                </div>
              ) : null}
            </div>
          ) : (form.customer_id && propsLoading) ? (
            <div className="text-xs" style={{ color: colors.onSurfaceSecondary }}>Loading properties…</div>
          ) : null}
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
          <Button
            variant="ghost"
            onClick={(e) => {
              e.preventDefault();
              if (renderMode === "modal" && typeof onCancel === "function") {
                onCancel();
              } else {
                navigate(-1);
              }
            }}
          >
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
