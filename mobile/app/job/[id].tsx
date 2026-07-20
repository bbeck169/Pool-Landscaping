import React, { useCallback, useState } from "react";
import { View, Text, ScrollView, Pressable, Linking, StyleSheet } from "react-native";
import { Image } from "expo-image";
import * as ImagePicker from "expo-image-picker";
import { LinearGradient } from "expo-linear-gradient";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { useAttendance } from "@/src/hooks/useAttendance";
import { useOnline, queuePhoto, pendingForJob, flushPendingPhotos, getCachedJobs, cacheJob, getCachedJob, queueMutation, flushPendingMutations } from "@/src/offline";
import { colors, spacing, money, IMAGES } from "@/src/theme";
import { Loading, StatusChip, PrimaryButton, Sheet } from "@/src/components/ui";
import { styles } from "@/src/components/job/styles";
import { colors as themeColors, spacing as themeSpacing, radius as themeRadius, font as themeFont } from "@/src/theme";
import FieldReport from "@/src/components/job/FieldReport";

// Phase 49.0 — inline styles for the "Open Service Report" CTA. Kept
// local so we don't touch the shared `styles` module.
const openReportBtn = {
  flexDirection: "row" as const,
  alignItems: "center" as const,
  justifyContent: "center" as const,
  gap: 8,
  backgroundColor: themeColors.brand,
  paddingVertical: 14,
  borderRadius: themeRadius.md,
  marginVertical: themeSpacing.md,
};
const openReportBtnText = {
  fontFamily: themeFont.bold,
  fontSize: 14,
  color: "#fff",
  letterSpacing: 0.7,
};
import MaintenanceLog from "@/src/components/job/MaintenanceLog";
import ServiceIssues from "@/src/components/job/ServiceIssues";
import PhotoCarousel from "@/src/components/job/PhotoCarousel";
import Row from "@/src/components/job/Row";
import JobTimerCard from "@/src/components/job/JobTimerCard";
import VideoMediaUploader from "@/src/components/media/VideoMediaUploader";

export default function JobDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { user } = useAuth();
  const router = useRouter();
  const attendance = useAttendance();
  const insets = useSafeAreaInsets();
  const [job, setJob] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [techSheet, setTechSheet] = useState(false);
  const [techs, setTechs] = useState<any[]>([]);
  const [photoSheet, setPhotoSheet] = useState(false);
  const [permSheet, setPermSheet] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [onWaySending, setOnWaySending] = useState(false);
  const [onWaySent, setOnWaySent] = useState(false);
  const [pendingPhotos, setPendingPhotos] = useState<any[]>([]);
  // Feb-2026 MP2 UI — property info displayed alongside customer.
  const [property, setProperty] = useState<any>(null);
  const online = useOnline();

  // Phase 47 follow-up — removed the "tech must be clocked in" redirect
  // that used to send technicians to `/(app)/schedule` here. Techs now
  // land on the workstream list at `/(app)/jobs` and tap VIEW DETAILS to
  // reach this screen; forcing a redirect broke that flow. Any per-action
  // clock-in enforcement should happen at the mutating action layer, not
  // at read time.

  const load = useCallback(async () => {
    try {
      // Sync any offline-captured photos & mutations first, then refresh.
      await flushPendingMutations().catch(() => null);
      await flushPendingPhotos().catch(() => null);
      const fresh = await api.get(`/jobs/${id}`);
      setJob(fresh);
      cacheJob(fresh);
      // Feb-2026 MP2 UI — hydrate property info when the job carries
      // a property_id so techs can see label + address on-site.
      if (fresh?.property_id) {
        try {
          const p = await api.get(`/properties/${fresh.property_id}`);
          setProperty(p);
        } catch {
          setProperty(null);
        }
      } else {
        setProperty(null);
      }
      setPendingPhotos(await pendingForJob(id));
    } catch (e) {
      // Offline — use the single-job cache, then fall back to the cached schedule.
      let found: any = await getCachedJob(id as string);
      if (!found) {
        const roleKey = `${user?.role}_${user?.id}`;
        const cached = await getCachedJobs(roleKey);
        if (cached) found = cached.find((j: any) => j.id === id) || null;
      }
      if (found) setJob(found);
      setPendingPhotos(await pendingForJob(id));
    } finally {
      setLoading(false);
    }
  }, [id, user?.role, user?.id]);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load, online])
  );

  const isAdmin = user?.role === "admin";
  const isCustomer = user?.role === "customer";
  const canManage = user?.role === "admin" || user?.role === "technician";

  const pickPhoto = async (source: "camera" | "library") => {
    try {
      const perm =
        source === "camera"
          ? await ImagePicker.requestCameraPermissionsAsync()
          : await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!perm.granted) {
        setPhotoSheet(false);
        if (!perm.canAskAgain) setPermSheet(true);
        return;
      }
      const opts: ImagePicker.ImagePickerOptions = { base64: true, quality: 0.5, allowsEditing: true };
      const result =
        source === "camera"
          ? await ImagePicker.launchCameraAsync(opts)
          : await ImagePicker.launchImageLibraryAsync(opts);
      if (result.canceled || !result.assets?.[0]?.base64) return;
      const dataUri = `data:image/jpeg;base64,${result.assets[0].base64}`;
      setPhotoSheet(false);
      setUploading(true);
      if (online) {
        try {
          setJob(await api.post(`/jobs/${id}/photos`, { data: dataUri, label: "Service Image" }));
          return;
        } catch (e) {
          // fall through to offline queue
        }
      }
      // Offline (or upload failed) — queue locally and show optimistically.
      await queuePhoto({ jobId: id as string, data: dataUri, label: "Service Image" });
      setPendingPhotos(await pendingForJob(id));
    } catch (e) {
      // swallow — user can retry
    } finally {
      setUploading(false);
    }
  };

  const removePhoto = async (pid: string) => {
    setJob(await api.del(`/jobs/${id}/photos/${pid}`));
  };

  const sendOnMyWay = async () => {
    setOnWaySending(true);
    try {
      await api.post(`/jobs/${id}/on-my-way`);
      setOnWaySent(true);
    } catch (e) {
      // retry allowed
    } finally {
      setOnWaySending(false);
    }
  };

  const setStatus = async (status: string) => {
    setBusy(true);
    try {
      if (online) {
        const updated = await api.put(`/jobs/${id}`, { status });
        setJob(updated);
        cacheJob(updated);
      } else {
        const optimistic = { ...job, status };
        setJob(optimistic);
        cacheJob(optimistic);
        await queueMutation(`/jobs/${id}`, { status });
      }
    } catch {
      // If the online call failed, queue it so the change isn't lost.
      const optimistic = { ...job, status };
      setJob(optimistic);
      cacheJob(optimistic);
      await queueMutation(`/jobs/${id}`, { status });
    } finally {
      setBusy(false);
    }
  };

  const openTechSheet = async () => {
    setTechs(await api.get("/technicians"));
    setTechSheet(true);
  };

  const assignTech = async (tid: string) => {
    setTechSheet(false);
    setBusy(true);
    try {
      setJob(await api.put(`/jobs/${id}`, { technician_id: tid }));
    } finally {
      setBusy(false);
    }
  };

  if (loading) return <Loading testID="job-detail-loading" />;
  if (!job) return null;

  const st = (job.service_type || "").toLowerCase();
  const maintType: "filter" | "salt_cell" | null =
    job.maintenance_type === "filter" || job.maintenance_type === "salt_cell"
      ? job.maintenance_type
      : st.includes("salt")
      ? "salt_cell"
      : st.includes("filter")
      ? "filter"
      : null;

  return (
    <View style={styles.root}>
      <ScrollView contentContainerStyle={{ paddingBottom: 120 }} testID="job-detail-scroll">
        <View style={styles.hero}>
          <Image source={{ uri: IMAGES.jobPlaceholder }} style={StyleSheet.absoluteFill} contentFit="cover" />
          <LinearGradient colors={["rgba(0,0,0,0.15)", "rgba(26,43,60,0.9)"]} style={StyleSheet.absoluteFill} />
          <Pressable style={[styles.backBtn, { top: insets.top + 8 }]} onPress={() => router.back()} testID="job-back">
            <Ionicons name="chevron-back" size={24} color="#fff" />
          </Pressable>
          <View style={styles.heroContent}>
            <StatusChip status={job.status} testID="job-status-chip" />
            <Text style={styles.heroTitle}>{job.title}</Text>
            <Text style={styles.heroCustomer}>{job.customer_name}</Text>
          </View>
        </View>

        <View style={styles.body}>
          {/* Feb-2026 MP2 UI — property card. Only rendered when the
              job has a property_id AND the property fetch succeeded.
              Legacy jobs (no property) render the customer-level
              address as before via the Address row below. */}
          {property ? (
            <View
              style={{
                marginBottom: spacing.md,
                padding: spacing.md,
                borderRadius: 12,
                backgroundColor: colors.surfaceMuted,
                borderWidth: 1,
                borderColor: colors.border,
              }}
              testID="job-property-card"
            >
              <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}>
                <Ionicons name="home-outline" size={16} color={colors.brand} />
                <Text
                  style={{ fontFamily: themeFont.bold, color: colors.onSurface, fontSize: 14 }}
                  testID="job-property-label"
                >
                  {property.label || "Property"}
                </Text>
              </View>
              <Text
                style={{ marginTop: 4, color: colors.onSurfaceSecondary, fontSize: 13 }}
                testID="job-property-address"
              >
                {[property.address?.line1, property.address?.city, property.address?.state, property.address?.postal_code].filter(Boolean).join(", ")}
              </Text>
              {property.service_notes?.pool || property.service_notes?.landscape ? (
                <Text
                  style={{ marginTop: 6, color: colors.onSurfaceSecondary, fontSize: 12, fontStyle: "italic" }}
                  numberOfLines={2}
                  testID="job-property-note"
                >
                  {property.service_notes.pool || property.service_notes.landscape}
                </Text>
              ) : null}
            </View>
          ) : null}
          <Row icon="pricetag-outline" label="Service Type" value={job.service_type} />
          <Row icon="calendar-outline" label="Scheduled" value={job.scheduled_date || "Unscheduled"} />
          <Row icon="location-outline" label="Address" value={job.address || "—"} />
          {user?.role !== "technician" ? <Row icon="cash-outline" label="Price" value={money(job.price)} /> : null}

          <Pressable
            style={styles.techBox}
            onPress={isAdmin ? openTechSheet : undefined}
            testID="job-assign-technician"
          >
            <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.md, flex: 1 }}>
              {job.technician_avatar ? (
                <Image source={{ uri: job.technician_avatar }} style={styles.techAvatar} />
              ) : (
                <View style={[styles.techAvatar, styles.techFallback]}>
                  <Ionicons name="person" size={18} color={colors.muted} />
                </View>
              )}
              <View>
                <Text style={styles.techLabel}>Assigned Technician</Text>
                <Text style={styles.techName}>{job.technician_name || "Unassigned"}</Text>
              </View>
            </View>
            {isAdmin ? <Ionicons name="swap-horizontal" size={20} color={colors.brand} /> : null}
          </Pressable>

          {!isCustomer ? (
            <JobTimerCard job={job} isTech={user?.role === "technician"} onStarted={load} />
          ) : null}

          {canManage && (job.status === "pending" || job.status === "active") && job.customer_id ? (
            <Pressable
              style={[styles.onWayBtn, onWaySent && styles.onWaySentBtn]}
              onPress={sendOnMyWay}
              disabled={onWaySending || onWaySent}
              testID="on-my-way-button"
            >
              <Ionicons name={onWaySent ? "checkmark-circle" : "car-outline"} size={18} color={onWaySent ? colors.success : colors.brand} />
              <Text style={[styles.onWayText, onWaySent && { color: colors.success }]}>
                {onWaySent ? "Customer notified" : onWaySending ? "Notifying…" : "Notify customer: On My Way"}
              </Text>
            </Pressable>
          ) : null}

          {job.notes ? (
            <View style={styles.notesBox}>
              <Text style={styles.notesLabel}>Notes</Text>
              <Text style={styles.notes}>{job.notes}</Text>
            </View>
          ) : null}

          {canManage && !isCustomer ? (
            // Phase 49.0 — legacy FieldReport picker retired for editors.
            // The dedicated `/job/{id}/checklist` route hosts the new
            // PoolChecklistForm (manual text-entry chemicals + readings).
            // Keeping FieldReport in read-only mode for customers because
            // it purely renders the completed-report summary, not a picker.
            <Pressable
              onPress={() => router.push(`/job/${id}/checklist`)}
              style={openReportBtn}
              testID="open-service-report-btn"
            >
              <Ionicons name="clipboard-outline" size={18} color="#fff" />
              <Text style={openReportBtnText}>OPEN SERVICE REPORT</Text>
            </Pressable>
          ) : isCustomer ? (
            <FieldReport job={job} online={online} onSaved={setJob} readOnly={true} />
          ) : null}

          {maintType ? (
            <View style={styles.reportWrap}>
              <MaintenanceLog job={job} mtype={maintType} readOnly={isCustomer} online={online} onSaved={setJob} />
            </View>
          ) : null}

          <View style={styles.photosHeader}>
            <Text style={styles.photosTitle}>Service Images ({(job.photos?.length || 0) + pendingPhotos.length})</Text>
            {canManage ? (
              <Pressable style={styles.addPhotoBtn} onPress={() => setPhotoSheet(true)} testID="add-photo-button">
                <Ionicons name="camera" size={16} color={colors.brand} />
                <Text style={styles.addPhotoText}>Add</Text>
              </Pressable>
            ) : null}
          </View>
          {(job.photos?.length || pendingPhotos.length) ? (
            isCustomer ? (
              <PhotoCarousel photos={job.photos || []} />
            ) : (
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: spacing.sm }}>
              {job.photos?.map((p: any) => (
                <View key={p.id} style={styles.photoThumb} testID={`job-photo-${p.id}`}>
                  <Image source={{ uri: p.data }} style={styles.photoImg} contentFit="cover" />
                  {canManage ? (
                    <Pressable style={styles.photoDelete} onPress={() => removePhoto(p.id)} testID={`delete-photo-${p.id}`} hitSlop={6}>
                      <Ionicons name="close" size={14} color="#fff" />
                    </Pressable>
                  ) : null}
                </View>
              ))}
              {pendingPhotos.map((p: any) => (
                <View key={p.id} style={styles.photoThumb} testID={`pending-photo-${p.id}`}>
                  <Image source={{ uri: p.data }} style={styles.photoImg} contentFit="cover" />
                  <View style={styles.photoPendingBadge}>
                    <Ionicons name="cloud-upload-outline" size={11} color="#fff" />
                    <Text style={styles.photoLabelText}>Pending</Text>
                  </View>
                </View>
              ))}
            </ScrollView>
            )
          ) : (
            <Text style={styles.noPhotos}>{canManage ? "Add photos of this service." : "No photos uploaded yet."}</Text>
          )}

          {/* Videos section – Phase 5B */}
          <VideoMediaUploader
            entityKind="job"
            entityId={id as string}
            existingVideos={job.videos || []}
            onUploaded={(v) => setJob((j: any) => ({ ...j, videos: [...(j.videos || []), v] }))}
            onDeleted={(vid) => setJob((j: any) => ({ ...j, videos: (j.videos || []).filter((vv: any) => vv.id !== vid) }))}
            onPatched={(v) => setJob((j: any) => ({ ...j, videos: (j.videos || []).map((vv: any) => (vv.id === v.id ? v : vv)) }))}
            readonly={isCustomer}
          />
        </View>

        <ServiceIssues job={job} canManage={canManage} isCustomer={isCustomer} onSaved={setJob} />
      </ScrollView>

      <View style={[styles.footer, { paddingBottom: insets.bottom + spacing.md }]}>
        {isCustomer ? (
          <View style={styles.completedBanner}>
            <Ionicons name="information-circle-outline" size={20} color={colors.brand} />
            <Text style={[styles.completedText, { color: colors.brand }]}>
              {job.status === "completed" ? "Service completed" : "Service scheduled"}
            </Text>
          </View>
        ) : job.status === "requested" && isAdmin ? (
          <PrimaryButton title="Approve & Schedule" icon="checkmark-circle-outline" onPress={() => setStatus("pending")} loading={busy} testID="job-approve-button" />
        ) : job.status === "pending" ? (
          <PrimaryButton title="Start Job" icon="play" onPress={() => setStatus("active")} loading={busy} testID="job-start-button" />
        ) : job.status === "active" ? (
          <PrimaryButton title="Mark Complete" icon="checkmark-done" variant="success" onPress={() => setStatus("completed")} loading={busy} testID="job-complete-button" />
        ) : (
          <View style={styles.completedBanner}>
            <Ionicons name="checkmark-circle" size={20} color={colors.success} />
            <Text style={styles.completedText}>Job completed</Text>
          </View>
        )}
      </View>

      <Sheet visible={techSheet} onClose={() => setTechSheet(false)} title="Assign Technician" testID="tech-sheet">
        {techs.map((t) => (
          <Pressable key={t.id} style={styles.techRow} onPress={() => assignTech(t.id)} testID={`assign-tech-${t.id}`}>
            {t.avatar ? (
              <Image source={{ uri: t.avatar }} style={styles.techAvatar} />
            ) : (
              <View style={[styles.techAvatar, styles.techFallback]}>
                <Ionicons name="person" size={18} color={colors.muted} />
              </View>
            )}
            <View style={{ flex: 1 }}>
              <Text style={styles.techName}>{t.name}</Text>
              <Text style={styles.techLabel}>{t.specialty} · {t.active_jobs} active</Text>
            </View>
            {job.technician_id === t.id ? <Ionicons name="checkmark-circle" size={22} color={colors.brand} /> : null}
          </Pressable>
        ))}
      </Sheet>

      <Sheet visible={photoSheet} onClose={() => setPhotoSheet(false)} title="Add Service Image" testID="photo-sheet">
        <Pressable style={styles.photoOpt} onPress={() => pickPhoto("camera")} testID="photo-take">
          <Ionicons name="camera-outline" size={22} color={colors.brand} />
          <Text style={styles.photoOptText}>Take Photo</Text>
        </Pressable>
        <Pressable style={styles.photoOpt} onPress={() => pickPhoto("library")} testID="photo-library">
          <Ionicons name="images-outline" size={22} color={colors.brand} />
          <Text style={styles.photoOptText}>Choose from Library</Text>
        </Pressable>
        {uploading ? <Text style={styles.uploadingText}>Uploading…</Text> : null}
      </Sheet>

      <Sheet visible={permSheet} onClose={() => setPermSheet(false)} title="Permission needed" testID="perm-sheet">
        <Text style={styles.sheetHint}>
          Camera/photo access is blocked. Enable it in Settings to add job photos.
        </Text>
        <View style={{ height: spacing.md }} />
        <PrimaryButton
          title="Open Settings"
          icon="settings-outline"
          onPress={() => {
            setPermSheet(false);
            Linking.openSettings();
          }}
          testID="open-settings-button"
        />
      </Sheet>
    </View>
  );
}
