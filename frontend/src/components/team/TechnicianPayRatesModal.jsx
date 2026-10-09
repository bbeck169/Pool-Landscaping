/**
 * Phase 10 · Feb-2026 — Technician pay rates edit modal.
 *
 * Opened from the TeamRoster kebab menu (admin / super_admin only).
 * Two decimal inputs: hourly rate and per-pool-job flat rate. Both
 * are nullable — leaving an input blank persists ``null`` and the
 * labor-cost compute treats it as zero.
 *
 * Payload shape on save:
 *   PATCH /api/users/{id}
 *     { "hourly_rate": "25.50", "per_pool_rate": "10.00" }
 *
 * Rates are sent as strings (not floats) so the server's Decimal
 * parse is lossless. The ``DecimalInput`` primitive already keeps
 * the raw string buffer during entry, so we just forward the
 * commit value as-is when it's a number, or ``null`` when the
 * input is empty.
 */
import React, { useEffect, useState } from "react";

import { api } from "@/api";
import DecimalInput from "@/components/common/DecimalInput";
import { colors } from "@/theme";


function _rateToString(v) {
  // Mongo may return the stored rate as a number (legacy
  // ``users.hourly_rate`` shipped as a float), a string, or null.
  // DecimalInput wants either a number or a string that looks like
  // a number. We stringify numbers to avoid the DecimalInput's
  // "0" fallback that fires when ``value === 0`` ambiguously.
  if (v == null || v === "") return "";
  return String(v);
}


export default function TechnicianPayRatesModal({
  target,
  onClose,
  onSaved,
  onError,
}) {
  const [hourly, setHourly] = useState("");
  const [perPool, setPerPool] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!target) return;
    setHourly(_rateToString(target.hourly_rate));
    setPerPool(_rateToString(target.per_pool_rate));
    setBusy(false);
  }, [target?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!target) return null;

  const submit = async () => {
    setBusy(true);
    try {
      // Null-coalesce — an empty input clears the field on the
      // server; the compute path treats null as zero.
      //
      // DecimalInput's ``onChange`` fires with a parsed Number
      // (not the raw string). Format back to 2-place string on
      // send so the wire payload matches what the user typed —
      // "25.50" stays "25.50", not "25.5". The server also
      // quantises to 2 places on write, but formatting here keeps
      // the wire-level contract tight (and gives the test suite a
      // stable string to assert on).
      const _fmt = (v) => {
        if (v === "" || v == null) return null;
        const n = typeof v === "number" ? v : Number.parseFloat(v);
        if (!Number.isFinite(n)) return null;
        return n.toFixed(2);
      };
      const payload = {
        hourly_rate:   _fmt(hourly),
        per_pool_rate: _fmt(perPool),
      };
      await api.patch(`/users/${target.id}`, payload);
      onSaved?.(`Pay rates saved for ${target.name || target.email}`);
    } catch (e) {
      onError?.(e?.message || "Failed to save pay rates");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ backgroundColor: "rgba(0,0,0,0.5)" }}
      role="dialog"
      aria-modal="true"
      data-testid="tech-pay-rates-modal"
    >
      <div
        className="rounded-xl w-full max-w-md p-5"
        style={{
          backgroundColor: colors.surface,
          border: `1px solid ${colors.border}`,
        }}
      >
        <div
          className="text-lg font-semibold mb-1"
          style={{ color: colors.onSurface }}
        >
          Pay rates — {target.name || target.email}
        </div>
        <div className="text-xs mb-4" style={{ color: colors.muted }}>
          Combined labor cost = hours × hourly rate + completed pool jobs ×
          per-pool rate. Either field can be left blank; blank is treated
          as zero when the labor-cost report is computed.
        </div>

        <div className="mb-3">
          <label
            htmlFor="tech-pay-hourly-input"
            className="block text-sm font-medium mb-1"
            style={{ color: colors.onSurface }}
          >
            Hourly rate ($/hr)
          </label>
          <DecimalInput
            id="tech-pay-hourly-input"
            data-testid="tech-pay-rate-hourly-input"
            value={hourly}
            onChange={setHourly}
            placeholder="e.g. 25.50"
            className="w-full px-3 py-2 rounded-md border text-sm"
            style={{
              borderColor: colors.border,
              backgroundColor: colors.background,
              color: colors.onSurface,
            }}
            disabled={busy}
          />
          <div className="text-[11px] mt-1" style={{ color: colors.muted }}>
            Paid per hour of timecard activity (sourced from clock-in/
            clock-out punches).
          </div>
        </div>

        <div className="mb-5">
          <label
            htmlFor="tech-pay-perpool-input"
            className="block text-sm font-medium mb-1"
            style={{ color: colors.onSurface }}
          >
            Per pool job rate ($)
          </label>
          <DecimalInput
            id="tech-pay-perpool-input"
            data-testid="tech-pay-rate-per-pool-input"
            value={perPool}
            onChange={setPerPool}
            placeholder="e.g. 10.00"
            className="w-full px-3 py-2 rounded-md border text-sm"
            style={{
              borderColor: colors.border,
              backgroundColor: colors.background,
              color: colors.onSurface,
            }}
            disabled={busy}
          />
          <div className="text-[11px] mt-1" style={{ color: colors.muted }}>
            Flat dollar amount per completed pool-service job. Paid in
            addition to (or instead of) the hourly rate.
          </div>
        </div>

        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="px-3 py-2 rounded-md text-sm"
            style={{
              backgroundColor: "transparent",
              color: colors.muted,
              border: `1px solid ${colors.border}`,
            }}
            data-testid="tech-pay-rates-cancel-btn"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={busy}
            className="px-3 py-2 rounded-md text-sm font-semibold"
            style={{
              backgroundColor: colors.brandPrimary,
              color: colors.onBrandPrimary || "#FFFFFF",
              opacity: busy ? 0.6 : 1,
            }}
            data-testid="tech-pay-rates-save-btn"
          >
            {busy ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}
