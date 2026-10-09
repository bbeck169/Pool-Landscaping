/**
 * Phase 7D · Form Template Runtime (mobile) — loader hook.
 * Port of web `frontend/src/hooks/useFormTemplateRuntime.js` (77a0c83de).
 *
 * FALLBACK CONTRACT: any failure (401/403/404/5xx/network/malformed)
 * resolves to `isEmpty: true`. Consumers MUST then render their current
 * hardcoded layout untouched. Note: GET /form-templates/{type} is gated to
 * admin/super_admin/owner/manager — techs & customers always get 403 →
 * isEmpty → hardcoded layout (same as web).
 *
 * Mobile additions vs web:
 *  • cache keyed by `${tenant_id}:${form_type}` (web: form_type only)
 *  • TTL: 5 min for resolved results, 30 s for network failures (so a
 *    reconnect recovers without any retry loop). No automatic retry.
 *  • Parallel mounts share one in-flight request. Unmount uses an `alive`
 *    guard instead of aborting the shared request (another mounted
 *    consumer may still be awaiting it); the response just warms the cache.
 */
import { useEffect, useState } from "react";
import { api, ApiNetworkError } from "@/src/api";
import { useAuth } from "@/src/auth";

export type TemplateField = {
  field_id: string;
  label?: string;
  field_type?: string;
  order?: number;
  locked_reorder?: boolean;
  style?: Record<string, any>;
};

export type FormTemplateRuntime = {
  fieldsById: Record<string, TemplateField>;
  fieldsOrdered: TemplateField[];
  isLoading: boolean;
  error: string | null;
  isEmpty: boolean;
  version: number | null;
};

export const TEMPLATE_TTL_MS = 5 * 60 * 1000;
export const TEMPLATE_NETWORK_FAIL_TTL_MS = 30 * 1000;

const EMPTY: FormTemplateRuntime = Object.freeze({
  fieldsById: Object.freeze({}) as Record<string, TemplateField>,
  fieldsOrdered: Object.freeze([]) as unknown as TemplateField[],
  isLoading: false,
  error: null,
  isEmpty: true,
  version: null,
});

type Entry = { value: FormTemplateRuntime; expires: number };
const cache = new Map<string, Entry>();
const inflight = new Map<string, Promise<FormTemplateRuntime>>();

export function normalizeTemplate(body: any): FormTemplateRuntime | null {
  if (!body || typeof body !== "object" || !Array.isArray(body.fields) || body.fields.length === 0) return null;
  const valid = body.fields.filter((f: any) => f && typeof f === "object" && typeof f.field_id === "string");
  if (valid.length === 0) return null;
  const fieldsById: Record<string, TemplateField> = {};
  for (const f of valid) fieldsById[f.field_id] = f;
  const fieldsOrdered = [...valid].sort((a, b) => (Number(a?.order) || 0) - (Number(b?.order) || 0));
  return {
    fieldsById, fieldsOrdered,
    version: typeof body.version === "number" ? body.version : null,
    isLoading: false, error: null, isEmpty: false,
  };
}

function readCache(key: string): FormTemplateRuntime | null {
  const e = cache.get(key);
  if (!e) return null;
  if (Date.now() > e.expires) { cache.delete(key); return null; }
  return e.value;
}

function fetchOnce(key: string, formType: string): Promise<FormTemplateRuntime> {
  const hit = readCache(key);
  if (hit) return Promise.resolve(hit);
  const pending = inflight.get(key);
  if (pending) return pending;
  const p = api.get(`/form-templates/${encodeURIComponent(formType)}`)
    .then((body: any) => normalizeTemplate(body) || { ...EMPTY, error: "empty_or_malformed" })
    .catch((e: any) => ({
      ...EMPTY,
      error: e instanceof ApiNetworkError ? "network" : `http_${e?.status ?? "error"}`,
    }))
    .then((value) => {
      const ttl = value.error === "network" ? TEMPLATE_NETWORK_FAIL_TTL_MS : TEMPLATE_TTL_MS;
      cache.set(key, { value, expires: Date.now() + ttl });
      inflight.delete(key);
      return value;
    });
  inflight.set(key, p);
  return p;
}

/** Drop cached templates (all, or one form_type across tenants). */
export function invalidateFormTemplateRuntime(formType?: string) {
  if (!formType) { cache.clear(); inflight.clear(); return; }
  for (const k of [...cache.keys()]) if (k.endsWith(`:${formType}`)) cache.delete(k);
  for (const k of [...inflight.keys()]) if (k.endsWith(`:${formType}`)) inflight.delete(k);
}

export function useFormTemplateRuntime(formType: string | null | undefined): FormTemplateRuntime {
  const { user } = useAuth() as any;
  const tenant = String(user?.tenant_id || user?.tenant_slug || "default");
  const key = formType ? `${tenant}:${formType}` : "";
  const [state, setState] = useState<FormTemplateRuntime>(() => {
    if (!key) return EMPTY;
    return readCache(key) || { ...EMPTY, isLoading: true };
  });

  useEffect(() => {
    if (!key || !formType) { setState(EMPTY); return undefined; }
    const hit = readCache(key);
    if (hit) { setState(hit); return undefined; }
    let alive = true;
    setState({ ...EMPTY, isLoading: true });
    fetchOnce(key, formType).then((v) => { if (alive) setState(v); });
    return () => { alive = false; };
  }, [key, formType]);

  return state;
}

export default useFormTemplateRuntime;
