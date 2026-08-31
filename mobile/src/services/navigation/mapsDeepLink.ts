/**
 * Maps deep-link helper — resolves the best maps URL per platform.
 *
 * iOS:     Google Maps app → Apple Maps fallback
 * Android: Google Maps native intent → https universal fallback
 * Web:     Always https://www.google.com/maps/dir/...
 */
import { Platform, Linking } from "react-native";

export type Destination = {
  kind: "coords" | "address";
  value: string;
};

/**
 * Resolve destination from a job-like object.
 *   1. lat/lng (finite, non-(0,0))
 *   2. Fall back to trimmed address string
 *   3. null when neither available
 */
export function resolveDestination(job: any): Destination | null {
  if (!job || typeof job !== "object") return null;
  const lat = Number(job.latitude);
  const lng = Number(job.longitude);
  if (
    Number.isFinite(lat) &&
    Number.isFinite(lng) &&
    !(lat === 0 && lng === 0)
  ) {
    return { kind: "coords", value: `${lat},${lng}` };
  }
  const addr = (job.address || "").trim();
  if (addr) return { kind: "address", value: addr };
  return null;
}

/**
 * Build a Google Maps web URL (universal fallback).
 */
export function buildGoogleMapsUrl(dest: Destination): string {
  const params = new URLSearchParams();
  params.set("api", "1");
  params.set("destination", dest.value);
  return `https://www.google.com/maps/dir/?${params.toString()}`;
}

/**
 * Open the best maps app for the current platform.
 */
export async function openMaps(dest: Destination): Promise<void> {
  const encoded = encodeURIComponent(dest.value);

  if (Platform.OS === "ios") {
    // Try Google Maps first
    const gmapsUrl = `comgooglemaps://?daddr=${encoded}&directionsmode=driving`;
    const canOpen = await Linking.canOpenURL(gmapsUrl).catch(() => false);
    if (canOpen) {
      await Linking.openURL(gmapsUrl);
      return;
    }
    // Fall back to Apple Maps
    const appleMapsUrl = `maps://?daddr=${encoded}`;
    await Linking.openURL(appleMapsUrl);
    return;
  }

  if (Platform.OS === "android") {
    // Try Google Maps native intent
    const intentUrl = `google.navigation:q=${encoded}`;
    try {
      const canOpen = await Linking.canOpenURL(intentUrl);
      if (canOpen) {
        await Linking.openURL(intentUrl);
        return;
      }
    } catch {
      // fall through
    }
  }

  // Web / fallback
  const universalUrl = buildGoogleMapsUrl(dest);
  await Linking.openURL(universalUrl);
}
