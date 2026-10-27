import React, { useCallback, useMemo, useState } from "react";
import { View, Text, ScrollView, Pressable, Linking, StyleSheet, Alert } from "react-native";
import { Image } from "expo-image";
import * as ImagePicker from "expo-image-picker";
import { LinearGradient } from "expo-linear-gradient";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";

import { api, ApiNetworkError } from "@/src/api";
import { useAuth } from "@/src/auth";
import { useAttendance } from "@/src/hooks/useAttendance";
import { useOnline, getCachedJobs, cacheJob, getCachedJob, queueMutation, flushPendingMutations } from "@/src/offline";
import { capturePhoto, getPhotosForEntity, flushPhotos, subscribePhotos, type PendingPhoto as SyncPendingPhoto } from "@/src/services/sync/photoWorker";
import { pickImagesMulti } from "@/src/lib/pickImages";
import { enqueueJobArrive } from "@/src/services/sync/jobArrive";
import { offlineWrite } from "@/src/services/offlineWrite";
import { colors, spacing, money, IMAGES , colors as themeColors, spacing as themeSpacing, radius as themeRadius, font as themeFont } from "@/src/theme";
import { useToast } from "@/src/components/ToastProvider";
import { mapApiError, errorKindIcon } from "@/src/utils/mapApiError";
import MarcoVoiceButton from "@/src/components/marco/MarcoVoiceButton";
// Phase 1 Offline Read — route hydrator cache + write-through.
import {
  getCachedJobDetail, CK,
} from "@/src/services/routeHydrator";
import { writeCache } from "@/src/services/readCache";
// Feb-2026 · Phase 1 offline foundation — cache /properties/{id}
// on success + fall back to the SQLite cache on network failure so
// the tech can still see property address / gate code offline.
import {
  writeThroughProperty, readCachedProperty,
} from "@/src/lib/offline/apiCache";
import OfflineBadge from "@/src/components/OfflineBadge";
import { Loading, StatusChip, PrimaryButton, Sheet } from "@/src/components/ui";
import { styles } from "@/src/components/job/styles";
import { JobBeforeAfterPhotos } from "@/src/components/files";
import FieldReport from "@/src/components/job/FieldReport";
import MaintenanceLog from "@/src/components/job/MaintenanceLog";
import ServiceIssues from "@/src/components/job/ServiceIssues";
import PhotoCarousel from "@/src/components/job/PhotoCarousel";
import Row from "@/src/components/job/Row";
import JobTimerCard from "@/src/components/job/JobTimerCard";
// Feb-2026 · Slice 6 — 24h post-completion edit window (mobile).
import { isWithinEditWindow, hoursSinceCompletion, EDIT_WINDOW_HOURS } from "@/src/lib/editWindow";
import { canEditCompletedJob } from "@/src/lib/k6Unlock";
import ClosedJobEditsBanner from "@/src/components/job/ClosedJobEditsBanner";
import EditedAfterCompletionBadge from "@/src/components/job/EditedAfterCompletionBadge";
import VideoMediaUploader from "@/src/components/media/VideoMediaUploader";
import CouldNotServiceButton from "@/src/components/schedule/CouldNotServiceButton";
import LineItemsSection from "@/src/components/jobs/LineItemsSection";
import SmartBriefCard from "@/src/components/job/SmartBriefCard";
import { formatCustomerName } from "@/src/utils/formatCustomerName";
import AppTextInput from "@/src/components/ui/AppTextInput";
import { CustomerLink, AddressLink } from "@/src/components/customer";
import { absolutizeUrl } from "@/src/lib/absolutizeUrl";
// FLEET-B · Manual check-in buttons for fleet tracking.
import CheckInButtons from "@/src/components/fleet/CheckInButtons";

// P0 fix — hard timeout so the detail screen never hangs on slow networks.
const LOAD_TIMEOUT_MS = 20_000;

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

export default function JobDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { showToast } = useToast();
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
  const [pendingPhotos, setPendingPhotos] = useState<SyncPendingPhoto[]>([]);
  // Task L — service-report photos fetched from /detail endpoint.
  const [srPhotos, setSrPhotos] = useState<any[]>([]);
  // Feb-2026 MP2 UI — property info displayed alongside customer.
  const [property, setProperty] = useState<any>(null);
  // lineItems state removed — LineItemsSection component manages its own data
  const [activeSection, setActiveSection] = useState("overview");
  const online = useOnline();
  // Phase 1 Offline Read — track whether data came from cache.
  const [offlineRead, setOfflineRead] = useState(false);
  // Feb-2026 · Slice 6 — 24h post-completion edit window (mobile).
  const [editSheet, setEditSheet] = useState(false);
  const [editNotes, setEditNotes] = useState("");
  const [editReason, setEditReason] = useState("");
  const [editSaving, setEditSaving] = useState(false);
  const [editError, setEditError] = useState("");
  // P0 fix — user-visible error when load times out or fails completely.
  const [loadError, setLoadError] = useState("");
  const [rawLoadError, setRawLoadError] = useState<unknown>(null);

  // Phase 47 follow-up — removed the "tech must be clocked in" redirect
  // that used to send technicians to `/(app)/schedule` here. Techs now
  // land on the workstream list at `/(app)/jobs` and tap VIEW DETAILS to
  // reach this screen; forcing a redirect broke that flow. Any per-action
  // clock-in enforcement should happen at the mutating action layer, not
  // at read time.

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError("");
    setRawLoadError(null);
    try {
      // P0 fix: fire-and-forget — don't block the fetch on offline flushes.
      flushPendingMutations().catch(() => {});
      flushPhotos().catch(() => {});

      // P0 fix: hard 20s timeout on the main API fetch.
      const fresh = await Promise.race([
        api.get(`/jobs/${id}`),
        new Promise<never>((_, rej) =>
          setTimeout(() => rej(new Error("__LOAD_TIMEOUT__")), LOAD_TIMEOUT_MS),
        ),
      ]);
      setJob(fresh);
      setOfflineRead(false);
      cacheJob(fresh);
      // Phase 1 Offline Read — also write to SQLite read_cache.
      writeCache(CK.jobDetail(String(id)), fresh).catch(() => {});
      // Feb-2026 MP2 UI — hydrate property info when the job carries
      // a property_id so techs can see label + address on-site.
      if (fresh?.property_id) {
        try {
          const p = await api.get(`/properties/${fresh.property_id}`);
          setProperty(p);
          writeThroughProperty(p).catch(() => {});
        } catch {
          // Offline / server error — fall back to the SQLite cache
          // if we cached this property on a previous online load.
          const cachedProp = await readCachedProperty(fresh.property_id).catch(() => null);
          setProperty(cachedProp || null);
        }
      } else {
        setProperty(null);
      }
      // Line items fetching moved to LineItemsSection component
      setPendingPhotos(await getPhotosForEntity(id as string));
      // Task L — fire-and-forget /detail fetch for service_report_photos.
      // Non-blocking: failure silently leaves srPhotos empty.
      api.get(`/jobs/${id}/detail`).then((d: any) => {
        setSrPhotos(d?.service_report_photos || []);
      }).catch(() => setSrPhotos([]));
    } catch (e: any) {
      // Phase 1 Offline Read — try SQLite read_cache first (hydrator-populated),
      // then AsyncStorage caches as fallback.
      let found: any = await getCachedJobDetail(String(id)).catch(() => null);
      if (!found) found = await getCachedJob(id as string);
      if (!found) {
        const roleKey = `${user?.role}_${user?.id}`;
        const cached = await getCachedJobs(roleKey);
        if (cached) found = cached.find((j: any) => j.id === id) || null;
      }
      if (found) {
        setJob(found);
        setOfflineRead(true);
        // Try property from cache too.
        if (found.property_id) {
          const cachedProp = await readCachedProperty(found.property_id).catch(() => null);
          setProperty(cachedProp || null);
        }
      } else {
        // P0 fix: set user-visible error instead of blank screen.
        setJob(null);
        setOfflineRead(true);
        setRawLoadError(e);
        setLoadError(
          e?.message === "__LOAD_TIMEOUT__"
            ? "Loading timed out. Check your connection and try again."
            : "Couldn't load job. Retry?"
        );
      }
      setPendingPhotos(await getPhotosForEntity(id as string));
    } finally {
      setLoading(false);
    }
  }, [id, user?.role, user?.id]);

  useFocusEffect(
    useCallback(() => {
      load();
      // ``online`` is intentionally NOT a dep — reconnection refetch
      // happens via a separate effect; including it here would
      // double-fire on focus + toggle.
    }, [load])
  );

  const isAdmin = user?.role === "admin" || user?.role === "super_admin";
  const isCustomer = user?.role === "customer";
  const isTech = user?.role === "technician";
  const canManage = isAdmin || isTech;
  // TD-78b · K6 (web JobDetail parity) — K6 roles keep the Edit
  // affordance on completed jobs past the 24h window (BE
  // `role_bypasses_edit_window`); the banner tells them edits are logged.
  const canEditCompleted = !isCustomer && canEditCompletedJob(user?.role, job);
  const inEditWindow = !isCustomer && isWithinEditWindow(job);
  const canEditNow = inEditWindow || canEditCompleted;
  const editHoursLeft = inEditWindow
    ? Math.max(0, EDIT_WINDOW_HOURS - (hoursSinceCompletion(job) || 0))
    : null;

  const openEditSheet = () => {
    setEditNotes(String(job?.notes || ""));
    setEditReason("");
    setEditError("");
    setEditSheet(true);
  };

  const saveEdit = async () => {
    if (editSaving || !job?.id) return;
    setEditSaving(true);
    setEditError("");
    try {
      const body: any = { notes: editNotes, edit_source: "mobile" };
      const trimmed = editReason.trim();
      if (trimmed) body.edit_reason = trimmed;
      const { data: fresh, queued } = await offlineWrite({
        op_type: "job.update",
        entity_id: job.id,
        endpoint: `/jobs/${job.id}`,
        method: "PATCH",
        payload: body,
        onlineFn: () => api.patch(`/jobs/${job.id}`, body),
      });
      if (fresh) setJob(fresh);
      else if (queued) {
        // Optimistic: apply locally.
        setJob({ ...job, ...body });
      }
      setEditSheet(false);
    } catch (e: any) {
      const detail = e?.detail || e?.data?.detail;
      if (detail && typeof detail === "object") {
        if (detail.detail === "edit_window_expired") {
          setEditError(
            `Edit window closed (${detail.edit_window_hours || EDIT_WINDOW_HOURS}h).`,
          );
        } else {
          setEditError(detail.message || detail.detail || "Save failed.");
        }
      } else {
        setEditError(e?.message || "Save failed.");
      }
    } finally {
      setEditSaving(false);
    }
  };
  const MAX_PHOTOS = 10;
  const MAX_VIDEOS = 3;
  const photoCount = (job?.photos?.length || 0) + pendingPhotos.length;
  const videoCount = job?.videos?.length || 0;
  const photoCapHit = photoCount >= MAX_PHOTOS;
  const videoCapHit = videoCount >= MAX_VIDEOS;

  // Task L — merge job.photos + service_report_photos for unified display.
  // Backend deduplicates (SR wins on ID collision), so concat is safe.
  const allPhotos = useMemo(() => {
    const jp = (job?.photos || []).map((p: any) => ({ ...p, _source: "job" }));
    const sr = srPhotos.map((p: any) => ({ ...p, _source: "service_report" }));
    return [...sr, ...jp];
  }, [job?.photos, srPhotos]);
  const displayPhotoCount = allPhotos.length + pendingPhotos.length;

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
      // Phase P21 — no {base64: true}; use URI-only path to avoid OOM.
      // TD-88e — library is multi-select (cap = MAX_PHOTOS - photoCount);
      // camera stays single-shot with crop.
      let uris: string[];
      if (source === "camera") {
        const opts: ImagePicker.ImagePickerOptions = { quality: 0.7, allowsEditing: true };
        const result = await ImagePicker.launchCameraAsync(opts);
        if (result.canceled || !result.assets?.[0]?.uri) return;
        uris = [result.assets[0].uri];
      } else {
        const assets = await pickImagesMulti({ remainingCap: MAX_PHOTOS - photoCount, quality: 0.7 });
        if (!assets) return;
        uris = assets.map((a) => a.uri);
      }
      setPhotoSheet(false);
      setUploading(true);
      // Route each asset through the durable SQLite photoWorker pipeline.
      // It downscales, stages to filesystem, inserts into SQLite,
      // and flushes upload when online — no base64 in JS memory.
      for (const rawUri of uris) {
        try { await capturePhoto(rawUri, "job", id as string); } catch { /* user can retry */ }
      }
      setPendingPhotos(await getPhotosForEntity(id as string));
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
      if (online) {
        await api.post(`/jobs/${id}/on-my-way`);
      }
      // Always enqueue job.arrive through the sync queue for offline resilience.
      await enqueueJobArrive(id as string);
      setOnWaySent(true);
    } catch (e) {
      // Offline fallback — still enqueue so it fires on reconnect.
      try { await enqueueJobArrive(id as string); setOnWaySent(true); } catch { /* */ }
    } finally {
      setOnWaySending(false);
    }
  };

  const setStatus = async (status: string) => {
    setBusy(true);
    try {
      const body = { status };
      const { data: updated, queued } = await offlineWrite({
        op_type: status === "completed" ? "job.complete" : "job.status",
        entity_id: id as string,
        endpoint: `/jobs/${id}`,
        method: "PUT",
        payload: body,
        onlineFn: () => api.put(`/jobs/${id}`, body),
      });
      if (updated) {
        setJob(updated);
        cacheJob(updated);
      } else if (queued) {
        // Phase 2 — optimistic UI fires immediately.
        const optimistic = { ...job, status };
        setJob(optimistic);
        cacheJob(optimistic);
        showToast("Saved — will sync when online", "info");
      }
    } catch {
      // Last resort — optimistic update + legacy queue.
      const optimistic = { ...job, status };
      setJob(optimistic);
      cacheJob(optimistic);
      await queueMutation(`/jobs/${id}`, { status });
      showToast("Saved — will sync when online", "info");
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
      const body = { technician_id: tid };
      const { data: fresh, queued } = await offlineWrite({
        op_type: "job.assign",
        entity_id: id as string,
        endpoint: `/jobs/${id}`,
        method: "PUT",
        payload: body,
        onlineFn: () => api.put(`/jobs/${id}`, body),
      });
      if (fresh) setJob(fresh);
      else if (queued) setJob({ ...job, technician_id: tid } as any);
    } finally {
      setBusy(false);
    }
  };

  if (loading) return <Loading testID="job-detail-loading" />;
  // P0 fix — timeout / network error with no cache → show retry UI.
  if (!job && !loading && loadError) {
    const mapped = rawLoadError ? mapApiError(rawLoadError) : null;
    const icon = mapped ? errorKindIcon(mapped.kind) : "warning-outline";
    return (
      <View style={styles.root} testID="job-detail-error">
        <View style={{ flex: 1, alignItems: "center", justifyContent: "center", padding: spacing.lg }}>
          <Pressable style={[styles.backBtn, { top: insets.top + 8, left: 12, position: "absolute" }]} onPress={() => router.back()} testID="job-back-error">
            <Ionicons name="chevron-back" size={24} color={themeColors.onSurface} />
          </Pressable>
          <Ionicons name={icon as any} size={48} color={themeColors.muted} />
          <Text style={{ fontFamily: themeFont.bold, fontSize: 18, color: themeColors.onSurface, marginTop: spacing.md, textAlign: "center" }} testID="job-detail-error-message">
            {mapped?.title || loadError}
          </Text>
          {mapped && mapped.message !== mapped.title && (
            <Text style={{ fontFamily: themeFont.regular, fontSize: 14, color: themeColors.muted, marginTop: spacing.sm, textAlign: "center" }}>
              {mapped.message}
            </Text>
          )}
          <Pressable
            style={{ marginTop: spacing.lg, paddingHorizontal: spacing.lg, paddingVertical: spacing.md, backgroundColor: themeColors.brand, borderRadius: themeRadius.md }}
            onPress={load}
            testID="job-detail-retry-btn"
          >
            <Text style={{ fontFamily: themeFont.bold, fontSize: 14, color: "#fff" }}>Retry</Text>
          </Pressable>
        </View>
      </View>
    );
  }
  // Phase 1 Offline Read — clean empty state for uncached offline jobs.
  if (!job && !loading) {
    return (
      <View style={styles.root}>
        <View style={{ flex: 1, alignItems: "center", justifyContent: "center", padding: spacing.lg }}>
          <Pressable style={[styles.backBtn, { top: insets.top + 8, left: 12, position: "absolute" }]} onPress={() => router.back()} testID="job-back-empty">
            <Ionicons name="chevron-back" size={24} color={themeColors.onSurface} />
          </Pressable>
          <Ionicons name={online ? "help-circle-outline" : "cloud-offline-outline"} size={48} color={themeColors.muted} />
          <Text style={{ fontFamily: themeFont.bold, fontSize: 18, color: themeColors.onSurface, marginTop: spacing.md, textAlign: "center" }}>
            {online ? "Job not found" : "Not cached for offline"}
          </Text>
          <Text style={{ fontFamily: themeFont.regular, fontSize: 14, color: themeColors.muted, marginTop: spacing.sm, textAlign: "center" }} testID="job-detail-not-cached-msg">
            {online ? "This job may have been removed." : "Connect to Wi-Fi or cellular once to cache this job for offline use."}
          </Text>
          <Pressable style={{ marginTop: spacing.lg, paddingHorizontal: spacing.lg, paddingVertical: spacing.md, backgroundColor: themeColors.brand, borderRadius: themeRadius.md }} onPress={() => router.back()} testID="job-detail-go-back-btn">
            <Text style={{ fontFamily: themeFont.bold, fontSize: 14, color: "#fff" }}>Go back</Text>
          </Pressable>
        </View>
      </View>
    );
  }
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
          {/* Feb-2026 · Phase 1 offline foundation — floating "Offline"
              pill above the hero.  Only renders when netinfo reports
              disconnected; on the hero image a light chip stays legible. */}
          <View
            style={{ position: "absolute", right: 12, top: insets.top + 12 }}
            testID="job-detail-header-offline-badge-wrap"
            pointerEvents="none"
          >
            <OfflineBadge testID="job-detail-header-offline-badge" />
          </View>
          <View style={styles.heroContent}>
            {/* WW — POST-edit badge next to the status chip (BE denorm). */}
            <View style={{ flexDirection: "row", alignItems: "center", flexWrap: "wrap", gap: 8 }} testID="job-status-row">
              <StatusChip status={job.status} testID="job-status-chip" />
              <EditedAfterCompletionBadge visible={job.edited_after_completion === true} />
            </View>
            <Text style={styles.heroTitle}>{job.title}</Text>
            <CustomerLink customerId={job.customer_id} name={formatCustomerName(job)} style={styles.heroCustomer} testID="job-customer-link" />
          </View>
        </View>

        <View style={styles.body}>
          {/* TD-78b — "Closed job — edits logged" (completed + K6 role). */}
          {canEditCompleted ? <ClosedJobEditsBanner /> : null}
          {/* A5 · Smart Brief — tech intelligence pane at top of job detail */}
          <SmartBriefCard jobId={id as string} testID="smart-brief" />
          {/* Phase 1 Offline Read — "showing cached copy" banner */}
          {offlineRead && !online ? (
            <View style={{ flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: "#FEF3C7", paddingHorizontal: 12, paddingVertical: 8, borderRadius: 8, marginBottom: spacing.md }} testID="job-detail-cached-banner">
              <Ionicons name="cloud-done-outline" size={14} color="#92400E" />
              <Text style={{ fontFamily: themeFont.medium, fontSize: 12, color: "#92400E" }}>You're offline — showing cached copy</Text>
            </View>
          ) : null}
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
              <AddressLink
                address={[property.address?.line1, property.address?.city, property.address?.state, property.address?.postal_code].filter(Boolean).join(", ")}
                showIcon={false}
                style={{ marginTop: 4, color: colors.onSurfaceSecondary, fontSize: 13 }}
                testID="job-property-address"
              />
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
          <View style={{ flexDirection: "row", alignItems: "center", paddingVertical: 10, gap: 10, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border }}>
            <Ionicons name="location-outline" size={16} color={colors.brand} />
            <AddressLink address={job.address || "—"} showIcon={false} testID="job-address-link" />
          </View>
          {!isTech ? <Row icon="cash-outline" label="Price" value={money(job.price)} /> : null}

          {/* F7 Line Items CRUD — full editor (admin: price/category/writeback; tech: qty+desc) */}
          {(isAdmin || isTech) ? (
            <LineItemsSection jobId={id as string} jobStatus={job.status} />
          ) : null}

          <Pressable
            style={styles.techBox}
            onPress={isAdmin ? openTechSheet : undefined}
            testID="job-assign-technician"
          >
            <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.md, flex: 1 }}>
              {(job.assignee_photo_url || job.technician_avatar) ? (
                <Image
                  source={{ uri: (job.assignee_photo_url || job.technician_avatar) as string }}
                  style={styles.techAvatar}
                  testID="job-assignee-avatar"
                />
              ) : (
                <View style={[styles.techAvatar, styles.techFallback]}
                      testID="job-assignee-avatar-fallback">
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

          {canManage && job.id ? (
            <CouldNotServiceButton
              jobId={job.id}
              jobStatus={job.status}
              role={user?.role || ""}
              variant="detail"
              onDone={load}
              testID="could-not-service-detail-btn"
            />
          ) : null}

          {/* FLEET-B · Fleet check-in buttons — On My Way / Arrived */}
          {canManage && job.id && (job.status === "pending" || job.status === "active") ? (
            <CheckInButtons jobId={job.id} testID="fleet-checkin-section" />
          ) : null}

          {/* Tech Check-In — public customer feed entry */}
          {canManage && job.id ? (
            <Pressable
              style={{
                flexDirection: "row",
                alignItems: "center",
                justifyContent: "center",
                gap: 8,
                backgroundColor: "#ECFDF5",
                paddingVertical: 14,
                borderRadius: themeRadius.md,
                borderWidth: 1,
                borderColor: "#A7F3D0",
                marginTop: themeSpacing.sm,
              }}
              onPress={() => router.push(`/job/${id}/checkin`)}
              testID="job-detail-log-checkin-btn"
            >
              <Ionicons name="location" size={18} color="#059669" />
              <Text style={{ fontFamily: themeFont.bold, fontSize: 14, color: "#059669", letterSpacing: 0.5 }}>
                Log Check-In
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
            <Text style={styles.photosTitle}>Service Images ({displayPhotoCount}/{MAX_PHOTOS})</Text>
            {canManage && !photoCapHit ? (
              <Pressable style={styles.addPhotoBtn} onPress={() => setPhotoSheet(true)} testID="add-photo-button">
                <Ionicons name="camera" size={16} color={colors.brand} />
                <Text style={styles.addPhotoText}>Add</Text>
              </Pressable>
            ) : photoCapHit && canManage ? (
              <Text style={{ fontSize: 11, color: colors.muted, fontFamily: themeFont.medium }} testID="photo-cap-reached">
                {MAX_PHOTOS}/{MAX_PHOTOS} limit
              </Text>
            ) : null}
          </View>
          {(allPhotos.length || pendingPhotos.length) ? (
            isCustomer ? (
              <PhotoCarousel photos={allPhotos} />
            ) : (
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: spacing.sm }}>
              {allPhotos.map((p: any) => (
                <View key={p.id} style={styles.photoThumb} testID={`job-photo-${p.id}`}>
                  <Image source={{ uri: absolutizeUrl(p.url || p.data) }} style={styles.photoImg} contentFit="cover" />
                  {canManage && p._source !== "service_report" ? (
                    <Pressable style={styles.photoDelete} onPress={() => removePhoto(p.id)} testID={`delete-photo-${p.id}`} hitSlop={6}>
                      <Ionicons name="close" size={14} color="#fff" />
                    </Pressable>
                  ) : null}
                  {p._source === "service_report" ? (
                    <View style={styles.photoPendingBadge}>
                      <Ionicons name="document-text-outline" size={11} color="#fff" />
                      <Text style={styles.photoLabelText}>SR</Text>
                    </View>
                  ) : null}
                </View>
              ))}
              {pendingPhotos.map((p) => (
                <View key={p.id} style={styles.photoThumb} testID={`pending-photo-${p.id}`}>
                  <Image source={{ uri: p.local_uri }} style={styles.photoImg} contentFit="cover" />
                  <View style={styles.photoPendingBadge}>
                    <Ionicons name="cloud-upload-outline" size={11} color="#fff" />
                    <Text style={styles.photoLabelText}>
                      {p.upload_status === "stalled" ? "Failed" : "Pending"}
                    </Text>
                  </View>
                </View>
              ))}
            </ScrollView>
            )
          ) : (
            <Text style={styles.noPhotos}>{canManage ? "Add photos of this service." : "No photos uploaded yet."}</Text>
          )}

          {/* Videos section – Phase 5B — 3-video cap */}
          <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: spacing.md, marginBottom: 4 }}>
            <Text style={styles.photosTitle}>Videos ({videoCount}/{MAX_VIDEOS})</Text>
            {videoCapHit && canManage ? (
              <Text style={{ fontSize: 11, color: colors.muted, fontFamily: themeFont.medium }} testID="video-cap-reached">
                {MAX_VIDEOS}/{MAX_VIDEOS} limit
              </Text>
            ) : null}
          </View>
          <VideoMediaUploader
            entityKind="job"
            entityId={id as string}
            existingVideos={job.videos || []}
            maxVideos={MAX_VIDEOS}
            onUploaded={(v) => setJob((j: any) => ({ ...j, videos: [...(j.videos || []), v] }))}
            onDeleted={(vid) => setJob((j: any) => ({ ...j, videos: (j.videos || []).filter((vv: any) => vv.id !== vid) }))}
            onPatched={(v) => setJob((j: any) => ({ ...j, videos: (j.videos || []).map((vv: any) => (vv.id === v.id ? v : vv)) }))}
            readonly={isCustomer}
          />

          {/* F2a — Before/After Photos (F0 pipeline).
              Tech + admin: full upload.  Customer: read-only (hidden if empty). */}
          <View style={{ marginTop: spacing.md }}>
            <JobBeforeAfterPhotos jobId={id!} readOnly={isCustomer} />
          </View>
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
          <View>
            <PrimaryButton title="Mark Complete" icon="checkmark-done" variant="success" onPress={() => setStatus("completed")} loading={busy} testID="job-complete-button" />
            <View style={styles.autoNotifyBanner} testID="auto-send-completion-banner">
              <Ionicons name="mail-outline" size={14} color={colors.muted} />
              <Text style={styles.autoNotifyText}>
                A completion summary will be sent to the customer automatically.
              </Text>
            </View>
          </View>
        ) : (
          <View style={styles.completedBanner}>
            <Ionicons name="checkmark-circle" size={20} color={colors.success} />
            <Text style={styles.completedText}>Job completed</Text>
            {canEditNow ? (
              <Pressable
                onPress={openEditSheet}
                testID="job-edit-open"
                disabled={!online}
                style={{
                  marginLeft: "auto",
                  paddingHorizontal: spacing.md,
                  paddingVertical: spacing.sm,
                  borderRadius: 8,
                  backgroundColor: online ? colors.brand : colors.muted,
                  opacity: online ? 1 : 0.6,
                }}
              >
                <Text
                  style={{ color: "#fff", fontWeight: "600", fontSize: 13 }}
                  testID="job-edit-button-label"
                >
                  {online
                    ? editHoursLeft != null
                      ? `Edit (${editHoursLeft.toFixed(1)}h left)`
                      : "Edit"
                    : "Online required to edit"}
                </Text>
              </Pressable>
            ) : null}
          </View>
        )}

        {/* Feb-2026 · "+ New Scheduled Job" quick-action — parity
            with the web JobDetail button. Pushes the existing
            /job/new route with pre-fill query params derived from
            this job; the form hydrates them once the customer /
            technician pickers finish loading. Admin-only, matches
            the web permission gate. */}
        {isAdmin ? (
          <Pressable
            style={styles.newJobBtn}
            onPress={() =>
              router.push({
                pathname: "/job/new",
                params: {
                  customer_id: job.customer_id || "",
                  technician_id: job.technician_id || "",
                  // Feb-2026 bug fix — service_type MUST start blank
                  // in the new-job form so the admin re-picks it for
                  // the next visit. Prior version forwarded
                  // ``job.service_type`` which caused the modal to
                  // arrive pre-populated with "Pool Cleaning" etc.
                  service_type: "",
                  scheduled_date: new Date().toISOString().slice(0, 10),
                },
              })
            }
            testID="jd-new-scheduled-job"
          >
            <Ionicons name="add" size={18} color={colors.brand} />
            <Text style={styles.newJobBtnText}>New Scheduled Job</Text>
          </Pressable>
        ) : null}
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

      <Sheet
        visible={editSheet}
        onClose={() => setEditSheet(false)}
        title="Edit completed job"
        testID="job-edit-sheet"
      >
        <Text style={styles.sheetHint} testID="job-edit-sheet-hint">
          Edits within the {EDIT_WINDOW_HOURS}h window do not re-send
          customer notifications.
        </Text>
        <View style={{ height: spacing.sm }} />
        <Text style={{ color: colors.muted, fontSize: 12, marginBottom: 4 }}>
          Notes
        </Text>
        <AppTextInput
          testID="job-edit-notes-input"
          value={editNotes}
          onChangeText={setEditNotes}
          multiline
          numberOfLines={5}
          style={{
            borderWidth: 1,
            borderColor: colors.border,
            borderRadius: 8,
            padding: spacing.sm,
            color: colors.onSurface,
            textAlignVertical: "top",
            minHeight: 100,
          }}
        />
        <View style={{ height: spacing.sm }} />
        <Text style={{ color: colors.muted, fontSize: 12, marginBottom: 4 }}>
          Reason (optional)
        </Text>
        <AppTextInput
          testID="job-edit-reason-input"
          value={editReason}
          onChangeText={setEditReason}
          placeholder="e.g., Fixed typo"
          placeholderTextColor={colors.muted}
          style={{
            borderWidth: 1,
            borderColor: colors.border,
            borderRadius: 8,
            padding: spacing.sm,
            color: colors.onSurface,
          }}
        />
        {editError ? (
          <View style={{ marginTop: spacing.sm }} testID="job-edit-error">
            <Text style={{ color: colors.danger || "#991B1B", fontSize: 13 }}>
              {editError}
            </Text>
          </View>
        ) : null}
        <View style={{ height: spacing.md }} />
        <PrimaryButton
          title={editSaving ? "Saving…" : "Save changes"}
          icon="save-outline"
          onPress={saveEdit}
          loading={editSaving}
          testID="job-edit-save"
        />
      </Sheet>
      {/* MARCO voice command FAB — tech or admin only */}
      {!isCustomer && <MarcoVoiceButton screen="job_detail" entityId={job?.id || null} />}
    </View>
  );
}
