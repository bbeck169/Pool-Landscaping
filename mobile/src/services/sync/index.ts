/**
 * Phase O2/O3 · Sync infrastructure — public barrel export.
 */

// Database + schema
export { getSyncDb, getConfig, setConfig, getSchemaVersion } from "./db";

// Sync queue
export {
  enqueue,
  flush,
  triggerSyncNow,
  retrySingle,
  getPending,
  getFailed,
  getAll,
  clearDone,
  wireAutoFlush,
  subscribe as subscribeQueue,
  type SyncEntry,
  type EnqueueParams,
  type FlushResult,
} from "./queue";

// Status
export { getSyncStatus, useSyncStatus, type SyncStatus } from "./status";

// Network bus
export {
  startListening,
  isOnlineNow,
  isOnlineAsync,
  on as onNetEvent,
} from "./netBus";

// UUID
export { clientUuid } from "../ids/clientUuid";

// Phase O3: Offline service log
export {
  cacheServiceReport,
  getCachedServiceReport,
  markDirty,
  clearDirty,
  submitOffline,
} from "./offlineServiceLog";

// Phase O3: Photo pipeline
export {
  capturePhoto,
  downscaleAndStage,
  insertPendingPhoto,
  flushPhotos,
  retryStalled,
  retryAllStalled,
  getPendingPhotos,
  getStalledPhotos,
  getPhotosForEntity,
  purgePhotosForEntity,
  cleanupUploaded,
  wirePhotoAutoUpload,
  subscribePhotos,
  type PendingPhoto,
} from "./photoWorker";

// Phase O3: Job arrive
export { enqueueJobArrive } from "./jobArrive";

// Phase O3: Conflict detection
export {
  recordConflict,
  onConflict,
  getUnresolvedConflicts,
  resolveConflict,
  getConflictCount,
  type SyncConflict,
} from "./conflicts";
