/**
 * TD-g2 · mobile parity of web β (1eff40b8a) — unlock-before-save for a
 * submitted service report (`service_reports.submitted_at` set).
 *
 * Role split (never a silent `{ ok: true }` drop):
 *   - "technician"        → PATCH fires; BE post-submit bypass
 *                           (routers/service_reports.py:604-610) accepts it.
 *   - UNLOCK_ADMIN_ROLES  → reason prompt → POST /jobs/{jid}/unlock →
 *                           re-fetch report → PATCH.
 *   - anything else       → read-only; the save aborts with a message.
 *
 * UNLOCK_ADMIN_ROLES = BE `unlock_submitted_job._ADMIN_ROLES`
 * (routers/jobs.py:4331) = web `JobUnlockButton.jsx:21`. Dispatcher is
 * NOT in it (BE answers 403). The BE writes the `job_edits` audit row —
 * nothing is written client-side. Unlock is online-only, never queued.
 */
import { api, ApiError } from "@/src/api";

export const UNLOCK_ADMIN_ROLES: ReadonlySet<string> = new Set([
  "admin", "super_admin", "manager", "owner",
]);
export const MIN_UNLOCK_REASON_LEN = 8;

export const UNLOCK_OFFLINE_MESSAGE =
  "Unlocking a submitted report requires a network connection. Reconnect and try again.";
export const SUBMITTED_READ_ONLY_MESSAGE = "This report has been submitted and is locked.";
export const UNLOCK_REFETCH_FAILED_MESSAGE =
  "The report was unlocked but couldn't be reloaded. Your edits are still on screen — tap Save draft again.";

/** Fields the checklist PATCHes — local values win after an unlock re-fetch. */
export const REPORT_PATCH_FIELDS = [
  "chemical_readings", "chemicals_added", "checklist_items",
  "notes", "internal_notes", "customer_notes",
] as const;

export type SubmittedSaveMode = "open" | "tech-bypass" | "needs-unlock" | "read-only";

export type FlushSaveResult = {
  ok: boolean;
  queued?: boolean;
  error?: string;
  /** Admin role on a submitted report — run the unlock prompt first. */
  needsUnlock?: boolean;
  /** Read-only role on a submitted report — nothing was saved. */
  blocked?: boolean;
  /** Operator dismissed the unlock prompt — nothing was saved. */
  cancelled?: boolean;
};

export function isUnlockAdminRole(role: string | null | undefined): boolean {
  return UNLOCK_ADMIN_ROLES.has(String(role || "").toLowerCase());
}

export function submittedSaveMode(role: string | null | undefined, report: any): SubmittedSaveMode {
  if (!report?.submitted_at) return "open";
  // Exact match — the BE bypass checks `role == "technician"`.
  if (String(role || "") === "technician") return "tech-bypass";
  if (isUnlockAdminRole(role)) return "needs-unlock";
  return "read-only";
}

export function isValidUnlockReason(reason: string | null | undefined): boolean {
  return String(reason || "").trim().length >= MIN_UNLOCK_REASON_LEN;
}

export function unlockErrorMessage(e: any): string {
  if (e instanceof ApiError) {
    if (e.status === 403) return "You don't have permission to unlock this report.";
    const d: any = e.detail;
    if (e.status === 400 && d && typeof d === "object" && d.message) return String(d.message);
    if (e.status >= 500) return "The server couldn't unlock this report. Try again in a moment.";
    return e.message || "Unlock failed.";
  }
  return "Couldn't reach the server to unlock this report. Check your connection and try again.";
}

/** Shipped CHEM-LOCK endpoint — routers/jobs.py:4304. */
export function unlockSubmittedJob(jobId: string, reason: string) {
  return api.post(`/jobs/${jobId}/unlock`, { reason: String(reason || "").trim() });
}

/** Server copy (now unlocked) + the operator's unsaved local edits on top. */
export function mergeUnlockedReport(fresh: any, local: any): any {
  const merged: any = { ...(fresh || {}) };
  if (local) {
    for (const k of REPORT_PATCH_FIELDS) {
      if (k in local) merged[k] = local[k];
    }
  }
  return merged;
}

export type SaveWithUnlockDeps = {
  flush: () => Promise<FlushSaveResult>;
  online: boolean;
  requestReason: () => Promise<string | null>;
  unlock: (reason: string) => Promise<unknown>;
  refetch: () => Promise<any>;
  applyUnlocked: (fresh: any) => void;
};

/**
 * One orchestration for Save draft / Save & close / Close-job pre-flush.
 * After a successful unlock the report's `submitted_at` is cleared, so
 * later saves in the same session go straight to PATCH (no second prompt)
 * until the report is resubmitted.
 */
export async function saveWithUnlock(deps: SaveWithUnlockDeps): Promise<FlushSaveResult> {
  const first = await deps.flush();
  if (!first.needsUnlock) return first;
  if (!deps.online) return { ok: false, error: UNLOCK_OFFLINE_MESSAGE };

  const reason = await deps.requestReason();
  if (reason == null) return { ok: false, cancelled: true };
  if (!isValidUnlockReason(reason)) {
    return { ok: false, error: `Reason must be at least ${MIN_UNLOCK_REASON_LEN} characters.` };
  }

  try {
    await deps.unlock(reason.trim());
  } catch (e: any) {
    // 409 `not_locked` = already unlocked elsewhere (e.g. on web) — the
    // re-fetch below confirms it and the save proceeds.
    if (!(e instanceof ApiError && e.status === 409)) {
      return { ok: false, error: unlockErrorMessage(e) };
    }
  }

  let fresh: any;
  try {
    fresh = await deps.refetch();
  } catch {
    return { ok: false, error: UNLOCK_REFETCH_FAILED_MESSAGE };
  }
  if (!fresh || fresh.submitted_at) return { ok: false, error: UNLOCK_REFETCH_FAILED_MESSAGE };

  deps.applyUnlocked(fresh);
  return deps.flush();
}
