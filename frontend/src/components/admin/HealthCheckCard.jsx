/**
 * Phase I3 · Feb-2026 — Health Check modal.
 *
 * Wraps the ``GET /admin/health-check/comprehensive`` endpoint with a
 * one-click modal that surfaces the per-check verdict, the aggregate
 * GO / GO_WITH_WARNINGS / NO_GO banner, and a "Copy JSON" button so
 * ops can paste the payload into a support ticket without reaching
 * for the browser devtools.
 *
 * Rendered on the ``/admin/migrations`` page next to the existing
 * data-integrity tile. super_admin only — the backend endpoint
 * enforces the RBAC gate independently.
 */
import React, { useState } from "react";
import { api } from "@/api";
import { colors } from "../../theme";

const VERDICT_STYLES = {
  GO: {
    bg: "#DCFCE7",
    fg: "#166534",
    border: "#86EFAC",
    label: "GO — deploy is healthy",
  },
  GO_WITH_WARNINGS: {
    bg: "#FEF3C7",
    fg: "#92400E",
    border: "#FDE68A",
    label: "GO WITH WARNINGS — proceed but review",
  },
  NO_GO: {
    bg: "#FEE2E2",
    fg: "#991B1B",
    border: "#FCA5A5",
    label: "NO-GO — deploy has blocking issues",
  },
};


function StatusPill({ status, testid }) {
  const map = {
    ok: { bg: "#DCFCE7", fg: "#166534" },
    warn: { bg: "#FEF3C7", fg: "#92400E" },
    fail: { bg: "#FEE2E2", fg: "#991B1B" },
  };
  const s = map[status] || { bg: "#F1F5F9", fg: "#475569" };
  return (
    <span
      className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full"
      style={{ background: s.bg, color: s.fg }}
      data-testid={testid}
    >
      {status}
    </span>
  );
}


export default function HealthCheckCard() {
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const [payload, setPayload] = useState(null);
  const [error, setError] = useState("");
  const [copyOk, setCopyOk] = useState(false);

  const run = async () => {
    setBusy(true);
    setError("");
    try {
      const r = await api.get("/admin/health-check/comprehensive");
      setPayload(r);
      setOpen(true);
    } catch (e) {
      setError(e?.message || "Health check failed");
      setOpen(true);
    } finally {
      setBusy(false);
    }
  };

  const copyJson = async () => {
    if (!payload) return;
    const text = JSON.stringify(payload, null, 2);
    try {
      if (navigator?.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        // Fallback for browsers without the async clipboard API.
        const ta = document.createElement("textarea");
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
      }
      setCopyOk(true);
      setTimeout(() => setCopyOk(false), 2000);
    } catch { /* clipboard blocked — silent, user can reopen the modal */ }
  };

  const verdict = payload?.overall_verdict;
  const style = verdict ? VERDICT_STYLES[verdict] : null;

  return (
    <>
      <div
        className="rounded-2xl p-5 mb-4"
        style={{
          background: colors.surface,
          border: `1px solid ${colors.border}`,
        }}
        data-testid="admin-health-check-card"
      >
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2
              className="text-lg font-bold"
              style={{ color: colors.onSurface }}
            >
              Post-Deploy Health Check
            </h2>
            <p className="text-sm mt-1" style={{ color: colors.muted }}>
              Runs ten deep checks against boot state, Mongo, migrations,
              hot paths, comms gate, RC SMS, scheduler, env sanity, and
              feature gates. Returns a GO / GO_WITH_WARNINGS / NO_GO
              verdict for the deploying operator.
            </p>
          </div>
          <button
            type="button"
            onClick={run}
            disabled={busy}
            className="rounded-lg px-4 py-2 text-sm font-semibold shrink-0"
            style={{
              background: busy ? colors.surfaceSecondary : colors.brand,
              color: busy ? colors.muted : "#fff",
              opacity: busy ? 0.7 : 1,
              cursor: busy ? "not-allowed" : "pointer",
            }}
            data-testid="admin-health-check-btn"
          >
            {busy ? "Running…" : "Run Health Check"}
          </button>
        </div>
      </div>

      {open ? (
        <div
          className="fixed inset-0 z-50 flex items-start justify-center px-4 py-8 overflow-y-auto"
          style={{ background: "rgba(0,0,0,0.5)" }}
          onClick={() => setOpen(false)}
          data-testid="admin-health-check-modal"
        >
          <div
            className="w-full max-w-3xl rounded-2xl overflow-hidden shadow-2xl"
            style={{ background: colors.surface }}
            onClick={(e) => e.stopPropagation()}
          >
            <header
              className="px-5 py-3 flex items-center justify-between"
              style={{ borderBottom: `1px solid ${colors.border}` }}
            >
              <div
                className="text-base font-bold"
                style={{ color: colors.onSurface }}
              >
                Deploy Health Check
              </div>
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="text-xl leading-none px-1"
                style={{ color: colors.muted }}
                data-testid="admin-health-check-close"
              >
                ×
              </button>
            </header>

            <div className="px-5 py-4 max-h-[75vh] overflow-y-auto">
              {error ? (
                <div
                  className="p-3 rounded-lg text-sm"
                  style={{ background: "#FEE2E2", color: "#991B1B" }}
                  data-testid="admin-health-check-error"
                >
                  {error}
                </div>
              ) : null}

              {payload && style ? (
                <>
                  <div
                    className="rounded-xl p-4 mb-4"
                    style={{
                      background: style.bg,
                      color: style.fg,
                      border: `2px solid ${style.border}`,
                    }}
                    data-testid={`admin-health-check-verdict-${verdict.toLowerCase()}`}
                  >
                    <div className="text-xs font-bold uppercase tracking-wider mb-1">
                      Verdict
                    </div>
                    <div
                      className="text-lg font-bold"
                      data-testid="admin-health-check-verdict-label"
                    >
                      {style.label}
                    </div>
                    <div className="text-xs mt-2 font-mono">
                      tenant={payload.tenant_id} · v={payload.app_version}{" "}
                      · {payload.summary.checks_total} checks · {" "}
                      <span data-testid="admin-health-check-summary-ok">
                        {payload.summary.ok} ok
                      </span>
                      {" · "}
                      <span data-testid="admin-health-check-summary-warn">
                        {payload.summary.warn} warn
                      </span>
                      {" · "}
                      <span data-testid="admin-health-check-summary-fail">
                        {payload.summary.fail} fail
                      </span>
                    </div>
                  </div>

                  <div className="mb-4" data-testid="admin-health-check-rows">
                    {(payload.checks || []).map((c) => (
                      <div
                        key={c.name}
                        className="flex items-start gap-3 py-2"
                        style={{ borderTop: `1px solid ${colors.border}` }}
                        data-testid={`admin-health-check-row-${c.name}`}
                      >
                        <div style={{ minWidth: 84 }}>
                          <StatusPill
                            status={c.status}
                            testid={`admin-health-check-status-${c.name}`}
                          />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div
                            className="text-sm font-semibold"
                            style={{ color: colors.onSurface }}
                          >
                            {c.name}
                            <span
                              className="ml-2 text-[10px] font-normal"
                              style={{ color: colors.muted }}
                            >
                              {c.duration_ms}ms
                            </span>
                          </div>
                          <div
                            className="text-xs font-mono mt-0.5 break-all"
                            style={{ color: colors.muted }}
                          >
                            {JSON.stringify(c.details)}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>

                  {(payload.recommendations || []).length ? (
                    <div
                      className="rounded-lg p-3 mb-4"
                      style={{ background: colors.surfaceSecondary }}
                      data-testid="admin-health-check-recommendations"
                    >
                      <div
                        className="text-[10px] font-bold uppercase tracking-wider mb-2"
                        style={{ color: colors.muted }}
                      >
                        Recommendations ({payload.recommendations.length})
                      </div>
                      <ul
                        className="list-disc pl-4 text-xs space-y-1"
                        style={{ color: colors.onSurface }}
                      >
                        {payload.recommendations.map((r, i) => (
                          <li
                            key={i}
                            data-testid={`admin-health-check-recommendation-${i}`}
                          >
                            {r}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                </>
              ) : null}
            </div>

            <footer
              className="px-5 py-3 flex justify-between items-center"
              style={{
                borderTop: `1px solid ${colors.border}`,
                background: colors.surfaceSecondary,
              }}
            >
              <span
                className="text-xs"
                style={{ color: colors.muted }}
              >
                {payload?.timestamp || ""}
              </span>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={copyJson}
                  disabled={!payload}
                  className="text-sm font-semibold px-3 py-1.5 rounded-lg"
                  style={{
                    background: colors.brandTertiary,
                    color: colors.brand,
                    border: `1px solid ${colors.brand}`,
                    opacity: payload ? 1 : 0.4,
                    cursor: payload ? "pointer" : "not-allowed",
                  }}
                  data-testid="admin-health-check-copy-json"
                >
                  {copyOk ? "Copied ✓" : "Copy JSON"}
                </button>
                <button
                  type="button"
                  onClick={() => setOpen(false)}
                  className="text-sm font-semibold px-3 py-1.5 rounded-lg"
                  style={{
                    background: colors.brand,
                    color: "#fff",
                  }}
                  data-testid="admin-health-check-done"
                >
                  Done
                </button>
              </div>
            </footer>
          </div>
        </div>
      ) : null}
    </>
  );
}
