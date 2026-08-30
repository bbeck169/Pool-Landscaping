/**
 * Tenant brand hook — mirrors frontend/src/hooks/useTenantBrand.js
 *
 * Fetches `GET /api/tenants/current` on mount, caches the logo URL
 * per session via AsyncStorage. Exposes `refresh()` for future admin
 * upload UI. Listens for `tenant-brand:updated` via the sync netBus.
 *
 * Offline: returns last-cached URL without hitting the network.
 */
import { useState, useEffect, useCallback, useRef } from "react";
import { api } from "@/src/api";
import { storage } from "@/src/utils/storage";
import { isOnlineNow, on as onNetEvent } from "@/src/services/sync/netBus";

const CACHE_KEY = "tenant_brand_logo_url";

/** In-memory session cache so we don't read AsyncStorage on every mount. */
let _sessionCache: string | null = null;
let _sessionLoaded = false;

export type TenantBrand = {
  /** Tenant logo URL, or null when using bundled default. */
  logoUrl: string | null;
  /** True while the initial fetch is in flight. */
  loading: boolean;
  /** Re-fetch tenant branding from the server. */
  refresh: () => Promise<void>;
};

export function useTenantBrand(): TenantBrand {
  const [logoUrl, setLogoUrl] = useState<string | null>(_sessionCache);
  const [loading, setLoading] = useState(!_sessionLoaded);
  const mountedRef = useRef(true);

  const fetchBrand = useCallback(async () => {
    try {
      const tenant: any = await api.get("/tenants/current");
      const url: string | null = tenant?.branding?.logo_url || null;
      if (mountedRef.current) {
        setLogoUrl(url);
        setLoading(false);
      }
      // Persist to cache.
      _sessionCache = url;
      _sessionLoaded = true;
      await storage.setItem(CACHE_KEY, url ?? "");
    } catch {
      // On error, keep whatever we had cached.
      if (mountedRef.current) setLoading(false);
    }
  }, []);

  const loadCached = useCallback(async () => {
    if (_sessionLoaded) {
      // Already loaded this session.
      setLogoUrl(_sessionCache);
      setLoading(false);
      return;
    }
    // Read from AsyncStorage first for instant render.
    const cached = await storage.getItem(CACHE_KEY, "");
    if (mountedRef.current && cached) {
      setLogoUrl(cached || null);
      _sessionCache = cached || null;
    }
    // Then fetch fresh if online.
    if (isOnlineNow()) {
      await fetchBrand();
    } else {
      _sessionLoaded = true;
      if (mountedRef.current) setLoading(false);
    }
  }, [fetchBrand]);

  useEffect(() => {
    mountedRef.current = true;
    loadCached();
    return () => { mountedRef.current = false; };
  }, [loadCached]);

  // Listen for brand-updated events (from future admin upload UI).
  useEffect(() => {
    const unsub = onNetEvent("network:online", () => {
      // Re-fetch brand on reconnect in case it changed while offline.
      fetchBrand();
    });
    return unsub;
  }, [fetchBrand]);

  const refresh = useCallback(async () => {
    setLoading(true);
    await fetchBrand();
  }, [fetchBrand]);

  return { logoUrl, loading, refresh };
}

/** Reset session cache (for testing). */
export function __resetSessionCache() {
  _sessionCache = null;
  _sessionLoaded = false;
}
