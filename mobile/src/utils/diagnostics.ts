/**
 * K36 · Diagnostic ring-buffer + crash-report persistence.
 *
 * Two independent ring buffers (last 20 entries each):
 *   - nav crumbs   — screen focus / navigation breadcrumbs
 *   - api crumbs   — every API request + response summary
 *
 * Both live in AsyncStorage so they survive a JS crash + relaunch.
 * A separate `last_crash` slot is written by the RootErrorBoundary
 * so the next successful launch can attempt to upload it.
 *
 * Public API:
 *   logNav(route, extra?)         push a nav breadcrumb
 *   logApi(entry)                 push an API breadcrumb
 *   getDiagnostics()              read the current snapshot
 *   clearDiagnostics()            wipe all breadcrumbs + crash
 *   persistCrash(err, stack)      called from error boundary
 *   consumePendingCrash()         called at boot to grab + clear
 *
 * All helpers are best-effort — every read/write is wrapped so that
 * a broken AsyncStorage never surfaces as an uncaught exception.
 */
import AsyncStorage from "@react-native-async-storage/async-storage";
import { Platform } from "react-native";

const RING_SIZE = 20;
const KEY_NAV   = "k36_diag_nav_v1";
const KEY_API   = "k36_diag_api_v1";
const KEY_CRASH = "k36_diag_last_crash_v1";

export type NavCrumb = {
  ts: number;
  route: string;
  extra?: Record<string, unknown>;
};

export type ApiCrumb = {
  ts: number;
  method: string;
  path: string;
  status?: number;
  ms?: number;
  errorKind?: "network" | "http" | "timeout";
  errorMsg?: string;
};

export type CrashRecord = {
  ts: number;
  message: string;
  stack?: string;
  componentStack?: string;
  platform: string;
  osVersion?: string;
};

export type DiagnosticsSnapshot = {
  nav: NavCrumb[];
  api: ApiCrumb[];
  lastCrash: CrashRecord | null;
  platform: string;
  osVersion?: string;
  capturedAt: number;
};

/* ------------------------------------------------------------------ */
/*  In-memory mirrors so a hot session doesn't hit AsyncStorage on
 *  every crumb. Both buffers are kept small (RING_SIZE * few bytes).   */
/* ------------------------------------------------------------------ */
let _nav: NavCrumb[] = [];
let _api: ApiCrumb[] = [];
let _hydrated = false;

async function _hydrate() {
  if (_hydrated) return;
  _hydrated = true;
  try {
    const [nRaw, aRaw] = await Promise.all([
      AsyncStorage.getItem(KEY_NAV),
      AsyncStorage.getItem(KEY_API),
    ]);
    if (nRaw) {
      try { const p = JSON.parse(nRaw); if (Array.isArray(p)) _nav = p.slice(-RING_SIZE); } catch { /* ignore */ }
    }
    if (aRaw) {
      try { const p = JSON.parse(aRaw); if (Array.isArray(p)) _api = p.slice(-RING_SIZE); } catch { /* ignore */ }
    }
  } catch {
    // AsyncStorage unavailable — start with empty in-memory buffers.
  }
}

// Fire-and-forget hydrate on module load.
_hydrate();

function _push<T>(buf: T[], item: T): T[] {
  buf.push(item);
  if (buf.length > RING_SIZE) buf.splice(0, buf.length - RING_SIZE);
  return buf;
}

function _flushNav() {
  AsyncStorage.setItem(KEY_NAV, JSON.stringify(_nav)).catch(() => {});
}
function _flushApi() {
  AsyncStorage.setItem(KEY_API, JSON.stringify(_api)).catch(() => {});
}

/* ------------------------------------------------------------------ */
/*  Public writers                                                     */
/* ------------------------------------------------------------------ */
export function logNav(route: string, extra?: Record<string, unknown>): void {
  try {
    _push(_nav, { ts: Date.now(), route: String(route || ""), extra });
    _flushNav();
  } catch { /* swallow */ }
}

export function logApi(entry: Omit<ApiCrumb, "ts"> & { ts?: number }): void {
  try {
    _push(_api, {
      ts: entry.ts ?? Date.now(),
      method: entry.method,
      path: entry.path,
      status: entry.status,
      ms: entry.ms,
      errorKind: entry.errorKind,
      errorMsg: entry.errorMsg ? String(entry.errorMsg).slice(0, 200) : undefined,
    });
    _flushApi();
  } catch { /* swallow */ }
}

/* ------------------------------------------------------------------ */
/*  Public readers                                                     */
/* ------------------------------------------------------------------ */
export async function getDiagnostics(): Promise<DiagnosticsSnapshot> {
  await _hydrate();
  let lastCrash: CrashRecord | null = null;
  try {
    const raw = await AsyncStorage.getItem(KEY_CRASH);
    if (raw) lastCrash = JSON.parse(raw);
  } catch { /* ignore */ }
  return {
    nav: [..._nav],
    api: [..._api],
    lastCrash,
    platform: Platform.OS,
    osVersion: String(Platform.Version ?? ""),
    capturedAt: Date.now(),
  };
}

export async function clearDiagnostics(): Promise<void> {
  _nav = [];
  _api = [];
  try {
    await Promise.all([
      AsyncStorage.removeItem(KEY_NAV),
      AsyncStorage.removeItem(KEY_API),
      AsyncStorage.removeItem(KEY_CRASH),
    ]);
  } catch { /* ignore */ }
}

/* ------------------------------------------------------------------ */
/*  Crash slot                                                         */
/* ------------------------------------------------------------------ */
export function persistCrash(
  err: Error | unknown,
  componentStack?: string | null,
): void {
  try {
    const e: any = err || {};
    const record: CrashRecord = {
      ts: Date.now(),
      message: String(e?.message || e || "unknown"),
      stack: e?.stack ? String(e.stack).slice(0, 4000) : undefined,
      componentStack: componentStack ? String(componentStack).slice(0, 4000) : undefined,
      platform: Platform.OS,
      osVersion: String(Platform.Version ?? ""),
    };
    AsyncStorage.setItem(KEY_CRASH, JSON.stringify(record)).catch(() => {});
  } catch { /* swallow */ }
}

export async function consumePendingCrash(): Promise<CrashRecord | null> {
  try {
    const raw = await AsyncStorage.getItem(KEY_CRASH);
    if (!raw) return null;
    await AsyncStorage.removeItem(KEY_CRASH);
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

/* ------------------------------------------------------------------ */
/*  Human-readable dump for the "Send diagnostics" button.             */
/* ------------------------------------------------------------------ */
export function formatDiagnostics(snap: DiagnosticsSnapshot): string {
  const lines: string[] = [];
  lines.push("=== Pool Landscaping · Mobile Diagnostics ===");
  lines.push(`Captured: ${new Date(snap.capturedAt).toISOString()}`);
  lines.push(`Platform: ${snap.platform} ${snap.osVersion || ""}`.trim());
  lines.push("");
  if (snap.lastCrash) {
    lines.push("--- Last crash ---");
    lines.push(`When:  ${new Date(snap.lastCrash.ts).toISOString()}`);
    lines.push(`Error: ${snap.lastCrash.message}`);
    if (snap.lastCrash.componentStack) {
      lines.push(`Component stack:\n${snap.lastCrash.componentStack}`);
    }
    if (snap.lastCrash.stack) {
      lines.push(`Stack:\n${snap.lastCrash.stack}`);
    }
    lines.push("");
  }
  lines.push(`--- Nav breadcrumbs (last ${snap.nav.length}) ---`);
  for (const c of snap.nav) {
    const ex = c.extra ? ` ${JSON.stringify(c.extra)}` : "";
    lines.push(`${new Date(c.ts).toISOString()}  ${c.route}${ex}`);
  }
  lines.push("");
  lines.push(`--- API breadcrumbs (last ${snap.api.length}) ---`);
  for (const c of snap.api) {
    const s = c.status != null ? String(c.status) : (c.errorKind || "?");
    const ms = c.ms != null ? `${c.ms}ms` : "";
    const err = c.errorMsg ? ` err="${c.errorMsg}"` : "";
    lines.push(`${new Date(c.ts).toISOString()}  ${c.method} ${c.path} → ${s} ${ms}${err}`.trim());
  }
  return lines.join("\n");
}
