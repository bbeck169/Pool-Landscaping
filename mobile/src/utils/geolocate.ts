/**
 * geolocate — shared best-effort foreground-permission device position.
 *
 * Mirrors the inline helper in ``OnMyWayButton.tsx`` so the Optimize
 * Route flow doesn't need to duplicate the same 4-branch permission
 * / timeout dance. Signature is intentionally a superset — callers
 * can ignore ``timeoutMs`` and get the same 4s default.
 *
 * Returns:
 *   • { lat, lng }               on success
 *   • { lat: null, reason: ... } on permission-denied / timeout
 *
 * Reason codes let callers surface a specific fallback banner:
 *   "denied"       — user rejected the OS permission prompt
 *   "undetermined" — permission still ``undetermined`` after prompt
 *   "timeout"      — got permission but no coord within the window
 *   "error"        — unexpected exception from expo-location
 */
import * as Location from "expo-location";

export type GeolocateResult =
  | { lat: number; lng: number; reason: null }
  | { lat: null; lng: null; reason: "denied" | "undetermined" | "timeout" | "error" };

const DEFAULT_TIMEOUT_MS = 4000;

export async function geolocate(timeoutMs = DEFAULT_TIMEOUT_MS): Promise<GeolocateResult> {
  try {
    const { status } = await Location.getForegroundPermissionsAsync();
    if (status === "undetermined") {
      const { status: after } = await Location.requestForegroundPermissionsAsync();
      if (after !== "granted") return { lat: null, lng: null, reason: "denied" };
    } else if (status !== "granted") {
      return { lat: null, lng: null, reason: "denied" };
    }

    const loc = await Promise.race<Location.LocationObject | null>([
      Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced }),
      new Promise<null>((r) => setTimeout(() => r(null), timeoutMs)),
    ]);
    if (!loc) return { lat: null, lng: null, reason: "timeout" };
    return { lat: loc.coords.latitude, lng: loc.coords.longitude, reason: null };
  } catch {
    return { lat: null, lng: null, reason: "error" };
  }
}
