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
 * so the tile is contextual to the workflow it drives — each
 * cohort card deep-links to the customers list filtered to just
 * that cohort using the same predicate the tile counts against
 * (chip / list / tile stay numerically consistent).
 *
 * Feb-2026 · Onboarding-tile clickable + Chase-move ship
 *   * All 4 cards are now clickable (Enter/Space + click). Deep-
 *     link map:
 *
 *       Card             → URL
 *       Invited          → /customers?portal_invited=any
 *       Activated        → /customers?portal_activated=1
 *       Signed in        → /customers?first_access=any
 *       Never logged in  → /customers?first_access=never   (preserved)
 *
 *   * The "Chase" button lives under the INVITED card now
 *     (previously under Never). Semantically the chase audience
 *     is invited-but-never-signed-in, so the affordance surfaces
 *     next to the invite concept. Button test-id renamed:
 *
 *         onboarding-tile-never-chase-cta  →
 *         onboarding-tile-invited-chase-cta
 *
 *     The old test-id has been retired — see the migration memo
 *     ``FEATURE_ONBOARDING_TILE_CLICKABLE_AND_CHASE_MOVE.md``.
 *
 * Test-ids:
 *   * ``onboarding-health-tile``
 *   * ``onboarding-cohort-invited`` / ``-activated`` /
 *     ``-signed-in`` / ``-never``  (per-card blocks)
 *   * ``onboarding-cohort-*-delta``  (per-card delta arrow)
 *   * ``onboarding-tile-invited-cta`` / ``-activated-cta`` /
 *     ``-signed-in-cta`` / ``-never-cta``  (per-card deep-link)
 *   * ``onboarding-tile-invited-chase-cta`` (Chase button)
 */
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { api } from "@/api";
import { colors } from "@/theme";
import ChaseStalledInvitesModal from "@/components/customers/ChaseStalledInvitesModal";


const COHORT_ORDER = [
  {
    key: "invited", label: "Invited",
    testid: "onboarding-cohort-invited",
    ctaHref: "/customers?portal_invited=any",
    ctaTestid: "onboarding-tile-invited-cta",
  },
  {
    key: "activated", label: "Activated",
    testid: "onboarding-cohort-activated",
    ctaHref: "/customers?portal_activated=1",
    ctaTestid: "onboarding-tile-activated-cta",
  },
  {
    key: "signed_in", label: "Signed in",
    testid: "onboarding-cohort-signed-in",
    ctaHref: "/customers?first_access=any",
    ctaTestid: "onboarding-tile-signed-in-cta",
  },
  {
    key: "never_logged_in", label: "Never logged in",
    testid: "onboarding-cohort-never",
    ctaHref: "/customers?first_access=never",
    ctaTestid: "onboarding-tile-never-cta",
  },
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
  // Every clickable card also exposes a hidden CTA test-id anchor
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


export default function PortalOnboardingHealthTile({ externalRefetchToken }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [chaseOpen, setChaseOpen] = useState(false);
  // Feb-2026 · Chase Stalled Invites — bump on send so the tile
  // refetches its cohort counts after the batch resolves. The
  // server has a 60s cache so consecutive bumps within the window
  // return the same numbers, which is intentional.
  //
  // Feb-2026 · Bulk-Portal-Invite-from-CustomersList ship — the
  // ``externalRefetchToken`` prop plumbs the SAME refetch signal
  // from the parent CustomersList toolbar button.
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
  }, [refetchTick, externalRefetchToken]);

  if (loading) {
    return <TileSkeleton />;
  }
  if (error || !data || !data.cohorts) {
    return null;
  }

  // Feb-2026 · Chase-move ship — the button is enabled based on
  // the SIZE of the chase audience, not the raw Invited count.
  // Audience = invited-and-never-signed-in ≈ min(invited, never)
  // as an upper-bound approximation; the modal fetches the real
  // list on open so the exact count settles there.
  const invitedCount = data.cohorts?.invited?.count ?? 0;
  const neverCount   = data.cohorts?.never_logged_in?.count ?? 0;
  const chaseAudienceUpperBound = Math.min(invitedCount, neverCount);

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
          const isInvited = c.key === "invited";
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
                ctaHref={c.ctaHref}
                ctaTestid={c.ctaTestid}
              />
              {isInvited ? (
                <button
                  type="button"
                  onClick={() => setChaseOpen(true)}
                  disabled={chaseAudienceUpperBound === 0}
                  data-testid="onboarding-tile-invited-chase-cta"
                  className="inline-flex items-center justify-center rounded-md px-3 py-1.5 text-xs font-semibold hover:brightness-95 disabled:opacity-40 disabled:cursor-not-allowed"
                  style={{
                    backgroundColor: colors.brand,
                    color: "#fff",
                  }}
                  aria-label="Chase stalled portal invites"
                  title={
                    chaseAudienceUpperBound === 0
                      ? "No stalled invites to chase"
                      : `Chase up to ${chaseAudienceUpperBound} stalled invite${chaseAudienceUpperBound === 1 ? "" : "s"}`
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
