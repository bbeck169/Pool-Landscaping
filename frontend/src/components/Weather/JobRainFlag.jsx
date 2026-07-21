/**
 * JobRainFlag — Feb-2026.
 *
 * Inline warning badge that renders on a tech's / admin's day-list
 * job card when the forecast for the job's scheduled date shows
 * ``chance_of_rain >= 60`` for at least one hour. Purely
 * informational — no rescheduling, no auto-actions. If the hourly
 * payload isn't available (upstream failure, missing key), the
 * badge stays hidden — never surfaces an error state on the card.
 *
 * The badge reuses the shared ``useWeatherHourly`` hook so a job
 * list of N cards + the weather widget only ever issues ONE HTTP
 * request per ``(lat, lon)`` per refresh cycle.
 */
import React from "react";
import { CloudRain } from "lucide-react";
import useWeatherHourly, { hasRainOnDate, maxRainChanceOnDate } from "@/hooks/useWeatherHourly";

const RAIN_THRESHOLD = 60;
const DEFAULT_LAT = 33.7897;
const DEFAULT_LON = -112.3226;

export default function JobRainFlag({ jobId, scheduledDate, lat = DEFAULT_LAT, lon = DEFAULT_LON }) {
  const hourly = useWeatherHourly(lat, lon);
  if (!hourly || !scheduledDate) return null;
  if (!hasRainOnDate(hourly, scheduledDate, RAIN_THRESHOLD)) return null;
  const mx = maxRainChanceOnDate(hourly, scheduledDate);
  const label = `${mx != null ? mx : RAIN_THRESHOLD}% rain`;
  return (
    <span
      className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md text-[10px] font-bold ml-1"
      style={{
        backgroundColor: "#FEE2E2",
        color: "#991B1B",
        border: "1px solid #FCA5A5",
      }}
      data-testid={`job-rain-flag-${jobId}`}
      data-rain-max={mx == null ? "" : String(mx)}
      title={`Forecast shows ≥${RAIN_THRESHOLD}% chance of rain during this job's scheduled day.`}
    >
      <CloudRain size={10} />
      {label}
    </span>
  );
}
