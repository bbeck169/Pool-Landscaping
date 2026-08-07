/**
 * Phase 51c · Feb 2026 — Mobile walkie-talkie pure-logic helpers.
 *
 * Mirror of ``frontend/src/pages/walkie/walkie-helpers.js`` — the two
 * files stay in lock-step so the admin gate + auto-play behavior +
 * MIME negotiation + mute persistence are identical on web and
 * mobile.
 *
 * Persistence uses ``AsyncStorage`` on mobile (async) vs
 * ``localStorage`` on web (sync). The rest is pure.
 */
import AsyncStorage from "@react-native-async-storage/async-storage";

/** Roles allowed to broadcast to the ``all_hands`` channel. */
export const BROADCAST_ROLES = new Set(["super_admin", "admin", "manager"]);

/** Staff roles that see the walkie surface at all. */
export const STAFF_ROLES = new Set([
  "super_admin", "admin", "manager", "owner", "dispatcher", "technician",
]);

/**
 * Preferred audio MIME order for ``expo-audio`` recorder presets.
 *
 * ``expo-audio`` normally records to ``.m4a`` (AAC) on iOS and
 * ``.m4a`` (AAC) on Android, but the caller uploads whatever the
 * platform gave us with the correct content-type. Backend accepts
 * m4a/aac/webm/mp4/mpeg/ogg (Phase 51a whitelist).
 */
export const AUDIO_MIME_CANDIDATES = [
  "audio/mp4",  // .m4a on iOS + modern Android
  "audio/aac",
  "audio/webm",
  "audio/mpeg",
  "audio/ogg",
];

/**
 * Server-parity permission gate — mirrors ``routers/walkie.py``.
 */
export function canRecordInChannel(user: any, channel: any) {
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
    const members: string[] = channel.member_user_ids || [];
    if (!members.includes(user.id)) {
      return { allowed: false, reason: "not_a_channel_member" };
    }
    return { allowed: true };
  }
  if (channel.kind === "department") {
    if (BROADCAST_ROLES.has(role)) return { allowed: true };
    const dep = (user.department || "").toLowerCase();
    const norm = dep === "landscaping" ? "landscape" : dep;
    if (norm === channel.department) return { allowed: true };
    return { allowed: false, reason: "not_a_channel_member" };
  }
  return { allowed: false, reason: "unknown_channel_kind" };
}

export function isOwnMessage(user: any, message: any): boolean {
  return !!(user?.id && message?.sender_user_id && user.id === message.sender_user_id);
}

export function totalUnread(channels: any[]): number {
  return (channels || []).reduce((n: number, c: any) => n + (Number(c?.unread_count) || 0), 0);
}

const MUTE_KEY = "walkie_muted";

/** Persistent mute preference — defaults to unmuted. */
export async function isMuted(): Promise<boolean> {
  const v = await AsyncStorage.getItem(MUTE_KEY);
  return v === "1";
}

export async function setMuted(next: boolean): Promise<void> {
  if (next) await AsyncStorage.setItem(MUTE_KEY, "1");
  else await AsyncStorage.removeItem(MUTE_KEY);
}

export function shouldAutoPlay({ user, message, muted }: any): boolean {
  if (muted) return false;
  if (isOwnMessage(user, message)) return false;
  return true;
}

export function sortChannels<T extends { kind?: string; department?: string; created_at?: string }>(list: T[]): T[] {
  const priority: Record<string, number> = { all_hands: 0, department: 1, direct: 2 };
  return [...(list || [])].sort((a, b) => {
    const pa = priority[a.kind || ""] ?? 9;
    const pb = priority[b.kind || ""] ?? 9;
    if (pa !== pb) return pa - pb;
    if (a.kind === "department") return (a.department || "").localeCompare(b.department || "");
    return (b.created_at || "").localeCompare(a.created_at || "");
  });
}

/** Pick the extension for the recorded blob's MIME. */
export function extForMime(mime: string): string {
  if (mime.includes("mp4")) return "m4a";
  if (mime.includes("aac")) return "aac";
  if (mime.includes("mpeg")) return "mp3";
  if (mime.includes("ogg")) return "ogg";
  if (mime.includes("webm")) return "webm";
  return "m4a";
}
