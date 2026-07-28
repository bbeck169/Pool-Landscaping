/**
 * Task RR/SS Phase 2 follow-on · Feb 2026 — Expo persona avatar.
 *
 * Mirrors the web ``PersonaAvatar`` contract. Picks the bundled JPEG
 * from the static ``PERSONA_AVATARS`` map keyed by ``persona.key``.
 * Falls back to ``avatar_emoji`` rendered inside a rounded ``View``
 * when the key isn't in the map OR the image fails to load.
 *
 * Note: this component intentionally does NOT consume
 * ``persona.avatar_url`` — Metro cannot fetch remote images through
 * ``require()``. When the app later gains true remote avatars, swap
 * ``require`` for ``{ uri }`` inside a small feature-flag.
 */
import React, { useState } from "react";
import { View, Text, StyleSheet, ImageStyle } from "react-native";
import { Image } from "expo-image";
import { PERSONA_AVATARS } from "./avatarMap";

export interface PersonaAvatarProps {
  persona: {
    key?: string;
    name?: string;
    avatar_emoji?: string;
    avatar_url?: string | null;
  };
  size?: number;
  style?: ImageStyle;
  testID?: string;
}

function fallbackTint(personaKey?: string): string {
  return personaKey === "billy" ? "#DCFCE7" : "#DBEAFE";
}

export function PersonaAvatar({ persona, size = 40, style, testID }: PersonaAvatarProps) {
  const [broken, setBroken] = useState(false);
  const p = persona || {};
  const source = p.key ? PERSONA_AVATARS[p.key] : undefined;
  const showImage = !!source && !broken;
  const dims = { width: size, height: size, borderRadius: size / 2 };
  const resolvedTestID = testID || (p.key ? `persona-avatar-${p.key}` : "persona-avatar");

  if (showImage) {
    return (
      <Image
        source={source}
        onError={() => setBroken(true)}
        style={[dims, style]}
        contentFit="cover"
        testID={resolvedTestID}
        accessibilityLabel={p.name ? `${p.name} avatar` : "AI persona avatar"}
      />
    );
  }
  return (
    <View
      style={[dims, styles.fallback, { backgroundColor: fallbackTint(p.key) }, style]}
      testID={resolvedTestID}
      accessibilityLabel={p.name ? `${p.name} avatar` : "AI persona avatar"}
    >
      <Text style={{ fontSize: Math.max(14, Math.round(size * 0.5)) }}>
        {p.avatar_emoji || "🤖"}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  fallback: {
    alignItems: "center",
    justifyContent: "center",
  },
});

export default PersonaAvatar;
