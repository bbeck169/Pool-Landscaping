/**
 * Daily Route Map — barrel re-export.
 *
 * Metro picks ``.native.tsx`` on iOS / Android and ``.web.tsx`` for Expo Web.
 * This file is the fallback / type-hint for non-platform-resolved imports
 * (e.g. Jest, TypeScript language-server).
 */
export { default } from "./DailyRouteMap.native";
export { resolveJobCoords, statusKind } from "./DailyRouteMap.native";
export type { RouteMapJob, DailyRouteMapProps } from "./DailyRouteMap.native";
