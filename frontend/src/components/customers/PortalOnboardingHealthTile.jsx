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
 *     link map (P53 tail · Feb-2026 — 4th card swap):
 *
 *       Card             → URL
 *       Invited          → /customers?portal_invited=any
 *       Activated        → /customers?portal_activated=1
 *       Signed in        → /customers?first_access=any
 *       Cards on file    → /customers?has_payment_method=true
 *                            &is_active=true                 (NEW)
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
 * P53 tail · Feb-2026 — Customer stats tile swap
 *   * The "Never logged in" card was swapped for a "Cards on
 *     file" card. Rationale: the "Never" number was a lagging
 *     onboarding negative that most admins glanced past; the
 *     "Cards on file" number is a leading revenue-quality
 *     positive that surfaces the % of the active book we can
 *     bill instantly. Same shape, same 4-card layout.
 *   * The backend ``never_logged_in`` count is DELIBERATELY
 *     RETAINED in the ``/reports/portal-onboarding-health``
 *     response (see the paired comment in
 *     ``routers/profit_report.py``). The Chase button under
 *     Invited reads ``data.cohorts.never_logged_in.count`` for
 *     its ``chaseAudienceUpperBound = min(invited, never)``
 *     disabled-state calculation. Removing the count would
 *     silently break the Chase button's enabled state.
 *   * New card testid: ``portal-onboarding-cards-on-file-tile``
 *     (verbatim from the P53 tail brief — intentionally NOT
 *     ``onboarding-cohort-cards-on-file`` because the tile is
 *     surfaced in customer-stats coverage grids where the
 *     ``portal-onboarding-`` prefix is the canonical anchor).
 *
 * Test-ids:
 *   * ``onboarding-health-tile``
 *   * ``onboarding-cohort-invited`` / ``-activated`` /
 *     ``-signed-in``  (per-card blocks for the first 3 cards)
 *   * ``portal-onboarding-cards-on-file-tile`` (4th card block —
 *     P53 tail swap)
 *   * ``onboarding-cohort-*-delta``  (per-card delta arrow)
 *   * ``onboarding-tile-invited-cta`` / ``-activated-cta`` /
 *     ``-signed-in-cta`` / ``-cards-on-file-cta``  (per-card
 *     deep-link)
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
    key: "active_with_card_on_file",
    label: "Cards on file",
    // P53 tail (Feb-2026) — user-approved copy. Subtitle is
    // rendered under the label; only this card carries one
    // (rest of the cohort cards deliberately keep the pre-P53
    // one-line-label rhythm).
    subtitle: "Active customers with a saved payment method",
    // Verbatim from the P53 tail brief. The tile testid pattern
    // for cards 1-3 is ``onboarding-cohort-*``; the P53 tail
    // approval used a different anchor (``portal-onboarding-*``)
    // because this card is surfaced in customer-stats coverage
    // grids where ``portal-onboarding-`` is the canonical
    // prefix. Keep this testid EXACT — QA/product docs already
    // reference it.
    testid: "portal-onboarding-cards-on-file-tile",
    // Tile ↔ list parity — the CTA has to land on the SAME
    // subset the tile counted. Backend predicate:
    //   (is_active OR absent) AND NOT is_muted AND
    //   saved_payment_methods_count > 0
    // ``?is_active=true`` on the customers list already
    // implicitly enforces ``_NOT_MUTED`` (see customers.py L995),
    // and ``?has_payment_method=true`` reads the same denorm
    // (``saved_payment_methods_count > 0``). So this compound
    // URL selects exactly the tile's counted rows.
    ctaHref: "/customers?has_payment_method=true&is_active=true",
    ctaTestid: "onboarding-tile-cards-on-file-cta",
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


function CohortCard({ label, subtitle, testid, count, delta, ctaHref, ctaTestid }) {
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
      {subtitle ? (
        // P53 tail (Feb-2026) — subtitle line, only rendered when the
        // cohort config sets one. Kept inline with the label rhythm
        // (11px vs 3xl count) so the number stays the visual anchor.
        <div
          data-testid={`${testid}-subtitle`}
          className="text-[11px] leading-tight mt-0.5"
          style={{ color: colors.muted, fontWeight: 400 }}
        >
          {subtitle}
        </div>
      ) : null}
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
  //
  // P53 tail (Feb-2026) — the "Never logged in" TILE was swapped
  // for "Cards on file", but the underlying ``never_logged_in``
  // cohort count is still consumed here. Backend deliberately
  // keeps returning ``cohorts.never_logged_in.count`` for exactly
  // this Chase-button binding — removing this line would silently
  // break the button's ``disabled`` state.
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
                subtitle={c.subtitle}
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
