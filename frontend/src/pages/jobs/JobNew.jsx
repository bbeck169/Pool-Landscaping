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
import {
  MonthlyNthWeekdaySelector,
  RecurrenceEndsRadio,
} from "@/components/recurring/MonthlyNthWeekdaySelector";
import CustomerCombobox from "@/components/customers/CustomerCombobox";

const CADENCES = [
  { k: "one_time", label: "One-time" },
  { k: "weekly", label: "Weekly" },
  { k: "biweekly", label: "Bi-weekly" },
  { k: "monthly", label: "Monthly" },
  { k: "quarterly", label: "Quarterly (every 3 months)" },
  { k: "semi_annual", label: "Semi-annual (every 6 months)" },
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
  // Feb-2026 · "+ New Scheduled Job" bug fix — service_type must
  // start BLANK when the modal is opened from JobDetail. Uses
  // ``??`` so an empty string coming through ``initialValues`` /
  // URL param is respected (as opposed to ``||`` which would fall
  // back to the "Pool Cleaning" default on empty). Direct
  // navigations to ``/jobs/new`` still land on the historical
  // "Pool Cleaning" default because neither source is present.
  const preselectedService =
    iv.service_type ?? params.get("service_type") ?? "Pool Cleaning";

  const [customers, setCustomers] = useState([]);
  const [techs, setTechs] = useState([]);
  const [crews, setCrews] = useState([]);
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
    service_type: preselectedService,
    technician_id: preselectedTech,
    scheduled_date: preselectedDate,
    arrival_window: "",
    notes: "",
    cadence: "one_time",
    price: 0,
    property_id: preselectedProperty,
    // Feb-2026 · Crew Phase A · New Job crew overlay. Optional. When
    // set alongside ``technician_id`` the tech remains the lead and
    // the crew is an overlay (locked product decision). Validated
    // in ``routers/jobs.py::create_job`` against the caller's tenant.
    crew_id: "",
    // Feb 2026 · Work-class dimension. Orthogonal to ``service_type``
    // (which is a free-text service description like "Pool Cleaning"
    // or "Repair"). ``work_class`` splits every job into
    // ``"service"`` (routine visit) vs ``"repair"`` (fix-something)
    // so tech counters split cleanly. Backend defaults to service
    // when the field is missing, but we send it explicitly for
    // clarity. See ``backend/services/work_class.py``.
    work_class: "service",
    // Feb-2026 · Monthly Nth-weekday recurrence controls. Only sent
    // to the ``/api/recurring-jobs`` endpoint when ``cadence ===
    // "monthly"`` AND ``monthly_pattern === "nth_weekday"``. Kept in
    // the same ``form`` object so a single ``set(k)`` handler and
    // the shared ``MonthlyNthWeekdaySelector`` component can drive
    // both surfaces.
    monthly_pattern: "day_of_month",
    monthly_nth_week: "first",
    monthly_weekday: 0,
    recurrence_never_ends: true,
    end_date: null,
  });

  useEffect(() => {
    // Feb-2026 · Customer picker UX — filter to active customers only.
    // Backend supports ``is_active=true`` at ``routers/customers.py``.
    // Also excludes muted rows per that endpoint's semantics.
    api.get("/customers?is_active=true").then(setCustomers).catch(() => {});
    api.get("/technicians").then(setTechs).catch(() => {});
    // Feb-2026 · Crew Phase A — populate the crew overlay picker.
    // Silent failure keeps the form usable when the /crews endpoint
    // is 403 for the current role (only admin/manager see crews).
    api.get("/crews").then((rows) => setCrews(Array.isArray(rows) ? rows : []))
       .catch(() => setCrews([]));
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
      // Feb-2026 · Monthly Nth-weekday recurrence branch. When the
      // user selects ``cadence === "monthly"`` AND the shared
      // MonthlyNthWeekdaySelector is set to ``nth_weekday``, we
      // create a proper recurring-job TEMPLATE rather than one-off
      // jobs so the backend Nth-weekday engine drives future
      // materialization. The rest of the flow (POST /jobs +
      // preview loop) remains unchanged for one-time / weekly /
      // biweekly / same-day-monthly cadences.
      const wantsNthWeekdayTemplate =
        form.cadence === "monthly" &&
        form.monthly_pattern === "nth_weekday";
      if (wantsNthWeekdayTemplate) {
        const tplPayload = {
          customer_id: form.customer_id,
          service_type: form.service_type || null,
          notes: form.notes || "",
          price_cents: Math.round((Number(form.price) || 0) * 100),
          start_date: form.scheduled_date || null,
          frequency: "monthly",
          monthly_pattern: "nth_weekday",
          monthly_nth_week: form.monthly_nth_week,
          monthly_weekday: form.monthly_weekday,
          recurrence_never_ends: !!form.recurrence_never_ends,
          end_date: form.recurrence_never_ends ? null : (form.end_date || null),
          active: true,
          // Feb 2026 · Carry work_class into recurring templates so
          // materialized occurrences inherit the service/repair tag.
          work_class: form.work_class || "service",
        };
        if (form.property_id) tplPayload.property_id = form.property_id;
        if (form.technician_id) tplPayload.technician_id = form.technician_id;
        if (form.crew_id) tplPayload.crew_id = form.crew_id;
        const tpl = await api.post("/recurring-jobs", tplPayload);
        setToast({ tone: "success", message: "Recurring series created" });
        if (renderMode === "modal" && typeof onCreated === "function") {
          onCreated(tpl);
        } else {
          setTimeout(() => navigate(`/admin/recurring-jobs`), 400);
        }
        return;
      }
      const payload = {
        title: form.title,
        customer_id: form.customer_id,
        service_type: form.service_type,
        technician_id: form.technician_id || null,
        scheduled_date: form.scheduled_date || null,
        notes: form.notes,
        price: Number(form.price) || 0,
        status: "scheduled",
        // Feb 2026 · Persist the service/repair tag on one-off jobs.
        // Backend defaults to "service" when omitted; sending
        // explicitly keeps the wire payload self-documenting.
        work_class: form.work_class || "service",
      };
      if (form.property_id) payload.property_id = form.property_id;
      if (form.crew_id) payload.crew_id = form.crew_id;
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
            {/* Feb-2026 · UX — replaces the raw <select> with a
                searchable combobox (shadcn Popover + Command). Only
                active customers surface (filtered server-side via
                ``is_active=true``). Keeps ``customer_id`` state
                wiring identical to the old <select> so downstream
                validation + property auto-load behaviour is
                unchanged. testid ``jf-customer`` is preserved on
                the trigger for existing E2E assertions. */}
            <CustomerCombobox
              customers={customers}
              value={form.customer_id}
              onChange={(cid) => setForm((f) => ({ ...f, customer_id: cid }))}
              testid="jf-customer"
            />
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
          {/* Feb 2026 · Work-class picker (Repair vs Service).
              Orthogonal to SERVICE TYPE — a "Pool Cleaning" service_type
              can still be flagged as a Repair visit (e.g. equipment
              fix while onsite). Drives the tech's job-counter split on
              the Today Schedule summary chip + the /api/technicians +
              /api/team roster endpoints. Default Service — the far
              majority of jobs. */}
          <div>
            <label
              className="text-xs font-semibold tracking-wide mb-1 block"
              style={{ color: colors.onSurfaceSecondary }}
            >
              TYPE
            </label>
            <div
              className="inline-flex rounded-lg overflow-hidden"
              role="radiogroup"
              aria-label="Job type"
              data-testid="jf-work-class"
              style={{ border: `1px solid ${colors.border}` }}
            >
              {[
                { value: "service", label: "Service" },
                { value: "repair", label: "Repair" },
              ].map((opt) => {
                const selected = form.work_class === opt.value;
                return (
                  <button
                    key={opt.value}
                    type="button"
                    role="radio"
                    aria-checked={selected}
                    onClick={() =>
                      setForm((f) => ({ ...f, work_class: opt.value }))
                    }
                    className="px-4 py-2 text-sm font-semibold focus:outline-none focus-visible:ring-2"
                    style={{
                      backgroundColor: selected
                        ? colors.primary
                        : colors.surface,
                      color: selected ? "#fff" : colors.onSurface,
                    }}
                    data-testid={`jf-work-class-${opt.value}`}
                  >
                    {opt.label}
                  </button>
                );
              })}
            </div>
          </div>
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
                {/* Feb-2026 · placeholder option so the "+ New
                    Scheduled Job" modal renders visibly blank when
                    ``service_type=""`` is passed as an initial
                    value. Historical /jobs/new callers still land
                    on "Pool Cleaning" (the ``preselectedService``
                    default) so the placeholder is never selected
                    for them. */}
                {!form.service_type ? (
                  <option value="" data-testid="jf-service-placeholder">
                    Choose a service…
                  </option>
                ) : null}
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
          {/*
            Feb-2026 · Crew Phase A · New Job crew overlay.
            Rendered only when the /crews endpoint returned rows —
            for tech-role sessions the endpoint returns [] via the
            role gate in ``routers/ops.py``, so this row silently
            hides without a role check here.
          */}
          {crews.length > 0 ? (
            <div className="grid grid-cols-1 md:grid-cols-1 gap-4">
              <div>
                <label className="text-xs font-semibold tracking-wide mb-1 block"
                       style={{ color: colors.onSurfaceSecondary }}>
                  CREW <span style={{ color: colors.muted }}>(optional overlay)</span>
                </label>
                <select
                  value={form.crew_id}
                  onChange={set("crew_id")}
                  className="w-full px-3.5 py-2.5 rounded-lg outline-none text-sm focus:ring-2"
                  style={{
                    backgroundColor: colors.surface,
                    color: colors.onSurface,
                    border: `1px solid ${colors.border}`,
                  }}
                  data-testid="jf-crew"
                >
                  <option value="">No crew</option>
                  {crews.map((c) => {
                    const memberCount = (c.members || c.tech_ids || []).length;
                    const label = memberCount
                      ? `${c.name} · ${memberCount} member${memberCount === 1 ? "" : "s"}`
                      : c.name;
                    return (
                      <option key={c.id} value={c.id}
                              data-testid={`jf-crew-item-${c.id}`}>
                        {label}
                      </option>
                    );
                  })}
                </select>
              </div>
            </div>
          ) : null}
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
          {form.cadence === "monthly" ? (
            <div className="grid gap-3 mb-3" data-testid="jf-monthly-recurrence">
              {/* Feb-2026 · Monthly Nth-weekday selector + Ends
                  radio. Uses the SAME shared components as
                  /admin/recurring-jobs so the wire contract is
                  canonical in one place. */}
              <MonthlyNthWeekdaySelector
                value={form}
                onChange={(patch) => setForm((f) => ({ ...f, ...patch }))}
                testidPrefix="jf-monthly-"
              />
              <RecurrenceEndsRadio
                value={form}
                onChange={(patch) => setForm((f) => ({ ...f, ...patch }))}
                testidPrefix="jf-recurrence-ends-"
              />
            </div>
          ) : null}
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
