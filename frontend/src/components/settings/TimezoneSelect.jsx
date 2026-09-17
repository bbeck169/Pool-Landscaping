/**
 * Feb-2026 · Timezone Finalization — shared IANA timezone picker.
 *
 * Wraps a native ``<select>`` (kept native so the mobile web
 * browser keeps its native picker UX). Same option list rendered
 * on Billing Settings AND Business Settings so both surfaces stay
 * option-for-option identical — a divergence would cause an admin
 * who sets ``America/Denver`` on one page to see ``America/Phoenix``
 * on the other.
 *
 * Option list intentionally locked to the 5 US zones the cron
 * dispatch cares about + UTC for edge-case tenants. The backend
 * still accepts any IANA identifier — this is the CURATED list
 * for the picker, not the accept list for the API.
 *
 * ``data-testid`` remains ``tenant-timezone-picker`` on the root
 * select so downstream E2E tests keep working.
 */
import React from "react";

export const TIMEZONE_OPTIONS = Object.freeze([
  { value: "America/Phoenix", label: "America/Phoenix (AZ)" },
  { value: "America/Los_Angeles", label: "America/Los_Angeles (PT)" },
  { value: "America/Denver", label: "America/Denver (MT)" },
  { value: "America/Chicago", label: "America/Chicago (CT)" },
  { value: "America/New_York", label: "America/New_York (ET)" },
  { value: "UTC", label: "UTC" },
]);

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
        value={value || "America/Phoenix"}
        onChange={onChange}
        disabled={disabled}
        className="text-xs font-semibold px-3 py-1.5 rounded-lg border"
        style={{ opacity: disabled ? 0.6 : 1 }}
      >
        {TIMEZONE_OPTIONS.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </div>
  );
}

export default TimezoneSelect;
