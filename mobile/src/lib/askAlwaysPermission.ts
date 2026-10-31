/**
 * β-core 3 · single owner of the "Always" (background) location ask.
 *
 * Flow (iOS two-step / Android 10+ order respected):
 *   skip on web · non-fleet role · already granted · already asked this app
 *   session for this user
 *   → foreground permission (request if needed; denied → stop)
 *   → explainer (showConfirm) BEFORE any OS background dialog
 *   → Continue → requestBackgroundPermissionsAsync.
 *
 * Called after the first successful clock-in (ClockInCard, landscape clock,
 * time-clock). Never throws.
 */
import { Platform } from "react-native";
import * as Location from "expo-location";

import { isFleetTechRole } from "@/src/lib/fleetRoles";
import { showConfirm } from "@/src/components/ConfirmModal";

export const ALWAYS_EXPLAINER_TITLE = "Allow background location";
export const ALWAYS_EXPLAINER_MESSAGE =
  "Background location keeps your fleet pings running when the app isn't open. We only track during your shift.";

export type AlwaysResult = "granted" | "denied" | "dismissed" | "skipped";

const _askedThisSession = new Set<string>();
export function _resetAlwaysAskSession(): void { _askedThisSession.clear(); }

function _explain(): Promise<boolean> {
  return new Promise((resolve) => {
    showConfirm({
      title: ALWAYS_EXPLAINER_TITLE,
      message: ALWAYS_EXPLAINER_MESSAGE,
      confirmLabel: "Continue",
      cancelLabel: "Not now",
      onConfirm: () => resolve(true),
      onCancel: () => resolve(false),
    });
  });
}

export async function askAlwaysPermission(user: { id?: string; role?: string | null } | null | undefined): Promise<AlwaysResult> {
  if (Platform.OS === "web" || !user?.id || !isFleetTechRole(user.role)) return "skipped";
  try {
    const bg = await Location.getBackgroundPermissionsAsync();
    if (bg.status === "granted") return "granted";
    if (_askedThisSession.has(user.id)) return "skipped";
    _askedThisSession.add(user.id);

    let fg = await Location.getForegroundPermissionsAsync();
    if (fg.status !== "granted") fg = await Location.requestForegroundPermissionsAsync();
    if (fg.status !== "granted") return "denied";

    if (!(await _explain())) return "dismissed";
    const res = await Location.requestBackgroundPermissionsAsync();
    return res.status === "granted" ? "granted" : "denied";
  } catch {
    return "denied";
  }
}
