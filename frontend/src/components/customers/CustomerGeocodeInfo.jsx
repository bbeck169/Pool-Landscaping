/**
 * Feb-2026 · Customer profile — geocode observability line under the
 * primary address.
 *
 * Feature scope note (see /app/memory/FEATURE_CUSTOMER_MANUAL_REGEOCODE_UI.md):
 * Phase 17 (Feb-2026) already auto-geocodes on customer create + on
 * address-field update. This component is NOT a re-implementation of
 * that automation — it only surfaces the resulting lat/lng + a
 * "Re-geocode" escape hatch when the address is on file but the
 * coord fields are missing (ZERO_RESULTS or transient provider
 * error).
 *
 * Fields consumed (already on the ``customer`` payload):
 *   * ``customer.latitude`` + ``customer.longitude`` (canonical P37a
 *     pair — same fields read by ScheduleMap.jsx via
 *     ``service_lat/service_lng`` fallback below).
 *   * ``customer.geocoded_at`` — ISO string.
 *
 * Fallback pair: legacy ``service_lat/service_lng`` (some seed rows
 * only carry the legacy pair). Prefer canonical, fall back to legacy.
 *
 * RBAC — "Re-geocode" button visible only when caller is admin+ /
 * manager (mirrors the server-side ``_MANUAL_GEOCODE_ROLES`` gate in
 * ``routers/customers.py``). Non-admin roles see the coord line but
 * NOT the button.
 */
import React from "react";
import { MapPin, RefreshCcw } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

const _ADMIN_ROLES = new Set(["admin", "super_admin", "owner", "manager"]);

function readCoords(customer) {
  if (!customer) return { lat: null, lng: null };
  const lat = (customer.latitude !== undefined && customer.latitude !== null)
    ? customer.latitude
    : customer.service_lat;
  const lng = (customer.longitude !== undefined && customer.longitude !== null)
    ? customer.longitude
    : customer.service_lng;
  const latN = Number(lat);
  const lngN = Number(lng);
  if (!Number.isFinite(latN) || !Number.isFinite(lngN)) {
    return { lat: null, lng: null };
  }
  return { lat: latN, lng: lngN };
}

export default function CustomerGeocodeInfo({ customer, role, onRefetch, onToast }) {
  const [busy, setBusy] = React.useState(false);
  const { lat, lng } = readCoords(customer);
  const hasCoords = lat !== null && lng !== null;
  const canReGeocode = _ADMIN_ROLES.has((role || "").toLowerCase());

  const handleReGeocode = async () => {
    setBusy(true);
    try {
      const r = await api.post(
        `/customers/${customer.id}/geocode?force=true`
      );
      if (r?.ok) {
        onToast?.({ tone: "success",
                    message: `Geocoded to ${Number(r.lat).toFixed(4)}, ${Number(r.lng).toFixed(4)}` });
      } else {
        const reasonCopy = {
          no_address: "No address on file — add a service address first.",
          not_found: "Google could not locate that address.",
          fresh_cache: "Already geocoded recently.",
          provider_error: "Geocoding provider error — try again.",
        }[r?.reason] || (r?.error || "Geocode failed");
        onToast?.({ tone: "error", message: reasonCopy });
      }
      await onRefetch?.();
    } catch (e) {
      onToast?.({ tone: "error",
                  message: e?.message || "Re-geocode failed" });
    } finally {
      setBusy(false);
    }
  };

  if (hasCoords) {
    const stamp = customer.geocoded_at
      ? String(customer.geocoded_at).slice(0, 10)
      : null;
    return (
      <div
        className="mt-1 text-xs flex items-center gap-1.5"
        style={{ color: colors.muted }}
        data-testid="customer-geocode-info"
      >
        <MapPin size={12} aria-hidden />
        <span data-testid="customer-geocode-coords">
          Location: {lat.toFixed(4)}, {lng.toFixed(4)}
        </span>
        {stamp ? (
          <span
            className="opacity-70"
            data-testid="customer-geocode-stamp"
          >
            (geocoded {stamp})
          </span>
        ) : null}
      </div>
    );
  }

  return (
    <div
      className="mt-1 text-xs flex items-center gap-2 flex-wrap"
      style={{ color: colors.muted }}
      data-testid="customer-geocode-info"
    >
      <MapPin size={12} aria-hidden />
      <span data-testid="customer-geocode-unavailable">
        Location: unavailable
      </span>
      {canReGeocode ? (
        <button
          type="button"
          onClick={handleReGeocode}
          disabled={busy}
          data-testid="customer-regeocode-btn"
          aria-label="Re-geocode customer address"
          className="inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium transition hover:brightness-95 disabled:opacity-60"
          style={{
            backgroundColor: colors.surfaceSecondary,
            color: colors.onSurface,
            border: `1px solid ${colors.border}`,
          }}
        >
          <RefreshCcw size={11} className={busy ? "animate-spin" : ""} />
          <span>{busy ? "Re-geocoding…" : "Re-geocode"}</span>
        </button>
      ) : null}
    </div>
  );
}
