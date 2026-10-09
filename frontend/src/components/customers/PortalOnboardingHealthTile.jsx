/**
 * Feb-2026 · Portal onboarding health tile.
 *
 * Compact admin snapshot of the customer portal funnel. After
 * Phase 9b the tile renders THREE cohort cards (down from four):
 *   activated → signed_in → active_with_card_on_file
 *
 * The former "Invited" card + its "Chase stalled invites" button
 * were removed in Phase 9b. The server still returns an
 * ``invited`` cohort block (and the paired ``never_logged_in``
 * block that fed the Chase disabled-state) — the tile just no
 * longer consumes them. The former ``ChaseStalledInvitesModal``
 * component was deleted in Phase 15 (dead-code cleanup).
 *
 * Phase 9b · Clickable-toggle semantics
 *   * Each card is a toggle. Clicking an INACTIVE card activates
 *     its filter on the customers list. Clicking the ACTIVE card
 *     clears the filter. Clicking a different card SWAPS the
 *     filter (previous card deselects — only one tile active at
 *     a time; URL-level mutex guard).
 *   * Active state is derived from the current URL so refresh and
 *     deep-link sharing survive without extra state. The three
 *     backend-field URL conventions are preserved verbatim from
 *     the pre-Phase-9b deep-link map (user explicitly approved
 *     "mirror existing" so legacy bookmarks keep working):
 *
 *       Card             → Active-state URL match
 *       Activated        → ?portal_activated=1 | true
 *       Signed in        → ?first_access=any
 *       Cards on file    → ?has_payment_method=true | 1
 *
 *   * Activating a tile STACKS with other filters: search, tag
 *     chips, status tabs, missing-contact chips. The toggle only
 *     touches the tile-specific URL params (and the three tile
 *     params are mutually exclusive — activating one deletes the
 *     other two).
 *   * The Cards-on-file CTA additionally forces ``is_active=true``
 *     on activate so the list cohort matches the backend count
 *     predicate (``active AND NOT muted AND
 *     saved_payment_methods_count > 0``). On DEactivate the shared
 *     ``is_active`` param is left in place — it belongs to the
 *     status tab, not to this tile.
 *
 * Test-ids (unchanged — removal does not touch surviving testids):
 *   * ``onboarding-health-tile``
 *   * ``onboarding-cohort-activated`` / ``-signed-in``  (cards 1 & 2)
 *   * ``portal-onboarding-cards-on-file-tile`` (card 3)
 *   * ``onboarding-cohort-*-delta`` / ``portal-onboarding-cards-on-file-tile-delta``
 *   * ``onboarding-tile-activated-cta`` / ``-signed-in-cta`` /
 *     ``-cards-on-file-cta``
 *
 * RETIRED (Phase 9b) — these testids must NEVER re-appear in this
 * component (regression guards in the Phase 9b test suite assert
 * their absence):
 *   * ``onboarding-cohort-invited`` / ``-invited-delta``
 *   * ``onboarding-tile-invited-cta``
 *   * ``onboarding-tile-invited-chase-cta`` (Chase button)
 */
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";

import { api } from "@/api";
import { colors } from "@/theme";


// ───────────────────────────────────────────────────────────────
// Phase 9b · Feb-2026 — URL ⇄ tile mapping.
//
// Keys MUST match the backend cohort block names so
// ``data.cohorts[c.key]`` resolves without a translation layer.
// The ``urlParam`` tuple is the single source of truth for both
// (a) deriving active state from the current URL and (b) toggling
// a tile on/off. Keep in lockstep with the backend predicate map
// documented in ``routers/profit_report.py``.
// ───────────────────────────────────────────────────────────────
const COHORT_ORDER = [
  {
    key: "activated",
    label: "Activated",
    testid: "onboarding-cohort-activated",
    ctaTestid: "onboarding-tile-activated-cta",
    // ``?portal_activated=1`` is the canonical URL shorthand the
    // customers list hydrator accepts (see CustomersList.jsx
    // L376-L378 — ``1 | true`` ⇒ activated).
    urlParam: { key: "portal_activated", value: "1" },
    urlMatch: (sp) => {
      const v = sp.get("portal_activated");
      return v === "1" || v === "true";
    },
  },
  {
    key: "signed_in",
    label: "Signed in",
    testid: "onboarding-cohort-signed-in",
    ctaTestid: "onboarding-tile-signed-in-cta",
    urlParam: { key: "first_access", value: "any" },
    urlMatch: (sp) => sp.get("first_access") === "any",
  },
  {
    key: "active_with_card_on_file",
    label: "Cards on file",
    subtitle: "Active customers with a saved payment method",
    // Phase 9b · Feb-2026 — testid retained verbatim from the P53
    // tail swap (``portal-onboarding-cards-on-file-tile``). QA /
    // product docs already reference it; keep EXACT.
    testid: "portal-onboarding-cards-on-file-tile",
    ctaTestid: "onboarding-tile-cards-on-file-cta",
    urlParam: { key: "has_payment_method", value: "true" },
    // On activate we ALSO force ``is_active=true`` so the list
    // cohort matches the backend count's predicate (active + NOT
    // muted + card on file). On DEactivate we leave ``is_active``
    // alone — that param belongs to the status tab, not to us.
    extraActivateParam: { key: "is_active", value: "true" },
    urlMatch: (sp) => {
      const v = sp.get("has_payment_method");
      return v === "true" || v === "1";
    },
  },
];
// All tile params that must be stripped when a tile toggles (mutex
// guard). Includes the retired ``portal_invited`` key as defense-
// in-depth so a bookmark URL from before Phase 9b lands on a clean
// list rather than leaking a stale filter.
const _TILE_PARAM_KEYS = ["portal_activated", "first_access", "has_payment_method", "portal_invited"];


function DeltaArrow({ delta, testid }) {
  const muted = colors.muted;
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


function CohortCard({ label, subtitle, testid, count, delta, ctaTestid, isActive, onToggle }) {
  const body = (
    <div
      data-testid={testid}
      className="rounded-lg p-4 flex-1 min-w-0 outline-none"
      style={{
        backgroundColor: colors.surface,
        // Phase 9b active-state visual — 2px brand border + inner
        // ring box-shadow (keeps card dimensions stable on toggle
        // because the base border is 1px → delta is 1px, absorbed
        // by the ring shadow). Mirrors the P52 cohort-tab active
        // glow idiom (boxShadow accent) but tuned for a solid
        // bordered card rather than a pill tab.
        border: isActive
          ? `2px solid ${colors.brandPrimary}`
          : `1px solid ${colors.border}`,
        boxShadow: isActive
          ? `0 0 0 2px ${colors.brandPrimary}26, 0 1px 3px rgba(0,0,0,0.06)`
          : "none",
        cursor: "pointer",
        transition: "background-color 120ms ease-out, border-color 120ms ease-out, box-shadow 120ms ease-out",
      }}
      onClick={onToggle}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onToggle();
        }
      }}
      role="button"
      tabIndex={0}
      aria-pressed={isActive}
      aria-label={
        isActive
          ? `Clear ${label} filter`
          : `Filter customers to ${label}`
      }
      data-cta-testid={ctaTestid}
      data-active={isActive ? "true" : "false"}
    >
      <div
        className="text-[11px] font-semibold uppercase tracking-wide"
        style={{ color: colors.muted }}
      >
        {label}
      </div>
      {subtitle ? (
        <div
          data-testid={`${testid}-subtitle`}
          className="text-[11px] leading-tight mt-0.5"
          style={{ color: colors.muted, fontWeight: 400 }}
        >
          {subtitle}
        </div>
      ) : null}
      <div
        className="text-3xl my-1 tabular-nums"
        style={{
          // Phase 9b — active state bumps the count weight (600 →
          // 800) and tints it with the brand accent so the active
          // tile reads as unmistakably selected even at a glance.
          color: isActive ? colors.brandPrimary : colors.onSurface,
          fontWeight: isActive ? 800 : 700,
        }}
      >
        {typeof count === "number" ? count.toLocaleString() : "—"}
      </div>
      <DeltaArrow
        delta={delta}
        testid={`${testid}-delta`}
      />
    </div>
  );
  // Hidden CTA anchor sibling — gives tests + external callers a
  // stable testid handle that doesn't depend on the outer div's
  // role=button attribute. Click handler delegates to the same
  // toggle so manual CTA activations stay consistent with the
  // visible card click path.
  return (
    <div style={{ display: "contents" }}>
      {body}
      <span
        data-testid={ctaTestid}
        style={{ display: "none" }}
        onClick={onToggle}
      />
    </div>
  );
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
  const [refetchTick] = useState(0);
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

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

  // Phase 9b — compute active tile from current URL. Null when no
  // tile is active. Precedence matches the config declaration
  // order (``signed_in`` loses to earlier entries only if BOTH are
  // set simultaneously, which the toggle code prevents).
  const activeTileKey = useMemo(() => {
    for (const c of COHORT_ORDER) {
      if (c.urlMatch(searchParams)) return c.key;
    }
    return null;
  }, [searchParams]);

  const handleToggle = (clickedKey) => {
    const next = new URLSearchParams(searchParams);
    // Mutex strip — always clear every tile param, even when the
    // click is a swap (new tile wins → old params go).
    for (const k of _TILE_PARAM_KEYS) next.delete(k);

    if (clickedKey !== activeTileKey) {
      // Toggle ON — set this tile's canonical URL param (+ any
      // extra activation params, like Cards-on-file's cohort nudge).
      const cfg = COHORT_ORDER.find((c) => c.key === clickedKey);
      if (cfg) {
        next.set(cfg.urlParam.key, cfg.urlParam.value);
        if (cfg.extraActivateParam) {
          next.set(cfg.extraActivateParam.key, cfg.extraActivateParam.value);
        }
      }
    }
    // Toggle OFF path takes the already-stripped params as-is.
    // ``is_active`` is DELIBERATELY left intact on deactivate — it
    // belongs to the status tab, not to the Cards-on-file tile.

    const qs = next.toString();
    navigate(qs ? `/customers?${qs}` : "/customers");
  };

  if (loading) {
    return <TileSkeleton />;
  }
  if (error || !data || !data.cohorts) {
    return null;
  }

  return (
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
        const isActive = activeTileKey === c.key;
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
              ctaTestid={c.ctaTestid}
              isActive={isActive}
              onToggle={() => handleToggle(c.key)}
            />
          </div>
        );
      })}
    </div>
  );
}
