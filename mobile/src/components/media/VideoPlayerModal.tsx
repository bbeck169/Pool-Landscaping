/**
 * Phase 5B · VideoPlayerModal — full-screen video player.
 * Uses expo-video (SDK 54+) with useVideoPlayer + VideoView.
 */
import React, { useEffect, useState, useCallback } from "react";
import {
  View,
  Text,
  Modal,
  StyleSheet,
  TouchableOpacity,
  ActivityIndicator,
  Platform,
} from "react-native";
import { VideoView, useVideoPlayer } from "expo-video";
import { Ionicons } from "@expo/vector-icons";
import { font, fontSize, spacing } from "@/src/theme";
import { buildStreamUrl } from "@/src/api/media";

type Props = {
  visible: boolean;
  storagePath: string | null;
  caption?: string;
  onClose: () => void;
};

export default function VideoPlayerModal({ visible, storagePath, caption, onClose }: Props) {
  const [streamUrl, setStreamUrl] = useState<string | null>(null);
  const [error, setError] = useState("");

  const resolveUrl = useCallback(async () => {
    if (!storagePath) return;
    setError("");
    try {
      const url = await buildStreamUrl(storagePath);
      setStreamUrl(url);
    } catch (e: any) {
      setError(e.message || "Could not load video.");
    }
  }, [storagePath]);

  useEffect(() => {
    if (visible && storagePath) {
      resolveUrl();
    } else {
      setStreamUrl(null);
      setError("");
    }
  }, [visible, storagePath, resolveUrl]);

  // Create player with resolved URL
  const player = useVideoPlayer(streamUrl || "", (p) => {
    if (streamUrl) {
      p.play();
    }
  });

  return (
    <Modal
      visible={visible}
      animationType="fade"
      presentationStyle="overFullScreen"
      onRequestClose={onClose}
      testID="video-player-modal"
    >
      <View style={styles.root}>
        {/* Close button */}
        <TouchableOpacity
          style={styles.closeBtn}
          onPress={onClose}
          testID="video-player-close"
          hitSlop={12}
          activeOpacity={0.7}
        >
          <Ionicons name="close" size={28} color="#fff" />
        </TouchableOpacity>

        {/* Video or loading/error */}
        {error ? (
          <View style={styles.center}>
            <Ionicons name="alert-circle-outline" size={40} color="#ef4444" />
            <Text style={styles.errorText}>{error}</Text>
          </View>
        ) : !streamUrl ? (
          <View style={styles.center}>
            <ActivityIndicator size="large" color="#fff" />
            <Text style={styles.loadingText}>Loading video…</Text>
          </View>
        ) : (
          <VideoView
            style={styles.player}
            player={player}
            nativeControls={true}
            allowsFullscreen={true}
            testID="video-player-view"
          />
        )}

        {/* Caption */}
        {caption ? (
          <View style={styles.captionBar}>
            <Text style={styles.captionText}>{caption}</Text>
          </View>
        ) : null}
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.95)",
    justifyContent: "center",
    alignItems: "center",
  },
  closeBtn: {
    position: "absolute",
    top: Platform.OS === "ios" ? 56 : 32,
    right: 20,
    zIndex: 10,
    padding: 6,
    backgroundColor: "rgba(0,0,0,0.5)",
    borderRadius: 20,
  },
  center: {
    alignItems: "center",
    gap: 12,
    padding: 32,
  },
  loadingText: {
    color: "rgba(255,255,255,0.7)",
    fontFamily: font.regular,
    fontSize: fontSize.sm,
  },
  errorText: {
    color: "#ef4444",
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    textAlign: "center",
  },
  player: {
    width: "100%",
    height: "70%",
  },
  captionBar: {
    position: "absolute",
    bottom: 40,
    left: 0,
    right: 0,
    paddingHorizontal: spacing.lg,
    alignItems: "center",
  },
  captionText: {
    color: "#fff",
    fontFamily: font.semibold,
    fontSize: fontSize.base,
    textAlign: "center",
  },
});
