/**
 * Phase K39b · Feb-2026 — Public mobile maps API.
 *
 * Every consumer imports **only** from ``@/src/lib/maps``. Adapters
 * (google / here) are private implementation details.
 *
 * K39b AMENDMENT · Feb-2026 — Same rule as the K39a web amendment:
 * the customer-portal shell (``mobile/app/portal/**``) must NEVER
 * import from this module. Any map on a customer-portal screen has
 * to be mounted inside a locally-scoped component with its own
 * error boundary (see ``mobile/heresdk/README.md``). A companion
 * jest test (``__tests__/portal-maps-guard.test.ts``) statically
 * scans the ``app/portal/**`` tree and fails the suite if any file
 * imports from ``@/src/lib/maps`` or a raw ``react-native-maps`` /
 * ``react-native-here-explore``.
 */
import { useMapsProvider, _computeProvider } from "./provider";
import * as _google from "./googleAdapter";
import * as _here from "./hereAdapter";

export { useMapsProvider, _computeProvider };

// Runtime-resolved surface. ``_CACHED_PROVIDER`` is captured once at
// import time (Expo env is build-time constant) so the type of the
// export is stable across a session.
const _CACHED_PROVIDER = _computeProvider();
const _active: typeof _google = _CACHED_PROVIDER === "here"
  ? (_here as unknown as typeof _google)
  : _google;

export const MapView = _active.MapView;
export const Marker = _active.Marker;
export const Polyline = _active.Polyline;
export const Polygon = _active.Polygon;
export const Circle = _active.Circle;
export const PROVIDER_GOOGLE = _active.PROVIDER_GOOGLE;

// Convenience re-exports for consumers that used to grab types
// directly from ``react-native-maps``.
export type { Region, MapViewProps } from "./googleAdapter";
