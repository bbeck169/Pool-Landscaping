/**
 * Phase Lottie-web · Feb-2026 — Web fallback for the Mapbox tech-pin
 * map component.
 *
 * The native ``LiveTechPinsMap.tsx`` imports ``@rnmapbox/maps`` — a
 * dev-client-only native module that fails Metro's web-bundle
 * resolution. Phase 38b's ``LiveTechPinsWrapper.tsx`` already renders
 * an Expo Go / dev-client-required banner when the native require
 * fails at runtime; on web we simply return ``null`` so the wrapper's
 * banner UI + polling logic keep working without dragging Mapbox into
 * the web bundle.
 *
 * Any re-exported types from the native module are exposed as
 * ``LivePosition`` so consumers that ``import type {LivePosition}``
 * from this file compile cleanly on web. TypeScript's type-only
 * imports are erased before Metro sees them, so the web bundle
 * doesn't touch this shape.
 */
import React from "react";

export type LivePosition = {
  user_id: string;
  user_name?: string;
  latitude: number;
  longitude: number;
  updated_at?: string;
};

export default function LiveTechPinsMap(_props: any): React.ReactElement | null {
  return null;
}
