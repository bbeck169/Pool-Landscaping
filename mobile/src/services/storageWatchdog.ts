/**
 * Phase O6 · StorageWatchdog — monitors pending photos + queue size
 * and warns the user when storage pressure is high.
 *
 * Thresholds:
 *   - > 50 MB of pending photo files → yellow warning
 *   - > 100 queue entries → yellow warning
 *   - > 200 MB of pending photo files → red critical
 *
 * Runs a check every 60s while the app is in the foreground.
 * Exposes a hook for reactive UI and a manual check function.
 */
import { useState, useEffect, useCallback, useRef } from "react";
import { AppState, AppStateStatus } from "react-native";
import * as FileSystem from "expo-file-system/legacy";
import { getPending, getFailed } from "@/src/services/sync/queue";
import { getPendingPhotos, getStalledPhotos } from "@/src/services/sync/photoWorker";

export type StoragePressure = {
  level: "ok" | "warning" | "critical";
  queueCount: number;
  photoCount: number;
  photoSizeBytes: number;
  message: string | null;
};

const EMPTY: StoragePressure = {
  level: "ok",
  queueCount: 0,
  photoCount: 0,
  photoSizeBytes: 0,
  message: null,
};

// Thresholds.
const QUEUE_WARN = 100;
const PHOTO_WARN_BYTES = 50 * 1024 * 1024;   // 50 MB
const PHOTO_CRIT_BYTES = 200 * 1024 * 1024;  // 200 MB

function humanSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** One-shot check. */
export async function checkStoragePressure(): Promise<StoragePressure> {
  try {
    const [pending, failed, photos, stalledPhotos] = await Promise.all([
      getPending(),
      getFailed(),
      getPendingPhotos(),
      getStalledPhotos(),
    ]);

    const queueCount = pending.length + failed.length;
    const allPhotos = [...photos, ...stalledPhotos];

    // Sum file sizes.
    let totalBytes = 0;
    for (const p of allPhotos) {
      try {
        const uri = p.downscaled_uri || p.local_uri;
        if (uri) {
          const info = await FileSystem.getInfoAsync(uri);
          if (info.exists && "size" in info) totalBytes += info.size ?? 0;
        }
      } catch {
        // File may have been cleaned up.
      }
    }

    let level: StoragePressure["level"] = "ok";
    let message: string | null = null;

    if (totalBytes > PHOTO_CRIT_BYTES) {
      level = "critical";
      message = `${humanSize(totalBytes)} of photos pending upload. Connect to sync.`;
    } else if (totalBytes > PHOTO_WARN_BYTES) {
      level = "warning";
      message = `${humanSize(totalBytes)} of photos pending upload.`;
    } else if (queueCount > QUEUE_WARN) {
      level = "warning";
      message = `${queueCount} changes queued. Connect to sync.`;
    }

    const result: StoragePressure = {
      level,
      queueCount,
      photoCount: allPhotos.length,
      photoSizeBytes: totalBytes,
      message,
    };

    if (level !== "ok") {
      console.log(`[StorageWatchdog] ${level}: ${message}`);
    }

    return result;
  } catch (e) {
    console.warn("[StorageWatchdog] Check failed:", e);
    return EMPTY;
  }
}

/** React hook — checks on mount and every 60s while foreground. */
export function useStoragePressure(): StoragePressure {
  const [pressure, setPressure] = useState<StoragePressure>(EMPTY);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const check = useCallback(async () => {
    const p = await checkStoragePressure();
    setPressure(p);
  }, []);

  useEffect(() => {
    check();

    const handleAppState = (state: AppStateStatus) => {
      if (state === "active") {
        check();
        intervalRef.current = setInterval(check, 60_000);
      } else {
        if (intervalRef.current) clearInterval(intervalRef.current);
      }
    };

    const sub = AppState.addEventListener("change", handleAppState);

    // Start interval if already active.
    intervalRef.current = setInterval(check, 60_000);

    return () => {
      sub.remove();
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [check]);

  return pressure;
}
