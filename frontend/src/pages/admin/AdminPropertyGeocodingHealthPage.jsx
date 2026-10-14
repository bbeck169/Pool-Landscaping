import React from "react";
import { api } from "@/api";
import { colors } from "@/theme";
import { AlertTriangle, MapPin, PlayCircle, RefreshCw, Zap } from "lucide-react";
import SafeScrollContainer from "@/components/layout/SafeScrollContainer";

/**
 * Phase A.5 · Feb-2026 — Property Geocoding Health admin page.
 *
 * Diagnostic view for the property-geocoding health of the current
 * tenant. Shows:
 *   - 4 counts: total / with_valid_coords / null_coords / zero_coords.
 *   - Top duplicate-coord clusters (operators triage the bulk-geocode
 *     bug where hundreds of properties landed on a shared centroid).
 *   - A "Run Backfill (Dry Run)" preview + "Confirm Backfill" live-run
 *     against ``POST /admin/properties/geocode-backfill``.
 *
 * Admin / super_admin gated server-side.
 */
export default function AdminPropertyGeocodingHealthPage() {
  const [diag, setDiag] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState(null);

  // Backfill state
  const [dryResult, setDryResult] = React.useState(null);
  const [dryBusy, setDryBusy] = React.useState(false);
  const [liveResult, setLiveResult] = React.useState(null);
  const [liveBusy, setLiveBusy] = React.useState(false);
  const [opError, setOpError] = React.useState(null);

  const loadDiag = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await api.get("/admin/diagnostics/property-geocoding");
      setDiag(r);
    } catch (e) {
      setError(e?.message || "Failed to load diagnostics");
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => { loadDiag(); }, [loadDiag]);

  const runDryRun = React.useCallback(async () => {
    setDryBusy(true);
    setOpError(null);
    try {
      const r = await api.post(
        "/admin/properties/geocode-backfill",
        { dry_run: true, max_rows: 500 },
      );
      setDryResult(r);
      setLiveResult(null);
    } catch (e) {
      setOpError(e?.message || "Dry run failed");
    } finally {
      setDryBusy(false);
    }
  }, []);

  const runLive = React.useCallback(async () => {
    if (!dryResult || dryResult.candidates === 0) return;
    setLiveBusy(true);
    setOpError(null);
    try {
      const r = await api.post(
        "/admin/properties/geocode-backfill",
        { dry_run: false, max_rows: 500 },
      );
      setLiveResult(r);
      // Refresh counts after a live run.
      loadDiag();
    } catch (e) {
      setOpError(e?.message || "Backfill failed");
    } finally {
      setLiveBusy(false);
    }
  }, [dryResult, loadDiag]);

  const counts = diag || {
    total_properties: 0, with_valid_coords: 0,
    null_coords: 0, zero_coords: 0,
    duplicate_coord_clusters: [],
  };

  return (
    <SafeScrollContainer
      className="px-4 md:px-8 pt-6 space-y-5 pb-10"
      data-testid="admin-property-geocoding-page"
    >
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1
            className="text-2xl font-semibold inline-flex items-center gap-2"
            style={{ color: colors.onSurface }}
            data-testid="admin-property-geocoding-title"
          >
            <MapPin size={22} /> Property geocoding health
          </h1>
          <p className="text-sm mt-1" style={{ color: colors.muted }}>
            Per-tenant property coordinate audit. Identifies missing
            geocodes and duplicate-coord clusters (hundreds of
            properties pinned to the same spot).
          </p>
        </div>
        <button
          type="button"
          onClick={loadDiag}
          className="inline-flex items-center gap-2 h-9 px-3 rounded-lg text-sm font-semibold"
          style={{
            backgroundColor: colors.surface,
            color: colors.onSurface,
            border: `1px solid ${colors.border}`,
          }}
          data-testid="admin-property-geocoding-refresh"
        >
          <RefreshCw size={14} /> Refresh
        </button>
      </div>

      {error ? (
        <div
          className="p-3 rounded-lg inline-flex items-center gap-2 text-sm"
          style={{ backgroundColor: "#FEF2F2", color: "#B91C1C",
                   border: "1px solid #FCA5A5" }}
          data-testid="admin-property-geocoding-error"
        >
          <AlertTriangle size={14} /> {error}
        </div>
      ) : null}

      {/* Count tiles */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          { k: "total_properties", label: "Total properties",
            tint: colors.surface, color: colors.onSurface,
            testid: "pg-count-total" },
          { k: "with_valid_coords", label: "With valid coords",
            tint: "#ECFDF5", color: "#047857",
            testid: "pg-count-valid" },
          { k: "null_coords", label: "Null coords",
            tint: "#FEF3C7", color: "#92400E",
            testid: "pg-count-null" },
          { k: "zero_coords", label: "Zero coords",
            tint: "#FEE2E2", color: "#B91C1C",
            testid: "pg-count-zero" },
        ].map((t) => (
          <div
            key={t.k}
            className="rounded-xl p-4"
            style={{ backgroundColor: t.tint,
                     border: `1px solid ${colors.border}` }}
            data-testid={t.testid}
          >
            <div className="text-xs font-semibold uppercase tracking-wide"
                 style={{ color: colors.muted }}>
              {t.label}
            </div>
            <div className="text-3xl font-bold mt-1 tabular-nums"
                 style={{ color: t.color }}>
              {loading ? "…" : (counts[t.k] ?? 0).toLocaleString()}
            </div>
          </div>
        ))}
      </div>

      {/* Duplicate clusters */}
      <div
        className="rounded-xl p-4"
        style={{ backgroundColor: colors.surface,
                 border: `1px solid ${colors.border}` }}
        data-testid="pg-duplicate-clusters"
      >
        <div className="text-sm font-semibold mb-3"
             style={{ color: colors.onSurface }}>
          Duplicate coord clusters (top {counts.duplicate_coord_clusters?.length || 0})
        </div>
        {loading ? (
          <div className="text-sm" style={{ color: colors.muted }}>Loading…</div>
        ) : (counts.duplicate_coord_clusters || []).length === 0 ? (
          <div className="text-sm" style={{ color: colors.muted }}
               data-testid="pg-no-clusters">
            No duplicate clusters detected.
          </div>
        ) : (
          <ul className="divide-y" style={{ borderColor: colors.border }}>
            {counts.duplicate_coord_clusters.slice(0, 5).map((c, i) => (
              <li key={i} className="py-2 flex items-center justify-between gap-3"
                  data-testid={`pg-cluster-${i}`}>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-mono"
                       style={{ color: colors.onSurface }}>
                    ({c.lat}, {c.lng})
                  </div>
                  <div className="text-xs truncate"
                       style={{ color: colors.muted }}>
                    {(c.property_labels || []).slice(0, 3)
                      .filter(Boolean).join(", ") || "—"}
                  </div>
                </div>
                <div className="shrink-0 text-xs font-semibold tabular-nums"
                     style={{ color: "#B91C1C" }}>
                  {c.property_count} properties
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Backfill controls */}
      <div
        className="rounded-xl p-4 space-y-3"
        style={{ backgroundColor: colors.surface,
                 border: `1px solid ${colors.border}` }}
        data-testid="pg-backfill-panel"
      >
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div>
            <div className="text-sm font-semibold"
                 style={{ color: colors.onSurface }}>
              Geocode backfill
            </div>
            <div className="text-xs mt-1" style={{ color: colors.muted }}>
              Re-geocode properties missing coords via Google Maps.
              Dry-run previews candidates without writing. Capped at
              500 rows per invocation.
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={runDryRun}
              disabled={dryBusy || liveBusy}
              className="inline-flex items-center gap-2 h-9 px-3 rounded-lg text-sm font-semibold disabled:opacity-50"
              style={{
                backgroundColor: colors.surface,
                color: colors.onSurface,
                border: `1px solid ${colors.border}`,
              }}
              data-testid="pg-dry-run-btn"
            >
              <PlayCircle size={14} />
              {dryBusy ? "Running…" : "Run backfill (dry run)"}
            </button>
            <button
              type="button"
              onClick={runLive}
              disabled={!dryResult || dryResult.candidates === 0 || liveBusy || dryBusy}
              className="inline-flex items-center gap-2 h-9 px-3 rounded-lg text-sm font-semibold disabled:opacity-50 disabled:cursor-not-allowed"
              style={{
                backgroundColor: dryResult && dryResult.candidates > 0
                  ? "#1E40AF" : colors.border,
                color: "#fff",
              }}
              data-testid="pg-confirm-backfill-btn"
            >
              <Zap size={14} />
              {liveBusy ? "Backfilling…" : "Confirm backfill"}
            </button>
          </div>
        </div>

        {opError ? (
          <div
            className="p-2 rounded-lg inline-flex items-center gap-2 text-sm"
            style={{ backgroundColor: "#FEF2F2", color: "#B91C1C",
                     border: "1px solid #FCA5A5" }}
            data-testid="pg-op-error"
          >
            <AlertTriangle size={14} /> {opError}
          </div>
        ) : null}

        {dryResult ? (
          <div
            className="rounded-lg p-3 text-sm"
            style={{ backgroundColor: "#F8FAFC",
                     border: `1px solid ${colors.border}` }}
            data-testid="pg-dry-run-result"
          >
            <div style={{ color: colors.onSurface }}>
              <strong>{dryResult.candidates.toLocaleString()}</strong>
              {" "}properties would be re-geocoded.
            </div>
            {dryResult.sample_updates?.length ? (
              <ul className="mt-2 space-y-1">
                {dryResult.sample_updates.slice(0, 10).map((s) => (
                  <li key={s.property_id} className="text-xs"
                      style={{ color: colors.muted }}>
                    • {s.label || "(no label)"} — {s.address || "(no address)"}
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : null}

        {liveResult ? (
          <div
            className="rounded-lg p-3 text-sm"
            style={{ backgroundColor: "#ECFDF5",
                     border: "1px solid #86EFAC" }}
            data-testid="pg-live-result"
          >
            <div style={{ color: "#047857", fontWeight: 600 }}>
              Backfill complete
            </div>
            <div style={{ color: "#047857" }}>
              Processed <strong>{liveResult.processed}</strong>,
              updated <strong>{liveResult.updated}</strong>,
              failed <strong>{liveResult.failed}</strong>
              {liveResult.candidates > liveResult.processed ? (
                <span>{" "}· {liveResult.candidates - liveResult.processed} candidates remaining — re-run to continue.</span>
              ) : null}
            </div>
          </div>
        ) : null}
      </div>
    </SafeScrollContainer>
  );
}
