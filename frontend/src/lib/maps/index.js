/**
 * Phase K39a · Feb-2026 — Public maps API.
 *
 * Every consumer imports **only** from ``@/lib/maps``. Never from
 * the raw adapter or from ``@vis.gl/react-google-maps`` directly.
 * That keeps the K39c cutover surgical.
 *
 * Runtime dispatch: each named export below picks its
 * implementation from :mod:`googleAdapter` or :mod:`hereAdapter`
 * based on :func:`useMapsProvider` at render time.
 */
import React from "react";
import * as _google from "./googleAdapter";
import * as _here from "./hereAdapter";
import { useMapsProvider, _computeProvider } from "./provider";

export { useMapsProvider, _computeProvider };
export { default as MapsProviderGate } from "./MapsProviderGate";

function _resolveAdapter(provider) {
  return provider === "here" ? _here : _google;
}

const _dispatchComponent = (name) => {
  const _wrapped = React.forwardRef(function MapsDispatch(props, ref) {
    const provider = useMapsProvider();
    const Adapter = _resolveAdapter(provider);
    const Impl = Adapter[name];
    if (!Impl) return null;
    return React.createElement(Impl, { ref, ...props });
  });
  _wrapped.displayName = `MapsDispatch(${name})`;
  return _wrapped;
};

export const Map = _dispatchComponent("Map");
export const MapView = _dispatchComponent("MapView");
export const AdvancedMarker = _dispatchComponent("AdvancedMarker");
export const Marker = _dispatchComponent("Marker");
export const InfoWindow = _dispatchComponent("InfoWindow");
export const Polyline = _dispatchComponent("Polyline");
export const Pin = _dispatchComponent("Pin");

/**
 * ``useMap`` — provider-aware hook.  We can't conditionally invoke
 * hooks so we always call both; Google's ``useMap`` gracefully
 * returns ``null`` outside an ``<APIProvider>`` and HERE's returns
 * ``null`` outside a ``<Map>``.  The active-provider result wins.
 */
export function useMap(id) {
  const provider = useMapsProvider();
  const gMap = _google.useMap(id);
  const hMap = _here.useMap();
  return provider === "here" ? hMap : gMap;
}

/**
 * ``useMapsLibrary`` — Google-only.  Returns ``null`` under HERE so
 * ``if (lib) { … }`` branches skip cleanly (K39a §6: no changes to
 * geocoding/autocomplete/routing calls).
 */
export function useMapsLibrary(name) {
  const provider = useMapsProvider();
  const gLib = _google.useMapsLibrary(name);
  return provider === "here" ? null : gLib;
}
