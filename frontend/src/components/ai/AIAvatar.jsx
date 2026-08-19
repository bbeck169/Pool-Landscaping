/**
 * Phase 50 · Feb-2026 — Animated AI-employee avatar (web).
 *
 * Shared Lottie idle loop (blink + subtle breathing scale) rendered
 * behind a small circular badge that echoes the employee's static
 * ``avatar_url``. Lottie file at ``src/assets/lottie/ai/idle.json``
 * is hand-crafted — MIT-licensed by the repo, no third-party asset.
 *
 * Feb-2026 update — added the ``name`` prop so a persona that
 * hasn't got a hydrated ``avatar_url`` still shows a friendly
 * initial-in-a-pastel-circle instead of the raw Lottie loop. This is
 * the SAME fallback the AI Dock and the /ai-employees page share, so
 * both surfaces stay pixel-consistent for each persona.
 */
import React from "react";
import Lottie from "lottie-react";
import idle from "@/assets/lottie/ai/idle.json";


// Deterministic pastel tint for the initial-fallback badge — hashed
// off the persona name so Casey / Emmie / Buddy each get a stable
// unique background even when the ``avatar_url`` is missing.
const _PASTELS = [
  "#DCFCE7", "#BFDBFE", "#FEF3C7", "#FBCFE8", "#DDD6FE",
  "#BAE6FD", "#FED7AA", "#D1FAE5", "#E9D5FF", "#FECACA",
];


function pickPastel(name) {
  const s = String(name || "AI");
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return _PASTELS[h % _PASTELS.length];
}


export default function AIAvatar({ src, alt = "", size = 64, name, testId }) {
  const initial = String(name || alt || "AI").trim().slice(0, 1).toUpperCase() || "AI";
  const tint = pickPastel(name || alt);
  return (
    <div
      className="relative inline-block rounded-full overflow-hidden"
      style={{ width: size, height: size }}
      data-testid={testId || "ai-lottie-avatar"}
    >
      <Lottie
        animationData={idle}
        loop
        autoplay
        style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }}
        aria-hidden="true"
      />
      {src ? (
        <img
          src={src}
          alt={alt}
          style={{
            position: "absolute", inset: "18%", width: "64%", height: "64%",
            borderRadius: "50%", objectFit: "cover",
          }}
          data-testid={testId ? `${testId}-img` : undefined}
        />
      ) : (
        <div
          style={{
            position: "absolute", inset: "18%", width: "64%", height: "64%",
            borderRadius: "50%", backgroundColor: tint,
            display: "flex", alignItems: "center", justifyContent: "center",
            fontWeight: 700, color: "#1f2937",
            fontSize: Math.max(10, Math.round(size * 0.3)),
          }}
          data-testid={testId ? `${testId}-initial` : undefined}
          aria-label={alt || `${name || "AI"} avatar`}
        >
          {initial}
        </div>
      )}
    </div>
  );
}
