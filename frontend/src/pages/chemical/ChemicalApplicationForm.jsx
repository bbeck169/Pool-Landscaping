/**
 * Feb-2026 · C4 · Chemical Applications create/edit form.
 *
 * Two consumers:
 *   1. Route ``/admin/chemical-applications/new``      (create)
 *   2. Route ``/admin/chemical-applications/:id/edit`` (edit)
 *
 * Sections
 * ────────
 *   1. When       — date, start time, stop time
 *   2. Where      — customer picker (autocomplete) + property_address
 *                    (auto-filled from customer's address on select)
 *   3. Weather    — 4 fields + "Get Live Weather" button that calls
 *                    ``GET /api/weather/openweather/current?address=…``
 *                    from C2 and auto-fills the 4 fields.  Manual
 *                    overrides after auto-fill preserve
 *                    ``weather_source: "openweather"`` because the
 *                    regulatory context still applies.
 *   4. Chemical   — chemical name, area sqft, amount gal, concentrate oz
 *   5. Regulatory — target pest, REI hours (with live "unlocks at …"
 *                    helper below the input), read-only license number
 *                    from ``useAuth().user.applicator_license_number``
 *   6. Photos     — reuse ``<FileUpload multiple>`` → appends URLs into
 *                    ``attachments`` list
 *   7. Notes      — optional textarea
 *
 * Save
 * ────
 *   * Create → POST /api/chemical-applications, navigate to
 *     ``/admin/chemical-applications/:id`` on success.
 *   * Edit   → PATCH /api/chemical-applications/:id (admin-only per
 *     backend gate); non-admin viewers see a locked banner.
 *   * On 422: inline field-level error map from the backend detail.
 */
import React, {
  useCallback, useEffect, useMemo, useRef, useState,
} from "react";
import { useNavigate, useParams, Link } from "react-router-dom";
import {
  FlaskConical, Save, X as XIcon, Cloud, Loader2, AlertTriangle,
  Camera, Trash2, Shield, ArrowLeft,
} from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api";
import { colors } from "@/theme";
import { useAuth } from "@/auth";
import CustomerCombobox from "@/components/customers/CustomerCombobox";
import FileUpload from "@/components/files/FileUpload";


// ═══════════════════════════════════════════════════════════════════
// Constants
// ═══════════════════════════════════════════════════════════════════
const CARDINAL_DIRS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
const DEFAULT_STOP_MINUTES = 30;


// ═══════════════════════════════════════════════════════════════════
// Address composition — customer schema is unstructured (legacy
// ``address`` string) OR structured (``address_line1 + city + state
// + postal_code``). Prefer structured; fall back to legacy string.
// ═══════════════════════════════════════════════════════════════════
export function _composeCustomerAddress(customer) {
  if (!customer || typeof customer !== "object") return "";
  const line1 = (customer.address_line1 || "").trim();
  const city  = (customer.city           || "").trim();
  const state = (customer.state          || "").trim();
  const zip   = (customer.postal_code    || "").trim();
  if (line1 || city || state || zip) {
    const tail = [state, zip].filter(Boolean).join(" ");
    return [line1, city, tail].filter(Boolean).join(", ");
  }
  return (customer.address || "").trim();
}


// ═══════════════════════════════════════════════════════════════════
// REI unlock computation — client mirror of backend
// ``_compute_rei_unlock_at`` for the live helper.
// ═══════════════════════════════════════════════════════════════════
export function _computeReiUnlockAt(applicationDate, startTime, reiHours) {
  if (!applicationDate || !startTime) return null;
  const h = Number(reiHours);
  if (!Number.isFinite(h) || h < 0) return null;
  // ``applicationDate`` = "YYYY-MM-DD", ``startTime`` = "HH:MM" or "HH:MM:SS".
  const tt = String(startTime).length >= 5 ? String(startTime).slice(0, 5) : "00:00";
  const iso = `${applicationDate}T${tt}:00`;
  const start = new Date(iso);
  if (Number.isNaN(start.getTime())) return null;
  return new Date(start.getTime() + h * 60 * 60 * 1000);
}


function _fmtLocalDateTime(d) {
  if (!d) return "";
  return d.toLocaleString(undefined, {
    year: "numeric", month: "short", day: "numeric",
    hour: "numeric", minute: "2-digit",
  });
}


// ═══════════════════════════════════════════════════════════════════
// Section header primitive
// ═══════════════════════════════════════════════════════════════════
function SectionHeader({ index, title, right = null }) {
  return (
    <div className="flex items-center justify-between mt-6 mb-3">
      <div className="text-xs font-semibold uppercase tracking-wide"
           style={{ color: colors.muted }}>
        <span className="mr-2" style={{ color: colors.brand }}>
          {String(index).padStart(2, "0")}
        </span>
        {title}
      </div>
      {right}
    </div>
  );
}


function FieldLabel({ children, required = false }) {
  return (
    <label className="block text-xs font-semibold mb-1"
           style={{ color: colors.onSurfaceSecondary }}>
      {children}
      {required && <span className="ml-1" style={{ color: colors.error }}>*</span>}
    </label>
  );
}


function ErrorText({ children }) {
  if (!children) return null;
  return (
    <div className="text-xs mt-1" style={{ color: colors.error }}>
      {children}
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════════
// Form
// ═══════════════════════════════════════════════════════════════════
export default function ChemicalApplicationForm() {
  const navigate = useNavigate();
  const { id } = useParams();
  const isEdit = !!id;
  const { user, role } = useAuth();

  // ── State ──────────────────────────────────────────────────
  const _today = new Date().toISOString().slice(0, 10);
  const _now = new Date().toTimeString().slice(0, 5);
  const _stop = (() => {
    const d = new Date(Date.now() + DEFAULT_STOP_MINUTES * 60 * 1000);
    return d.toTimeString().slice(0, 5);
  })();

  const [form, setForm] = useState({
    application_date: _today,
    start_time: _now,
    stop_time: _stop,
    customer_id: "",
    property_address: "",
    temp_f: "",
    humidity_pct: "",
    wind_mph: "",
    wind_direction: "",
    weather_source: "manual",
    weather_fetched_at: null,
    chemical_name: "",
    area_treated_sqft: "",
    amount_sprayed_gal: "",
    concentrate_oz: "",
    target_pest: "",
    rei_hours: "",
    attachments: [],
    notes: "",
  });
  const [errors, setErrors] = useState({});
  const [customers, setCustomers] = useState([]);
  const [saving, setSaving] = useState(false);
  const [weatherFetching, setWeatherFetching] = useState(false);
  const [loadingRecord, setLoadingRecord] = useState(isEdit);

  const patch = useCallback((next) => {
    setForm((prev) => ({ ...prev, ...next }));
  }, []);

  // ── Bootstrap: customers, edit-mode record ──────────────────
  useEffect(() => {
    api.get("/customers")
      .then((r) => setCustomers(Array.isArray(r) ? r : (r?.items || [])))
      .catch(() => setCustomers([]));
  }, []);

  useEffect(() => {
    if (!isEdit) return;
    setLoadingRecord(true);
    api.get(`/chemical-applications/${id}`)
      .then((rec) => {
        if (!rec || typeof rec !== "object") return;
        patch({
          application_date:    rec.application_date || _today,
          start_time:          (rec.start_time || _now).slice(0, 5),
          stop_time:           (rec.stop_time || _stop).slice(0, 5),
          customer_id:         rec.customer_id || "",
          property_address:    rec.property_address || "",
          temp_f:              rec.temp_f ?? "",
          humidity_pct:        rec.humidity_pct ?? "",
          wind_mph:            rec.wind_mph ?? "",
          wind_direction:      rec.wind_direction || "",
          weather_source:      rec.weather_source || "manual",
          weather_fetched_at:  rec.weather_fetched_at || null,
          chemical_name:       rec.chemical_name || "",
          area_treated_sqft:   rec.area_treated_sqft ?? "",
          amount_sprayed_gal:  rec.amount_sprayed_gal ?? "",
          concentrate_oz:      rec.concentrate_oz ?? "",
          target_pest:         rec.target_pest || "",
          rei_hours:           rec.rei_hours ?? "",
          attachments:         Array.isArray(rec.attachments) ? rec.attachments : [],
          notes:               rec.notes || "",
        });
      })
      .catch((e) => toast.error(e?.message || "Failed to load record"))
      .finally(() => setLoadingRecord(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, isEdit]);

  // ── Customer select → auto-fill property_address ────────────
  const onCustomerChange = useCallback((custId) => {
    const c = customers.find((x) => x.id === custId);
    const addr = _composeCustomerAddress(c);
    patch({
      customer_id: custId,
      property_address: addr || form.property_address,
    });
  }, [customers, form.property_address, patch]);

  // ── Weather fetch — calls C2's /weather/openweather/current ─
  const fetchWeather = useCallback(async () => {
    const addr = (form.property_address || "").trim();
    if (!addr) {
      toast.error("Enter a property address first.");
      return;
    }
    setWeatherFetching(true);
    try {
      const url = `/weather/openweather/current?address=${encodeURIComponent(addr)}`;
      const snap = await api.get(url);
      patch({
        temp_f:            typeof snap.temp_f === "number" ? snap.temp_f : "",
        humidity_pct:      typeof snap.humidity_pct === "number" ? snap.humidity_pct : "",
        wind_mph:          typeof snap.wind_mph === "number" ? snap.wind_mph : "",
        wind_direction:    snap.wind_direction || "",
        weather_source:    "openweather",
        weather_fetched_at: snap.fetched_at || new Date().toISOString(),
      });
      toast.success("Weather fetched from OpenWeather");
    } catch (e) {
      // ``api.js`` wraps HTTPException(detail=...) into ``e.data`` +
      // ``e.status``. Map the taxonomy per C2 endpoint spec.
      const status = e?.status;
      const detail = e?.data?.detail;
      if (status === 404) {
        toast.error("Address not recognized. Please enter weather manually.");
      } else if (status === 500
                    && detail && typeof detail === "object"
                    && detail.code === "WEATHER_CONFIG_ERROR") {
        toast.error("Weather service not configured. Please contact your admin.");
      } else if (status === 502 || status === 503) {
        toast.error("Weather service temporarily unavailable. Please try again shortly.");
      } else {
        toast.error(e?.message || "Weather fetch failed.");
      }
    } finally {
      setWeatherFetching(false);
    }
  }, [form.property_address, patch]);

  // ── Live REI helper ─────────────────────────────────────────
  const reiUnlockPreview = useMemo(
    () => _computeReiUnlockAt(form.application_date, form.start_time, form.rei_hours),
    [form.application_date, form.start_time, form.rei_hours],
  );

  // ── Photo upload → append to attachments ────────────────────
  const onPhotoUploaded = useCallback((payload) => {
    if (!payload || !payload.url) return;
    patch({
      attachments: [
        ...form.attachments,
        {
          url: payload.url,
          filename: payload.filename || payload.name || "",
          content_type: payload.content_type || payload.type || "",
          size_bytes: payload.size_bytes ?? payload.size ?? 0,
        },
      ],
    });
  }, [form.attachments, patch]);

  const removeAttachment = useCallback((idx) => {
    patch({ attachments: form.attachments.filter((_, i) => i !== idx) });
  }, [form.attachments, patch]);

  // ── Client-side validation ──────────────────────────────────
  const validate = useCallback(() => {
    const e = {};
    if (!form.application_date) e.application_date = "Required";
    if (!form.start_time) e.start_time = "Required";
    if (!form.stop_time) e.stop_time = "Required";
    if (!form.customer_id) e.customer_id = "Customer is required";
    if (!form.chemical_name.trim()) e.chemical_name = "Required";
    const area = Number(form.area_treated_sqft);
    if (!Number.isFinite(area) || area <= 0) e.area_treated_sqft = "Must be > 0";
    const amt = Number(form.amount_sprayed_gal);
    if (!Number.isFinite(amt) || amt < 0) e.amount_sprayed_gal = "Must be >= 0";
    const conc = Number(form.concentrate_oz);
    if (!Number.isFinite(conc) || conc < 0) e.concentrate_oz = "Must be >= 0";
    if (!form.target_pest.trim()) e.target_pest = "Required";
    const rh = Number(form.rei_hours);
    if (!Number.isFinite(rh) || rh < 0) e.rei_hours = "Must be >= 0";
    return e;
  }, [form]);

  // ── Submit ──────────────────────────────────────────────────
  const onSubmit = useCallback(async (evt) => {
    if (evt && evt.preventDefault) evt.preventDefault();
    const clientErrors = validate();
    if (Object.keys(clientErrors).length) {
      setErrors(clientErrors);
      toast.error("Please fix the errors above");
      return;
    }
    setErrors({});
    setSaving(true);
    try {
      const body = {
        application_date:   form.application_date,
        start_time:         form.start_time.length === 5
                              ? `${form.start_time}:00` : form.start_time,
        stop_time:          form.stop_time.length === 5
                              ? `${form.stop_time}:00` : form.stop_time,
        customer_id:        form.customer_id,
        property_address:   form.property_address || null,
        temp_f:             form.temp_f === "" ? null : Number(form.temp_f),
        humidity_pct:       form.humidity_pct === "" ? null : Number(form.humidity_pct),
        wind_mph:           form.wind_mph === "" ? null : Number(form.wind_mph),
        wind_direction:     form.wind_direction || null,
        weather_source:     form.weather_source || "manual",
        weather_fetched_at: form.weather_fetched_at || null,
        chemical_name:      form.chemical_name.trim(),
        area_treated_sqft:  Number(form.area_treated_sqft),
        amount_sprayed_gal: Number(form.amount_sprayed_gal),
        concentrate_oz:     Number(form.concentrate_oz),
        target_pest:        form.target_pest.trim(),
        rei_hours:          Number(form.rei_hours),
        attachments:        form.attachments,
        notes:              form.notes || "",
      };
      let saved;
      if (isEdit) {
        saved = await api.patch(`/chemical-applications/${id}`, body);
      } else {
        saved = await api.post("/chemical-applications", body);
      }
      toast.success(isEdit ? "Application updated" : "Application saved");
      const nextId = (saved && saved.id) || id;
      if (nextId) navigate(`/admin/chemical-applications/${nextId}`);
    } catch (e) {
      // Backend returns Pydantic ValidationError as ``detail: [{loc:[..]}]``.
      const detail = e?.data?.detail;
      if (Array.isArray(detail)) {
        const map = {};
        for (const item of detail) {
          const loc = Array.isArray(item?.loc) ? item.loc : [];
          const field = loc.length ? loc[loc.length - 1] : null;
          if (field) map[field] = item.msg || "Invalid";
        }
        setErrors(map);
        toast.error("Please fix the errors above");
      } else {
        toast.error(e?.message || "Save failed");
      }
    } finally {
      setSaving(false);
    }
  }, [form, id, isEdit, navigate, validate]);

  // ── Edit-mode role gate ─────────────────────────────────────
  // Backend PATCH is ``require_admin``. Show a locked banner for
  // non-admin viewers on the edit route rather than blowing up at
  // save-time — they came here from somewhere so we owe them clear
  // context, not a submit rejection.
  const canEdit = !isEdit || role === "admin" || role === "super_admin";

  const licenseNumber = user?.applicator_license_number || "";

  if (loadingRecord) {
    return (
      <div className="max-w-3xl mx-auto px-4 py-8"
           data-testid="chem-app-form-loading">
        <div className="animate-pulse h-8 w-64 rounded"
             style={{ backgroundColor: colors.surfaceSecondary }} />
        <div className="mt-4 animate-pulse h-64 rounded-2xl"
             style={{ backgroundColor: colors.surfaceSecondary }} />
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 py-6 pb-32"
         data-testid="chemical-application-form-page">
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <Link to="/admin/chemical-applications"
              className="text-xs font-semibold inline-flex items-center gap-1"
              style={{ color: colors.muted }}
              data-testid="chem-app-form-back">
          <ArrowLeft size={12} /> Back to list
        </Link>
      </div>
      <h1 className="text-2xl md:text-3xl font-bold"
          style={{ color: colors.onSurface }}
          data-testid="chem-app-form-title">
        <FlaskConical size={22} className="inline mr-2" />
        {isEdit ? "Edit Application" : "New Application"}
      </h1>
      <p className="text-xs mt-1" style={{ color: colors.muted }}>
        Regulatory spray log · WPS-compliant fields required.
      </p>

      {/* Edit-mode role lock */}
      {isEdit && !canEdit && (
        <div className="mt-4 p-3 rounded-xl flex items-center gap-2"
             style={{ backgroundColor: "#FEF3C7", color: "#92400E",
                       border: "1px solid #FCD34D" }}
             data-testid="chem-app-form-role-lock">
          <Shield size={14} />
          <span className="text-xs">
            Only admins can edit chemical applications. You can view this record but not save changes.
          </span>
        </div>
      )}

      <form onSubmit={onSubmit}
            data-testid="chem-app-form"
            className="mt-2"
            {...(isEdit && !canEdit ? { onSubmit: (e) => e.preventDefault() } : {})}>

        {/* ─── 1. When ─────────────────────────────────────── */}
        <SectionHeader index={1} title="When" />
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <div>
            <FieldLabel required>Application Date</FieldLabel>
            <input type="date"
                   value={form.application_date}
                   onChange={(e) => patch({ application_date: e.target.value })}
                   disabled={!canEdit}
                   className="w-full px-3 py-2 rounded-lg text-sm outline-none"
                   style={{ backgroundColor: colors.surface,
                             color: colors.onSurface,
                             border: `1px solid ${colors.border}` }}
                   data-testid="chem-app-form-application-date" />
            <ErrorText>{errors.application_date}</ErrorText>
          </div>
          <div>
            <FieldLabel required>Start Time</FieldLabel>
            <input type="time"
                   value={form.start_time}
                   onChange={(e) => patch({ start_time: e.target.value })}
                   disabled={!canEdit}
                   className="w-full px-3 py-2 rounded-lg text-sm outline-none"
                   style={{ backgroundColor: colors.surface,
                             color: colors.onSurface,
                             border: `1px solid ${colors.border}` }}
                   data-testid="chem-app-form-start-time" />
            <ErrorText>{errors.start_time}</ErrorText>
          </div>
          <div>
            <FieldLabel required>Stop Time</FieldLabel>
            <input type="time"
                   value={form.stop_time}
                   onChange={(e) => patch({ stop_time: e.target.value })}
                   disabled={!canEdit}
                   className="w-full px-3 py-2 rounded-lg text-sm outline-none"
                   style={{ backgroundColor: colors.surface,
                             color: colors.onSurface,
                             border: `1px solid ${colors.border}` }}
                   data-testid="chem-app-form-stop-time" />
            <ErrorText>{errors.stop_time}</ErrorText>
          </div>
        </div>

        {/* ─── 2. Where ────────────────────────────────────── */}
        <SectionHeader index={2} title="Where" />
        <div className="space-y-3">
          <div>
            <FieldLabel required>Customer</FieldLabel>
            <CustomerCombobox
              value={form.customer_id}
              onChange={onCustomerChange}
              customers={customers}
              testid="chem-app-form-customer"
              placeholder="Choose a customer…"
              disabled={!canEdit}
            />
            <ErrorText>{errors.customer_id}</ErrorText>
          </div>
          <div>
            <FieldLabel>Property Address</FieldLabel>
            <input type="text"
                   value={form.property_address}
                   onChange={(e) => patch({ property_address: e.target.value })}
                   disabled={!canEdit}
                   placeholder="123 Main St, Austin TX 78701"
                   className="w-full px-3 py-2 rounded-lg text-sm outline-none"
                   style={{ backgroundColor: colors.surface,
                             color: colors.onSurface,
                             border: `1px solid ${colors.border}` }}
                   data-testid="chem-app-form-property-address" />
            <div className="text-xs mt-1" style={{ color: colors.muted }}>
              Auto-filled from the customer&apos;s address on select. Edit if needed for outbuildings / lots.
            </div>
          </div>
        </div>

        {/* ─── 3. Weather ──────────────────────────────────── */}
        <SectionHeader
          index={3}
          title="Weather Conditions"
          right={(
            <button type="button"
                    onClick={fetchWeather}
                    disabled={!canEdit || weatherFetching || !form.customer_id}
                    className="text-xs font-semibold px-3 py-1.5 rounded-lg inline-flex items-center gap-1.5"
                    style={{ backgroundColor: colors.brand,
                              color: colors.onBrandPrimary,
                              opacity: (!canEdit || weatherFetching || !form.customer_id) ? 0.5 : 1,
                              cursor: (!canEdit || weatherFetching || !form.customer_id) ? "not-allowed" : "pointer" }}
                    data-testid="chem-app-form-fetch-weather">
              {weatherFetching
                ? <><Loader2 size={12} className="animate-spin" /> Fetching…</>
                : <><Cloud size={12} /> Get Live Weather Data</>}
            </button>
          )}
        />
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div>
            <FieldLabel>Temperature (°F)</FieldLabel>
            <input type="number" step="0.1" value={form.temp_f}
                   onChange={(e) => patch({ temp_f: e.target.value })}
                   disabled={!canEdit}
                   className="w-full px-3 py-2 rounded-lg text-sm outline-none"
                   style={{ backgroundColor: colors.surface,
                             color: colors.onSurface,
                             border: `1px solid ${colors.border}` }}
                   data-testid="chem-app-form-temp-f" />
          </div>
          <div>
            <FieldLabel>Humidity (%)</FieldLabel>
            <input type="number" step="1" min="0" max="100"
                   value={form.humidity_pct}
                   onChange={(e) => patch({ humidity_pct: e.target.value })}
                   disabled={!canEdit}
                   className="w-full px-3 py-2 rounded-lg text-sm outline-none"
                   style={{ backgroundColor: colors.surface,
                             color: colors.onSurface,
                             border: `1px solid ${colors.border}` }}
                   data-testid="chem-app-form-humidity-pct" />
          </div>
          <div>
            <FieldLabel>Wind Speed (mph)</FieldLabel>
            <input type="number" step="0.1" min="0"
                   value={form.wind_mph}
                   onChange={(e) => patch({ wind_mph: e.target.value })}
                   disabled={!canEdit}
                   className="w-full px-3 py-2 rounded-lg text-sm outline-none"
                   style={{ backgroundColor: colors.surface,
                             color: colors.onSurface,
                             border: `1px solid ${colors.border}` }}
                   data-testid="chem-app-form-wind-mph" />
          </div>
          <div>
            <FieldLabel>Wind Direction</FieldLabel>
            <select value={form.wind_direction}
                    onChange={(e) => patch({ wind_direction: e.target.value })}
                    disabled={!canEdit}
                    className="w-full px-3 py-2 rounded-lg text-sm outline-none"
                    style={{ backgroundColor: colors.surface,
                              color: colors.onSurface,
                              border: `1px solid ${colors.border}` }}
                    data-testid="chem-app-form-wind-direction">
              <option value="">—</option>
              {CARDINAL_DIRS.map((d) => <option key={d} value={d}>{d}</option>)}
            </select>
          </div>
        </div>
        {form.weather_source === "openweather" && (
          <div className="text-xs mt-2 inline-flex items-center gap-1"
               style={{ color: colors.success }}
               data-testid="chem-app-form-weather-source-badge">
            <Cloud size={11} /> Source: OpenWeather
            {form.weather_fetched_at && (
              <span style={{ color: colors.muted }}>
                &nbsp;· fetched {new Date(form.weather_fetched_at).toLocaleString(undefined,
                  { hour: "numeric", minute: "2-digit" })}
              </span>
            )}
          </div>
        )}

        {/* ─── 4. Chemical Details ─────────────────────────── */}
        <SectionHeader index={4} title="Chemical Details" />
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div className="sm:col-span-2">
            <FieldLabel required>Chemical Name</FieldLabel>
            <input type="text" value={form.chemical_name}
                   onChange={(e) => patch({ chemical_name: e.target.value })}
                   disabled={!canEdit}
                   placeholder="e.g. Roundup PowerMAX"
                   className="w-full px-3 py-2 rounded-lg text-sm outline-none"
                   style={{ backgroundColor: colors.surface,
                             color: colors.onSurface,
                             border: `1px solid ${colors.border}` }}
                   data-testid="chem-app-form-chemical-name" />
            <ErrorText>{errors.chemical_name}</ErrorText>
          </div>
          <div>
            <FieldLabel required>Area Treated (sqft)</FieldLabel>
            <input type="number" step="1" min="0"
                   value={form.area_treated_sqft}
                   onChange={(e) => patch({ area_treated_sqft: e.target.value })}
                   disabled={!canEdit}
                   className="w-full px-3 py-2 rounded-lg text-sm outline-none"
                   style={{ backgroundColor: colors.surface,
                             color: colors.onSurface,
                             border: `1px solid ${colors.border}` }}
                   data-testid="chem-app-form-area-treated-sqft" />
            <ErrorText>{errors.area_treated_sqft}</ErrorText>
          </div>
          <div>
            <FieldLabel required>Amount Sprayed (gal)</FieldLabel>
            <input type="number" step="0.1" min="0"
                   value={form.amount_sprayed_gal}
                   onChange={(e) => patch({ amount_sprayed_gal: e.target.value })}
                   disabled={!canEdit}
                   className="w-full px-3 py-2 rounded-lg text-sm outline-none"
                   style={{ backgroundColor: colors.surface,
                             color: colors.onSurface,
                             border: `1px solid ${colors.border}` }}
                   data-testid="chem-app-form-amount-sprayed-gal" />
            <ErrorText>{errors.amount_sprayed_gal}</ErrorText>
          </div>
          <div>
            <FieldLabel required>Concentrate (oz)</FieldLabel>
            <input type="number" step="0.1" min="0"
                   value={form.concentrate_oz}
                   onChange={(e) => patch({ concentrate_oz: e.target.value })}
                   disabled={!canEdit}
                   className="w-full px-3 py-2 rounded-lg text-sm outline-none"
                   style={{ backgroundColor: colors.surface,
                             color: colors.onSurface,
                             border: `1px solid ${colors.border}` }}
                   data-testid="chem-app-form-concentrate-oz" />
            <ErrorText>{errors.concentrate_oz}</ErrorText>
          </div>
        </div>

        {/* ─── 5. Regulatory ───────────────────────────────── */}
        <SectionHeader index={5} title="Regulatory" />
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div className="sm:col-span-2">
            <FieldLabel required>Target Pest</FieldLabel>
            <input type="text" value={form.target_pest}
                   onChange={(e) => patch({ target_pest: e.target.value })}
                   disabled={!canEdit}
                   placeholder="e.g. Poa annua (crabgrass)"
                   className="w-full px-3 py-2 rounded-lg text-sm outline-none"
                   style={{ backgroundColor: colors.surface,
                             color: colors.onSurface,
                             border: `1px solid ${colors.border}` }}
                   data-testid="chem-app-form-target-pest" />
            <ErrorText>{errors.target_pest}</ErrorText>
          </div>
          <div>
            <FieldLabel required>REI (hours)</FieldLabel>
            <input type="number" step="1" min="0"
                   value={form.rei_hours}
                   onChange={(e) => patch({ rei_hours: e.target.value })}
                   disabled={!canEdit}
                   className="w-full px-3 py-2 rounded-lg text-sm outline-none"
                   style={{ backgroundColor: colors.surface,
                             color: colors.onSurface,
                             border: `1px solid ${colors.border}` }}
                   data-testid="chem-app-form-rei-hours" />
            <ErrorText>{errors.rei_hours}</ErrorText>
            {reiUnlockPreview && (
              <div className="text-xs mt-1"
                   style={{ color: colors.brand }}
                   data-testid="chem-app-form-rei-unlock-preview">
                Reentry unlocks at {_fmtLocalDateTime(reiUnlockPreview)}
              </div>
            )}
          </div>
          <div>
            <FieldLabel>Applicator License Number</FieldLabel>
            <div className="w-full px-3 py-2 rounded-lg text-sm"
                 style={{ backgroundColor: colors.surfaceSecondary,
                           color: licenseNumber ? colors.onSurface : colors.muted,
                           border: `1px solid ${colors.border}` }}
                 data-testid="chem-app-form-license-number">
              {licenseNumber || "(not on file)"}
            </div>
            {!licenseNumber && (
              <div className="text-xs mt-1 flex items-center gap-1"
                   style={{ color: "#92400E" }}
                   data-testid="chem-app-form-license-missing-warning">
                <AlertTriangle size={11} />
                No applicator license on file — record will be saved without one.
                Update in your profile settings.
              </div>
            )}
          </div>
        </div>

        {/* ─── 6. Photos ───────────────────────────────────── */}
        <SectionHeader index={6} title="Photos & Documents" />
        <div data-testid="chem-app-form-photos-section">
          {canEdit && (
            <FileUpload
              purpose="chemical_application_evidence"
              linkedEntityType="chemical_application"
              linkedEntityId={id || null}
              accept="image/*,application/pdf"
              multiple
              maxFiles={10}
              onUploaded={onPhotoUploaded}
              buttonLabel="Add photo or document"
            />
          )}
          {form.attachments.length > 0 && (
            <ul className="mt-3 space-y-2"
                data-testid="chem-app-form-attachments-list">
              {form.attachments.map((att, i) => (
                <li key={`${att.url}-${i}`}
                    className="flex items-center gap-3 px-3 py-2 rounded-lg text-sm"
                    style={{ backgroundColor: colors.surfaceSecondary,
                              border: `1px solid ${colors.border}` }}
                    data-testid={`chem-app-form-attachment-${i}`}>
                  <Camera size={14} style={{ color: colors.muted }} />
                  <span className="flex-1 truncate">{att.filename || att.url}</span>
                  {canEdit && (
                    <button type="button"
                            onClick={() => removeAttachment(i)}
                            aria-label={`Remove ${att.filename || "attachment"}`}
                            data-testid={`chem-app-form-attachment-${i}-remove`}>
                      <Trash2 size={13} style={{ color: colors.error }} />
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* ─── 7. Notes ────────────────────────────────────── */}
        <SectionHeader index={7} title="Notes" />
        <textarea rows={3}
                   value={form.notes}
                   onChange={(e) => patch({ notes: e.target.value })}
                   disabled={!canEdit}
                   placeholder="Application context, weather anomalies, customer requests…"
                   className="w-full px-3 py-2 rounded-lg text-sm outline-none"
                   style={{ backgroundColor: colors.surface,
                             color: colors.onSurface,
                             border: `1px solid ${colors.border}` }}
                   data-testid="chem-app-form-notes" />

        {/* ─── Submit bar (sticky) ─────────────────────────── */}
        <div className="fixed left-0 right-0 bottom-0 z-30 p-3 backdrop-blur"
             style={{ backgroundColor: "rgba(255,255,255,0.94)",
                       borderTop: `1px solid ${colors.border}` }}>
          <div className="max-w-3xl mx-auto flex items-center justify-end gap-2">
            <button type="button"
                    onClick={() => navigate("/admin/chemical-applications")}
                    className="text-sm font-semibold px-4 py-2 rounded-lg inline-flex items-center gap-1"
                    style={{ backgroundColor: colors.surface,
                              color: colors.onSurface,
                              border: `1px solid ${colors.border}` }}
                    data-testid="chem-app-form-cancel">
              <XIcon size={14} /> Cancel
            </button>
            <button type="submit"
                    disabled={!canEdit || saving}
                    className="text-sm font-semibold px-4 py-2 rounded-lg inline-flex items-center gap-1"
                    style={{ backgroundColor: colors.nav.bg,
                              color: colors.nav.fg,
                              opacity: (!canEdit || saving) ? 0.5 : 1,
                              cursor: (!canEdit || saving) ? "not-allowed" : "pointer" }}
                    data-testid="chem-app-form-submit">
              {saving
                ? <><Loader2 size={14} className="animate-spin" /> Saving…</>
                : <><Save size={14} /> Save Application</>}
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}
