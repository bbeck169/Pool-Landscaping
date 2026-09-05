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
 *
 * K45 AMENDMENT · Feb-2026 — Provider gate hardening.
 *
 *   Previously this file did ``import * as _here from "./hereAdapter"``
 *   at the module top level. Metro/EAS bundles that even when the
 *   resolver returns ``google``, and the eager import fired the HERE
 *   ``require("react-native-here-explore")`` which crashed the app
 *   when native binaries were missing.
 *
 *   Fix:
 *     - The Google adapter stays statically imported (always safe —
 *       ``react-native-maps`` binaries are always present in this
 *       app because Expo ships them by default).
 *     - The HERE adapter is now only ``require()``d **inside this
 *       module's boot block**, and **only when** the resolver
 *       returned ``here`` AND the generated ``HERE_BINARIES_PRESENT``
 *       constant is true.
 *     - Any require failure downgrades silently to the Google
 *       adapter — never throws.
 */
import { useMapsProvider, _computeProvider } from "./provider";
import * as _google from "./googleAdapter";

export { useMapsProvider, _computeProvider };

// ``_CACHED_PROVIDER`` captures the resolver's decision once at
// import time (Expo env vars are baked at build time). The resolver
// already downgrades ``here`` → ``google`` when binaries are missing
// or the HERE access key isn't set — see ``provider.ts``.
const _CACHED_PROVIDER = _computeProvider();

// eslint-disable-next-line @typescript-eslint/no-explicit-any
let _resolved: any = _google;

if (_CACHED_PROVIDER === "here") {
  try {
    // K45 · lazy-load hereAdapter only when we've committed to HERE
    // mode. This is the ONLY place ``./hereAdapter`` is referenced
    // in the module graph; if the tree-shaker keeps it in the bundle,
    // its internal ``require("react-native-here-explore")`` is
    // itself gated by a lazy-load — see ``hereAdapter.tsx`` for the
    // K45 amendment there.
    // eslint-disable-next-line @typescript-eslint/no-require-imports, global-require
    const _here = require("./hereAdapter");
    _resolved = _here;
  } catch (err) {
    // Never throw — silent downgrade to Google, log once.
    // eslint-disable-next-line no-console
    console.warn(
      "[K45/maps] provider=here requested but hereAdapter failed to load: " +
        String((err as Error)?.message || err) +
        " — using google adapter.",
    );
    _resolved = _google;
  }
}

export const MapView = _resolved.MapView;
export const Marker = _resolved.Marker;
export const Polyline = _resolved.Polyline;
export const Polygon = _resolved.Polygon;
export const Circle = _resolved.Circle;
export const PROVIDER_GOOGLE = _resolved.PROVIDER_GOOGLE;

// Convenience re-exports for consumers that used to grab types
// directly from ``react-native-maps``.
export type { Region, MapViewProps } from "./googleAdapter";
