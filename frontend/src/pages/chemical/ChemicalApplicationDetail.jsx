/**
 * Feb-2026 · C4 · Chemical Application detail view.
 *
 * Thin admin/manager read-only shell that fetches a single
 * chemical-application record and renders it in a read-only layout
 * mirroring the form sections. Admins see an "Edit" link that
 * routes to ``/admin/chemical-applications/:id/edit``; managers +
 * super_admins see the read-only layout only (backend PATCH is
 * ``require_admin`` per C1).
 */
import React, { useEffect, useState } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import { FlaskConical, ArrowLeft, Pencil, Lock } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api";
import { colors } from "@/theme";
import { useAuth } from "@/auth";
import { ReiBadge } from "@/pages/chemical/ChemicalApplicationsList";
// Feb-2026 · N5-T1 · PageHeader adoption sweep (Option A: replace).
import PageHeader from "@/components/layout/PageHeader";


function Field({ label, value, testid }) {
  return (
    <div>
      <div className="text-xs font-semibold uppercase tracking-wide"
           style={{ color: colors.muted }}>
        {label}
      </div>
      <div className="text-sm mt-0.5"
           style={{ color: colors.onSurface }}
           data-testid={testid}>
        {value === null || value === undefined || value === "" ? "—" : value}
      </div>
    </div>
  );
}


export default function ChemicalApplicationDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { role } = useAuth();
  const [rec, setRec] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    let cancelled = false;
    api.get(`/chemical-applications/${id}`)
      .then((r) => { if (!cancelled) setRec(r); })
      .catch((e) => {
        if (cancelled) return;
        setErr(e?.message || "Failed to load record");
        toast.error(e?.message || "Failed to load record");
      });
    return () => { cancelled = true; };
  }, [id]);

  const isAdmin = role === "admin" || role === "super_admin";

  if (err) {
    return (
      <div className="max-w-3xl mx-auto px-4 py-8"
           data-testid="chem-app-detail-error">
        <div className="p-4 rounded-xl text-sm"
             style={{ backgroundColor: "#FEF2F2", color: "#991B1B" }}>
          {err}
        </div>
      </div>
    );
  }

  if (!rec) {
    return (
      <div className="max-w-3xl mx-auto px-4 py-8"
           data-testid="chem-app-detail-loading">
        <div className="animate-pulse h-8 w-64 rounded"
             style={{ backgroundColor: colors.surfaceSecondary }} />
        <div className="mt-4 animate-pulse h-64 rounded-2xl"
             style={{ backgroundColor: colors.surfaceSecondary }} />
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 py-6"
         data-testid="chemical-application-detail-page">
      <div className="flex items-center justify-between mb-4">
        <Link to="/admin/chemical-applications"
              className="text-xs font-semibold inline-flex items-center gap-1"
              style={{ color: colors.muted }}
              data-testid="chem-app-detail-back">
          <ArrowLeft size={12} /> Back to list
        </Link>
        {isAdmin ? (
          <button type="button"
                  onClick={() => navigate(`/admin/chemical-applications/${id}/edit`)}
                  className="text-xs font-semibold px-3 py-1.5 rounded-lg inline-flex items-center gap-1"
                  style={{ backgroundColor: colors.brand,
                            color: colors.onBrandPrimary }}
                  data-testid="chem-app-detail-edit-btn">
            <Pencil size={12} /> Edit
          </button>
        ) : (
          <span className="text-xs inline-flex items-center gap-1"
                style={{ color: colors.muted }}
                data-testid="chem-app-detail-read-only-badge">
            <Lock size={11} /> Read-only
          </span>
        )}
      </div>

      <h1 className="sr-only" data-testid="chem-app-detail-title">
        {rec.chemical_name || "Chemical Application"}
      </h1>
      {/* Feb-2026 · N5-T1 · PageHeader adoption. Replaces the
          inline H1 + REI badge row with the shared <PageHeader/>;
          the screen-reader-only H1 above preserves the
          ``chem-app-detail-title`` testid contract. */}
      <PageHeader
        title={
          <span className="inline-flex items-center gap-2">
            <FlaskConical size={22} />
            <span>{rec.chemical_name || "Chemical Application"}</span>
          </span>
        }
        actions={
          <ReiBadge reiUnlockAt={rec.rei_unlock_at}
                    testid="chem-app-detail-rei" />
        }
      />

      <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 p-4 rounded-2xl"
           style={{ backgroundColor: colors.surface,
                     border: `1px solid ${colors.border}` }}>
        <Field label="Date"           value={rec.application_date}
               testid="chem-app-detail-date" />
        <Field label="Start / Stop"   value={`${(rec.start_time || "").slice(0,5)} – ${(rec.stop_time || "").slice(0,5)}`}
               testid="chem-app-detail-time" />
        <Field label="Technician"     value={rec.technician_name || "—"}
               testid="chem-app-detail-technician" />
        <Field label="Address"        value={rec.property_address || "—"}
               testid="chem-app-detail-address" />
        <Field label="Target Pest"    value={rec.target_pest}
               testid="chem-app-detail-target-pest" />
        <Field label="REI (hours)"    value={rec.rei_hours}
               testid="chem-app-detail-rei-hours" />
        <Field label="Area (sqft)"    value={rec.area_treated_sqft}
               testid="chem-app-detail-area" />
        <Field label="Amount (gal)"   value={rec.amount_sprayed_gal}
               testid="chem-app-detail-amount" />
        <Field label="Concentrate (oz)" value={rec.concentrate_oz}
               testid="chem-app-detail-concentrate" />
        <Field label="Temp (°F)"       value={rec.temp_f}
               testid="chem-app-detail-temp" />
        <Field label="Humidity (%)"    value={rec.humidity_pct}
               testid="chem-app-detail-humidity" />
        <Field label="Wind"            value={rec.wind_mph
                                                  ? `${rec.wind_mph} mph ${rec.wind_direction || ""}`.trim()
                                                  : "—"}
               testid="chem-app-detail-wind" />
        <Field label="Weather Source"  value={rec.weather_source || "manual"}
               testid="chem-app-detail-weather-source" />
        <Field label="License #"       value={rec.license_number || "(not on file)"}
               testid="chem-app-detail-license" />
      </div>

      {Array.isArray(rec.attachments) && rec.attachments.length > 0 && (
        <div className="mt-4 p-4 rounded-2xl"
             style={{ backgroundColor: colors.surface,
                       border: `1px solid ${colors.border}` }}>
          <div className="text-xs font-semibold uppercase tracking-wide mb-2"
               style={{ color: colors.muted }}>
            Attachments
          </div>
          <ul className="space-y-2" data-testid="chem-app-detail-attachments">
            {rec.attachments.map((a, i) => (
              <li key={`${a.url}-${i}`} className="text-sm">
                <a href={a.url} target="_blank" rel="noreferrer"
                   style={{ color: colors.brand }}>
                  {a.filename || a.url}
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}

      {rec.notes && (
        <div className="mt-4 p-4 rounded-2xl"
             style={{ backgroundColor: colors.surface,
                       border: `1px solid ${colors.border}` }}
             data-testid="chem-app-detail-notes">
          <div className="text-xs font-semibold uppercase tracking-wide mb-2"
               style={{ color: colors.muted }}>
            Notes
          </div>
          <div className="text-sm whitespace-pre-wrap"
               style={{ color: colors.onSurface }}>
            {rec.notes}
          </div>
        </div>
      )}
    </div>
  );
}
