import React, { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ArrowLeft, Repeat, Plus, Trash2 } from 'lucide-react';
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
import JobTitleCombobox from "@/components/JobTitleCombobox";
import MasterServiceCombobox from "@/components/services/MasterServiceCombobox";
// Feb 2026 · Color-coded Service / Repair segmented toggle. Same
// control lives on ScheduleJobEditModal via the shared component.
import WorkClassToggle from "@/components/jobs/WorkClassToggle";
// Feb-2026 · Jobs Overhaul Phase 1 — inline pricebook combobox for
// the new Line Items section on /jobs/new. Shared with K71 quotes/
// invoices editor and JobDetail's LineItemsSection picker modal.
// TODO(jobs-overhaul-phase-3): extract the whole Line Items block
// (JSX + helpers) into a shared LineItemsEditor once JobDetail's
// overhaul lands so /jobs/new and the Edit Job modal parity work
// from a single implementation.
import PricebookItemPicker from "@/components/pricebook/PricebookItemPicker";

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
  // Feb-2026 · Jobs Overhaul Phase 1 — Service Category dropdown.
  // Sourced from ``GET /api/service-categories`` (payload shape:
  // ``{items: [{id, name, ...}], total}``). Paired-ID pattern:
  // ``form.service_category_id`` drives the <select>;
  // ``form.service_category_name`` is denormalized alongside so
  // the create payload carries both in the same wire contract
  // Income Drilldown uses.
  const [serviceCategories, setServiceCategories] = useState([]);
  // Inline pricebook combobox for the Line Items section — value
  // is emptied on each pick so the search field resets to add
  // another line without stale text.
  const [pbSearch, setPbSearch] = useState("");
  const [toast, setToast] = useState(null);
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState(null);
  // Feb-2026 · Backlog Item 2 — auto-suggest tech from crew. When the
  // admin picks a crew, we auto-populate the technician field with
  // the crew's ``default_tech_id`` (or first member as fallback).
  // ``techDirty`` tracks whether the admin has manually touched the
  // technician field — once true, a subsequent crew change no longer
  // overwrites the pick. Reset on submit.
  const [techDirty, setTechDirty] = useState(Boolean(preselectedTech));
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
    // Feb-2026 · Jobs Overhaul Phase 1 — Service Category paired
    // ID/name plus editable Line Items array. Line Items subtotal
    // auto-writes ``form.price`` unless the user hand-edits the
    // Price field (``price_manually_overridden`` flag). See the
    // sync ``useEffect`` + ``onPriceChange`` handler below.
    service_category_id: "",
    service_category_name: "",
    line_items: [],
    price_manually_overridden: false,
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
    // Feb-2026 · Jobs Overhaul Phase 1 — Service Categories for
    // the new dropdown. GET /api/service-categories returns
    // ``{items: [{id, name, ...}], total}`` — silent failure keeps
    // the form usable when the caller's role is 403 (only
    // admin/super_admin can list categories today).
    api.get("/service-categories")
      .then((res) => setServiceCategories(
        Array.isArray(res?.items) ? res.items : (Array.isArray(res) ? res : []),
      ))
      .catch(() => setServiceCategories([]));
  }, []);

  // Refresh property list whenever the picked customer changes.
  //
  // Phase P1 · Feb-2026 — customer-switch invalidates the previously
  // picked property.  Previous ship's ``if (f.property_id) return f``
  // "preserve user pick" clause LEAKED the outgoing customer's
  // ``property_id`` into the new customer's payload, which then
  // 422-ed on the backend (``property_customer_mismatch``) or —
  // worse — silently paired the new customer with a stale
  // property.  We now clear ``property_id`` before every fetch so
  // the 0/1/2+ auto-select rules re-run cleanly against the new
  // customer's property set.
  const previousCustomerRef = React.useRef(preselectedCustomer);
  useEffect(() => {
    // If the customer_id actually CHANGED (vs. initial mount for
    // an edit-mode pre-fill), null the previous customer's
    // property before we refetch.
    if (previousCustomerRef.current && previousCustomerRef.current !== form.customer_id) {
      setForm((f) => ({ ...f, property_id: "" }));
    }
    previousCustomerRef.current = form.customer_id;

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
          // Preserve a user pick ONLY when the new customer actually
          // owns that property; otherwise the auto-select below
          // takes over.
          if (f.property_id && active.some((p) => p.id === f.property_id)) {
            return f;
          }
          if (active.length === 1) return { ...f, property_id: active[0].id };
          if (active.length >= 2) {
            const primary = active.find((p) => (p.sort_order ?? 99) === 0) || active[0];
            return { ...f, property_id: primary.id };
          }
          return { ...f, property_id: "" };
        });
      })
      .catch(() => setProperties([]))
      .finally(() => setPropsLoading(false));
  }, [form.customer_id]);

  const services = useMemo(
    () => Array.from(new Set(items.map((i) => i.category).concat(["Pool Cleaning", "Repair", "Chemical Delivery", "Landscape"]))),
    [items]
  );

  // Feb-2026 · Backlog Item 2 — crew → technician auto-suggest.
  // When the admin picks a crew, populate the technician field
  // with the crew's ``default_tech_id`` (if the schema starts
  // carrying it) OR the first tech in ``tech_ids`` as the
  // pragmatic fallback. Never overwrites a manual pick (see
  // ``techDirty``). Runs client-side against the already-loaded
  // ``crews`` list — no extra API call needed since the /crews
  // response includes the members array.
  useEffect(() => {
    if (!form.crew_id) return;
    if (techDirty) return;
    const crew = crews.find((c) => c.id === form.crew_id);
    if (!crew) return;
    // Prefer explicit default_tech_id → first member's tech id →
    // raw first tech_ids entry (crews may carry either shape).
    const memberTechId =
      crew.default_tech_id
      || (crew.members || []).find((m) => m && m.id && m.is_active !== false)?.id
      || (crew.tech_ids || [])[0]
      || "";
    if (memberTechId && memberTechId !== form.technician_id) {
      setForm((f) => ({ ...f, technician_id: memberTechId }));
    }
  }, [form.crew_id, crews, techDirty]);   // eslint-disable-line react-hooks/exhaustive-deps -- form.technician_id read is intentionally not a dep to avoid rebounce loops

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  // Feb-2026 · Jobs Overhaul Phase 1 — Line Items helpers.
  //
  // Design rationale (matches user directive Q1 = "manual override
  // flag"):
  //   • ``lineItemsSubtotal`` = Σ (row.quantity × row.unit_price).
  //   • When line items are non-empty AND the user has NOT typed
  //     into the Price field, ``form.price`` mirrors the subtotal
  //     via the sync effect below.
  //   • When the user types into the Price field, we flip
  //     ``price_manually_overridden`` — the sync effect steps back
  //     and lets their value stick. A subtle hint + "Recalculate"
  //     affordance clears the flag and returns to subtotal-driven.
  //
  // TODO(jobs-overhaul-phase-3): extract this cluster + the JSX
  // below into ``@/components/jobs/LineItemsEditor`` so the Edit
  // Job modal parity (Phase 2) and the JobDetail overhaul (Phase 3)
  // share one implementation.
  const lineItemsSubtotal = useMemo(
    () =>
      (form.line_items || []).reduce(
        (sum, li) =>
          sum
          + (Number(li.quantity) || 0) * (Number(li.unit_price) || 0),
        0,
      ),
    [form.line_items],
  );

  useEffect(() => {
    if ((form.line_items || []).length === 0) return;
    if (form.price_manually_overridden) return;
    const next = Number(lineItemsSubtotal.toFixed(2));
    setForm((f) => (Number(f.price) === next ? f : { ...f, price: next }));
  }, [lineItemsSubtotal, form.line_items, form.price_manually_overridden]);

  const addBlankLine = () =>
    setForm((f) => ({
      ...f,
      line_items: [
        ...(f.line_items || []),
        { description: "", quantity: 1, unit_price: 0 },
      ],
    }));

  const addPricebookLine = (row) =>
    setForm((f) => ({
      ...f,
      line_items: [
        ...(f.line_items || []),
        {
          description: row?.name || row?.description || "",
          quantity: 1,
          unit_price: Number(row?.unit_price || 0),
          // Optional back-reference so a future backend contract
          // extension (Phase 2/3) can persist the pricebook link.
          pricebook_item_id: row?.id || null,
        },
      ],
    }));

  const updateLine = (idx, patch) =>
    setForm((f) => ({
      ...f,
      line_items: (f.line_items || []).map((li, i) =>
        i === idx ? { ...li, ...patch } : li,
      ),
    }));

  const removeLine = (idx) =>
    setForm((f) => ({
      ...f,
      line_items: (f.line_items || []).filter((_, i) => i !== idx),
    }));

  const onPriceChange = (e) =>
    setForm((f) => ({
      ...f,
      price: e.target.value,
      price_manually_overridden: true,
    }));

  const recalcPriceFromLineItems = () =>
    setForm((f) => ({
      ...f,
      price: Number(lineItemsSubtotal.toFixed(2)),
      price_manually_overridden: false,
    }));

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
      // Feb-2026 · Jobs Overhaul Phase 1 — Service Category paired
      // ID + name. Only sent when a category is picked so back-
      // compat with existing POST /jobs consumers is preserved
      // (Pydantic v2 default ``extra="ignore"`` silently drops
      // these until a follow-up phase widens the backend
      // contract). Mirrors the Income Drilldown FE→BE payload.
      if (form.service_category_id) {
        payload.service_category_id = form.service_category_id;
        payload.service_category_name = form.service_category_name || "";
      }
      // Feb-2026 · Jobs Overhaul Phase 1 — Line Items list. Only
      // sent when the operator actually filled the section so
      // legacy price-only flows stay byte-identical on the wire.
      if ((form.line_items || []).length > 0) {
        payload.line_items = form.line_items.map((li) => ({
          description: li.description || "",
          quantity: Number(li.quantity) || 0,
          unit_price: Number(li.unit_price) || 0,
          ...(li.pricebook_item_id
            ? { pricebook_item_id: li.pricebook_item_id }
            : {}),
        }));
      }
      const first = await api.post("/jobs", payload);
      // If recurring, create the follow-up visits from the preview.
      const cadenceIsRecurring = preview && Array.isArray(preview.dates)
        && preview.dates.length > 1
        && form.cadence !== "one_time";
      let lastMaterialisedDate = form.scheduled_date;
      if (cadenceIsRecurring) {
        for (const d of preview.dates.slice(1)) {
          await api.post("/jobs", { ...payload, scheduled_date: d });
          lastMaterialisedDate = d;
        }
      }
      // Phase K4 · Feb-2026 — Bug fix: recurring jobs created from
      // the Schedule (`/jobs/new` reached from the Schedule page)
      // were never appearing on the Recurring Jobs page.  The
      // weekly / biweekly / same-day-monthly cadences historically
      // only pre-materialized N one-off `db.jobs` rows and never
      // wrote a template to `db.recurring_job_templates`, so the
      // `GET /recurring-jobs` listing was blind to them.  We now
      // also POST /recurring-jobs alongside the pre-materialized
      // jobs.  ``last_generated_through`` is stamped to the last
      // preview date so the H10 daily generator won't double-book
      // any occurrence the frontend has already created; it will
      // pick up cleanly from ``lastMaterialisedDate + 1`` on the
      // next nightly run.  Best-effort — a template-side failure
      // does NOT roll back the Jobs inserts (they're the source
      // of truth for scheduling).
      if (cadenceIsRecurring) {
        const cadenceToFreq = {
          weekly:   "weekly",
          biweekly: "biweekly",
          monthly:  "monthly",
        };
        const freq = cadenceToFreq[form.cadence] || null;
        if (freq) {
          const tplPayload = {
            customer_id: form.customer_id,
            service_type: form.service_type || "Pool Cleaning",
            frequency: freq,
            start_date: form.scheduled_date,
            price_cents: Math.round((Number(form.price) || 0) * 100),
            notes: form.notes || "",
            active: true,
            work_class: form.work_class || "service",
            recurrence_never_ends: true,
            end_date: null,
          };
          // Anchor day-of-week for weekly/biweekly cadences so the
          // generator advances on the correct weekday. day_of_month
          // for monthly same-day-of-month.
          if (freq === "weekly" || freq === "biweekly") {
            const d = new Date(form.scheduled_date);
            if (!Number.isNaN(d.getTime())) {
              // ISO weekday: Mon=0 … Sun=6 per RecurringJobIn.
              const jsDow = d.getUTCDay(); // 0=Sun … 6=Sat
              tplPayload.day_of_week = (jsDow + 6) % 7;
            }
          } else if (freq === "monthly") {
            const d = new Date(form.scheduled_date);
            if (!Number.isNaN(d.getTime())) {
              tplPayload.day_of_month = d.getUTCDate();
            }
          }
          if (form.property_id) tplPayload.property_id = form.property_id;
          if (form.technician_id) tplPayload.assigned_tech_id = form.technician_id;
          if (form.crew_id) tplPayload.crew_id = form.crew_id;
          // Phase K4 · Feb-2026 — seed the generator cursor to the
          // last pre-materialized date so H10 doesn't double-book.
          if (lastMaterialisedDate) {
            tplPayload.last_generated_through = lastMaterialisedDate;
          }
          try {
            await api.post("/recurring-jobs", tplPayload);
          } catch (_te) {
            // Template creation is a best-effort mirror — never
            // rolls back the pre-materialized jobs.  Surface a
            // soft warning so the operator can retry the template
            // side manually from the Recurring Jobs page.
            setToast({
              tone: "warn",
              message: "Series created — Recurring Jobs entry may need manual creation.",
            });
          }
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
          {/* Feb-2026 MP2 UI — property picker.
              Phase P1 · Feb-2026 — dropdown is ONLY rendered when the
              customer has ≥2 active properties.  Single-property
              customers get the property auto-selected silently via
              the ``useEffect`` above (no UI noise on the common
              case).  Zero-property (legacy) customers fall through
              to the customer's default address on the server side. */}
          {form.customer_id && properties.length >= 2 ? (
            <div>
              <label className="text-xs font-semibold tracking-wide mb-1 block" style={{ color: colors.onSurfaceSecondary }}>
                SELECT PROPERTY *
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
                <option value="">Choose a property…</option>
                {properties.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.label} — {p.address?.line1 || ""}
                  </option>
                ))}
              </select>
              {!form.property_id ? (
                <div className="text-xs mt-1" style={{ color: colors.danger }} data-testid="jf-property-required">
                  This customer has {properties.length} properties — pick one.
                </div>
              ) : null}
            </div>
          ) : (form.customer_id && propsLoading) ? (
            <div className="text-xs" style={{ color: colors.onSurfaceSecondary }}>Loading properties…</div>
          ) : null}
          <JobTitleCombobox
            label="TITLE *"
            value={form.title}
            onChange={(v) => setForm((prev) => ({ ...prev, title: v }))}
            testid="jf-title"
          />
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
            <WorkClassToggle
              value={form.work_class}
              onChange={(v) => setForm((f) => ({ ...f, work_class: v }))}
              testIdPrefix="jf-work-class"
            />
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="text-xs font-semibold tracking-wide mb-1 block" style={{ color: colors.onSurfaceSecondary }}>
                SERVICE TYPE
              </label>
              {/* Phase P16.1 · Feb-2026 — searchable Master Service
                   combobox in place of the plain select. Picks
                   auto-fill ``form.price`` (dollars) from the
                   Master Service ``default_price``. JobNew has no
                   ``service_category_id`` field, so the combobox's
                   category auto-fill is a no-op here (parent
                   simply doesn't watch it). Free-typing still
                   works — service_type stays a plain string, which
                   preserves back-compat with legacy job seeds. */}
              <MasterServiceCombobox
                value={form.service_type || ""}
                defaultPriceHint={
                  Number.isFinite(form.price) && form.price > 0
                    ? Number(form.price) : null
                }
                onChange={({ name, default_price }) => {
                  setForm((f) => {
                    const next = { ...f, service_type: name };
                    // Feb-2026 · Jobs Overhaul Phase 1 — when the
                    // user has already built a Line Items list on
                    // this form, defer to the subtotal-driven
                    // Price. Picking a Master Service still
                    // updates ``service_type`` but leaves Price
                    // alone so the K2 subtotal contract wins.
                    const hasLineItems =
                      (f.line_items || []).length > 0;
                    if (
                      Number.isFinite(default_price)
                      && default_price != null
                      && !hasLineItems
                    ) {
                      next.price = Number(default_price);
                    }
                    return next;
                  });
                }}
                placeholder="Choose a service…"
                testid="jf-service"
              />
            </div>
            <div>
              <label className="text-xs font-semibold tracking-wide mb-1 block" style={{ color: colors.onSurfaceSecondary }}>
                TECHNICIAN
              </label>
              <select
                value={form.technician_id}
                onChange={(e) => {
                  // Feb-2026 · Backlog Item 2 — flag manual pick so
                  // the crew-auto-suggest effect stops overwriting.
                  setTechDirty(true);
                  set("technician_id")(e);
                }}
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
          {/* Feb-2026 · Jobs Overhaul Phase 1 — Service Category
              dropdown. Sourced from ``GET /api/service-categories``;
              stores the paired ``{id, name}`` on the form so the
              submit payload carries both fields (mirrors the
              Income Drilldown FE→BE contract).  Placed directly
              beneath the Service Type / Technician row so the two
              related taxonomy axes sit together on the form. */}
          <div>
            <label
              className="text-xs font-semibold tracking-wide mb-1 block"
              style={{ color: colors.onSurfaceSecondary }}
            >
              SERVICE CATEGORY
            </label>
            <select
              value={form.service_category_id || ""}
              onChange={(e) => {
                const id = e.target.value;
                const cat = serviceCategories.find(
                  (c) => c.id === id,
                );
                setForm((f) => ({
                  ...f,
                  service_category_id: id,
                  service_category_name: cat?.name || "",
                }));
              }}
              className="w-full px-3.5 py-2.5 rounded-lg outline-none text-sm focus:ring-2"
              style={{
                backgroundColor: colors.surface,
                color: colors.onSurface,
                border: `1px solid ${colors.border}`,
              }}
              data-testid="jf-service-category"
            >
              <option value="">Choose a category…</option>
              {serviceCategories.map((c) => (
                <option
                  key={c.id}
                  value={c.id}
                  data-testid={`jf-service-category-opt-${c.id}`}
                >
                  {c.name}
                </option>
              ))}
            </select>
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
          <div>
            <TextInput
              label="PRICE"
              type="number"
              step="0.01"
              value={form.price}
              onChange={onPriceChange}
              testid="jf-price"
            />
            {/* Feb-2026 · Jobs Overhaul Phase 1 — subtle hint when
                the user's manual Price edit is overriding a
                populated Line Items subtotal.  "Recalculate" clears
                the override flag so the sync effect re-drives
                Price from the subtotal. */}
            {(form.line_items || []).length > 0
              && form.price_manually_overridden ? (
              <div
                className="text-xs mt-1 flex items-center gap-2"
                style={{ color: colors.muted }}
                data-testid="jf-price-manual-hint"
              >
                <span>
                  Manually overridden — Line Items subtotal was $
                  {lineItemsSubtotal.toFixed(2)}.
                </span>
                <button
                  type="button"
                  onClick={recalcPriceFromLineItems}
                  className="underline font-semibold"
                  style={{ color: colors.brand }}
                  data-testid="jf-price-recalc"
                >
                  Recalculate
                </button>
              </div>
            ) : null}
          </div>
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

        {/*
          Feb-2026 · Jobs Overhaul Phase 1 — Line Items card.
          Mirrors the Edit Job modal's ``LineItemsSection`` shape
          in spirit but operates on ``form.line_items`` (in-memory
          state) since JobNew is a create form — no ``jobId`` yet.
          The array is included in the ``POST /jobs`` payload only
          when non-empty (see submit handler).
          TODO(jobs-overhaul-phase-3): extract this whole block +
          the helpers into a shared LineItemsEditor once JobDetail
          overhaul lands.
        */}
        <div
          className="rounded-2xl p-5 mb-4"
          style={{
            backgroundColor: colors.surface,
            border: `1px solid ${colors.border}`,
          }}
          data-testid="jf-line-items-section"
        >
          <div className="flex items-center justify-between mb-3 gap-3 flex-wrap">
            <div>
              <h3
                className="text-lg font-bold"
                style={{ color: colors.onSurface }}
              >
                Line Items
              </h3>
              <p className="text-xs" style={{ color: colors.muted }}>
                Add items from the pricebook or type your own. The
                subtotal auto-fills the Price field above.
              </p>
            </div>
            <div className="flex items-center">
              <Button
                type="button"
                testid="jf-li-add-blank"
                onClick={addBlankLine}
              >
                <Plus size={14} /> Add line
              </Button>
            </div>
          </div>
          {/* "Add from pricebook" affordance — the inline picker
              acts as a search-and-add. Typing surfaces the
              pricebook dropdown; picking a row appends a line and
              clears the input.  See
              ``@/components/pricebook/PricebookItemPicker`` for
              the debounce + keyboard-navigation contract. */}
          <div className="mb-3">
            <PricebookItemPicker
              value={pbSearch}
              onChange={setPbSearch}
              onSelect={(row) => {
                addPricebookLine(row);
                setPbSearch("");
              }}
              placeholder="Add from pricebook — search by item name…"
              testidPrefix="jf-li-pricebook"
              wrapperTestid="jf-li-add-pricebook"
              inputTestid="jf-li-pricebook-input"
            />
          </div>
          {(form.line_items || []).length === 0 ? (
            <div
              className="p-4 text-sm text-center rounded-lg"
              style={{
                background: colors.surfaceSecondary,
                color: colors.muted,
              }}
              data-testid="jf-li-empty"
            >
              No line items yet.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table
                className="w-full text-sm"
                data-testid="jf-li-table"
              >
                <thead>
                  <tr>
                    {["Description", "Qty", "Unit", "Total", ""].map(
                      (h) => (
                        <th
                          key={h || "actions"}
                          className={
                            h === "Total"
                              ? "text-right text-[10px] uppercase font-bold px-2 py-1"
                              : "text-left text-[10px] uppercase font-bold px-2 py-1"
                          }
                          style={{
                            color: colors.muted,
                            borderBottom: `1px solid ${colors.border}`,
                          }}
                        >
                          {h}
                        </th>
                      ),
                    )}
                  </tr>
                </thead>
                <tbody>
                  {form.line_items.map((li, i) => {
                    const rowTotal =
                      (Number(li.quantity) || 0)
                      * (Number(li.unit_price) || 0);
                    return (
                      <tr
                        key={i}
                        data-testid={`jf-li-row-${i}`}
                        style={{
                          borderBottom: `1px solid ${colors.border}`,
                        }}
                      >
                        <td className="px-2 py-2 align-top">
                          <input
                            type="text"
                            value={li.description || ""}
                            onChange={(e) =>
                              updateLine(i, {
                                description: e.target.value,
                              })
                            }
                            className="w-full px-2 py-1 rounded-md text-sm"
                            style={{
                              border: `1px solid ${colors.border}`,
                              background: colors.surface,
                              color: colors.onSurface,
                            }}
                            data-testid={`jf-li-desc-${i}`}
                          />
                        </td>
                        <td className="px-2 py-2 align-top">
                          <input
                            type="number"
                            min="0"
                            step="0.5"
                            value={li.quantity ?? 1}
                            onChange={(e) =>
                              updateLine(i, {
                                quantity: e.target.value,
                              })
                            }
                            className="w-20 px-2 py-1 rounded-md text-sm"
                            style={{
                              border: `1px solid ${colors.border}`,
                              background: colors.surface,
                              color: colors.onSurface,
                            }}
                            data-testid={`jf-li-qty-${i}`}
                          />
                        </td>
                        <td className="px-2 py-2 align-top">
                          <input
                            type="number"
                            min="0"
                            step="0.01"
                            value={li.unit_price ?? 0}
                            onChange={(e) =>
                              updateLine(i, {
                                unit_price: e.target.value,
                              })
                            }
                            className="w-24 px-2 py-1 rounded-md text-sm"
                            style={{
                              border: `1px solid ${colors.border}`,
                              background: colors.surface,
                              color: colors.onSurface,
                            }}
                            data-testid={`jf-li-unit-${i}`}
                          />
                        </td>
                        <td
                          className="px-2 py-2 align-top text-right font-semibold"
                          style={{ color: colors.onSurface }}
                          data-testid={`jf-li-total-${i}`}
                        >
                          {`$${rowTotal.toFixed(2)}`}
                        </td>
                        <td className="px-2 py-2 align-top text-right">
                          <button
                            type="button"
                            onClick={() => removeLine(i)}
                            style={{
                              background: "transparent",
                              border: 0,
                              cursor: "pointer",
                              color: colors.danger || colors.error,
                            }}
                            aria-label="Remove line"
                            data-testid={`jf-li-del-${i}`}
                          >
                            <Trash2 size={14} />
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
                <tfoot>
                  <tr>
                    <td colSpan={3} className="px-2 py-1"></td>
                    <td
                      className="px-2 py-1 text-right text-sm font-bold"
                      style={{ color: colors.onSurface }}
                      data-testid="jf-li-subtotal"
                    >
                      {`Subtotal $${lineItemsSubtotal.toFixed(2)}`}
                    </td>
                    <td></td>
                  </tr>
                </tfoot>
              </table>
            </div>
          )}
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
          <Button type="submit" variant="primary" disabled={busy} testid="jf-submit">
            {busy ? "Creating…" : "Create job"}
          </Button>
        </div>
      </form>

      <Toast toast={toast} onClose={() => setToast(null)} />
    </div>
  );
}
