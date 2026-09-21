/**
 * P9-C · One-shot purge migration for the SQLite offline jobs cache.
 *
 * On first launch after this change ships, iterates pre-existing cached
 * jobs and drops any whose `technician_id` doesn't match the current
 * user's `technician_id`.  Guarded by a version marker in AsyncStorage
 * so it runs at most once per install.
 */
import AsyncStorage from "@react-native-async-storage/async-storage";
import * as SQLite from "expo-sqlite";

const PURGE_GUARD_KEY = "p9c_purged_v1";

export async function runP9cPurgeMigration(
  role: string,
  technicianId: string | null | undefined,
  userId: string,
): Promise<void> {
  if (role !== "technician" && role !== "tech") return;

  const guard = await AsyncStorage.getItem(PURGE_GUARD_KEY).catch(() => null);
  if (guard === "true") return;

  try {
    const db = await SQLite.openDatabaseAsync("poolcrm-offline.db");

    // Ensure table exists (cold-start edge case).
    await db.execAsync(`
      CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY,
        tech_user_id TEXT,
        scheduled_date TEXT,
        payload TEXT NOT NULL,
        cached_at INTEGER NOT NULL
      );
    `);

    if (!technicianId) {
      console.warn("[P9-C purge] Tech has no technician_id — wiping all cached jobs (fail closed)");
      await db.runAsync(`DELETE FROM jobs WHERE tech_user_id = ?`, [userId]);
    } else {
      const rows = await db.getAllAsync<{ id: string; payload: string }>(
        `SELECT id, payload FROM jobs WHERE tech_user_id = ?`,
        [userId],
      );

      let purged = 0;
      for (const row of rows) {
        try {
          const job = JSON.parse(row.payload);
          if (job.technician_id && job.technician_id !== technicianId) {
            await db.runAsync(`DELETE FROM jobs WHERE id = ?`, [row.id]);
            purged++;
          }
        } catch {
          await db.runAsync(`DELETE FROM jobs WHERE id = ?`, [row.id]);
          purged++;
        }
      }
      if (purged > 0) {
        console.log(`[P9-C purge] Removed ${purged} peer job(s) from offline cache.`);
      }
    }
  } catch (e: any) {
    console.warn("[P9-C purge] Migration error:", e?.message || e);
  }

  // Set guard even on failure — don't retry indefinitely.
  await AsyncStorage.setItem(PURGE_GUARD_KEY, "true").catch(() => {});
}

/** Exported for testing. */
export const _PURGE_GUARD_KEY = PURGE_GUARD_KEY;
