/**
 * Phase K39b · Feb-2026 — HERE adapter (react-native-here-explore).
 *
 * K45 · Feb-2026 AMENDMENT — Lazy-load fix for mobile white screen.
 *
 *   Previously this file called ``require("react-native-here-explore")``
 *   at **module scope**. Metro/EAS bundles both adapters regardless
 *   of the runtime ``EXPO_PUBLIC_MAPS_PROVIDER`` flag, so the require
 *   fired the moment any code path (including a Schedule screen with
 *   assigned jobs) imported ``@/src/lib/maps``. When the ``.aar`` /
 *   ``.xcframework`` binaries were not present on disk, native init
 *   inside the module's constructor threw before the JS render loop
 *   started — bypassing every React error boundary — and the app
 *   died with a silent white screen.
 *
 *   K45 fix:
 *     1.  The ``require()`` now lives inside a lazy loader that runs
 *         **inside a component body** the first time a HERE adapter
 *         is actually rendered.
 *     2.  The result is memoized in module scope so the require only
 *         happens once per session.
 *     3.  Any failure (missing package, missing native binaries,
 *         constructor throw) is caught and short-circuits every
 *         export to the placeholder — no module-scope side effects.
 *     4.  ``@/src/lib/maps/index.ts`` no longer statically imports
 *         this file — it only lazy-``require()``s it when the
 *         resolver has decided ``provider === "here"``.  So on
 *         provider=google Metro can drop this file from the bundle
 *         if the tree-shaker is enabled.
 */
import React from "react";
import { View, StyleSheet } from "react-native";
import { MapUnavailablePlaceholder } from "@/src/utils/mapsKey";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type HereSDK = any;

// Module-scope memoization for the lazy require.
let _HERE: HereSDK | null = null;
let _hereError: string | null = null;
let _hereLoaded = false;

/**
 * K45 · Feb-2026 — Deferred loader for the HERE SDK.
 *
 * Called from inside a component render only. Every render past the
 * first no-ops (returns the memoized result). If the require throws
 * — either because the JS module is missing OR because native init
 * fails when binaries aren't linked — the error is captured and
 * every downstream export short-circuits to the placeholder branch.
 * Crucially, no code path in this module runs at import time.
 */
function _loadHere(): HereSDK | null {
  if (_hereLoaded) return _HERE;
  _hereLoaded = true;
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports, global-require
    _HERE = require("react-native-here-explore");
  } catch (err) {
    _HERE = null;
    _hereError = (err as Error)?.message || "not-installed";
    // eslint-disable-next-line no-console
    console.warn(
      "[K45/maps] HERE SDK failed to load — falling back to placeholder. " +
        "Details: " +
        _hereError,
    );
  }
  return _HERE;
}

function _placeholder(testID?: string) {
  return (
    <View style={styles.wrap} testID={testID || "maps-here-fallback"}>
      <MapUnavailablePlaceholder
        provider="HERE"
        message={
          _hereError
            ? "HERE SDK not installed. See mobile/heresdk/README.md."
            : "HERE credentials missing. Contact your administrator."
        }
      />
    </View>
  );
}

// ``MapView`` — proxies to HERE's ``MapView`` (or ``NavigationMap``
// depending on the SDK's exported name). We accept both to survive
// minor SDK renames.
export function MapView(props: any) {
  const sdk = _loadHere();
  if (!sdk) return _placeholder(props?.testID);
  const Impl = sdk.MapView || sdk.NavigationMap || sdk.default;
  if (!Impl) return _placeholder(props?.testID);
  return <Impl {...props} />;
}

export function Marker(props: any) {
  const sdk = _loadHere();
  if (!sdk) return null;
  const Impl = sdk.Marker;
  if (!Impl) return null;
  return <Impl {...props} />;
}

export function Polyline(props: any) {
  const sdk = _loadHere();
  if (!sdk) return null;
  const Impl = sdk.Polyline;
  if (!Impl) return null;
  return <Impl {...props} />;
}

export function Polygon(props: any) {
  const sdk = _loadHere();
  if (!sdk) return null;
  const Impl = sdk.Polygon;
  if (!Impl) return null;
  return <Impl {...props} />;
}

export function Circle(props: any) {
  const sdk = _loadHere();
  if (!sdk) return null;
  const Impl = sdk.Circle;
  if (!Impl) return null;
  return <Impl {...props} />;
}

export const PROVIDER_GOOGLE = undefined;

const styles = StyleSheet.create({
  wrap: { flex: 1 },
});
