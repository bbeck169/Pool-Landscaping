/**
 * Phase K39b · Feb-2026 — Google adapter (react-native-maps).
 *
 * Thin pass-through re-export. The abstraction lives at
 * ``@/src/lib/maps`` — every consumer imports from there and this
 * file remains a private implementation detail so the K39c cutover
 * is a one-file swap.
 */
import RNMapView, {
  Marker as RNMarker,
  Polyline as RNPolyline,
  Polygon as RNPolygon,
  Circle as RNCircle,
  PROVIDER_GOOGLE,
  type Region,
  type MapViewProps,
} from "react-native-maps";

export const MapView = RNMapView;
export const Marker = RNMarker;
export const Polyline = RNPolyline;
export const Polygon = RNPolygon;
export const Circle = RNCircle;
export { PROVIDER_GOOGLE };
export type { Region, MapViewProps };
