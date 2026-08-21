/**
 * Feb-2026 · Slice 2C — Customer portal Onboarding gate.
 *
 * Wraps the authenticated portal shell and blocks the customer from
 * interacting with any child route until they've accepted every
 * currently-published ToS document for their active service types.
 *
 * Fetch contract (from 2A backend):
 *   ``GET /customer-portal/onboarding-state`` →
 *     ``{ tutorial_completed, pending_tos: [
 *          {document_id, service_type, version, title,
 *           content_html, effective_date}, ...
 *        ] }``
 *
 * Loop: pending_tos is already server-sorted pool → landscaping.
 * The gate renders ONE blocking modal per pending entry; after
 * ``POST /customer-portal/tos/{doc_id}/accept`` succeeds the next
 * entry loads. When the array empties, ``children`` renders.
 *
 * Role gating: this component is a no-op unless the auth user has
 * ``role === "customer"``. Admin / super_admin / technician / manager
 * flow through untouched. The gate is compatible with the legacy
 * :file:`components/legal/TosGate.jsx` (which self-gates on
 * ``user.must_accept_tos`` for the single-doc admin flow) — both
 * can co-mount because their role predicates don't overlap.
 *
 * Design decision — REPLACE, don't adapt: the legacy ``TosGate`` is
 * single-doc / non-loopable, uses ``user.must_accept_tos`` +
 * ``/users/me/accept-tos``, and rehydrates markdown. Adapting it
 * would require rewriting 90% of the file AND obscuring which system
 * is authoritative for which audience. Cleaner to add this sibling
 * component; legacy ``TosGate`` remains as the admin ToS flow until
 * that audience is migrated in a later phase.
 *
 * Tutorial (``tutorial_completed`` in the DTO): out-of-scope this
 * pass because persisting completion requires a
 * ``POST /customer-portal/tutorial/complete`` endpoint that 2A does
 * NOT expose. The scope guard for 2C explicitly freezes the 2A
 * backend, so this iteration renders the ToS loop only and treats
 * the tutorial step as a future follow-up. See
 * ``_STUB_NEEDS_TUTORIAL`` below.
 *
 * Client-side DOMPurify pass: NOT added because DOMPurify isn't in
 * ``package.json`` and the scope guard forbids adding a new dep.
 * The 2A backend sanitizer (``services/tos_service.sanitize_html``)
 * is the sole HTML gate — allow-list only, ``javascript:`` blocked,
 * external links auto-hardened.
 */
import React, {
  useCallback, useEffect, useMemo, useRef, useState,
} from "react";
import { AlertTriangle, ShieldCheck } from "lucide-react";

import { api } from "@/api";
import { useAuth } from "@/auth";
import { colors } from "@/theme";


// See jsdoc above — tutorial step deferred until 2A exposes a
// completion endpoint. Flipping this to ``true`` (or reading it from
// ``state.tutorial_completed`` once the endpoint lands) is the only
// change needed to enable the walkthrough leg of the flow.
const _STUB_NEEDS_TUTORIAL = false;


function _scrollAtBottom(el, slack = 8) {
  if (!el) return false;
  return el.scrollTop + el.clientHeight >= el.scrollHeight - slack;
}


function TosBlockingModal({ doc, onAccept, onError, error }) {
  const scrollRef = useRef(null);
  const [reachedBottom, setReachedBottom] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  // Content changes → re-evaluate whether the modal is already
  // short enough that "bottom" is instantly reached (small ToS
  // texts). Runs after paint so ``scrollHeight`` is stable.
  useEffect(() => {
    setReachedBottom(false);
    setSubmitting(false);
    const t = setTimeout(() => {
      const el = scrollRef.current;
      if (el && el.scrollHeight <= el.clientHeight + 8) {
        setReachedBottom(true);
      }
    }, 30);
    return () => clearTimeout(t);
  }, [doc?.document_id]);

  const handleScroll = () => {
    if (_scrollAtBottom(scrollRef.current)) setReachedBottom(true);
  };

  const onAgree = async () => {
    if (!reachedBottom || submitting) return;
    setSubmitting(true);
    try {
      await onAccept();
    } catch (e) {
      onError(e);
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-[85] flex items-center justify-center p-4"
      style={{ backgroundColor: "rgba(15,23,42,0.55)" }}
      data-testid="onboarding-tos-modal"
      data-service-type={doc?.service_type}
    >
      <div
        className="w-full max-w-2xl rounded-2xl overflow-hidden flex flex-col"
        style={{
          backgroundColor: colors.surface,
          border: `1px solid ${colors.border}`,
          maxHeight: "88vh",
        }}
      >
        <header
          className="flex items-center gap-3 px-5 py-4"
          style={{
            backgroundColor: colors.brand,
            color: colors.onBrand,
          }}
        >
          <ShieldCheck size={18} />
          <div>
            <div className="text-sm opacity-75 uppercase tracking-wide">
              {doc?.service_type === "landscaping"
                ? "Landscaping Services"
                : "Pool Services"}
            </div>
            <div
              className="text-lg font-bold"
              data-testid="onboarding-tos-title"
            >
              {doc?.title || "Terms of Service"}
            </div>
            <div className="text-xs opacity-75">
              Version {doc?.version}
              {doc?.effective_date
                ? ` · Effective ${doc.effective_date}`
                : ""}
            </div>
          </div>
        </header>

        <div
          ref={scrollRef}
          onScroll={handleScroll}
          className="flex-1 overflow-y-auto px-5 py-4 text-sm"
          style={{ color: colors.onSurface }}
          data-testid="onboarding-tos-scroll"
          // Server-sanitized via ``services/tos_service.sanitize_html``
          // (bleach allow-list, ``javascript:`` blocked, external
          // ``<a>`` auto-hardened with rel="noopener noreferrer"
          // target="_blank"). No client-side DOMPurify — the dep
          // isn't installed and the scope guard forbids adding it.
          dangerouslySetInnerHTML={{ __html: doc?.content_html || "" }}
        />

        <footer
          className="px-5 py-4 flex items-center justify-between gap-3"
          style={{
            backgroundColor: colors.surfaceSubtle,
            borderTop: `1px solid ${colors.border}`,
          }}
        >
          <div
            className="text-xs"
            style={{ color: colors.muted }}
            data-testid="onboarding-tos-scroll-hint"
          >
            {reachedBottom
              ? "You've read the full terms. You can agree below."
              : "Scroll to the bottom to enable the agree button."}
          </div>
          <button
            type="button"
            onClick={onAgree}
            disabled={!reachedBottom || submitting}
            data-testid="onboarding-tos-agree"
            className="px-5 py-2 rounded-md text-sm font-semibold disabled:opacity-40"
            style={{
              backgroundColor: colors.brand,
              color: colors.onBrand,
            }}
          >
            {submitting ? "Saving…" : "I Agree"}
          </button>
        </footer>

        {error ? (
          <div
            className="px-5 py-2 text-xs flex items-center gap-2"
            style={{
              backgroundColor: "#FEE2E2",
              color: "#991B1B",
              borderTop: "1px solid #FCA5A5",
            }}
            data-testid="onboarding-tos-error"
          >
            <AlertTriangle size={12} /> {error}
          </div>
        ) : null}
      </div>
    </div>
  );
}


export default function OnboardingGate({ children }) {
  const { user } = useAuth() || {};
  const [state, setState] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const isCustomer = user?.role === "customer";

  const load = useCallback(async () => {
    if (!isCustomer) return;
    setLoading(true);
    setError("");
    try {
      const r = await api.get("/customer-portal/onboarding-state");
      setState(r || { pending_tos: [], tutorial_completed: true });
    } catch (e) {
      // Non-blocking: if the endpoint 500s, we intentionally
      // render children rather than trap the customer in a
      // broken gate. The next navigation retries.
      setState({ pending_tos: [], tutorial_completed: true });
      setError(e?.message || String(e));
    } finally {
      setLoading(false);
    }
  }, [isCustomer]);

  useEffect(() => {
    if (isCustomer) {
      load();
    } else {
      setState(null);
      setError("");
    }
  }, [isCustomer, load]);

  const nextDoc = useMemo(() => {
    const arr = (state?.pending_tos || []).filter(Boolean);
    return arr.length ? arr[0] : null;
  }, [state]);

  const onAccept = useCallback(async () => {
    if (!nextDoc) return;
    const r = await api.post(
      `/customer-portal/tos/${nextDoc.document_id}/accept`, {},
    );
    // Server returns the recomputed ``pending_tos`` — swap it in so
    // the next iteration renders (or the modal unmounts on empty).
    setState((prev) => ({
      ...(prev || {}),
      pending_tos: r?.pending_tos || [],
    }));
    setError("");
  }, [nextDoc]);

  const handleErr = useCallback((e) => {
    const detail = e?.detail || e?.data?.detail;
    if (detail === "document_not_published") {
      setError("This version is no longer active. Reloading…");
      // Refresh state so the (potentially superseded) doc is
      // replaced with the current published version.
      setTimeout(() => load(), 400);
    } else if (detail === "document_not_found") {
      setError("Document could not be located. Please refresh.");
    } else {
      setError(detail || e?.message || "Could not save acceptance.");
    }
  }, [load]);

  if (!isCustomer) {
    return <>{children}</>;
  }
  // While the initial fetch is in flight, don't render the child
  // routes yet — they may be tenant-scoped and we want to avoid a
  // brief flash of the underlying page.
  if (loading && state === null) {
    return (
      <div
        className="fixed inset-0 z-[85] flex items-center justify-center"
        style={{ backgroundColor: "rgba(15,23,42,0.4)" }}
        data-testid="onboarding-gate-loading"
      >
        <div
          className="rounded-md px-4 py-2 text-sm"
          style={{
            backgroundColor: colors.surface,
            color: colors.onSurface,
          }}
        >
          Checking account…
        </div>
      </div>
    );
  }

  const needsTutorial = _STUB_NEEDS_TUTORIAL && !state?.tutorial_completed;

  if (needsTutorial) {
    // Placeholder — the tutorial persistence endpoint doesn't
    // exist yet (see jsdoc). When it lands, wire ``PortalWalkthrough``
    // here and POST /customer-portal/tutorial/complete on its onClose.
    return <>{children}</>;
  }

  if (!nextDoc) {
    return <>{children}</>;
  }

  return (
    <>
      {children}
      <TosBlockingModal
        doc={nextDoc}
        onAccept={onAccept}
        onError={handleErr}
        error={error}
      />
    </>
  );
}
