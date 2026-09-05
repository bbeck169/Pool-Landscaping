/**
 * Phase K39b · Feb-2026 — HERE adapter (react-native-here-explore).
 *
 * Phase K45b · Feb-2026 AMENDMENT — Nuclear disable.
 *
 *   `react-native-here-explore` is NOT in `mobile/package.json`.
 *   It is not installed under `node_modules`. The `.aar` /
 *   `.xcframework` binaries were never dropped into
 *   `mobile/heresdk/`. `EXPO_PUBLIC_HERE_ACCESS_KEY_ID` is empty in
 *   every environment we ship to. The plugin registration was
 *   removed from `mobile/app.config.js` in K45b.
 *
 *   In other words: HERE is disabled at every layer of the stack.
 *
 *   The K45 lazy-require refactor is preserved (defensive), but
 *   `_loadHere()` now **hard-throws** an explanatory error so anyone
 *   who accidentally routes traffic to this adapter gets a loud,
 *   diagnosable failure rather than a silent placeholder. The
 *   provider gate at `index.ts` catches the throw and downgrades
 *   silently to the Google adapter — this file is defensive belt
 *   for that suspenders.
 *
 *   To re-enable HERE later, see `mobile/heresdk/README.md`.
 */
import React from "react";
import { View, StyleSheet } from "react-native";
import { MapUnavailablePlaceholder } from "@/src/utils/mapsKey";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type HereSDK = any;

const _DISABLED_MSG =
  "HERE Maps adapter is not installed in this build. " +
  "Add react-native-here-explore to package.json + drop the SDK " +
  "binaries into mobile/heresdk/ + re-register the Expo config " +
  "plugin in app.config.js to enable. See mobile/heresdk/README.md.";

// K45b · Hard-throw. Retained inside a function so no side effects
// fire at module import time — the provider gate in `index.ts` only
// invokes `_loadHere()` when it has committed to HERE mode, which
// itself only happens when the runtime binary-presence check passes
// (see `provider.ts` + `heresdkStatus.generated.ts`). Under normal
// operation this function is never called.
function _loadHere(): HereSDK {
  throw new Error(_DISABLED_MSG);
}

function _placeholder(testID?: string) {
  return (
    <View style={styles.wrap} testID={testID || "maps-here-fallback"}>
      <MapUnavailablePlaceholder
        provider="HERE"
        message="HERE adapter disabled. See mobile/heresdk/README.md."
      />
    </View>
  );
}

// K45b · Every export short-circuits to the placeholder without
// invoking `_loadHere()` (which would throw). The adapter is a
// no-op renderer end-to-end. This keeps `index.ts`'s conditional
// `require("./hereAdapter")` a safe operation even under an
// unexpected `provider=here` runtime flip.
export function MapView(props: any) {
  return _placeholder(props?.testID);
}
export function Marker(_props: any) { return null; }
export function Polyline(_props: any) { return null; }
export function Polygon(_props: any) { return null; }
export function Circle(_props: any) { return null; }
export const PROVIDER_GOOGLE = undefined;

// Exposed for jest so the K45b guard suite can assert the hard-throw
// contract without rendering.
export const __k45b_loadHere = _loadHere;

const styles = StyleSheet.create({
  wrap: { flex: 1 },
});
