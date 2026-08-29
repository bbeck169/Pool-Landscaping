/**
 * Phase O2 · Sync infrastructure — public barrel export.
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
