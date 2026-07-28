/**
 * Task RR/SS Phase 2 follow-on · Feb 2026 — shared persona avatar.
 *
 * Renders a circular avatar image for an AI persona. Falls back to
 * the persona's ``avatar_emoji`` (inside a colored circle) when
 * ``persona.avatar_url`` is null / undefined OR the image fails to
 * load (network error, 404, etc.).
 *
 * Props:
 *   persona   – the persona row (needs ``avatar_url`` and/or
 *               ``avatar_emoji`` + ``key``; ``name`` used for alt text).
 *   size      – pixel size of the circle (default 40).
 *   className – extra classes to layer on the outer wrapper.
 *   testid    – optional data-testid override.
 */
import React, { useState } from "react";
import { AuthedImage } from "@/components/files/AuthedImage";

// Feb-2026 · F2e — persona avatars uploaded via F0 store their file
// id inside ``avatar_url`` as ``/api/files/{id}/download`` (no auth
// query). Detect that and route through the AuthedImage blob fetcher
// so the token stays in the header, not the URL.
function _extractF0FileId(url) {
  if (!url || typeof url !== "string") return null;
  const m = url.match(/^\/api\/files\/([^/?#]+)\/download/);
  return m ? m[1] : null;
}

function fallbackTint(personaKey) {
  // Match the tint used in PortalHome's chat panels so the emoji
  // fallback isn't jarring when a legacy row misses an avatar_url.
  if (personaKey === "billy") return "linear-gradient(135deg,#DCFCE7,#BBF7D0)";
  return "linear-gradient(135deg,#DBEAFE,#BFDBFE)";
}

// Exported for the F2e Vitest suite — detects whether a persona
// ``avatar_url`` was written by the F0 upload path.
export function extractF0FileId(url) {
  return _extractF0FileId(url);
}

export function PersonaAvatar({ persona, size = 40, className = "", testid }) {
  const [broken, setBroken] = useState(false);
  const p = persona || {};
  const src = p.avatar_url;
  const showImage = !!src && !broken;
  const px = `${size}px`;
  const emojiScale = Math.max(14, Math.round(size * 0.5));
  const alt = p.name ? `${p.name} avatar` : "AI persona avatar";
  const resolvedTestid = testid || (p.key ? `persona-avatar-${p.key}` : "persona-avatar");

  if (showImage) {
    // F2e · route F0-hosted avatars through <AuthedImage> so requests
    // include the bearer header (no ?auth= token in URL / referrer /
    // access logs). Legacy static ``/avatars/personas/*.jpg`` paths
    // continue through the plain <img>.
    const f0Id = _extractF0FileId(src);
    if (f0Id) {
      return (
        <AuthedImage
          fileId={f0Id}
          alt={alt}
          size={size}
          className={`rounded-full object-cover shrink-0 ${className}`}
          testid={resolvedTestid}
        />
      );
    }
    return (
      <img
        src={src}
        alt={alt}
        onError={() => setBroken(true)}
        className={`rounded-full object-cover shrink-0 ${className}`}
        style={{ width: px, height: px }}
        data-testid={resolvedTestid}
        loading="lazy"
      />
    );
  }
  return (
    <div
      className={`rounded-full flex items-center justify-center shrink-0 ${className}`}
      style={{
        width: px,
        height: px,
        background: fallbackTint(p.key),
        fontSize: `${emojiScale}px`,
        lineHeight: 1,
      }}
      aria-label={alt}
      data-testid={resolvedTestid}
    >
      <span aria-hidden="true">{p.avatar_emoji || "🤖"}</span>
    </div>
  );
}

export default PersonaAvatar;
