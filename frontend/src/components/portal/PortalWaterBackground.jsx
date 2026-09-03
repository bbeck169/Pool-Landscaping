import React from "react";

/**
 * Phase K35 · Feb-2026 — Animated pool-water background for the
 * customer portal login page.  SVG-only (no external assets, no
 * libraries).  Uses ``<feTurbulence>`` + ``<feDisplacementMap>``
 * with a CSS-animated ``baseFrequency`` seed to produce a slow
 * caustics shimmer over a fixed pool-tone gradient.  Two extra
 * white "ripple" arcs animate their opacity for a subtle
 * highlight.
 *
 * Respects ``prefers-reduced-motion``: when the media query is on
 * we render a static caustics texture (still frame — no animation
 * loop) so users with vestibular preferences don't get motion.
 *
 * Rendered fixed-position at ``inset: 0`` behind the login card;
 * ``pointer-events: none`` so it never intercepts clicks.
 */
export default function PortalWaterBackground() {
  return (
    <div
      data-testid="portal-water-bg"
      aria-hidden="true"
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 0,
        pointerEvents: "none",
        background:
          "linear-gradient(180deg, #7dd3fc 0%, #38bdf8 45%, #0284c7 100%)",
        overflow: "hidden",
      }}
    >
      {/* Caustics overlay — a solid white layer distorted by a
          slow-moving turbulence filter so it looks like light
          rippling through pool water. */}
      <svg
        width="100%" height="100%"
        style={{
          position: "absolute", inset: 0,
          mixBlendMode: "soft-light",
          opacity: 0.65,
        }}
      >
        <defs>
          <filter id="k35-caustics">
            <feTurbulence
              type="fractalNoise"
              baseFrequency="0.012 0.024"
              numOctaves="2" seed="4"
            >
              <animate
                attributeName="baseFrequency"
                dur="18s" repeatCount="indefinite"
                values="0.012 0.024; 0.020 0.030; 0.012 0.024"
                className="k35-caustics-animate"
              />
            </feTurbulence>
            <feDisplacementMap in="SourceGraphic" scale="30" />
            <feColorMatrix
              type="matrix"
              values="0 0 0 0 1
                      0 0 0 0 1
                      0 0 0 0 1
                      0 0 0 0.6 0"
            />
          </filter>
        </defs>
        <rect width="100%" height="100%"
              fill="#ffffff" filter="url(#k35-caustics)" />
      </svg>

      {/* Two soft white ripple arcs — opacity animation for a
          gentle "specular" flash across the top-half of the water. */}
      <div
        data-testid="portal-water-ripple-1"
        style={{
          position: "absolute", top: "15%", left: "-10%",
          width: "60%", height: "40%",
          borderRadius: "50%",
          background:
            "radial-gradient(ellipse at center, rgba(255,255,255,0.35) 0%, transparent 70%)",
          filter: "blur(28px)",
          animation: "k35-ripple 12s ease-in-out infinite",
        }}
      />
      <div
        data-testid="portal-water-ripple-2"
        style={{
          position: "absolute", bottom: "10%", right: "-10%",
          width: "55%", height: "35%",
          borderRadius: "50%",
          background:
            "radial-gradient(ellipse at center, rgba(255,255,255,0.28) 0%, transparent 70%)",
          filter: "blur(24px)",
          animation: "k35-ripple-2 15s ease-in-out infinite",
        }}
      />

      <style>{`
        @keyframes k35-ripple {
          0%, 100% { opacity: 0.35; transform: translateX(0); }
          50%      { opacity: 0.75; transform: translateX(30px); }
        }
        @keyframes k35-ripple-2 {
          0%, 100% { opacity: 0.28; transform: translateX(0); }
          50%      { opacity: 0.60; transform: translateX(-30px); }
        }
        /* K35 · Feb-2026 · a11y — halve battery drain on mobile
           by slowing the turbulence loop, and honor
           prefers-reduced-motion by freezing every animation.
           The gradient + still caustics still convey the pool-
           water aesthetic without any motion. */
        @media (max-width: 640px) {
          [data-testid="portal-water-ripple-1"],
          [data-testid="portal-water-ripple-2"] {
            animation-duration: 22s;
          }
        }
        @media (prefers-reduced-motion: reduce) {
          [data-testid="portal-water-bg"] .k35-caustics-animate,
          [data-testid="portal-water-bg"] animate {
            display: none;
          }
          [data-testid="portal-water-ripple-1"],
          [data-testid="portal-water-ripple-2"] {
            animation: none !important;
          }
        }
      `}</style>
    </div>
  );
}
