/**
 * Phase K39a · Feb-2026 — Google Maps adapter.
 *
 * Thin pass-through over ``@vis.gl/react-google-maps`` so the rest
 * of the app can import from ``@/lib/maps`` without knowing which
 * provider is active.  Everything below is a re-export by design;
 * K39a's promise is "google-mode behavior is byte-identical".
 *
 * NOTE: we use ``import * as`` + resolve at access time so vitest
 * partial mocks (which only export the names the test cares about)
 * don't error out on the missing surface (Map/Pin/useMap/etc).
 */
import React from "react";
import * as _GM from "@vis.gl/react-google-maps";

/**
 * MapsProviderGate (google branch).
 *
 * When ``apiKey`` is falsy we intentionally render children
 * unwrapped so downstream ``<Map>`` calls no-op instead of throwing —
 * this preserves the pre-K39a AppLayout behaviour where no key ==
 * no ``<APIProvider>`` mount.
 */
export function MapsProviderGate({
  apiKey,
  libraries = ["marker", "geometry"],
  children,
}) {
  const key = apiKey || process.env.REACT_APP_GOOGLE_MAPS_API_KEY || "";
  const APIProvider = _GM.APIProvider;
  if (!key || !APIProvider) return React.createElement(React.Fragment, null, children);
  return React.createElement(
    APIProvider,
    { apiKey: key, libraries },
    children,
  );
}

// Late-binding wrappers so vitest partial mocks (that omit e.g.
// ``Map`` or ``useMap``) don't throw at module-load time.
function _passthrough(name) {
  const _F = React.forwardRef(function _MapsGooglePT(props, ref) {
    const Impl = _GM[name];
    if (!Impl) return null;
    return React.createElement(Impl, { ref, ...props });
  });
  _F.displayName = `GoogleMaps(${name})`;
  return _F;
}

// Component API surface — same names as ``@vis.gl/react-google-maps``.
export const Map = _passthrough("Map");
export const MapView = _passthrough("Map"); // spec alias
export const AdvancedMarker = _passthrough("AdvancedMarker");
// Google no longer has a distinct raster ``Marker`` component; alias
// to ``AdvancedMarker`` so consumers can import either name.
export const Marker = _passthrough("AdvancedMarker");
export const InfoWindow = _passthrough("InfoWindow");
export const Pin = _passthrough("Pin");

/**
 * HERE has no built-in "Polyline" React component in
 * ``@vis.gl/react-google-maps`` — most consumers roll their own via
 * ``useMapsLibrary('maps')``.  We surface a no-op placeholder so the
 * type shape matches the HERE adapter's ``Polyline`` export.
 * Nothing in the code base currently imports Polyline from
 * ``@vis.gl/react-google-maps`` (verified 2026-Feb-04), so this stub
 * is purely for API-surface parity.
 */
export function Polyline() {
  return null;
}

// Hooks — late-binding so vitest partial mocks don't blow up.
export function useMap(id) {
  const _h = _GM.useMap;
  return typeof _h === "function" ? _h(id) : null;
}
export function useMapsLibrary(name) {
  const _h = _GM.useMapsLibrary;
  return typeof _h === "function" ? _h(name) : null;
}
