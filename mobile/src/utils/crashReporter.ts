/**
 * K36 · Best-effort crash uploader.
 *
 * On boot, checks for a persisted crash slot. If one exists, tries to
 * POST it to the backend telemetry endpoint. Silently degrades to a
 * no-op if the endpoint doesn't exist yet — the "Send diagnostics"
 * button on `more.tsx` is the reliable user-triggered path in that
 * case.
 *
 * Intentionally minimal: no retries, no batching, no queuing. The
 * ring buffer + persisted crash slot are the source of truth.
 */
import { api } from "@/src/api";
import { consumePendingCrash, logNav, getDiagnostics } from "@/src/utils/diagnostics";

const ENDPOINT = "/telemetry/mobile-crash";

export async function uploadPendingCrash(): Promise<"uploaded" | "none" | "failed"> {
  try {
    const crash = await consumePendingCrash();
    if (!crash) return "none";
    logNav("boot.crash.uploading", { message: crash.message.slice(0, 80) });
    const snap = await getDiagnostics();
    try {
      await api.post(ENDPOINT, {
        crash,
        nav: snap.nav,
        api: snap.api,
        platform: snap.platform,
        os_version: snap.osVersion,
        captured_at: snap.capturedAt,
      });
      logNav("boot.crash.upload.ok");
      return "uploaded";
    } catch (e: any) {
      // Endpoint may not exist yet — do NOT surface as a hard error.
      // The crash record has already been consumed from AsyncStorage
      // above, but we re-log it into the ring buffer so the tech's
      // next "Send diagnostics" tap still carries the context.
      logNav("boot.crash.upload.failed", {
        err: String(e?.message || e).slice(0, 120),
        crash: crash.message.slice(0, 80),
      });
      return "failed";
    }
  } catch {
    return "failed";
  }
}
