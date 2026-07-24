import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import { Shield, Check, AlertTriangle } from "lucide-react";
import { api } from "@/api";
import { useAuth } from "@/auth";
import { colors, brandGradientCss } from "@/theme";

/**
 * Feb-2026 · BUG E — global Terms of Service gate.
 *
 * Renders NOTHING unless the server-authoritative ``user.must_accept_tos``
 * flag is true. When it renders, the modal blocks the entire viewport
 * (fixed inset-0 · z-[80]) — no ESC-close, no backdrop click-through,
 * no route escape. The gate is dismissed only by a successful
 * ``POST /users/me/accept-tos`` round-trip.
 *
 * Successful acceptance:
 *   1. PATCH the auth-context user in place so the modal unmounts
 *      immediately (no reload required).
 *   2. Persist the updated user to localStorage so refreshes preserve
 *      the acceptance without another /auth/me hit.
 *   3. Route the user to their role-appropriate landing page.
 *
 * Failure handling: on any non-2xx the button re-enables and an inline
 * error banner is shown with the server's ``detail`` (409 → force
 * reload button; everything else → keep the button clickable).
 */
export default function TosGate() {
  const { user, setUser } = useAuth();
  const navigate = useNavigate();
  const [doc, setDoc] = useState(null);
  const [docErr, setDocErr] = useState("");
  const [checked, setChecked] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [versionMismatch, setVersionMismatch] = useState(false);

  const gated = !!(user && user.must_accept_tos);

  useEffect(() => {
    if (!gated) return;
    let alive = true;
    api
      .get("/legal/tos")
      .then((d) => { if (alive) setDoc(d); })
      .catch((e) => { if (alive) setDocErr(e?.message || "Failed to load Terms of Service"); });
    return () => { alive = false; };
  }, [gated]);

  if (!gated) return null;

  const landingForRole = (role) => {
    if (role === "customer") return "/portal/home";
    if (role === "technician") return "/schedule";
    return "/"; // admin, manager, other → admin dashboard root
  };

  const onAgree = async () => {
    if (!doc?.version) {
      setError("Terms have not finished loading yet — please wait a moment.");
      return;
    }
    setSaving(true);
    setError("");
    setVersionMismatch(false);
    try {
      const res = await api.post("/users/me/accept-tos", { version: doc.version });
      // Optimistic + authoritative state update.
      const nextUser = {
        ...user,
        must_accept_tos: !!res.must_accept_tos,
        tos_version_accepted: res.tos_version_accepted,
        tos_accepted_at: res.tos_accepted_at,
      };
      setUser(nextUser);
      try {
        localStorage.setItem("user", JSON.stringify(nextUser));
      } catch { /* ignore quota errors */ }
      // Route to role-appropriate landing so the user lands somewhere
      // that makes sense post-acceptance.
      navigate(landingForRole(user.role), { replace: true });
    } catch (e) {
      const msg = e?.message || "Failed to record acceptance. Please try again.";
      if (String(msg).toLowerCase().includes("version mismatch") ||
          e?.status === 409) {
        setVersionMismatch(true);
        setError("The Terms of Service have been updated since you loaded this page.");
      } else {
        setError(msg);
      }
    } finally {
      setSaving(false);
    }
  };

  const onReload = () => {
    try { window.location.reload(); } catch { /* noop */ }
  };

  return (
    <div
      className="fixed inset-0 z-[80] flex items-center justify-center p-0 sm:p-4"
      style={{ background: "rgba(15,23,42,0.72)" }}
      role="dialog"
      aria-modal="true"
      aria-labelledby="tos-gate-title"
      data-testid="tos-gate-modal"
    >
      <div
        className="w-full sm:max-w-2xl h-full sm:h-auto sm:max-h-[92vh] rounded-none sm:rounded-2xl shadow-2xl flex flex-col overflow-hidden"
        style={{
          backgroundColor: colors.surface,
          border: `1px solid ${colors.border}`,
        }}
        onMouseDown={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div
          className="px-5 py-4 flex items-center gap-3"
          style={{
            borderBottom: `1px solid ${colors.border}`,
            background: brandGradientCss,
            color: "#fff",
          }}
        >
          <div
            className="w-10 h-10 rounded-xl flex items-center justify-center shrink-0"
            style={{ backgroundColor: "rgba(255,255,255,0.18)" }}
            aria-hidden="true"
          >
            <Shield size={20} />
          </div>
          <div className="min-w-0">
            <h2
              id="tos-gate-title"
              className="text-lg font-bold leading-tight"
              data-testid="tos-gate-title"
            >
              Please review our Terms of Service
            </h2>
            <p className="text-xs opacity-90 mt-0.5">
              A quick read and acknowledgement is required to continue.
            </p>
          </div>
        </div>

        {/* Body */}
        <div
          className="flex-1 overflow-y-auto px-5 py-4 prose prose-sm max-w-none"
          style={{ color: colors.onSurface, lineHeight: 1.65 }}
          data-testid="tos-gate-body"
        >
          {docErr ? (
            <div
              className="rounded-xl p-4"
              style={{
                backgroundColor: "#FEE2E2",
                color: "#991B1B",
                border: "1px solid #FCA5A5",
              }}
              data-testid="tos-gate-load-error"
            >
              <strong>Could not load Terms of Service.</strong>
              <div className="text-sm mt-1">{docErr}</div>
              <button
                onClick={onReload}
                className="mt-3 px-3 py-1.5 rounded-lg text-xs font-bold"
                style={{ backgroundColor: "#991B1B", color: "#fff" }}
                data-testid="tos-gate-reload-error"
              >
                Reload
              </button>
            </div>
          ) : !doc ? (
            <div
              className="h-40 rounded-xl animate-pulse"
              style={{ backgroundColor: colors.surfaceTertiary }}
              data-testid="tos-gate-loading"
            />
          ) : (
            <>
              <div
                className="text-xs mb-3"
                style={{ color: colors.muted }}
                data-testid="tos-gate-version"
              >
                Version <b style={{ color: colors.onSurface }}>{doc.version}</b>
                {doc.effective_date ? (
                  <> · Effective <b style={{ color: colors.onSurface }}>{doc.effective_date}</b></>
                ) : null}
              </div>
              <TosMarkdown source={doc.markdown || ""} />
            </>
          )}
        </div>

        {/* Footer */}
        <div
          className="px-5 py-4 flex flex-col gap-3"
          style={{
            borderTop: `1px solid ${colors.border}`,
            backgroundColor: colors.surfaceSecondary,
          }}
        >
          {error ? (
            <div
              className="text-sm flex items-start gap-2 rounded-lg px-3 py-2"
              style={{
                backgroundColor: "#FEF3C7",
                color: "#92400E",
                border: "1px solid #FDE68A",
              }}
              data-testid="tos-gate-error"
            >
              <AlertTriangle size={16} className="shrink-0 mt-0.5" />
              <div className="flex-1">
                <div className="font-semibold">{error}</div>
                {versionMismatch ? (
                  <button
                    onClick={onReload}
                    className="mt-1 px-3 py-1 rounded-md text-xs font-bold"
                    style={{ backgroundColor: "#92400E", color: "#fff" }}
                    data-testid="tos-gate-reload"
                  >
                    Reload
                  </button>
                ) : null}
              </div>
            </div>
          ) : null}

          <label
            className="flex items-start gap-2 cursor-pointer select-none"
            data-testid="tos-gate-checkbox-label"
          >
            <input
              type="checkbox"
              checked={checked}
              onChange={(e) => setChecked(e.target.checked)}
              className="mt-0.5 w-4 h-4"
              style={{ accentColor: colors.brand }}
              disabled={!doc || !!docErr}
              data-testid="tos-gate-checkbox"
            />
            <span className="text-sm" style={{ color: colors.onSurface }}>
              I have read and agree to the Terms of Service.
            </span>
          </label>

          <div className="flex items-center justify-end">
            <button
              type="button"
              onClick={onAgree}
              disabled={!checked || saving || !doc || !!docErr}
              className="inline-flex items-center gap-1.5 px-5 py-2.5 rounded-xl text-sm font-bold text-white disabled:opacity-50 disabled:cursor-not-allowed"
              style={{ background: brandGradientCss }}
              data-testid="tos-gate-agree-btn"
            >
              <Check size={15} />
              {saving ? "Recording…" : "I Agree"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function TosMarkdown({ source }) {
  return (
    <ReactMarkdown
      components={{
        h2: ({ node, ...p }) => (
          <h2 className="text-xl font-bold mt-4 mb-2" style={{ color: colors.onSurface }} {...p} />
        ),
        h3: ({ node, ...p }) => (
          <h3 className="text-base font-bold mt-4 mb-2" style={{ color: colors.onSurface }} {...p} />
        ),
        p: ({ node, ...p }) => (
          <p className="text-sm mb-2" style={{ color: colors.onSurface }} {...p} />
        ),
        ul: ({ node, ...p }) => (
          <ul className="list-disc pl-6 mb-2 space-y-1" style={{ color: colors.onSurface }} {...p} />
        ),
        li: ({ node, ...p }) => (
          <li className="text-sm" {...p} />
        ),
        strong: ({ node, ...p }) => (
          <strong className="font-bold" style={{ color: colors.onSurface }} {...p} />
        ),
        hr: () => <hr className="my-4" style={{ borderColor: colors.border }} />,
      }}
    >
      {source}
    </ReactMarkdown>
  );
}
