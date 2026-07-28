/**
 * Phase 20B.1b · Customer self-service appointment booking.
 */
import React, { useEffect, useState } from "react";
import { CalendarClock, CheckCircle2, Clock as ClockIcon } from "lucide-react";
import { api } from "@/api";
import { colors, brandGradientCss } from "@/theme";
import PortalBookingPhotos from "@/components/portal/PortalBookingPhotos";

const SERVICE_TYPES = [
  "Pool Cleaning", "Weekly Pool Service", "Chemical Balance Only",
  "Landscape Maintenance", "Monthly Landscaping", "One-time Cleanup",
];

export default function PortalBook() {
  const [avail, setAvail] = useState({ windows: [] });
  const [service, setService] = useState(SERVICE_TYPES[0]);
  const [pick, setPick] = useState(null);
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [history, setHistory] = useState([]);

  useEffect(() => {
    api.get("/portal/availability?date_range=14")
      .then(setAvail)
      .catch(() => setAvail({ windows: [] }));
    api.get("/portal/appointments").then(setHistory).catch(() => {});
  }, []);

  const submit = async () => {
    if (!pick) { setError("Pick a date & time window"); return; }
    setSubmitting(true); setError("");
    try {
      const r = await api.post("/portal/appointments", {
        service_type: service,
        preferred_date: pick.date,
        preferred_window: pick.window,
        notes,
      });
      setResult(r);
      setHistory([r, ...history]);
    } catch (e) { setError(e.message); }
    finally { setSubmitting(false); }
  };

  return (
    <div className="max-w-4xl mx-auto p-4 md:p-6" data-testid="portal-book-page">
      <div className="mb-6">
        <div className="flex items-center gap-2 mb-1">
          <CalendarClock size={22} style={{ color: colors.brand }}/>
          <h1 className="text-3xl font-bold" style={{ color: colors.onSurface }}>
            Book a Service
          </h1>
        </div>
        <p className="text-sm" style={{ color: colors.muted }}>
          Pick a day + window. Our team will confirm within 24 hours.
        </p>
      </div>

      {result ? (
        <div className="rounded-2xl p-8 text-center"
             style={{ backgroundColor: "#ECFDF5", border: "1px solid #6EE7B7" }}
             data-testid="portal-book-confirmation">
          <CheckCircle2 size={40} className="mx-auto mb-3" style={{ color: "#065F46" }}/>
          <div className="text-lg font-bold" style={{ color: "#065F46" }}>
            Request submitted — pending confirmation
          </div>
          <div className="text-sm mt-2" style={{ color: "#065F46" }}>
            {result.service_type} · {result.preferred_date} · {result.preferred_window}
          </div>
          <button onClick={() => { setResult(null); setPick(null); }}
                  className="mt-6 px-4 py-2 text-sm font-semibold rounded-lg"
                  style={{ backgroundColor: colors.brand, color: "#fff" }}
                  data-testid="portal-book-another">
            Book another
          </button>
          {/* Phase F2c.1 · optional photo upload on the confirmation
              panel — attaches to the freshly created appointment. */}
          <PortalBookingPhotos appointmentId={result.id} />
        </div>
      ) : (
        <>
          <div className="rounded-2xl p-6 mb-4"
               style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
            <label className="block text-xs font-bold uppercase mb-2 tracking-wider"
                   style={{ color: colors.muted }}>Service type</label>
            <select value={service} onChange={(e) => setService(e.target.value)}
                    className="w-full rounded-lg p-2.5 text-sm mb-4"
                    style={{ backgroundColor: colors.background, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                    data-testid="portal-book-service">
              {SERVICE_TYPES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>

            <label className="block text-xs font-bold uppercase mb-2 tracking-wider"
                   style={{ color: colors.muted }}>Preferred window</label>
            <div className="grid grid-cols-2 gap-2 max-h-80 overflow-auto"
                 data-testid="portal-book-windows">
              {avail.windows.slice(0, 12).map((w, i) => (
                <button key={`${w.date}-${w.window}`}
                        onClick={() => !w.full && setPick({ date: w.date, window: w.window })}
                        disabled={w.full}
                        className="p-3 text-sm rounded-lg text-left transition disabled:opacity-40"
                        style={{
                          backgroundColor: pick?.date === w.date && pick?.window === w.window
                            ? colors.brand : colors.background,
                          color: pick?.date === w.date && pick?.window === w.window
                            ? "#fff" : colors.onSurface,
                          border: `1px solid ${colors.border}`,
                        }}
                        data-testid={`portal-book-window-${i}`}>
                  <div className="font-semibold text-xs">{w.label}</div>
                  <div className="text-[10px] mt-0.5 opacity-80">
                    {w.full ? "Full" : `${w.slots_remaining} slots left`}
                  </div>
                </button>
              ))}
            </div>

            <label className="block text-xs font-bold uppercase mb-2 mt-4 tracking-wider"
                   style={{ color: colors.muted }}>Notes (optional)</label>
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)}
                      rows={3}
                      className="w-full rounded-lg p-2.5 text-sm resize-none"
                      style={{ backgroundColor: colors.background, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                      placeholder="Gate code, dog on premises, particular problem area…"
                      data-testid="portal-book-notes" />
          </div>

          {error && (
            <div className="text-sm mb-3 p-2 rounded-lg"
                 style={{ backgroundColor: "#FEE2E2", color: "#991B1B" }}
                 data-testid="portal-book-error">
              {error}
            </div>
          )}

          <button onClick={submit} disabled={submitting}
                  className="w-full py-3 text-sm font-bold rounded-xl disabled:opacity-60 transition"
                  style={{ background: brandGradientCss, color: "#fff" }}
                  data-testid="portal-book-submit">
            {submitting ? "Submitting…" : "Request appointment"}
          </button>
        </>
      )}

      {history.length > 0 && (
        <div className="mt-8">
          <h2 className="text-lg font-bold mb-3" style={{ color: colors.onSurface }}>
            Recent requests
          </h2>
          <div className="space-y-2" data-testid="portal-book-history">
            {history.slice(0, 6).map((h) => (
              <div key={h.id} className="p-3 rounded-lg flex items-center gap-3"
                   style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
                <ClockIcon size={16} style={{ color: colors.muted }}/>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-semibold truncate" style={{ color: colors.onSurface }}>
                    {h.service_type}
                  </div>
                  <div className="text-xs" style={{ color: colors.muted }}>
                    {h.preferred_date} · {h.preferred_window}
                  </div>
                </div>
                <span className="text-xs font-bold uppercase px-2 py-0.5 rounded"
                      style={{
                        backgroundColor:
                          h.status === "confirmed" ? "#DCFCE7" :
                          h.status === "rejected"  ? "#FEE2E2" : "#FEF3C7",
                        color:
                          h.status === "confirmed" ? "#166534" :
                          h.status === "rejected"  ? "#991B1B" : "#92400E",
                      }}>
                  {h.status}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
