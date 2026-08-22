/**
 * Offline cache — barrel re-export.
 *
 * Metro picks ``.native.ts`` on iOS / Android and ``.web.ts`` for Expo Web.
 * This file is the fallback / type-hint for non-platform-resolved imports
 * (e.g. Jest, TypeScript language-server).
 */
export {
  initCache,
  cacheWeekJobs,
  getCachedWeekJobs,
  getCachedJob,
  cacheCustomer,
  getCachedCustomer,
  cacheProperty,
  getCachedProperty,
  cacheMe,
  getCachedMe,
  wipeCache,
  __resetForTests,
} from "./cache.native";
