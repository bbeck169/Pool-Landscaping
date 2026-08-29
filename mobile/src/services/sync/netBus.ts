/**
 * Phase O2 · Network event bus.
 *
 * Wraps `@react-native-community/netinfo` into a module-level event
 * emitter.  Subscribers (sync queue, UI components) listen for
 * `network:online` and `network:offline` transitions.
 *
 * Also exposes `isOnlineNow()` for one-shot checks and the existing
 * React hook `useOnline()` re-exported for convenience.
 */
import NetInfo, { NetInfoState } from "@react-native-community/netinfo";

// ─── state ─────────────────────────────────────────────────────────
let _online: boolean = true; // optimistic default

// ─── event bus ─────────────────────────────────────────────────────
type EventName = "network:online" | "network:offline";
type Handler = () => void;
const _subs = new Map<EventName, Set<Handler>>();

export function on(event: EventName, handler: Handler): () => void {
  if (!_subs.has(event)) _subs.set(event, new Set());
  _subs.get(event)!.add(handler);
  return () => { _subs.get(event)?.delete(handler); };
}

function _emit(event: EventName) {
  _subs.get(event)?.forEach((h) => { try { h(); } catch { /* subscriber threw */ } });
}

// ─── NetInfo listener (singleton) ──────────────────────────────────
let _listening = false;

function _onStateChange(state: NetInfoState) {
  const nowOnline = state.isConnected !== false;
  const wasOnline = _online;
  _online = nowOnline;
  if (nowOnline && !wasOnline) _emit("network:online");
  if (!nowOnline && wasOnline) _emit("network:offline");
}

/**
 * Start listening to NetInfo. Idempotent — safe to call multiple
 * times (only the first call registers the listener).
 */
export function startListening(): void {
  if (_listening) return;
  _listening = true;
  NetInfo.addEventListener(_onStateChange);
  // Prime the initial value.
  NetInfo.fetch().then(_onStateChange).catch(() => {});
}

// ─── public queries ────────────────────────────────────────────────
/** Synchronous snapshot — valid after `startListening()` has been
 *  called at least once. */
export function isOnlineNow(): boolean {
  return _online;
}

/** Async one-shot that hits NetInfo directly. */
export async function isOnlineAsync(): Promise<boolean> {
  const state = await NetInfo.fetch();
  return state.isConnected !== false;
}

// ─── test helpers ──────────────────────────────────────────────────
export function __setOnlineForTests(v: boolean) { _online = v; }
export function __emitForTests(event: EventName) { _emit(event); }
