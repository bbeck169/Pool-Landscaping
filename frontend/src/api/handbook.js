/**
 * Phase 4 · Batch B / Deliverable 6 — Handbook + Onboarding API client.
 * Reuses the shared `api` wrapper for auth + tenant handling.
 */
import { api } from "@/api";

// ─── Handbook ─────────────────────────────────────────────────
export function listHandbookSections() { return api.get("/handbook/sections"); }
export function getHandbookSection(code) { return api.get(`/handbook/sections/${encodeURIComponent(code)}`); }
export function createHandbookSection(body) { return api.post("/handbook/sections", body); }
export function updateHandbookSection(code, patch) { return api.patch(`/handbook/sections/${encodeURIComponent(code)}`, patch); }
export function deleteHandbookSection(code) { return api.del(`/handbook/sections/${encodeURIComponent(code)}`); }

// ─── Onboarding ──────────────────────────────────────────────
export function listOnboardingTasks() { return api.get("/onboarding/tasks"); }
export function createOnboardingTask(body) { return api.post("/onboarding/tasks", body); }
export function updateOnboardingTask(code, patch) { return api.patch(`/onboarding/tasks/${encodeURIComponent(code)}`, patch); }
export function getUserProgress(userId = "me") { return api.get(`/onboarding/user-progress?user_id=${encodeURIComponent(userId)}`); }
export function markTaskComplete(task_code, evidence, user_id) {
  const body = { task_code };
  if (evidence) body.evidence = evidence;
  if (user_id) body.user_id = user_id;
  return api.post("/onboarding/user-progress/mark-complete", body);
}
export function getOnboardingDashboard(role) {
  const qs = role ? `?role=${encodeURIComponent(role)}` : "";
  return api.get(`/onboarding/dashboard${qs}`);
}

export const TASK_KIND_LABEL = {
  read_handbook_section: "Read Section",
  training_module: "Training Module",
  form_signature: "Fill / Sign Form",
  video_watch: "Watch Video",
  checklist: "Checklist",
};

export function taskDeepLink(task) {
  const ref = task.related_ref || "";
  switch (task.kind) {
    case "read_handbook_section": return `/handbook/${encodeURIComponent(ref)}`;
    case "training_module":       return `/training?module=${encodeURIComponent(ref)}`;
    case "form_signature":        return `/admin/templates?code=${encodeURIComponent(ref)}`;
    default:                       return "/onboarding-checklist";
  }
}
