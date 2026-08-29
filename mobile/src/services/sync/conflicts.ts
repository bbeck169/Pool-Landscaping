/**
 * Phase O3 · Conflict detection (starter).
 *
 * Captures 409 and "server changed underneath" responses from the sync
 * queue dispatch. Persists the conflict in SQLite for later resolution
 * (O6 will render the diff banner + accept/discard flow).
 *
 * Emits `sync:conflict` events on the netBus so the UI can show a badge
 * count or log it. No user-facing resolution UI in O3.
 */
import { getSyncDb } from "./db";
import { clientUuid } from "../ids/clientUuid";

// ─── types ─────────────────────────────────────────────────────────
export type SyncConflict = {
  id: string;
  queue_entry_id: string;
  op_type: string;
  entity_id: string;
  client_payload: string;   // JSON of what the client sent
  server_state: string;     // JSON of what the server returned
  status_code: number;
  resolved: number;         // 0 = unresolved, 1 = resolved
  created_at: string;
};

// ─── event bus ─────────────────────────────────────────────────────
type ConflictHandler = (conflict: SyncConflict) => void;
const _handlers = new Set<ConflictHandler>();

export function onConflict(handler: ConflictHandler): () => void {
  _handlers.add(handler);
  return () => { _handlers.delete(handler); };
}

function _emit(conflict: SyncConflict) {
  _handlers.forEach((h) => { try { h(conflict); } catch { /* subscriber error */ } });
}

// ─── schema (run in db.ts migration v2 if needed, or create on
//     first use) ────────────────────────────────────────────────────
async function ensureTable(): Promise<void> {
  const db = await getSyncDb();
  await db.execAsync(`
    CREATE TABLE IF NOT EXISTS sync_conflicts (
      id                TEXT PRIMARY KEY,
      queue_entry_id    TEXT NOT NULL,
      op_type           TEXT NOT NULL,
      entity_id         TEXT NOT NULL,
      client_payload    TEXT NOT NULL DEFAULT '{}',
      server_state      TEXT NOT NULL DEFAULT '{}',
      status_code       INTEGER NOT NULL DEFAULT 409,
      resolved          INTEGER NOT NULL DEFAULT 0,
      created_at        TEXT NOT NULL
    );
  `);
}

// ─── record a conflict ─────────────────────────────────────────────
/**
 * Called from the sync queue's dispatch error handler when the server
 * returns 409 or a body indicating a conflict.
 */
export async function recordConflict(params: {
  queueEntryId: string;
  opType: string;
  entityId: string;
  clientPayload: Record<string, any>;
  serverState: Record<string, any>;
  statusCode: number;
}): Promise<SyncConflict> {
  await ensureTable();
  const db = await getSyncDb();
  const id = clientUuid();
  const now = new Date().toISOString();

  const conflict: SyncConflict = {
    id,
    queue_entry_id: params.queueEntryId,
    op_type: params.opType,
    entity_id: params.entityId,
    client_payload: JSON.stringify(params.clientPayload),
    server_state: JSON.stringify(params.serverState),
    status_code: params.statusCode,
    resolved: 0,
    created_at: now,
  };

  await db.runAsync(
    `INSERT INTO sync_conflicts
       (id, queue_entry_id, op_type, entity_id, client_payload,
        server_state, status_code, resolved, created_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)`,
    [
      conflict.id,
      conflict.queue_entry_id,
      conflict.op_type,
      conflict.entity_id,
      conflict.client_payload,
      conflict.server_state,
      conflict.status_code,
      conflict.created_at,
    ],
  );

  console.log(`[sync:conflict] Recorded conflict ${id} for ${params.opType}/${params.entityId} (HTTP ${params.statusCode})`);
  _emit(conflict);

  return conflict;
}

// ─── query helpers ─────────────────────────────────────────────────
export async function getUnresolvedConflicts(): Promise<SyncConflict[]> {
  await ensureTable();
  const db = await getSyncDb();
  return db.getAllAsync<SyncConflict>(
    `SELECT * FROM sync_conflicts WHERE resolved = 0 ORDER BY created_at DESC`,
  );
}

export async function resolveConflict(conflictId: string): Promise<void> {
  await ensureTable();
  const db = await getSyncDb();
  await db.runAsync(
    `UPDATE sync_conflicts SET resolved = 1 WHERE id = ?`,
    [conflictId],
  );
}

export async function getConflictCount(): Promise<number> {
  await ensureTable();
  const db = await getSyncDb();
  const row = await db.getFirstAsync<{ cnt: number }>(
    `SELECT COUNT(*) as cnt FROM sync_conflicts WHERE resolved = 0`,
  );
  return row?.cnt ?? 0;
}

// ─── test helpers ──────────────────────────────────────────────────
export async function __clearForTests(): Promise<void> {
  await ensureTable();
  const db = await getSyncDb();
  await db.runAsync("DELETE FROM sync_conflicts");
}
