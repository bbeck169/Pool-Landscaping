/**
 * MTH-B · Feb-2026 — Action-inventory labels + namespace grouping.
 *
 * The MTH-A backend ships the full ``action_inventory`` array on
 * ``GET /api/tenant-ai-rules`` (raw dot-namespaced keys, e.g.
 * ``marco.clock_in``, ``casey.draft_directory_submission``).
 *
 * This module maps each namespace to a human-friendly group header
 * and derives a per-action label from the key suffix
 * (``draft_directory_submission`` → ``Draft Directory Submission``).
 *
 * Kept in-FE (not exported by the backend) because the labels are
 * pure display text — the backend's server-side allowlist stays
 * authoritative on the action *keys* themselves.
 */

// Namespace → human group name.  Matches the schema.py section
// comments so the FE mirrors backend intent.
export const NAMESPACE_LABELS = Object.freeze({
  marco: "MARCO · Executive Assistant",
  casey: "Casey · Visibility Copilot",
  emmie: "Emmie · Email Marketing",
  buddy: "Buddy · Growth Analyst",
  vizzy: "Vizzy · Daily Ops Brief",
  dexter: "Dexter · Data Analyst",
  soshie: "Soshie · Social Media",
  scouty: "Scouty · Recruiting",
  commet: "Commet · Funnel Copywriter",
});

// Namespace display order — keeps the UI predictable across
// tenants regardless of the sort order the backend returns.
export const NAMESPACE_ORDER = Object.freeze([
  "marco",
  "casey",
  "emmie",
  "buddy",
  "vizzy",
  "dexter",
  "soshie",
  "scouty",
  "commet",
]);

/** Split ``marco.clock_in`` → ``["marco", "clock_in"]``. */
export function splitAction(actionKey) {
  const idx = (actionKey || "").indexOf(".");
  if (idx === -1) return ["", actionKey || ""];
  return [actionKey.slice(0, idx), actionKey.slice(idx + 1)];
}

/**
 * Convert ``"draft_directory_submission"`` →
 * ``"Draft Directory Submission"``.
 */
export function humanizeSuffix(suffix) {
  return String(suffix || "")
    .split("_")
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

/** Human display label for one action key. */
export function actionLabel(actionKey) {
  const [, suffix] = splitAction(actionKey);
  return humanizeSuffix(suffix);
}

/**
 * Group a flat action-inventory array into
 * ``[{ namespace, label, actions: [...] }, ...]`` ordered by
 * ``NAMESPACE_ORDER``.  Unknown namespaces bucket into an
 * "Other" group at the tail so a future backend addition never
 * disappears from the UI silently.
 */
export function groupActions(actionInventory) {
  const bucketed = new Map();
  for (const a of actionInventory || []) {
    const [ns] = splitAction(a);
    const key = ns || "other";
    if (!bucketed.has(key)) bucketed.set(key, []);
    bucketed.get(key).push(a);
  }
  const groups = [];
  for (const ns of NAMESPACE_ORDER) {
    if (bucketed.has(ns)) {
      groups.push({
        namespace: ns,
        label: NAMESPACE_LABELS[ns] || ns,
        actions: [...bucketed.get(ns)].sort(),
      });
      bucketed.delete(ns);
    }
  }
  for (const [ns, actions] of bucketed.entries()) {
    groups.push({
      namespace: ns,
      label: NAMESPACE_LABELS[ns] || `Other · ${ns}`,
      actions: [...actions].sort(),
    });
  }
  return groups;
}
