/**
 * Phase F2a / F2c.2 · Job Before/After Photos (mobile).
 *
 * Reusable component for both:
 *   - F2a: tech/admin upload on job detail (readOnly=false)
 *   - F2c.2: customer read-only view on portal service detail (readOnly=true)
 *
 * Uses two sections: "Before" (purpose=job_before_photo) and
 * "After" (purpose=job_after_photo), both with linked_entity_type=job.
 *
 * Hidden entirely when readOnly=true AND both lists are empty.
 */
import React, { useState } from "react";
import { StyleSheet, Text, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { FileUpload } from "./FileUpload";
import { FileList } from "./FileList";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";

const ACCEPT = "image/*,video/mp4";

type Props = {
  jobId: string;
  readOnly?: boolean;
};

function PhotoSection({
  label,
  purpose,
  jobId,
  readOnly,
  onCountChange,
}: {
  label: string;
  purpose: string;
  jobId: string;
  readOnly: boolean;
  onCountChange: (count: number) => void;
}) {
  const [nonce, setNonce] = useState(0);

  return (
    <View style={styles.section} testID={`job-photos-${purpose}`}>
      <Text style={styles.sectionLabel}>{label}</Text>
      {!readOnly && (
        <FileUpload
          purpose={purpose}
          linkedEntityType="job"
          linkedEntityId={jobId}
          accept={ACCEPT}
          multiple
          maxFiles={10}
          onUploaded={() => setNonce((n) => n + 1)}
          buttonLabel="Choose Photo"
        />
      )}
      <FileList
        key={nonce}
        linkedEntityType="job"
        linkedEntityId={jobId}
        purpose={purpose}
        canDelete={!readOnly}
        onChange={(items) => onCountChange((items || []).length)}
      />
    </View>
  );
}

export function JobBeforeAfterPhotos({ jobId, readOnly = false }: Props) {
  // null = "still loading"; 0 = "loaded, empty"
  const [beforeCount, setBeforeCount] = useState<number | null>(null);
  const [afterCount, setAfterCount] = useState<number | null>(null);

  const loaded = beforeCount !== null && afterCount !== null;
  const empty = loaded && beforeCount === 0 && afterCount === 0;

  // In readOnly mode, hide entirely once we know both lists are empty
  if (readOnly && loaded && empty) {
    return <View testID="job-before-after-photos-empty" />;
  }

  // While loading in readOnly mode, render the FileLists hidden so they
  // can fetch counts — but wrap in an invisible container
  const hide = readOnly && !loaded;

  return (
    <View style={[styles.card, hide && { height: 0, overflow: "hidden", opacity: 0 }]} testID={hide ? "job-before-after-photos-loading" : "job-before-after-photos"}>
      <View style={styles.header}>
        <Ionicons name="camera-outline" size={18} color={colors.muted} />
        <Text style={styles.title}>Before &amp; After Photos</Text>
      </View>
      {!readOnly && (
        <Text style={styles.subtitle}>
          Capture the job site before and after your work.
        </Text>
      )}
      <PhotoSection
        label="Before"
        purpose="job_before_photo"
        jobId={jobId}
        readOnly={readOnly}
        onCountChange={setBeforeCount}
      />
      <PhotoSection
        label="After"
        purpose="job_after_photo"
        jobId={jobId}
        readOnly={readOnly}
        onCountChange={setAfterCount}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    padding: spacing.lg,
    marginBottom: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    marginBottom: 4,
  },
  title: {
    fontFamily: font.bold,
    fontSize: fontSize.base,
    color: colors.onSurface,
  },
  subtitle: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
    marginBottom: spacing.md,
  },
  section: {
    marginTop: spacing.md,
  },
  sectionLabel: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.onSurfaceSecondary,
    textTransform: "uppercase",
    letterSpacing: 0.8,
    marginBottom: spacing.sm,
  },
});

export default JobBeforeAfterPhotos;
