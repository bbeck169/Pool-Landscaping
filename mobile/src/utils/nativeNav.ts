/**
 * Phase K46 · Feb-2026 — Native navigation deep-link helper.
 *
 * K46 replaces the in-app @rnmapbox/maps route rendering with a
 * `react-native-maps` view (Google provider) for pins-only, and
 * defers turn-by-turn navigation to the platform's native maps app
 * via a deep link. No Google Directions API integration; no
 * in-app turn-by-turn.
 *
 * Public API — `openNativeNavTo(lat, lng, label?)`:
 *
 *   1. iOS   → `maps://?daddr=<lat>,<lng>` (Apple Maps).
 *   2. Android → `google.navigation:q=<lat>,<lng>` (Google Maps intent).
 *   3. Universal fallback (either platform, if the native scheme
 *      fails to open — e.g. Google Maps not installed on Android,
 *      or the OS returns `canOpenURL=false` on iOS 14+ without a
 *      matching entry in `LSApplicationQueriesSchemes`):
 *      `https://www.google.com/maps/dir/?api=1&destination=<lat>,<lng>`
 *      opened in the system browser.
 *
 * Every consumer routes through this helper — a jest guard in
 * `mobile/__tests__/k46-nativeNav.test.ts` asserts the URL scheme
 * per platform and the fallback behavior.
 */
import { Linking, Platform } from "react-native";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const _isFinite = (n: any): boolean =>
  typeof n === "number" && Number.isFinite(n);

function _encLabel(label?: string): string {
  if (!label || typeof label !== "string") return "";
  return encodeURIComponent(label.trim().slice(0, 120));
}

/**
 * Build the platform-native scheme URL. Exported for the jest
 * regression suite — consumers should call `openNativeNavTo()`.
 */
export function _buildNativeNavUrl(
  lat: number,
  lng: number,
  label?: string,
): string {
  const lb = _encLabel(label);
  if (Platform.OS === "ios") {
    // Apple Maps — the `q=` param populates the pin label so users
    // get context on the destination before hitting "Go".
    const q = lb ? `&q=${lb}` : "";
    return `maps://?daddr=${lat},${lng}${q}`;
  }
  // Android: `google.navigation` opens Google Maps directly into
  // turn-by-turn. If the user has picked another default maps app
  // (e.g. Waze) the OS chooser will still surface it.
  return `google.navigation:q=${lat},${lng}`;
}

/**
 * Build the universal HTTPS fallback URL. Google Maps' web
 * "directions" surface always resolves, opens the installed native
 * app when possible, and works on every OS/browser combo — the
 * safest fallback we have.
 */
export function _buildUniversalNavUrl(
  lat: number,
  lng: number,
  _label?: string,
): string {
  return (
    "https://www.google.com/maps/dir/?api=1&destination=" +
    encodeURIComponent(`${lat},${lng}`)
  );
}

/**
 * Open the platform-native navigation deep-link to `(lat, lng)`.
 * Resolves once the URL has been dispatched. Never rejects — the
 * public contract is "best-effort, silent fallback".
 *
 * @returns `true` when a native scheme was opened, `false` when the
 *          universal HTTPS fallback was used, `false` when the
 *          inputs were invalid (nothing opened).
 */
export async function openNativeNavTo(
  lat: number,
  lng: number,
  label?: string,
): Promise<boolean> {
  if (!_isFinite(lat) || !_isFinite(lng)) {
    // eslint-disable-next-line no-console
    console.warn("[K46/nativeNav] invalid coordinates:", lat, lng);
    return false;
  }
  const nativeUrl = _buildNativeNavUrl(lat, lng, label);
  const fallbackUrl = _buildUniversalNavUrl(lat, lng, label);

  // Try the platform-native scheme first — one shot, catch every
  // error variant (canOpenURL false, openURL throw, unknown-scheme
  // rejection) and fall back silently to the universal HTTPS URL.
  try {
    // `canOpenURL` is best-effort — on Android it's reliable, on
    // iOS 14+ it requires the scheme to be listed in
    // `LSApplicationQueriesSchemes` in Info.plist. When it returns
    // false we skip straight to the fallback rather than fighting
    // it.
    let canOpen = true;
    try {
      canOpen = await Linking.canOpenURL(nativeUrl);
    } catch {
      canOpen = false;
    }
    if (canOpen) {
      await Linking.openURL(nativeUrl);
      return true;
    }
  } catch (err) {
    // eslint-disable-next-line no-console
    console.warn(
      "[K46/nativeNav] native scheme failed, falling back to https:",
      err && (err as Error).message,
    );
  }
  try {
    await Linking.openURL(fallbackUrl);
    return false;
  } catch (err) {
    // eslint-disable-next-line no-console
    console.warn(
      "[K46/nativeNav] fallback URL failed too — giving up:",
      err && (err as Error).message,
    );
    return false;
  }
}
