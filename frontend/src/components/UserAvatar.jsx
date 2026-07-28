/**
 * Phase B1 · Feb 2026 — Global staff/user avatar (web).
 *
 * Fallback chain:
 *   1. ``user.profile_photo_url`` set → render <img>
 *   2. otherwise → initials badge (first letter of first + last word,
 *      up to 2 chars)
 *   3. onError of <img> → fall back to initials badge as well
 *
 * Sizes: ``xs`` (16), ``sm`` (24), ``md`` (32), ``lg`` (48).
 * Accepts a numeric ``size`` prop as well for exact pixel needs.
 *
 * Uses the F0 URL shape (``/api/files/{id}/download``) verbatim. When
 * the URL requires auth (i.e. starts with ``/api/files/``), we do NOT
 * pipe through <AuthedImage> here because most surfaces are inside
 * an authenticated shell and the browser cookie/bearer is already
 * attached to same-origin requests. If a surface renders in a
 * non-authenticated context (e.g. public share pages), it should
 * either pass ``photoUrl`` explicitly (an absolute CDN URL) or use
 * <AuthedImage> directly.
 */
import React, { useState } from "react";

/** Compute up-to-two-letter initials from a display name / email. */
export function computeInitials(nameOrEmail) {
  const raw = String(nameOrEmail || "").trim();
  if (!raw) return "?";
  // If it's an email, use the local part.
  const cleaned = raw.includes("@") ? raw.split("@")[0] : raw;
  const parts = cleaned.split(/[\s._-]+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

const SIZE_PX = { xs: 16, sm: 24, md: 32, lg: 48 };

/** Deterministic pastel-ish tint from the initials so avatars don't
 *  all look like the same gray dot. Same input → same color. */
function tintFor(initials) {
  const palette = [
    "#DBEAFE", // sky-100
    "#DCFCE7", // green-100
    "#FEE2E2", // red-100
    "#FEF3C7", // amber-100
    "#E9D5FF", // purple-100
    "#CFFAFE", // cyan-100
    "#FCE7F3", // pink-100
    "#F1F5F9", // slate-100
  ];
  const key = String(initials || "?");
  let hash = 0;
  for (let i = 0; i < key.length; i += 1) {
    hash = (hash * 31 + key.charCodeAt(i)) >>> 0;
  }
  return palette[hash % palette.length];
}

export function UserAvatar({ user, size = "md", className = "", testid }) {
  const [imgBroken, setImgBroken] = useState(false);
  const px = typeof size === "number" ? size : (SIZE_PX[size] || SIZE_PX.md);
  const photoUrl =
    (user && (user.profile_photo_url || user.photo_url)) || "";
  const initials = computeInitials(user?.name || user?.email || user?.display_name);
  const showImage = !!photoUrl && !imgBroken;
  const bg = tintFor(initials);

  const rootStyle = {
    width: px,
    height: px,
    borderRadius: "9999px",
    overflow: "hidden",
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    flexShrink: 0,
    background: bg,
    color: "#1E293B",
    fontSize: Math.max(10, Math.round(px * 0.42)),
    fontWeight: 600,
    lineHeight: 1,
    userSelect: "none",
  };

  const dataAttrs = testid ? { "data-testid": testid } : {};

  if (showImage) {
    return (
      <span className={className} style={rootStyle} {...dataAttrs}>
        <img
          src={photoUrl}
          alt={user?.name || user?.email || "User avatar"}
          data-testid={testid ? `${testid}-img` : undefined}
          onError={() => setImgBroken(true)}
          style={{
            width: "100%",
            height: "100%",
            objectFit: "cover",
            display: "block",
          }}
        />
      </span>
    );
  }

  return (
    <span
      className={className}
      style={rootStyle}
      title={user?.name || user?.email || ""}
      {...dataAttrs}
    >
      <span data-testid={testid ? `${testid}-initials` : undefined}>
        {initials}
      </span>
    </span>
  );
}

export default UserAvatar;
