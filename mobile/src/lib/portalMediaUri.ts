/**
 * TD-67 / TD-76 Phase A — mobile portal media URI helpers.
 *
 * Mobile-owned port of web `lib/urlToken.js::withAuthToken` (TD-76b
 * `?auth=` scheme) plus the canonical `{thumb_url, full_url}` field
 * chains from web `PortalPhotos.jsx` / `PortalServiceReports.jsx`.
 *
 * - Relative `/api/...` paths are prefixed with the backend origin via
 *   the existing `absolutizeUrl` (RN <Image> can't load relative URIs).
 * - `?auth=<token>` is stamped ONLY on the authenticated streaming
 *   routes (`/api/customers/me/...`, `/api/files/...`) — the TD-67
 *   handler contract. Public `/api/public/...` paths are left alone.
 * - `data:` URIs pass through untouched (never token-stamped).
 * - Legacy `url` / `thumb` stay as defensive fallbacks until TD-76
 *   Phase B removes them from BE emission.
 */
import { useEffect, useState } from "react";

import { getAuthToken } from "@/src/api";
import { absolutizeUrl } from "@/src/lib/absolutizeUrl";

const AUTH_PATH_RE = /\/api\/(customers\/me\/|files\/)/;

/** Idempotent, fragment-safe `?auth=` stamp (string splice — RN's URL
 *  polyfill doesn't implement `searchParams.set`). */
export function withAuthToken(url: string, token: string): string {
  if (!url || !token) return url;
  const hashIdx = url.indexOf("#");
  const fragment = hashIdx >= 0 ? url.slice(hashIdx) : "";
  const base = hashIdx >= 0 ? url.slice(0, hashIdx) : url;
  const enc = encodeURIComponent(token);
  if (/[?&]auth=/.test(base)) {
    return `${base.replace(/([?&])auth=[^&]*/, `$1auth=${enc}`)}${fragment}`;
  }
  return `${base}${base.includes("?") ? "&" : "?"}auth=${enc}${fragment}`;
}

/** Raw → loadable RN image URI. Returns "" when nothing usable. */
export function resolvePortalMediaUri(raw: unknown, token: string): string {
  const s = typeof raw === "string" ? raw.trim() : "";
  if (!s) return "";
  if (s.startsWith("data:")) return s;
  const abs = absolutizeUrl(s) || "";
  return AUTH_PATH_RE.test(abs) ? withAuthToken(abs, token) : abs;
}

/** Grid tile chain — web `p.thumb_url || p.thumb || p.url`. */
export const portalPhotoThumbRaw = (p: any): string =>
  (p && (p.thumb_url || p.thumb || p.url)) || "";

/** Lightbox chain — web `full_url || url || thumb_url || thumb`. */
export const portalPhotoFullRaw = (p: any): string =>
  (p && (p.full_url || p.url || p.thumb_url || p.thumb)) || "";

/** SR-detail job_photos chain — web `thumb_url || thumb || full_url || url`. */
export const portalJobPhotoRaw = (p: any): string =>
  (p && (p.thumb_url || p.thumb || p.full_url || p.url)) || "";

/** Bearer token for `?auth=` stamping (async storage → state). */
export function usePortalAuthToken(): string {
  const [token, setToken] = useState("");
  useEffect(() => {
    let alive = true;
    getAuthToken().then((t) => { if (alive) setToken(t); }).catch(() => {});
    return () => { alive = false; };
  }, []);
  return token;
}

export type PhotoVisit = { visitKey: string; jobTitle: string; firstStamp: string; photos: any[] };
export type PhotoDay = { day: string; visits: PhotoVisit[] };

/**
 * Port of web `groupPhotosByDateAndVisit` (TD-76de):
 * days DESC · visits within a day by first `submitted_at` ASC, then
 * `job_id` lex ASC · photos keep BE order · no-stamp → "Unknown date".
 */
export function groupPhotosByDateAndVisit(photos: any[]): PhotoDay[] {
  const byDay = new Map<string, Map<string, PhotoVisit>>();
  for (const p of photos || []) {
    const stamp: string = p.submitted_at || p.uploaded_at || p.created_at || "";
    const day = stamp.slice(0, 10) || "Unknown date";
    const visitKey: string = p.job_id || p.report_id || "no-visit";
    if (!byDay.has(day)) byDay.set(day, new Map());
    const dayMap = byDay.get(day)!;
    if (!dayMap.has(visitKey)) {
      dayMap.set(visitKey, {
        visitKey, jobTitle: p.job_title || p.service_type || "Service visit", firstStamp: stamp, photos: [],
      });
    }
    const v = dayMap.get(visitKey)!;
    if (!v.firstStamp || (stamp && stamp < v.firstStamp)) v.firstStamp = stamp;
    v.photos.push(p);
  }
  return Array.from(byDay.keys())
    .sort((a, b) => b.localeCompare(a))
    .map((day) => ({
      day,
      visits: Array.from(byDay.get(day)!.values()).sort((a, b) => {
        const t = (a.firstStamp || "").localeCompare(b.firstStamp || "");
        return t !== 0 ? t : (a.visitKey || "").localeCompare(b.visitKey || "");
      }),
    }));
}
