/**
 * Phase 27 · Feb-2026 — Shared compact `<TechAvatar />` for dense
 * layouts (Dispatch Board, Schedule tiles/cards).
 *
 * Thin wrapper over the existing `<UserAvatar />` component
 * (`components/UserAvatar.jsx`). This shim exists so dense layouts
 * can standardise on a fixed pixel size vocabulary
 * (``xs=20 · sm=28 · md=40``) without every caller repeating the
 * numeric ``size`` prop. All Phase-19 fallback behaviour (image →
 * initials → deterministic pastel tint) is inherited from
 * ``UserAvatar`` — this file adds ZERO business logic.
 *
 * Usage:
 *   <TechAvatar user={tech} size="xs" testid="dispatch-tech-42" />
 *
 * The ``user`` prop accepts anything ``UserAvatar`` accepts —
 * ``{name?, email?, profile_photo_url?, photo_url?}``.
 */
import React from "react";
import UserAvatar from "../UserAvatar";

const TECH_SIZE_PX = { xs: 20, sm: 28, md: 40 };

export default function TechAvatar({
  user,
  size = "xs",
  className = "",
  testid,
}) {
  const px = typeof size === "number"
    ? size
    : (TECH_SIZE_PX[size] || TECH_SIZE_PX.xs);
  return (
    <UserAvatar
      user={user}
      size={px}
      className={className}
      testid={testid}
    />
  );
}

export { TECH_SIZE_PX };
