import React, { useEffect, useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { Sun, Cloud, CloudRain, CloudLightning, Snowflake, Settings2, ArrowRight } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

/**
 * Phase 15C — 5-day weather forecast widget.
 * Mounts on admin dashboard + tech landing page. Uses existing /weather/risk
 * endpoint that already returns service_risk_rating + reasons.
 *
 * Props: role ("admin" | "technician"). Admin lets you click a day → /schedule?date=X.
 */
const ZIP_TO_LATLNG = {
  "85383": { lat: 33.7897, lng: -112.3226 }, // Peoria, AZ default
};

function iconFor(code, label = "") {
  const l = (label || "").toLowerCase();
  if (l.includes("thunder")) return CloudLightning;
  if (l.includes("snow"))    return Snowflake;
  if (l.includes("rain") || l.includes("drizzle")) return CloudRain;
  if (l.includes("cloud"))   return Cloud;
  return Sun;
}
const TONE = {
  good: { bg: "#DCFCE7", fg: "#166534", border: "#86EFAC", label: "Good" },
  fair: { bg: "#FEF3C7", fg: "#92400E", border: "#FCD34D", label: "Fair" },
  poor: { bg: "#FEE2E2", fg: "#991B1B", border: "#FCA5A5", label: "Poor" },
};

const DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
function dayLabel(dateStr, idx) {
  if (idx === 0) return "Today";
  const d = new Date(dateStr + "T12:00:00");
  return DAY_NAMES[d.getDay()];
}

export default function WeatherWidget5Day({ role = "admin" }) {
  const navigate = useNavigate();
  const [zip, setZip] = useState(() => localStorage.getItem("weather_zip") || "85383");
  const [data, setData] = useState(null);
  const [recs, setRecs] = useState(null);
  const [editing, setEditing] = useState(false);
  const [zipInput, setZipInput] = useState(zip);

  const coords = ZIP_TO_LATLNG[zip] || ZIP_TO_LATLNG["85383"];

  const load = () => {
    api.get(`/weather/risk?lat=${coords.lat}&lng=${coords.lng}&days=5`)
       .then(setData).catch(() => setData({ days: [] }));
    if (role === "admin") {
      api.get("/weather/reschedule-recommendations")
         .then(setRecs).catch(() => setRecs({ suggested: [] }));
    }
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 30 * 60 * 1000); // auto refresh every 30 min
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [zip]);

  const saveZip = () => {
    const z = (zipInput || "").trim();
    if (!z) return;
    localStorage.setItem("weather_zip", z);
    setZip(z);
    setEditing(false);
  };

  const days = (data?.days || []).slice(0, 5);
  const affectedCount = recs?.suggested?.length || 0;

  return (
    <div className="rounded-2xl p-4"
         style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
         data-testid="weather-widget-5day">
      <div className="flex items-center justify-between mb-3">
        <div>
          <div className="text-xs font-bold uppercase tracking-wider" style={{ color: colors.muted }}>
            5-day forecast
          </div>
          <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>
            {ZIP_TO_LATLNG[zip] ? "Peoria, AZ" : "Zip"} · {zip}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {role === "admin" && affectedCount > 0 && (
            <button onClick={() => navigate("/schedule")}
                    className="text-[10px] font-bold uppercase px-2 py-1 rounded"
                    style={{ backgroundColor: TONE.poor.bg, color: TONE.poor.fg }}
                    data-testid="weather-reschedule-chip">
              {affectedCount} reschedule{affectedCount > 1 ? "s" : ""} suggested
            </button>
          )}
          {role === "technician" && affectedCount > 0 && (
            <span className="text-[10px] font-bold uppercase px-2 py-1 rounded"
                  style={{ backgroundColor: TONE.fair.bg, color: TONE.fair.fg }}
                  data-testid="weather-tech-warning">
              {affectedCount} weather-impacted
            </span>
          )}
          <button onClick={() => { setEditing((v) => !v); setZipInput(zip); }}
                  className="p-1.5 rounded-lg"
                  style={{ backgroundColor: colors.surfaceSecondary }}
                  title="Change zip" data-testid="weather-zip-toggle">
            <Settings2 size={12} style={{ color: colors.muted }} />
          </button>
        </div>
      </div>

      {editing && (
        <div className="flex items-center gap-2 mb-3">
          <input value={zipInput} onChange={(e) => setZipInput(e.target.value)}
                 placeholder="Zip code"
                 className="px-2 py-1 rounded text-sm outline-none"
                 style={{ border: `1px solid ${colors.border}`, backgroundColor: colors.surface, color: colors.onSurface }}
                 data-testid="weather-zip-input" />
          <button onClick={saveZip}
                  className="text-xs font-bold px-2 py-1 rounded text-white"
                  style={{ backgroundColor: colors.brand }}
                  data-testid="weather-zip-save">Save</button>
        </div>
      )}

      {days.length === 0 ? (
        <div className="text-xs py-4 text-center" style={{ color: colors.muted }}>Loading forecast…</div>
      ) : (
        <div className="grid grid-cols-5 gap-2 md:gap-3 -mx-1 overflow-x-auto"
             data-testid="weather-days-grid">
          {days.map((d, i) => {
            const tone = TONE[d.service_risk_rating] || TONE.fair;
            const Icon = iconFor(d.code, d.label);
            const clickable = role === "admin";
            return (
              <button key={d.date || i}
                      onClick={() => clickable && navigate(`/schedule?date=${d.date}`)}
                      disabled={!clickable}
                      className={"text-left rounded-xl p-2 md:p-3 min-w-[92px] transition " + (clickable ? "hover:brightness-95" : "cursor-default")}
                      style={{
                        backgroundColor: tone.bg,
                        border: `1px solid ${tone.border}`,
                        color: tone.fg,
                      }}
                      data-testid={`weather-day-${i}`}>
                <div className="text-[10px] font-bold uppercase tracking-wide" data-testid={`weather-day-label-${i}`}>
                  {dayLabel(d.date, i)}
                </div>
                <Icon size={20} className="my-1" />
                <div className="text-base font-bold" data-testid={`weather-day-temp-${i}`}>
                  {d.high}°<span className="text-xs font-normal opacity-70"> / {d.low}°</span>
                </div>
                <div className="text-[10px] mt-0.5">💧 {d.precip ?? 0}%</div>
                <div className="text-[10px] font-bold uppercase mt-1" data-testid={`weather-day-risk-${i}`}>
                  {tone.label}
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
