/**
 * Phase F1 · Dev-only file upload demo screen.
 *
 * Route: /dev/file-upload
 * Gated on EXPO_PUBLIC_ENV === "preview" — hidden otherwise.
 */
import React, { useState } from "react";
import {
  SafeAreaView,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { FileUpload } from "@/src/components/files/FileUpload";
import { FileList } from "@/src/components/files/FileList";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";

export default function DevFileUploadScreen() {
  const [refreshKey, setRefreshKey] = useState(0);

  // Guard: only render in preview builds
  if (process.env.EXPO_PUBLIC_ENV !== "preview") {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.center}>
          <Ionicons name="lock-closed-outline" size={32} color={colors.muted} />
          <Text style={styles.gatedText}>This screen is only available in preview builds.</Text>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container} testID="dev-file-upload-screen">
      <ScrollView contentContainerStyle={styles.scroll}>
        {/* Header */}
        <View style={styles.header}>
          <View>
            <Text style={styles.title}>File Upload Demo</Text>
            <Text style={styles.subtitle}>Dev-only smoke test for F1 file components</Text>
          </View>
        </View>

        {/* Upload Section */}
        <View style={styles.card}>
          <Text style={styles.sectionTitle}>Upload</Text>
          <FileUpload
            purpose="dev_smoke"
            linkedEntityType="dev"
            linkedEntityId="local_test"
            accept="image/*,video/mp4,application/pdf"
            multiple
            maxFiles={5}
            onUploaded={() => setRefreshKey((k) => k + 1)}
            onError={(err) => console.warn("[FileUpload error]", err)}
          />
        </View>

        {/* File List Section */}
        <View style={styles.card}>
          <Text style={styles.sectionTitle}>Uploaded Files</Text>
          <FileList
            key={refreshKey}
            linkedEntityType="dev"
            linkedEntityId="local_test"
            canDelete
          />
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.surfaceSecondary },
  scroll: { padding: spacing.lg, paddingBottom: spacing["2xl"] },
  center: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.md,
    padding: spacing.xl,
  },
  gatedText: {
    fontFamily: font.medium,
    fontSize: fontSize.base,
    color: colors.muted,
    textAlign: "center",
  },
  header: {
    marginBottom: spacing.xl,
  },
  title: {
    fontFamily: font.bold,
    fontSize: fontSize["2xl"],
    color: colors.onSurface,
  },
  subtitle: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
    marginTop: 2,
  },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.lg,
    marginBottom: spacing.lg,
  },
  sectionTitle: {
    fontFamily: font.semibold,
    fontSize: fontSize.lg,
    color: colors.onSurface,
    marginBottom: spacing.md,
  },
});
