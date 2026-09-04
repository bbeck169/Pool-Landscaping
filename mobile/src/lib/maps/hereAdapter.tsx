/**
 * Phase K39b · Feb-2026 — HERE adapter (react-native-here-explore).
 *
 * Wraps ``react-native-here-explore`` behind the same public API as
 * the Google adapter (``MapView``, ``Marker``, ``Polyline``,
 * ``Polygon``) so consumers can swap providers via a single env
 * flag. Never throws at render time — if the HERE SDK (or its
 * binary drop) isn't present, each component renders the
 * ``MapUnavailablePlaceholder`` from ``src/utils/mapsKey`` so we
 * keep parity with the web adapter's boundary contract (K39a §4).
 *
 * NOTE: ``react-native-here-explore`` is loaded via ``require`` in
 * a ``try/catch`` — Metro will still try to resolve at bundle time,
 * but if the package is missing the ``catch`` short-circuits every
 * component to the placeholder. Docs for wiring the ``.aar`` /
 * ``.xcframework`` drop live in ``mobile/heresdk/README.md``.
 */
import React from "react";
import { View, StyleSheet } from "react-native";
import { MapUnavailablePlaceholder } from "@/src/utils/mapsKey";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
let _HERE: any = null;
let _hereError: string | null = null;
try {
  // Guard so a missing package doesn't crash bundling in
  // preview/dev — the require call is wrapped and the failure is
  // captured for the placeholder branch.
  // eslint-disable-next-line @typescript-eslint/no-require-imports, global-require
  _HERE = require("react-native-here-explore");
} catch (err) {
  _hereError = (err as Error)?.message || "not-installed";
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
  if (!_HERE) return _placeholder(props?.testID);
  const Impl = _HERE.MapView || _HERE.NavigationMap || _HERE.default;
  if (!Impl) return _placeholder(props?.testID);
  return <Impl {...props} />;
}

export function Marker(props: any) {
  if (!_HERE) return null;
  const Impl = _HERE.Marker;
  if (!Impl) return null;
  return <Impl {...props} />;
}

export function Polyline(props: any) {
  if (!_HERE) return null;
  const Impl = _HERE.Polyline;
  if (!Impl) return null;
  return <Impl {...props} />;
}

export function Polygon(props: any) {
  if (!_HERE) return null;
  const Impl = _HERE.Polygon;
  if (!Impl) return null;
  return <Impl {...props} />;
}

export function Circle(props: any) {
  if (!_HERE) return null;
  const Impl = _HERE.Circle;
  if (!Impl) return null;
  return <Impl {...props} />;
}

export const PROVIDER_GOOGLE = undefined;

const styles = StyleSheet.create({
  wrap: { flex: 1 },
});
