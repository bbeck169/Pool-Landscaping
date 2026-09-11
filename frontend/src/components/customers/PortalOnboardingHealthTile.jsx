/**
 * Feb-2026 · Portal onboarding health tile.
 *
 * Compact 4-card admin snapshot of the customer portal funnel:
 *   invited → activated → signed_in  (+ the "never" cohort the
 *   ops team chases). Reads
 *   ``GET /api/reports/portal-onboarding-health`` (60s cache on
 *   the server, admin-gated).
 *
 * Placement: rendered on the customers-list header (admin-only)
 * so the tile is contextual to the workflow it drives — the
 * "Never logged in" card deep-links to the existing chip
 * (``/customers?first_access=never``) that scopes the list to
 * the same cohort.
 *
 * Feb-2026 · Chase Stalled Invites ship — the Never card now also
 * carries an inline "Chase" CTA (``onboarding-tile-never-chase-cta``)
 * that opens ``ChaseStalledInvitesModal`` for a one-click batch
 * re-invite of the top-N stalest never-logged-in customers.
 *
 * Test-ids:
 *   * ``onboarding-health-tile``
 *   * ``onboarding-cohort-invited``
 *   * ``onboarding-cohort-activated``
 *   * ``onboarding-cohort-signed-in``
 *   * ``onboarding-cohort-never``
 *   * ``onboarding-cohort-*-delta``  (per-card delta arrow)
 *   * ``onboarding-tile-never-cta``      (never-card click target — deep-link)
 *   * ``onboarding-tile-never-chase-cta`` (Chase button — opens modal)
 */
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { api } from "@/api";
import { colors } from "@/theme";
import ChaseStalledInvitesModal from "@/components/customers/ChaseStalledInvitesModal";


const COHORT_ORDER = [
  { key: "invited",         label: "Invited",         testid: "onboarding-cohort-invited" },
  { key: "activated",       label: "Activated",       testid: "onboarding-cohort-activated" },
  { key: "signed_in",       label: "Signed in",       testid: "onboarding-cohort-signed-in" },
  { key: "never_logged_in", label: "Never logged in", testid: "onboarding-cohort-never" },
];


function DeltaArrow({ delta, testid }) {
  const muted = colors.muted;
  // ``null`` is a documented state (see backend assumptions) —
  // render a dimmed dash so ops sees the "no delta available"
  // signal instead of a scary empty space.
  if (delta === null || delta === undefined) {
    return (
      <span
        data-testid={testid}
        className="text-xs"
        style={{ color: muted, fontWeight: 500 }}
      >
        — vs last 30d
      </span>
    );
  }
  const isUp = delta > 0;
  const isFlat = delta === 0;
  const arrow = isFlat ? "→" : (isUp ? "↑" : "↓");
  const color = isFlat ? muted : (isUp ? "#059669" : "#DC2626");
  return (
    <span
      data-testid={testid}
      className="text-xs inline-flex items-center gap-1"
      style={{ color, fontWeight: 600 }}
    >
      <span aria-hidden="true">{arrow}</span>
      <span>{Math.abs(delta).toLocaleString()} vs last 30d</span>
    </span>
  );
}


function CohortCard({ label, testid, count, delta, ctaHref, ctaTestid }) {
  const navigate = useNavigate();
  const clickable = Boolean(ctaHref);
  const body = (
    <div
      data-testid={testid}
      className="rounded-lg p-4 flex-1 min-w-0"
      style={{
        backgroundColor: colors.surface,
        border: `1px solid ${colors.border}`,
        cursor: clickable ? "pointer" : "default",
        transition: "background-color 120ms ease-out, border-color 120ms ease-out",
      }}
      onClick={clickable ? () => navigate(ctaHref) : undefined}
      onKeyDown={
        clickable
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                navigate(ctaHref);
              }
            }
          : undefined
      }
      role={clickable ? "button" : undefined}
      tabIndex={clickable ? 0 : undefined}
      aria-label={clickable ? `View ${label} customers` : undefined}
      {...(clickable ? { "data-cta-testid": ctaTestid } : {})}
    >
      <div
        className="text-[11px] font-semibold uppercase tracking-wide"
        style={{ color: colors.muted }}
      >
        {label}
      </div>
      <div
        className="text-3xl font-bold my-1 tabular-nums"
        style={{ color: colors.onSurface }}
      >
        {typeof count === "number" ? count.toLocaleString() : "—"}
      </div>
      <DeltaArrow
        delta={delta}
        testid={`${testid}-delta`}
      />
    </div>
  );
  // The Never card also renders the CTA testid on an inner span
  // so tests can drive the click without depending on the outer
  // div's role attribute (some testing harnesses skip role=button
  // on non-<button> nodes).
  if (clickable) {
    return (
      <div style={{ display: "contents" }}>
        {body}
        <span
          data-testid={ctaTestid}
          style={{ display: "none" }}
          onClick={() => navigate(ctaHref)}
        />
      </div>
    );
  }
  return body;
}


function TileSkeleton() {
  return (
    <div
      data-testid="onboarding-health-tile-skeleton"
      className="rounded-xl p-3 flex flex-col sm:flex-row gap-2"
      style={{
        backgroundColor: colors.surface,
        border: `1px dashed ${colors.border}`,
      }}
    >
      {COHORT_ORDER.map((c) => (
        <div
          key={c.key}
          className="rounded-lg p-4 flex-1 animate-pulse"
          style={{
            backgroundColor: colors.background,
            border: `1px solid ${colors.border}`,
            minHeight: 88,
          }}
        />
      ))}
    </div>
  );
}


export default function PortalOnboardingHealthTile() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [chaseOpen, setChaseOpen] = useState(false);
  // Feb-2026 · Chase Stalled Invites — bump on send so the tile
  // refetches its cohort counts after the batch resolves. The
  // server has a 60s cache so consecutive bumps within the window
  // return the same numbers, which is intentional.
  const [refetchTick, setRefetchTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    (async () => {
      try {
        const r = await api.get(
          "/reports/portal-onboarding-health?window_days=30",
        );
        if (!cancelled) {
          setData(r);
          setLoading(false);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e);
          setLoading(false);
          toast.error("Could not load portal onboarding health");
        }
      }
    })();
    return () => { cancelled = true; };
  }, [refetchTick]);

  if (loading) {
    return <TileSkeleton />;
  }
  if (error || !data || !data.cohorts) {
    return null;
  }

  const neverCount = (data.cohorts?.never_logged_in?.count) || 0;

  return (
    <>
      <div
        data-testid="onboarding-health-tile"
        className="rounded-xl p-3 mb-3 flex flex-col sm:flex-row gap-2"
        style={{
          backgroundColor: colors.background,
          border: `1px solid ${colors.border}`,
        }}
      >
        {COHORT_ORDER.map((c) => {
          const block = data.cohorts[c.key] || {};
          const isNever = c.key === "never_logged_in";
          return (
            <div
              key={c.key}
              className="flex-1 min-w-0 flex flex-col gap-2"
            >
              <CohortCard
                label={c.label}
                testid={c.testid}
                count={block.count}
                delta={block.delta_30d}
                ctaHref={isNever ? "/customers?first_access=never" : null}
                ctaTestid={isNever ? "onboarding-tile-never-cta" : null}
              />
              {isNever ? (
                <button
                  type="button"
                  onClick={() => setChaseOpen(true)}
                  disabled={neverCount === 0}
                  data-testid="onboarding-tile-never-chase-cta"
                  className="inline-flex items-center justify-center rounded-md px-3 py-1.5 text-xs font-semibold hover:brightness-95 disabled:opacity-40 disabled:cursor-not-allowed"
                  style={{
                    backgroundColor: colors.brand,
                    color: "#fff",
                  }}
                  aria-label="Chase stalled portal invites"
                  title={
                    neverCount === 0
                      ? "No stalled invites to chase"
                      : `Chase up to ${neverCount} stalled invite${neverCount === 1 ? "" : "s"}`
                  }
                >
                  Chase
                </button>
              ) : null}
            </div>
          );
        })}
      </div>
      <ChaseStalledInvitesModal
        open={chaseOpen}
        onClose={() => setChaseOpen(false)}
        onSent={() => setRefetchTick((t) => t + 1)}
      />
    </>
  );
}
