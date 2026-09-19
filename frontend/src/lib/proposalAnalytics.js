/**
 * Feb-2026 · Proposal Analytics — client helper.
 *
 * Fires page-view / open / click / close events for the interactive
 * flipbook estimate viewer against
 * ``POST /api/analytics/proposal/{estimate_id}/event``.
 *
 * Design decisions:
 *   - session_id is a client-generated UUIDv4 persisted in
 *     sessionStorage under ``proposal_session_{estimateId}`` so the
 *     same tab session sees a stable id across refreshes but a new
 *     tab (or a new estimate) gets a fresh id.
 *   - Close/unload events fire via ``navigator.sendBeacon`` so the
 *     browser doesn't drop them mid-navigation. The backend accepts
 *     ``text/plain`` bodies as well as ``application/json``.
 *   - Regular events use ``fetch({ keepalive: true })`` so short
 *     network hiccups don't lose the event.
 *   - Every failure path is swallowed silently — analytics MUST NEVER
 *     break the customer viewer. Only ``console.debug`` on error.
 *
 * Usage::
 *
 *   const { fireEvent } = useProposalAnalytics(estimateId, magicToken);
 *   fireEvent("click", { button_id: "approve" });
 */
import { useEffect, useMemo, useRef } from "react";


const _STORAGE_PREFIX = "proposal_session_";


function _getSessionId(estimateId) {
  if (typeof window === "undefined") return "server";
  const key = `${_STORAGE_PREFIX}${estimateId}`;
  try {
    const existing = window.sessionStorage.getItem(key);
    if (existing) return existing;
    // ``crypto.randomUUID`` is supported in every browser Playwright
    // + the Emergent preview surface run in. Fall back to a Math-
    // based UUID for prehistoric environments.
    const fresh = (typeof crypto !== "undefined"
                    && typeof crypto.randomUUID === "function")
      ? crypto.randomUUID()
      : `sess-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
    window.sessionStorage.setItem(key, fresh);
    return fresh;
  } catch {
    // sessionStorage disabled — use a memoised in-page id so at
    // least THIS page-load stays consistent.
    return `sess-fallback-${Date.now()}`;
  }
}


function _endpoint(estimateId) {
  const base = process.env.REACT_APP_BACKEND_URL || "";
  return `${base.replace(/\/$/, "")}/api/analytics/proposal/${encodeURIComponent(estimateId)}/event`;
}


function _postJson(url, body) {
  if (typeof fetch === "undefined") return Promise.resolve();
  return fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    keepalive: true,
    credentials: "omit",
  }).catch((err) => {
    // Silent — analytics never blocks the viewer.
    if (typeof console !== "undefined" && console.debug) {
      console.debug("[proposalAnalytics] fetch failed", err?.message);
    }
  });
}


function _postBeacon(url, body) {
  if (typeof navigator === "undefined" || !navigator.sendBeacon) {
    return _postJson(url, body);
  }
  try {
    const blob = new Blob([JSON.stringify(body)], { type: "text/plain" });
    return navigator.sendBeacon(url, blob);
  } catch {
    return _postJson(url, body);
  }
}


/** Plain function form — used inline where a hook isn't practical
 *  (e.g., inside a raw ``beforeunload`` listener that fires after
 *  React has already begun teardown). */
export function sendProposalEvent(estimateId, token, eventType, extras = {}) {
  if (!estimateId || !token) return;
  const body = {
    token,
    session_id: _getSessionId(estimateId),
    event_type: eventType,
    ...extras,
  };
  const url = _endpoint(estimateId);
  if (eventType === "close") {
    _postBeacon(url, body);
  } else {
    _postJson(url, body);
  }
}


/** React hook wrapper — memoises the session id and returns a
 *  stable ``fireEvent`` bound to (estimateId, token). Also handles
 *  the mount ``open`` event + unmount/beforeunload ``close`` event
 *  so the caller only wires page_view + click. */
export function useProposalAnalytics(estimateId, token, {
  autoOpen = true, autoCloseOnUnload = true,
} = {}) {
  const sessionId = useMemo(
    () => (estimateId ? _getSessionId(estimateId) : ""),
    [estimateId],
  );

  // Latest page context — kept in a ref so the unload listener sees
  // the fresh value without React state churn re-registering the
  // listener on every page flip.
  const lastPageRef = useRef({
    page_index: null, page_key: null, entered_at: null,
  });

  const fireEvent = useMemo(() => {
    return (eventType, extras = {}) => {
      if (!estimateId || !token) return;
      sendProposalEvent(estimateId, token, eventType, extras);
    };
  }, [estimateId, token]);

  const setCurrentPage = useMemo(() => {
    return (page_index, page_key) => {
      lastPageRef.current = {
        page_index, page_key, entered_at: Date.now(),
      };
    };
  }, []);

  useEffect(() => {
    if (!estimateId || !token) return undefined;
    if (autoOpen) {
      fireEvent("open");
    }
    const flushOnUnload = () => {
      const cur = lastPageRef.current;
      if (cur.entered_at) {
        sendProposalEvent(estimateId, token, "page_view", {
          page_index: cur.page_index,
          page_key: cur.page_key,
          duration_ms: Math.max(0, Date.now() - cur.entered_at),
        });
      }
      sendProposalEvent(estimateId, token, "close");
    };
    if (!autoCloseOnUnload) return undefined;
    // ``pagehide`` fires more reliably than ``beforeunload`` on
    // mobile Safari and inside bfcache scenarios.
    window.addEventListener("pagehide", flushOnUnload);
    window.addEventListener("beforeunload", flushOnUnload);
    return () => {
      window.removeEventListener("pagehide", flushOnUnload);
      window.removeEventListener("beforeunload", flushOnUnload);
    };
  }, [estimateId, token, autoOpen, autoCloseOnUnload, fireEvent]);

  return { fireEvent, setCurrentPage, sessionId };
}


// Test-only helpers.
export const __TEST_ONLY__ = {
  getSessionId: _getSessionId,
  endpoint: _endpoint,
  storagePrefix: _STORAGE_PREFIX,
};
