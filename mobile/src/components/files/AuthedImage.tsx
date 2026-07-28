/**
 * Phase F1 · AuthedImage — renders an image from the file-upload API
 * using ?auth={token} query-param auth (acceptable on mobile per spec).
 *
 * Uses expo-image <Image> with the authed URL. Shows ActivityIndicator
 * while loading and a fallback icon on error.
 */
import React, { useEffect, useState } from "react";
import { ActivityIndicator, StyleSheet, View } from "react-native";
import { Image } from "expo-image";
import { Ionicons } from "@expo/vector-icons";
import { getAuthToken } from "@/src/api";
import { buildAuthedDownloadUrl } from "@/src/api/files";
import { colors, radius } from "@/src/theme";

type Props = {
  fileId: string;
  alt?: string;
  style?: any;
  size?: number;
  fallback?: React.ReactNode;
};

export function AuthedImage({ fileId, alt, style, size = 96, fallback }: Props) {
  const [uri, setUri] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(false);
    setUri(null);

    getAuthToken().then((token) => {
      if (cancelled) return;
      const url = buildAuthedDownloadUrl(fileId, token);
      setUri(url);
    }).catch(() => {
      if (!cancelled) setError(true);
    });

    return () => { cancelled = true; };
  }, [fileId]);

  const boxStyle = { width: size, height: size, borderRadius: radius.sm };

  if (error) {
    if (fallback !== undefined) return <>{fallback}</>;
    return (
      <View style={[styles.placeholder, boxStyle, style]} testID={`authed-image-${fileId}-error`}>
        <Ionicons name="image-outline" size={Math.max(14, size / 3)} color={colors.muted} />
      </View>
    );
  }

  if (!uri || loading) {
    return (
      <View style={[styles.placeholder, boxStyle, style]} testID={`authed-image-${fileId}-loading`}>
        <ActivityIndicator size="small" color={colors.muted} />
        {/* Image is pre-loaded below so onLoad/onError can fire */}
        {uri ? (
          <Image
            source={{ uri }}
            style={{ width: 0, height: 0, position: "absolute" }}
            onLoad={() => setLoading(false)}
            onError={() => { setLoading(false); setError(true); }}
            accessibilityLabel={alt}
          />
        ) : null}
      </View>
    );
  }

  return (
    <Image
      source={{ uri }}
      style={[boxStyle, style]}
      contentFit="cover"
      accessibilityLabel={alt}
      testID={`authed-image-${fileId}`}
      onError={() => setError(true)}
    />
  );
}

const styles = StyleSheet.create({
  placeholder: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.sm,
    alignItems: "center",
    justifyContent: "center",
    overflow: "hidden",
  },
});

export default AuthedImage;
