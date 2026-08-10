/**
 * Phase 54h-b · Aug-2026 — Challenge Handoff modal.
 *
 * Opens from ``SupplierSettings.jsx`` when ``POST /suppliers/{slug}/
 * test-connection`` returns ``challenge_required: true``. Guides the
 * operator through two cookie-import flavours + a Retry button that
 * re-fires the original test-connection call after cookies land.
 *
 *   Path 1 (primary): bookmarklet — operator drags the ``javascript:``
 *   anchor to their bookmarks bar, opens the supplier's site in a new
 *   tab, logs in solving Turnstile, then clicks the bookmarklet from
 *   that tab. The bookmarklet POSTs ``document.cookie`` back to
 *   ``/api/suppliers/{slug}/sessions?import_token=<5-min-JWT>``.
 *
 *   Path 2 (DevTools fallback): the operator copies a small snippet
 *   into DevTools console on the supplier's tab, gets back a JSON
 *   blob of cookies, pastes it into this modal, hits Submit → same
 *   endpoint via the primary auth header.
 *
 * Auth for path 1 uses the scoped ``import_token``; path 2 uses the
 * operator's live CRM session cookie automatically via ``api.post``.
 */
import React, { useEffect, useMemo, useState } from "react";
import { X, ExternalLink, RotateCcw, CheckCircle2 } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";


// Build the bookmarklet ``javascript:`` URL as a single-line IIFE.
// Uses the operator's tenant-scoped import token + the CRM API URL
// (both baked in at render time). ``document.cookie`` parsing is
// deliberately minimal — only ``name`` + ``value`` (the fields the
// backend truly needs to pass Playwright's ``context.add_cookies``).
function buildBookmarkletHref(apiUrl, slug, token) {
  const url = `${apiUrl}/api/suppliers/${slug}/sessions?import_token=${encodeURIComponent(token)}`;
  const src = `(function(){try{var cs=document.cookie.split(';').map(function(c){var p=c.trim().split('=');return{name:p.shift(),value:decodeURIComponent(p.join('=')),domain:location.hostname}}).filter(function(c){return c.name});fetch(${JSON.stringify(url)},{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cookies:cs})}).then(function(r){return r.json()}).then(function(j){alert(j.ok?('Session cached for AquaTerra CRM ('+j.cookie_count+' cookies).'):('Import failed: '+(j.detail&&j.detail.error||'unknown')));}).catch(function(e){alert('Bookmarklet error: '+e.message)});}catch(e){alert('Bookmarklet error: '+e.message);}})();`;
  return `javascript:${encodeURIComponent(src)}`;
}


export default function ChallengeHandoffModal({
  slug, displayName, loginUrl, onClose, onRetry,
}) {
  const [token, setToken] = useState(null);
  const [tokenError, setTokenError] = useState("");
  const [pasteText, setPasteText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);

  // Mint a fresh 5-min import token on mount so the bookmarklet
  // href is always valid at drag-time.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await api.post("/suppliers/sessions/import-token", {});
        if (!cancelled) setToken(r?.token || null);
      } catch (e) {
        if (!cancelled) setTokenError(e?.message || "Could not mint import token.");
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // REACT_APP_BACKEND_URL points at the CRM's public backend host.
  const apiUrl = useMemo(
    () => (process.env.REACT_APP_BACKEND_URL || "").replace(/\/$/, ""),
    [],
  );
  const bookmarkletHref = useMemo(
    () => token ? buildBookmarkletHref(apiUrl, slug, token) : "javascript:void(0)",
    [apiUrl, slug, token],
  );

  const submitPaste = async () => {
    if (submitting) return;
    setError("");
    let cookies;
    try {
      cookies = JSON.parse(pasteText);
      if (!Array.isArray(cookies)) throw new Error("must be an array");
    } catch (e) {
      setError(`Paste must be a JSON array of cookies: ${e.message}`);
      return;
    }
    setSubmitting(true);
    try {
      await api.post(`/suppliers/${slug}/sessions`, { cookies });
      setSuccess(true);
    } catch (e) {
      setError(e?.data?.detail?.message || e?.message || "Submit failed.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-4"
      style={{ background: "rgba(15,23,42,0.55)" }}
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
      data-testid="challenge-handoff-modal"
    >
      <div
        className="w-full max-w-lg rounded-2xl p-6 shadow-2xl bg-white max-h-[85vh] overflow-y-auto"
        style={{ border: `1px solid ${colors.border}` }}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-lg font-bold" style={{ color: colors.onSurface }}>
            Solve the {displayName} challenge
          </h2>
          <button onClick={onClose} aria-label="Close"
                    style={{ color: colors.muted }}
                    data-testid="challenge-handoff-close">
            <X size={18} />
          </button>
        </div>

        <p className="text-xs mb-4" style={{ color: colors.muted }}>
          {displayName}'s login is behind a "prove you're human"
          challenge that a scripted browser can't solve. Complete
          the challenge in your own browser once, then hand the
          resulting session cookies back to the CRM so the sync
          can proceed for the next 30 minutes.
        </p>

        {success ? (
          <div className="rounded-lg p-3 mb-4 text-sm flex items-start gap-2"
                style={{ background: "#DCFCE7", color: "#166534",
                          border: "1px solid #86EFAC" }}
                data-testid="challenge-handoff-success">
            <CheckCircle2 size={16} className="mt-0.5 flex-shrink-0" />
            <div>
              <div className="font-semibold mb-1">Session cached.</div>
              <div className="text-xs">Retry Test Login and the sync
                should now bypass the challenge.</div>
            </div>
          </div>
        ) : null}

        {/* Step 1 — log in on the supplier's site */}
        <div className="mb-4">
          <div className="text-[10px] uppercase font-bold mb-1"
                style={{ color: colors.muted }}>Step 1</div>
          <div className="text-sm" style={{ color: colors.onSurface }}>
            Open {displayName} in a new tab and log in normally.
            Solve any "I'm not a robot" challenge if prompted.
          </div>
          {loginUrl ? (
            <a href={loginUrl} target="_blank" rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-xs font-bold mt-1"
                style={{ color: colors.brand }}
                data-testid="challenge-handoff-supplier-link">
              Open {displayName} <ExternalLink size={12} />
            </a>
          ) : null}
        </div>

        {/* Step 2 — bookmarklet drag target */}
        <div className="mb-4">
          <div className="text-[10px] uppercase font-bold mb-1"
                style={{ color: colors.muted }}>Step 2</div>
          <div className="text-sm mb-2" style={{ color: colors.onSurface }}>
            Drag this bookmarklet to your bookmarks bar, then click
            it while on the {displayName} logged-in page.
          </div>
          {token ? (
            <a
              ref={(el) => {
                // React 16.9+ blocks ``javascript:`` URLs as a
                // security precaution — but this is EXACTLY the
                // browser API a bookmarklet needs. Set the href via
                // the DOM after mount so React's setter never sees
                // the string. Anchor is inert on click (bookmarklet
                // is drag-to-bookmarks-bar only) so no XSS surface.
                if (el && bookmarkletHref) {
                  el.setAttribute("href", bookmarkletHref);
                }
              }}
              draggable="true"
              onClick={(e) => e.preventDefault()}
              title="Drag me to your bookmarks bar"
              className="inline-block px-3 py-2 rounded-lg text-xs font-bold text-white cursor-grab"
              style={{ backgroundColor: colors.brand, textDecoration: "none" }}
              data-testid="challenge-handoff-bookmarklet"
            >
              🔖 Save session to CRM
            </a>
          ) : tokenError ? (
            <div className="text-xs" style={{ color: "#B91C1C" }}
                  data-testid="challenge-handoff-token-error">{tokenError}</div>
          ) : (
            <div className="text-xs" style={{ color: colors.muted }}
                  data-testid="challenge-handoff-token-loading">
              Minting one-time import token…
            </div>
          )}
        </div>

        {/* Step 3 — DevTools paste fallback */}
        <div className="mb-4">
          <button
            type="button"
            onClick={() => setShowAdvanced((v) => !v)}
            className="text-xs font-bold"
            style={{ color: colors.muted, textDecoration: "underline" }}
            data-testid="challenge-handoff-toggle-advanced"
          >
            {showAdvanced ? "Hide" : "Advanced:"} paste cookies manually
          </button>
          {showAdvanced ? (
            <div className="mt-2">
              <div className="text-xs mb-2" style={{ color: colors.muted }}>
                In DevTools console on the {displayName} tab, run:
              </div>
              <code
                className="block text-[11px] p-2 rounded"
                style={{ background: colors.surface,
                          color: colors.onSurface,
                          border: `1px solid ${colors.border}` }}
                data-testid="challenge-handoff-devtools-snippet"
              >
                {`copy(JSON.stringify(document.cookie.split(';').map(c => {const p = c.trim().split('='); return {name: p.shift(), value: p.join('='), domain: location.hostname}})))`}
              </code>
              <textarea
                value={pasteText}
                onChange={(e) => setPasteText(e.target.value)}
                placeholder='[{"name":"...","value":"..."}]'
                rows={4}
                className="w-full mt-2 px-2 py-1 text-xs font-mono rounded"
                style={{ background: "#fff",
                          border: `1px solid ${colors.border}`,
                          color: colors.onSurface }}
                data-testid="challenge-handoff-paste-textarea"
              />
              {error ? (
                <div className="text-xs mt-1" style={{ color: "#B91C1C" }}
                      data-testid="challenge-handoff-paste-error">{error}</div>
              ) : null}
              <button
                type="button"
                onClick={submitPaste}
                disabled={submitting || !pasteText.trim()}
                className="mt-2 px-3 py-1.5 rounded-md text-xs font-bold text-white disabled:opacity-60"
                style={{ backgroundColor: colors.brand }}
                data-testid="challenge-handoff-paste-submit"
              >
                {submitting ? "Submitting…" : "Submit pasted cookies"}
              </button>
            </div>
          ) : null}
        </div>

        <div className="flex justify-end gap-2 mt-4 pt-3"
              style={{ borderTop: `1px solid ${colors.border}` }}>
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 rounded-lg text-sm font-semibold bg-slate-100"
            data-testid="challenge-handoff-cancel"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => onRetry?.()}
            disabled={!success}
            className="inline-flex items-center gap-1 px-4 py-2 rounded-lg text-sm font-bold text-white disabled:opacity-40"
            style={{ backgroundColor: colors.brand,
                     cursor: success ? "pointer" : "not-allowed" }}
            data-testid="challenge-handoff-retry"
          >
            <RotateCcw size={12} /> Retry Test Login
          </button>
        </div>
      </div>
    </div>
  );
}
