/**
 * Phase P15 · Feb-2026 · Permanent Tenant Timezone Setting — the
 * shared IANA timezone picker.  Consumed exclusively by
 * BusinessSettings.jsx (relocated from BillingSettings.jsx).
 *
 * Wraps a native ``<select>`` (kept native so mobile web keeps
 * its native picker UX).  Option list is fetched from
 * ``GET /api/tenants/timezones`` on mount — the backend is the
 * source of truth for the curated 7-entry whitelist.  A
 * hardcoded ``FALLBACK_TIMEZONE_OPTIONS`` is used ONLY when the
 * fetch throws (network blip / test harness without mocks) so the
 * picker never renders empty.
 *
 * Legacy-value handling: if the tenant's currently-stored ``value``
 * is NOT in the fetched list (e.g. a tenant still on the pre-P15
 * ``UTC`` default), render a disabled synthetic option at the top
 * ``<option value={currentTz} disabled>{currentTz} (legacy)</option>``
 * so the field isn't blank AND the user has to make a fresh, valid
 * pick before ``onChange`` fires.
 *
 * ``data-testid`` remains ``tenant-timezone-picker`` on the root
 * select so downstream E2E tests keep working.
 *
 * Keep in sync with:
 *   * backend/routers/tenants.py :: TIMEZONE_OPTIONS
 */
import React from "react";
import { api } from "@/api";

// Keep in sync with backend/routers/tenants.py TIMEZONE_OPTIONS.
// Used ONLY as a fallback when the /api/tenants/timezones fetch
// fails (network blip, test harness without a mock).  The backend
// is the source of truth — the picker prefers the fetched list.
export const FALLBACK_TIMEZONE_OPTIONS = Object.freeze([
  { value: "America/New_York",    label: "Eastern Time (ET)" },
  { value: "America/Chicago",     label: "Central Time (CT)" },
  { value: "America/Denver",      label: "Mountain Time (MT)" },
  { value: "America/Los_Angeles", label: "Pacific Time (PT)" },
  { value: "America/Anchorage",   label: "Alaska Time" },
  { value: "America/Phoenix",     label: "Arizona (No DST)" },
  { value: "Pacific/Honolulu",    label: "Hawaii (No DST)" },
]);

// Legacy export — the old CHEM2-era code imported this named
// constant.  Kept as an alias so existing importers don't break;
// runtime behavior is fully driven by the fetched list.
export const TIMEZONE_OPTIONS = FALLBACK_TIMEZONE_OPTIONS;

export function TimezoneSelect({
  value,
  onChange,
  disabled = false,
  label = "Timezone",
  helperText = "",
  testid = "tenant-timezone-picker",
  className = "",
  style,
  showLabel = true,
}) {
  const [options, setOptions] = React.useState(FALLBACK_TIMEZONE_OPTIONS);
  const [loaded, setLoaded] = React.useState(false);

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await api.get("/tenants/timezones");
        const list = Array.isArray(r?.timezones) ? r.timezones : [];
        if (!cancelled && list.length > 0) setOptions(list);
      } catch {
        // Network / test-harness miss — keep the fallback list.
      } finally {
        if (!cancelled) setLoaded(true);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const currentTz = value || "";
  const isLegacyValue =
    !!currentTz && !options.some((o) => o.value === currentTz);

  return (
    <div className={`flex items-center justify-between ${className}`}
          style={style}
          data-testid={`${testid}-row`}>
      {showLabel ? (
        <div className="flex-1 min-w-0 pr-4">
          <div className="text-sm font-medium">{label}</div>
          {helperText ? (
            <div className="text-xs mt-0.5 opacity-70">{helperText}</div>
          ) : null}
        </div>
      ) : null}
      <select
        data-testid={testid}
        data-loaded={loaded ? "1" : "0"}
        value={currentTz || "America/Phoenix"}
        onChange={onChange}
        disabled={disabled}
        className="text-xs font-semibold px-3 py-1.5 rounded-lg border"
        style={{ opacity: disabled ? 0.6 : 1 }}
      >
        {isLegacyValue ? (
          <option
            value={currentTz}
            disabled
            data-testid={`${testid}-legacy-option`}
          >
            {currentTz} (legacy)
          </option>
        ) : null}
        {options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </div>
  );
}

export default TimezoneSelect;
