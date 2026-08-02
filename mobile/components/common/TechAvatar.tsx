/**
 * Phase 27 · Feb-2026 — Shared compact <TechAvatar /> for dense
 * mobile layouts (Schedule per-job rows, Dispatch board).
 *
 * Fallback chain:
 *   1. `user.profile_photo_url` set → render <Image>
 *   2. otherwise → initials badge (first letter of first + last word,
 *      up to 2 chars) on a deterministic pastel tint.
 *
 * Sizes: `xs=20 · sm=28 · md=40` dp (or accept a numeric size for
 * exact needs). Sizes deliberately match the web `TechAvatar` shim
 * so cross-platform reviewers see the same visual weight.
 *
 * No new dependencies — pure RN primitives + <Image>. No 3rd-party
 * avatar lib.
 */
import React, { useState } from "react";
import { View, Text, Image, StyleSheet } from "react-native";

const TECH_SIZE_PX = { xs: 20, sm: 28, md: 40 };

/** Compute up-to-two-letter initials from a display name / email. */
export function computeInitials(nameOrEmail: string | undefined | null) {
  const raw = String(nameOrEmail || "").trim();
  if (!raw) return "?";
  const cleaned = raw.includes("@") ? raw.split("@")[0] : raw;
  const parts = cleaned.split(/[\s._-]+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

/** Deterministic pastel tint. Same input → same colour. */
function tintFor(initials: string) {
  const palette = [
    "#DBEAFE", "#DCFCE7", "#FEE2E2", "#FEF3C7",
    "#E9D5FF", "#CFFAFE", "#FCE7F3", "#F1F5F9",
  ];
  const key = String(initials || "?");
  let hash = 0;
  for (let i = 0; i < key.length; i += 1) {
    hash = (hash * 31 + key.charCodeAt(i)) >>> 0;
  }
  return palette[hash % palette.length];
}

type TechAvatarUser = {
  name?: string | null;
  email?: string | null;
  profile_photo_url?: string | null;
  photo_url?: string | null;
};

type Props = {
  user?: TechAvatarUser | null;
  size?: "xs" | "sm" | "md" | number;
  testID?: string;
};

export default function TechAvatar({ user, size = "xs", testID }: Props) {
  const [broken, setBroken] = useState(false);
  const px = typeof size === "number"
    ? size
    : (TECH_SIZE_PX[size] || TECH_SIZE_PX.xs);
  const initials = computeInitials(user?.name || user?.email);
  const photoUrl = user?.profile_photo_url || user?.photo_url || "";
  const showImage = !!photoUrl && !broken;
  const bg = tintFor(initials);

  const container = {
    width: px,
    height: px,
    borderRadius: px / 2,
    backgroundColor: bg,
    alignItems: "center" as const,
    justifyContent: "center" as const,
    overflow: "hidden" as const,
  };

  if (showImage) {
    return (
      <View style={container} testID={testID}>
        <Image
          source={{ uri: photoUrl }}
          onError={() => setBroken(true)}
          style={{ width: "100%", height: "100%" }}
          resizeMode="cover"
          testID={testID ? `${testID}-img` : undefined}
        />
      </View>
    );
  }
  const fontSize = Math.max(9, Math.round(px * 0.42));
  return (
    <View style={container} testID={testID}>
      <Text
        style={[styles.initials, { fontSize }]}
        testID={testID ? `${testID}-initials` : undefined}
      >
        {initials}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  initials: {
    color: "#1E293B",
    fontWeight: "600",
    lineHeight: undefined,
    includeFontPadding: false,
  },
});

export { TECH_SIZE_PX };
