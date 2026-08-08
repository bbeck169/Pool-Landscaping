/**
 * Phase 51b · Feb 2026 — Walkie-Talkie pure-logic helpers.
 *
 * The main ``Walkie.jsx`` page is router + polling + MediaRecorder
 * heavy, so the tiny pure surface — permission gating, MIME
 * negotiation, mute persistence, own-message detection, unread
 * aggregation — is extracted here. Vitest exercises this module
 * directly (no jsdom-render hop) which keeps the walkie test files
 * < 100 ms each.
 */

/** Roles that are allowed to broadcast to the ``all_hands`` channel. */
export const BROADCAST_ROLES = new Set(["super_admin", "admin", "manager"]);

/** Phase 51.5 · Feb 2026 — Roles allowed to pin one message per channel. */
export const PIN_ROLES = new Set(["super_admin", "admin", "manager"]);

/** Staff roles that see the walkie surface at all. */
export const STAFF_ROLES = new Set([
  "super_admin", "admin", "manager", "owner", "dispatcher", "technician",
]);

/** Can the caller pin / unpin messages? Server also enforces. */
export function canPinInChannel(user, _channel) {
  if (!user) return false;
  return PIN_ROLES.has((user.role || "").toLowerCase());
}

/** MediaRecorder MIME preference order — first supported wins.
 *
 * Backend accepts webm/mp4/aac/mpeg/ogg. Chrome-family exposes webm/opus
 * as the default; Safari serves mp4/aac. If the browser's
 * ``MediaRecorder.isTypeSupported`` returns false for everything the
 * server accepts, we let the recorder fall back to the browser default
 * (which we then map to ``audio/webm`` at upload time — Safari's
 * ``audio/mp4`` blob type still parses server-side).
 */
export const AUDIO_MIME_CANDIDATES = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/mp4",
  "audio/aac",
  "audio/mpeg",
  "audio/ogg;codecs=opus",
];

/** Pick the first ``MediaRecorder``-supported MIME from our accept-list. */
export function pickAudioMime(isSupported = (t) => (typeof MediaRecorder !== "undefined") && MediaRecorder.isTypeSupported?.(t)) {
  for (const t of AUDIO_MIME_CANDIDATES) {
    try {
      if (isSupported(t)) return t;
    } catch { /* ignore */ }
  }
  return "audio/webm"; // safe default — server accepts it
}

/**
 * Can the caller record + send to the selected channel?
 *
 * Mirrors the server-side check in ``routers/walkie.py``:
 * - ``all_hands`` is admin/super_admin/manager only.
 * - ``department`` requires role in STAFF_ROLES (technician OK) — the
 *   server further scopes techs to their own department but the UI
 *   only ever surfaces the user's own department in the channel list
 *   (the server enforces it too).
 * - ``direct`` requires the caller to be one of the ``member_user_ids``.
 */
export function canRecordInChannel(user, channel) {
  if (!user || !channel) return { allowed: false, reason: "no_selection" };
  const role = (user.role || "").toLowerCase();
  if (!STAFF_ROLES.has(role)) return { allowed: false, reason: "not_staff" };
  if (channel.kind === "all_hands") {
    if (!BROADCAST_ROLES.has(role)) {
      return { allowed: false, reason: "Only admins can broadcast to all-hands" };
    }
    return { allowed: true };
  }
  if (channel.kind === "direct") {
    const members = channel.member_user_ids || [];
    if (!members.includes(user.id)) {
      return { allowed: false, reason: "not_a_channel_member" };
    }
    return { allowed: true };
  }
  // department — server also filters, but block techs on the wrong dept
  // client-side if the channel row somehow surfaces (defensive).
  if (channel.kind === "department") {
    if (BROADCAST_ROLES.has(role)) return { allowed: true };
    // technician / dispatcher — normalise ``landscaping`` → ``landscape``.
    const dep = (user.department || "").toLowerCase();
    const norm = dep === "landscaping" ? "landscape" : dep;
    if (norm === channel.department) return { allowed: true };
    return { allowed: false, reason: "not_a_channel_member" };
  }
  return { allowed: false, reason: "unknown_channel_kind" };
}

/** Is the given message authored by the current caller? */
export function isOwnMessage(user, message) {
  return !!(user?.id && message?.sender_user_id && user.id === message.sender_user_id);
}

/** Sum unread counts across the caller's channel list. */
export function totalUnread(channels) {
  return (channels || []).reduce((n, c) => n + (Number(c?.unread_count) || 0), 0);
}

const MUTE_KEY = "walkie_muted";

/** Persistent mute preference — defaults to unmuted. */
export function isMuted(storage = (typeof localStorage !== "undefined" ? localStorage : null)) {
  if (!storage) return false;
  return storage.getItem(MUTE_KEY) === "1";
}

/** Write the mute preference. Only ever writes "1" or clears the key. */
export function setMuted(next, storage = (typeof localStorage !== "undefined" ? localStorage : null)) {
  if (!storage) return;
  if (next) storage.setItem(MUTE_KEY, "1");
  else storage.removeItem(MUTE_KEY);
}

/**
 * Should we auto-play a freshly-received message?
 *
 *  1. Suppress if the user muted.
 *  2. Suppress if the message is our own (sender doesn't need to hear themselves).
 *  3. Otherwise play it.
 */
export function shouldAutoPlay({ user, message, muted }) {
  if (muted) return false;
  if (isOwnMessage(user, message)) return false;
  return true;
}

/**
 * Sort helper — All-hands first, then department (alphabetical), then directs (newest first).
 */
export function sortChannels(list) {
  const priority = { all_hands: 0, department: 1, direct: 2 };
  return [...(list || [])].sort((a, b) => {
    const pa = priority[a.kind] ?? 9;
    const pb = priority[b.kind] ?? 9;
    if (pa !== pb) return pa - pb;
    if (a.kind === "department") return (a.department || "").localeCompare(b.department || "");
    // directs — newest created_at first
    return (b.created_at || "").localeCompare(a.created_at || "");
  });
}
