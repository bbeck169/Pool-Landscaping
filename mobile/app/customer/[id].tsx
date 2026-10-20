import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, Linking, Platform, Alert, Switch, TouchableOpacity, Modal, KeyboardAvoidingView } from "react-native";
import * as ImagePicker from "expo-image-picker";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { writeCache, readCache } from "@/src/services/readCache";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { useToast } from "@/src/components/ToastProvider";
import { PrimaryButton, Sheet } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";
import CustomerEquipmentLibrary from "@/src/components/customers/CustomerEquipmentLibrary";
import CustomerEquipmentUnits from "@/src/components/customers/CustomerEquipmentUnits";
import CustomerWarrantiesSection from "@/src/components/warranties/CustomerWarrantiesSection";
import MultiContact from "@/src/components/customers/MultiContact";
import CustomerMultiContactEditor from "@/src/components/customers/CustomerMultiContactEditor";
import AutomationsMuteSection from "@/src/components/customers/AutomationsMuteSection";
import CustomerTasks from "@/src/components/customers/CustomerTasks";
import ServiceNotes from "@/src/components/customers/ServiceNotes";
import SendCreateSheet from "@/src/components/customers/SendCreateSheet";
import SendServiceRecordsLinkModal from "@/src/components/customers/SendServiceRecordsLinkModal";
import CustomerTagsSection from "@/src/components/customers/CustomerTagsSection";
import CustomerIdentityCard from "@/src/components/customers/CustomerIdentityCard";
import PaymentMethodTiles from "@/src/components/customers/PaymentMethodTiles";
import CustomerInvoiceList from "@/src/components/customers/CustomerInvoiceList";
import CommunicationTimeline from "@/src/components/customers/CommunicationTimeline";
import DemoAccountToggle from "@/src/components/comms/DemoAccountToggle";
// Feb-2026 · P29b — Mobile parity for the web mute picker.
import MuteControlSheet from "@/src/components/customers/MuteControlSheet";
import CustomerDeleteModal from "@/src/components/customers/CustomerDeleteModal";
import SubscriptionsSection from "@/src/components/subscriptions/SubscriptionsSection";
import PortalAccessPanel from "@/src/components/customers/PortalAccessPanel";
import CustomerJobsSection from "@/src/components/customers/CustomerJobsSection";
// Phase 25 · web parity 0a176aeeb (Phase 22) — immediate skeleton shell.
import CustomerProfileSkeleton from "@/src/components/customers/CustomerProfileSkeleton";
// Phase 25b · web parity 66328fc7d (Phase 27) — dark chassis + KPI tiles + Quick Actions.
import {
  KPITileGrid, QuickActionTileGrid, LightPanel, SectionAnchor, type KpiSummary, type QuickAction,
} from "@/src/components/customers/CustomerDarkProfileParts";
import {
  DARK_BG, DARK_BORDER, DARK_TILE_RADIUS, DARK_TEXT, DARK_TEXT_MUTED,
  CD_ACTION_BTN_BG, CD_ACTION_BTN_BORDER, CD_CALL_BTN_BG,
} from "@/src/lib/customerDarkTokens";
// Phase 32 · two-tone — white page + light card wrappers; dark tiles above.
import {
  LIGHT_PAGE_BG, LIGHT_CARD_BG, LIGHT_CARD_BORDER, LIGHT_TEXT, LIGHT_TEXT_MUTED, LIGHT_CARD_RADIUS,
} from "@/src/lib/customerLightTokens";

// Quick Action tiles → the section each would open (mobile: scroll target).
// Phase 40 · web Phase 38 parity — 12 tiles in web TABS order (Measurements /
// Chemical History / Quotes / Invoices / Reviews hidden: no mobile section).
// ``gate`` mirrors the section's own render gate so a tile never points at
// a section the viewer can't see (web role-gated tab pattern).
const QUICK_ACTIONS: (QuickAction & { gate?: "admin" | "adminOrTech" })[] = [
  { k: "overview", label: "Overview", icon: "person-circle-outline" },
  { k: "properties", label: "Properties", icon: "home-outline" },
  { k: "jobs", label: "Jobs", icon: "briefcase-outline" },
  { k: "documents", label: "Documents", icon: "folder-open-outline", gate: "admin" },
  { k: "equipment", label: "Equipment", icon: "construct-outline" },
  { k: "warranties", label: "Warranties", icon: "shield-checkmark-outline", gate: "adminOrTech" },
  { k: "tasks", label: "Tasks", icon: "checkbox-outline" },
  { k: "notes", label: "Notes", icon: "document-text-outline" },
  { k: "credits", label: "Credits", icon: "wallet-outline", gate: "admin" },
  { k: "payments", label: "Payments", icon: "card-outline", gate: "admin" },
  { k: "subscriptions", label: "Subscriptions", icon: "repeat-outline", gate: "admin" },
  { k: "portal", label: "Portal Access", icon: "key-outline", gate: "admin" },
];
import { formatCustomerName } from "@/src/utils/formatCustomerName";
import { mapApiError, errorKindIcon } from "@/src/utils/mapApiError";
import AppTextInput from "@/src/components/ui/AppTextInput";
import { AddressLink } from "@/src/components/customer";

export default function CustomerDetail() {
  const { id, tab: tabParam } = useLocalSearchParams<{ id: string; tab?: string }>();
  const { showToast } = useToast();
  const { user, startImpersonation } = useAuth();
  const router = useRouter();
  const [c, setC] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [loginSheet, setLoginSheet] = useState(false);
  const [loginEmail, setLoginEmail] = useState("");
  const [loginPw, setLoginPw] = useState("");
  const [loginBusy, setLoginBusy] = useState(false);
  const [loginErr, setLoginErr] = useState("");
  const [docs, setDocs] = useState<any[]>([]);
  const [uploading, setUploading] = useState(false);
  const [impersonating, setImpersonating] = useState(false);
  const [confirmImp, setConfirmImp] = useState(false);
  const [requesting, setRequesting] = useState(false);
  const [actionSheetOpen, setActionSheetOpen] = useState(false);
  const [serviceRecordsLinkOpen, setServiceRecordsLinkOpen] = useState(false);
  const [noteComposerOpen, setNoteComposerOpen] = useState(false);
  // Feb-2026 MP2 UI — read-only property list. Editing lives on
  // web-only (per the ship brief); mobile admins get visibility.
  const [properties, setProperties] = useState<any[]>([]);
  // Credits state (Phase 13B)
  const [creditsData, setCreditsData] = useState<any>({ balance_cents: 0, ledger: [] });
  const [showAllLedger, setShowAllLedger] = useState(false);
  const [adjustOpen, setAdjustOpen] = useState(false);
  const [adjAmount, setAdjAmount] = useState("");
  const [adjReason, setAdjReason] = useState("");
  const [adjError, setAdjError] = useState("");
  const [adjBusy, setAdjBusy] = useState(false);
  // Ship 2 · Customer Delete UX
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleteBusyMode, setDeleteBusyMode] = useState<"soft" | "hard" | null>(null);
  // Route-entry classifier — classify 403 / network errors properly.
  const [loadError, setLoadError] = useState("");
  const [rawLoadError, setRawLoadError] = useState<unknown>(null);
  // Phase 9-M (web parity b5c09c9dc) — counts snapshot from
  // ``GET /customers/{id}/summary``. Null until resolved (or on error —
  // section badges just render without a count).
  const [summary, setSummary] = useState<any>(null);
  // Phase 25b — KPI snapshot from ``GET /customers/{id}/kpi-summary``.
  const [kpi, setKpi] = useState<KpiSummary>(null);
  const [activeQa, setActiveQa] = useState<string | null>(null); // Phase 40 · active tile outline
  const scrollRef = React.useRef<ScrollView>(null);
  const sectionY = React.useRef<Record<string, number>>({});
  const onAnchor = useCallback((k: string, y: number) => { sectionY.current[k] = y; }, []);
  // Tap-time measurement: onLayout ``y`` goes stale on web (RNW only
  // re-fires on resize) once sections above finish loading, so measure
  // panel vs viewport page-Y + current offset; stored y is the fallback.
  const viewportRef = React.useRef<View>(null);
  const scrollYRef = React.useRef(0);
  const sectionNode = React.useRef<Record<string, any>>({});
  const onNode = useCallback((k: string, n: any) => { sectionNode.current[k] = n; }, []);
  const jumpTo = useCallback((k: string) => {
    let done = false;
    const go = (y: number) => {
      if (done) return;
      done = true;
      scrollRef.current?.scrollTo({ y: Math.max(0, y - spacing.md), animated: true });
    };
    const node = sectionNode.current[k];
    const vp: any = viewportRef.current;
    if (node?.measure && vp?.measure) {
      try {
        node.measure((_x: number, _y: number, _w: number, _h: number, _px: number, py: number) => {
          vp.measure((_a: number, _b: number, _c: number, _d: number, _e: number, vpy: number) => {
            if (Number.isFinite(py) && Number.isFinite(vpy)) go(scrollYRef.current + (py - vpy));
          });
        });
      } catch { /* fall through to stored y */ }
    }
    setTimeout(() => {
      const y = sectionY.current[k];
      if (typeof y === "number") go(y);
    }, 120);
  }, []);

  const loadCredits = useCallback(async () => {
    try {
      const res = await api.get(`/customers/${id}/credits`);
      setCreditsData(res || { balance_cents: 0, ledger: [] });
    } catch {}
  }, [id]);

  const load = useCallback(async () => {
    setLoadError("");
    setRawLoadError(null);
    // Phase 9-M — summary fetch runs in parallel with the slim profile.
    api.get(`/customers/${id}/summary`)
      .then((r: any) => setSummary(r && typeof r === "object" ? r : null))
      .catch(() => setSummary(null));
    // Phase 25b — KPI tiles fetch in parallel (non-fatal; tiles show zeros).
    api.get(`/customers/${id}/kpi-summary`)
      .then((r: any) => setKpi(r && typeof r === "object" ? r : null))
      .catch(() => setKpi(null));
    try {
      // Phase 9-M — ``slim=1`` drops the embedded ``jobs`` array; Job
      // History is lazy-loaded by <CustomerJobsSection>.
      const data = await api.get(`/customers/${id}?slim=1`);
      setC(data);
      setLoginEmail(data.email || "");
      api.get(`/documents?customer_id=${id}`).then(setDocs).catch(() => {});
      api.get(`/customers/${id}/properties`)
        .then((rows) => setProperties(rows || []))
        .catch(() => setProperties([]));
      loadCredits();
      writeCache(`customer:${id}`, data).catch(() => {});
    } catch (e) {
      // Phase O5 · Offline fallback for customer detail.
      const cached = await readCache<any>(`customer:${id}`);
      if (cached) {
        setC(cached);
        setLoginEmail(cached.email || "");
      } else {
        setC(null);
        setRawLoadError(e);
        setLoadError("Couldn't load customer.");
      }
    } finally {
      setLoading(false);
    }
  }, [id, loadCredits]);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load])
  );

  // Dashboard parity · web `/customers/<id>?tab=properties` (Properties
  // list row tap). Mobile profile is one scroll stack → jump to that
  // section once, after the profile has rendered.
  const tabJumped = React.useRef(false);
  React.useEffect(() => {
    if (tabJumped.current || loading || !c || !tabParam || tabParam === "overview") return;
    if (!QUICK_ACTIONS.some((a) => a.k === tabParam)) return;
    tabJumped.current = true;
    setActiveQa(tabParam);
    setTimeout(() => jumpTo(tabParam), 350);
  }, [loading, c, tabParam, jumpTo]);

  const createLogin = async () => {
    const pw = loginPw;
    const strong = pw.length >= 8 && /[A-Z]/.test(pw) && /[a-z]/.test(pw) && /[0-9]/.test(pw);
    if (!loginEmail.trim() || !strong) {
      setLoginErr("Enter an email and a password with 8+ chars, an uppercase, a lowercase and a number.");
      return;
    }
    setLoginBusy(true);
    setLoginErr("");
    try {
      await api.post(`/customers/${id}/create-login`, { email: loginEmail.trim().toLowerCase(), password: loginPw });
      setLoginSheet(false);
      setLoginPw("");
      load();
    } catch (e: any) {
      setLoginErr(e.message || "Failed to create login");
    } finally {
      setLoginBusy(false);
    }
  };

  // Phase 25 — skeleton shell instead of a bare spinner (no blank frame).
  if (loading) return <CustomerProfileSkeleton />;
  if (!c && loadError) {
    const mapped = rawLoadError ? mapApiError(rawLoadError) : null;
    const icon = mapped ? errorKindIcon(mapped.kind) : "alert-circle-outline";
    return (
      <View style={{ flex: 1, backgroundColor: LIGHT_PAGE_BG }} testID="customer-detail-error">
        <Header title="Customer" back dark />
        <View style={{ flex: 1, alignItems: "center", justifyContent: "center", padding: spacing.lg }}>
          <Ionicons name={icon as any} size={48} color={LIGHT_TEXT_MUTED} />
          <Text style={{ fontFamily: font.bold, fontSize: fontSize.lg, color: LIGHT_TEXT, marginTop: spacing.md, textAlign: "center" }} testID="customer-detail-error-title">
            {mapped?.title || loadError}
          </Text>
          {mapped && mapped.message !== mapped.title && (
            <Text style={{ fontFamily: font.regular, fontSize: fontSize.sm, color: LIGHT_TEXT_MUTED, marginTop: spacing.sm, textAlign: "center" }} testID="customer-detail-error-message">
              {mapped.message}
            </Text>
          )}
          <Pressable
            style={{ marginTop: spacing.lg, paddingHorizontal: spacing.lg, paddingVertical: spacing.md, backgroundColor: colors.brand, borderRadius: radius.md }}
            onPress={load}
            testID="customer-detail-retry-btn"
          >
            <Text style={{ fontFamily: font.bold, fontSize: fontSize.sm, color: "#fff" }}>Retry</Text>
          </Pressable>
        </View>
      </View>
    );
  }
  // Phase 25 — never a blank page: fall back to the skeleton shell.
  if (!c) return <CustomerProfileSkeleton />;

  const isAdmin = user?.role === "admin" || user?.role === "super_admin";
  const isAdminOrTech = isAdmin || user?.role === "technician";
  const isActive = c.is_active !== false;

  // Multi-contact · prefer primary entry from arrays, fall back to scalar.
  const primaryEmail = (Array.isArray(c.emails) && c.emails.length > 0)
    ? ((c.emails.find((e: any) => e.is_primary) || c.emails[0]) as any)?.address || c.email
    : c.email;
  const primaryPhone = (Array.isArray(c.mobiles) && c.mobiles.length > 0)
    ? ((c.mobiles.find((m: any) => m.is_primary) || c.mobiles[0]) as any)?.number_e164 || c.phone
    : c.phone;

  // Phase 56.2 — mobile activation toggle. Reuses the shared
  // PATCH /customers/{id}/activation endpoint so the Phase 34f auto-
  // cancel cascade and Phase 55 notifications behave identically on
  // web and native.
  const toggleActivation = () => {
    const nextActive = !isActive;
    const confirmTitle = nextActive ? "Reactivate customer?" : "Mark customer inactive?";
    const confirmBody = nextActive
      ? `Reactivate ${c.name}? Their jobs will need to be re-scheduled manually.`
      : `Marking ${c.name} inactive will auto-cancel their scheduled jobs. Continue?`;
    Alert.alert(confirmTitle, confirmBody, [
      { text: "Cancel", style: "cancel" },
      {
        text: nextActive ? "Reactivate" : "Mark inactive",
        style: nextActive ? "default" : "destructive",
        onPress: async () => {
          // Optimistic flip.
          setC((prev: any) => ({ ...prev, is_active: nextActive }));
          try {
            const updated = await api.patch(`/customers/${id}/activation`, { is_active: nextActive });
            setC(updated);
          } catch (e: any) {
            setC((prev: any) => ({ ...prev, is_active: !nextActive }));
            Alert.alert("Update failed", e.message || "Please try again.");
          }
        },
      },
    ]);
  };

  // Ship 2 · Customer Delete UX — mode-aware delete handler
  const doDelete = async (mode: "soft" | "hard") => {
    if (deleteBusyMode) return;
    setDeleteBusyMode(mode);
    try {
      const res: any = await api.del(`/customers/${id}?mode=${mode}`);
      const verb = mode === "hard" ? "permanently deleted" : "soft-deleted";
      Alert.alert(
        "Success",
        res?.already_deleted ? "Customer was already soft-deleted" : `Customer ${verb}`,
      );
      setConfirmDelete(false);
      router.back();
    } catch (e: any) {
      const detail = e?.response?.data?.detail || e?.data?.detail;
      const isDict = detail && typeof detail === "object";
      if (
        mode === "hard" &&
        (e?.response?.status === 409 || e?.status === 409) &&
        isDict &&
        detail.detail === "customer_has_unpaid_invoices"
      ) {
        const n = detail.invoice_count ?? "some";
        Alert.alert(
          "Cannot hard-delete",
          `Cannot hard-delete \u2014 ${n} unpaid invoice(s). Resolve them or use Soft Delete instead.`,
          [
            { text: "View invoices", onPress: () => { setConfirmDelete(false); router.push("/invoices"); } },
            { text: "OK" },
          ],
        );
      } else {
        Alert.alert("Delete failed", e?.message || "Please try again.");
      }
    } finally {
      setDeleteBusyMode(null);
    }
  };

  const loginAsCustomer = () => setConfirmImp(true);

  const doImpersonate = async () => {
    setImpersonating(true);
    try {
      await startImpersonation(id as string);
      setConfirmImp(false);
      router.replace("/portal/home");
    } catch (e: any) {
      Alert.alert("Couldn't switch", e.message || "Please try again.");
    } finally {
      setImpersonating(false);
    }
  };

  const requestCard = async () => {
    setRequesting(true);
    try {
      await api.post(`/customers/${id}/send-card-add-link`, {});
      showToast(`${c.name} will receive an email + SMS to add a card.`);
    } catch (e: any) {
      Alert.alert("Failed", e.message || "Please try again.");
    } finally {
      setRequesting(false);
    }
  };

  const submitAdjust = async () => {
    setAdjBusy(true);
    setAdjError("");
    try {
      const deltaCents = Math.round(parseFloat(adjAmount) * 100);
      if (isNaN(deltaCents) || deltaCents === 0) { setAdjError("Enter a valid amount."); setAdjBusy(false); return; }
      await api.post(`/customers/${id}/credits/adjust`, { delta_cents: deltaCents, reason: adjReason.trim() });
      setAdjustOpen(false);
      setAdjAmount("");
      setAdjReason("");
      showToast("Credit balance updated.");
      loadCredits();
      load();
    } catch (e: any) {
      const msg = e?.message || "";
      if (msg.includes("INSUFFICIENT_BALANCE")) {
        setAdjError("Insufficient balance — cannot go negative.");
      } else {
        setAdjError(msg || "Adjustment failed.");
      }
    } finally {
      setAdjBusy(false);
    }
  };

  const shareDocument = async () => {
    const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!perm.granted) return;
    const res = await ImagePicker.launchImageLibraryAsync({ base64: true, quality: 0.6 });
    if (res.canceled || !res.assets?.[0]?.base64) return;
    setUploading(true);
    try {
      const asset = res.assets[0];
      const name = (asset.fileName as string) || `Document ${new Date().toISOString().slice(0, 10)}`;
      const created = await api.post(`/documents`, {
        customer_id: id,
        name,
        type: "photo",
        data: `data:image/jpeg;base64,${asset.base64}`,
      });
      setDocs((prev) => [created, ...prev]);
    } catch {}
    finally { setUploading(false); }
  };

  const removeDoc = async (did: string) => {
    setDocs((prev) => prev.filter((d) => d.id !== did));
    await api.del(`/documents/${did}`).catch(() => {});
  };

  return (
    <View style={styles.root}>
      <Header
        title={c.name}
        back
        dark
        right={
          <Pressable onPress={() => router.push(`/customer/new?id=${id}`)} testID="edit-customer-button" hitSlop={8}>
            <Ionicons name="create-outline" size={24} color={colors.brand} />
          </Pressable>
        }
      />
      <View ref={viewportRef} style={{ flex: 1 }} collapsable={false}>
      <ScrollView
        ref={scrollRef}
        contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
        onScroll={(e) => { scrollYRef.current = e.nativeEvent.contentOffset.y; }}
        scrollEventThrottle={16}
      >
        {/* Phase 25 · web parity 6bf5306cf (Phase 20) — unified action row
            lifted ABOVE the section stack (mobile has no tabs row; the
            stacked sections below are its analogue). Delete + View-as-
            customer were relocated here verbatim — same testIDs, same
            handlers, same role gates. Header edit icon is untouched. */}
        {/* Phase 35 · web parity b40352a (Phase 28) — identity header card
            ABOVE the Phase 20 action row. Light chassis per Phase 32. */}
        <CustomerIdentityCard
          c={c}
          isActive={isActive}
          isAdmin={isAdmin}
          onToggleActive={toggleActivation}
          primaryPhone={primaryPhone}
          primaryEmail={primaryEmail}
          tagsSlot={
            <CustomerTagsSection
              customerId={id as string}
              value={c.tags || []}
              onChange={(nextTags) => setC((prev: any) => (prev ? { ...prev, tags: nextTags } : prev))}
            />
          }
        />
        <View style={s2.actionRow} testID="customer-action-row">
          <TouchableOpacity
            style={[s2.actionBtn, s2.actionBtnSteel]}
            onPress={() => router.push(`/customer/new?id=${id}`)}
            testID="customer-action-edit"
          >
            <Ionicons name="create-outline" size={16} color="#FFFFFF" />
            <Text style={[s2.actionBtnText, { color: "#FFFFFF" }]}>Edit</Text>
          </TouchableOpacity>
          {primaryPhone ? (
            <TouchableOpacity
              style={[s2.actionBtn, s2.actionBtnCall]}
              onPress={() => Linking.openURL(`tel:${String(primaryPhone).replace(/[^\d+]/g, "")}`)}
              testID="customer-action-call"
            >
              <Ionicons name="call-outline" size={16} color="#FFFFFF" />
              <Text style={[s2.actionBtnText, { color: "#FFFFFF" }]}>Call</Text>
            </TouchableOpacity>
          ) : null}
          {isAdmin && c.has_login ? (
            <Pressable style={[s2.actionBtn, s2.actionBtnSteel]} onPress={loginAsCustomer} disabled={impersonating} testID="impersonate-customer-button">
              <Ionicons name="eye-outline" size={16} color="#fff" />
              <Text style={[styles.impersonateText, s2.actionBtnText]}>{impersonating ? "Switching…" : "Switch to customer view"}</Text>
            </Pressable>
          ) : null}
          {/* Phase 40b · web ``cd-issue-credit-btn`` → scroll to the Credits
              section (its Adjust modal is reused untouched). Gated like the
              Credits section it targets (admin / super_admin). */}
          {isAdmin ? (
            <TouchableOpacity
              style={[s2.actionBtn, s2.actionBtnSteel]}
              onPress={() => jumpTo("credits")}
              testID="customer-action-issue-credit"
              accessibilityLabel="Issue Credit"
            >
              <Ionicons name="cash-outline" size={16} color="#FFFFFF" />
              <Text style={[s2.actionBtnText, { color: "#FFFFFF" }]}>Issue Credit</Text>
            </TouchableOpacity>
          ) : null}
        {isAdmin ? (
            <TouchableOpacity
              style={[s2.deleteBtn, s2.actionBtn]}
              onPress={() => setConfirmDelete(true)}
              testID="customer-delete-button"
            >
              <Ionicons name="trash-outline" size={16} color="#B91C1C" />
              <Text style={[s2.deleteBtnText, s2.actionBtnText]}>Delete customer</Text>
            </TouchableOpacity>
          ) : null}
        </View>

        {/* Phase 25b · web Phase 27 — 6 KPI tiles (locked order) + Quick
            Action tiles, both ABOVE the section stack. */}
        <KPITileGrid kpi={kpi} />
        <QuickActionTileGrid
          actions={QUICK_ACTIONS.filter((a) => !a.gate || (a.gate === "admin" ? isAdmin : isAdminOrTech))}
          activeKey={activeQa}
          onPick={(k) => {
            setActiveQa(k);
            if (k === "overview") scrollRef.current?.scrollTo({ y: 0, animated: true });
            else jumpTo(k);
          }}
        />
        {/* Feb-2026 · P29b — Mobile mute-picker parity. Admin + super_admin
            only (matches the web MuteControl gating). */}
        {isAdmin ? (
          <View style={s2.lightCard} testID="cd-light-card-mark-muted">
            <MuteControlSheet
              customer={c}
              canMute
              canUnmute
              onChange={(payload) => {
                if (!payload) return;
                if (payload.muted) {
                  setC((prev: any) => ({
                    ...prev,
                    is_muted: true,
                    is_active: false,
                    muted_at: payload.muted_at,
                    muted_reason: payload.muted_reason ?? null,
                  }));
                } else if (payload.unmuted) {
                  setC((prev: any) => ({
                    ...prev,
                    is_muted: false,
                    is_active: true,
                    muted_at: undefined,
                    muted_reason: undefined,
                  }));
                }
              }}
              onError={(msg) => Alert.alert("Update failed", msg)}
            />
          </View>
        ) : null}
        {/* Multi-Contact Phase 1 · Automations mute toggle + banner.
            Distinct from MuteControlSheet above which handles is_muted. */}
        {/* Phase 32 · light card wrapper — Mute automated comms. */}
        <View style={s2.lightCard} testID="cd-light-card-automations-mute">
          <AutomationsMuteSection
            customer={c}
            isAdmin={isAdmin}
            onUpdated={(patch) => setC((prev: any) => ({ ...prev, ...patch }))}
          />
        </View>
        {/* Phase 35 · phone / email / address / pool moved into the identity
            card above; billing address keeps its slot here (not in web's
            Phase 28 identity list). */}
        {c.billing_address ? (
          <View style={styles.card}>
            <View style={styles.contactRow}>
              <View style={styles.contactIcon}>
                <Ionicons name="card-outline" size={18} color={colors.brand} />
              </View>
              <AddressLink address={`Billing: ${c.billing_address}`} showIcon={false} style={styles.contactValue} testID="customer-billing-link" />
            </View>
          </View>
        ) : null}

        {/* Multi-Contact Phase 1 — admin gets editable editor; non-admin gets read-only */}
        {isAdmin ? (
          <LightPanel>
            <CustomerMultiContactEditor
              customerId={id as string}
              initialEmails={c.emails}
              initialMobiles={c.mobiles}
              onSaved={load}
            />
          </LightPanel>
        ) : (
          <LightPanel>
            <MultiContact mobiles={c.mobiles} emails={c.emails} />
          </LightPanel>
        )}

        {/* TD-79 (web db3ef6d2f) — last 10 invoices + "View all". Mirrors
            web placement: below the identity/contact block, above the
            payment-method controls. */}
        {isAdmin ? (
          <View style={{ marginTop: spacing.md }} testID="customer-overview-invoices-slot">
            <LightPanel>
              <CustomerInvoiceList customerId={id as string} />
            </LightPanel>
          </View>
        ) : null}


        {isAdmin ? (
          <Pressable
            style={styles.pmCard}
            testID="customer-payment-method"
            onPress={() => router.push(`/customer/${id}/payment-methods` as any)}
            accessibilityRole="button"
            accessibilityLabel="Manage payment methods"
          >
            <View style={styles.pmIcon}>
              <Ionicons name={c.has_card_on_file ? "card" : "card-outline"} size={18} color={colors.brand} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.pmLabel}>Payment method</Text>
              {c.has_card_on_file ? (
                <Text style={[styles.pmValue, { color: "#166534" }]}>
                  {c.card_brand || c.pm_brand || "Card"} •••• {c.card_last4 || c.pm_last4 || "----"}
                  {c.card_exp_month && c.card_exp_year ? ` (${c.card_exp_month}/${String(c.card_exp_year).slice(-2)})` : ""}
                </Text>
              ) : c.effective_require_card_on_file ? (
                <Text style={[styles.pmValue, { color: "#A16207" }]}>No card — required</Text>
              ) : (
                <Text style={[styles.pmValue, { color: colors.muted }]}>No card — not required</Text>
              )}
            </View>
            {c.has_card_on_file ? (
              <Ionicons name="checkmark-circle" size={20} color={colors.success} />
            ) : (
              <Pressable
                style={styles.pmRequest}
                onPress={() => router.push(`/customer/${id}/payment-methods` as any)}
                testID="add-payment-method-button"
              >
                <Text style={styles.pmRequestText}>Manage</Text>
              </Pressable>
            )}
            <Ionicons name="chevron-forward" size={16} color={colors.muted} />
          </Pressable>
        ) : null}

        {/* Secondary: Send add-card email link (still useful remotely) */}
        {isAdmin && !c.has_card_on_file && c.effective_require_card_on_file ? (
          <Pressable
            style={styles.sendLinkRow}
            onPress={requestCard}
            disabled={requesting}
            testID="send-card-link-button"
          >
            <Ionicons name="mail-outline" size={16} color={colors.brand} />
            <Text style={styles.sendLinkText}>
              {requesting ? "Sending…" : "Send add-card link to customer"}
            </Text>
          </Pressable>
        ) : null}

        {/* Phase J2 / I5 — Payment Method Tiles (green on-file, red empty).
            Placed between header/contact info and the card-required toggle. */}
        {isAdmin ? (
          <View
            style={{ marginTop: spacing.md }}
            testID="customer-payment-tiles-slot"
            ref={(n) => onNode("payments", n)}
            collapsable={false}
            onLayout={(e) => onAnchor("payments", e.nativeEvent.layout.y)}
          >
            <LightPanel>
              <PaymentMethodTiles
                customerId={id as string}
                variant="admin"
                onChange={load}
              />
            </LightPanel>
          </View>
        ) : null}

        {/* Card required override (Phase 12 tri-state) */}
        {isAdmin ? (
          <View style={styles.cardRequiredCard} testID="card-required-override">
            <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
              <Text style={styles.pmLabel}>Card on file required?</Text>
              <Switch
                testID="card-required-toggle"
                value={c.require_card_on_file_override === true || (c.require_card_on_file_override === null && c.effective_require_card_on_file)}
                onValueChange={async (val) => {
                  try {
                    const updated = await api.patch(`/customers/${id}`, { require_card_on_file_override: val });
                    setC(updated);
                  } catch (e: any) { Alert.alert("Failed", e.message || "Update failed"); }
                }}
                trackColor={{ false: "#9CA3AF", true: "#16A34A" }}
                thumbColor="#ffffff"
                ios_backgroundColor="#9CA3AF"
                style={{ transform: [{ scaleX: 0.85 }, { scaleY: 0.85 }] }}
              />
            </View>
            {c.require_card_on_file_override != null && (
              <Pressable
                style={styles.resetDefaultBtn}
                onPress={async () => {
                  try {
                    const updated = await api.patch(`/customers/${id}`, { require_card_on_file_override: null });
                    setC(updated);
                  } catch (e: any) { Alert.alert("Failed", e.message || "Update failed"); }
                }}
                testID="reset-card-default"
              >
                <Text style={styles.resetDefaultText}>Reset to tenant default</Text>
              </Pressable>
            )}
          </View>
        ) : null}

        <SectionAnchor k="subscriptions" onAnchor={onAnchor} onNode={onNode}>
        {/* B4 — Subscriptions CRUD */}
        {isAdmin ? (
          <View style={{ marginTop: spacing.xl }}>
            <LightPanel>
              <SubscriptionsSection customerId={id} canWrite={isAdmin} />
            </LightPanel>
          </View>
        ) : null}
        </SectionAnchor>

        <SectionAnchor k="credits" onAnchor={onAnchor} onNode={onNode}>
        {/* Credits section (Phase 10 / Phase 13B) */}
        {isAdmin ? (
          <View style={styles.creditsSection} testID="customer-credits-section">
            <View style={styles.creditsSectionHeader}>
              <View style={{ flex: 1 }}>
                <Text style={styles.creditsLabel}>CREDIT BALANCE</Text>
                <Text style={styles.creditsAmount} testID="customer-credits-balance">
                  ${((creditsData?.balance_cents ?? c.credits_balance_cents ?? 0) / 100).toFixed(2)}
                </Text>
              </View>
              <TouchableOpacity
                style={styles.adjustBtn}
                onPress={() => setAdjustOpen(true)}
                testID="credits-adjust-btn"
              >
                <Ionicons name="add-circle-outline" size={14} color={colors.brand} />
                <Text style={styles.adjustBtnText}>Adjust</Text>
              </TouchableOpacity>
            </View>
            {(creditsData?.ledger || []).length > 0 ? (
              <View style={styles.ledgerList}>
                {creditsData.ledger.slice(0, showAllLedger ? 50 : 5).map((entry: any) => {
                  const isPositive = entry.delta_cents > 0;
                  return (
                    <View key={entry.id} style={styles.ledgerRow} testID={`ledger-${entry.id}`}>
                      <View style={{ flex: 1 }}>
                        <Text style={styles.ledgerSource}>
                          {entry.source === "manual" ? "Manual" : entry.source === "referral" ? "Referral" : entry.source === "redeemed" ? "Redeemed" : entry.source === "revert" ? "Revert" : entry.source || "—"}
                        </Text>
                        {entry.reason || entry.note ? <Text style={styles.ledgerNote} numberOfLines={1}>{entry.reason || entry.note}</Text> : null}
                        {entry.actor_email ? <Text style={styles.ledgerActor}>{entry.actor_email}</Text> : null}
                      </View>
                      <View style={{ alignItems: "flex-end" }}>
                        <Text style={[styles.ledgerDelta, { color: isPositive ? "#166534" : "#DC2626" }]}>
                          {isPositive ? "+" : ""}${(entry.delta_cents / 100).toFixed(2)}
                        </Text>
                        <Text style={styles.ledgerDate}>{new Date(entry.created_at).toLocaleDateString()}</Text>
                      </View>
                    </View>
                  );
                })}
                {creditsData.ledger.length > 5 && !showAllLedger && (
                  <TouchableOpacity onPress={() => setShowAllLedger(true)} testID="ledger-load-more">
                    <Text style={styles.loadMoreText}>Show all ({creditsData.ledger.length})</Text>
                  </TouchableOpacity>
                )}
              </View>
            ) : (
              <Text style={styles.ledgerEmpty}>No credit transactions yet</Text>
            )}
          </View>
        ) : null}
        </SectionAnchor>

        {/* Adjust balance modal */}
        <Modal visible={adjustOpen} transparent animationType="fade" testID="adjust-credits-modal">
          <KeyboardAvoidingView style={styles.adjOverlay} behavior={Platform.OS === "ios" ? "padding" : "height"}>
            <View style={styles.adjCard}>
              <Text style={styles.adjTitle}>Adjust Credit Balance</Text>
              <Text style={styles.adjCurrent}>Current: ${((creditsData?.balance_cents ?? c.credits_balance_cents ?? 0) / 100).toFixed(2)}</Text>
              <AppTextInput
                style={styles.adjInput}
                value={adjAmount}
                onChangeText={setAdjAmount}
                placeholder="Amount in dollars (e.g. 25 or -10)"
                placeholderTextColor={colors.muted}
                keyboardType="numeric"
                testID="adjust-amount-input"
              />
              <AppTextInput
                style={[styles.adjInput, { minHeight: 60 }]}
                value={adjReason}
                onChangeText={setAdjReason}
                placeholder="Reason (min 5 characters)"
                placeholderTextColor={colors.muted}
                multiline
                testID="adjust-reason-input"
              />
              {adjAmount && adjReason.length >= 5 ? (
                <Text style={styles.adjPreview}>
                  Balance will change from ${((creditsData?.balance_cents ?? 0) / 100).toFixed(2)} to ${(((creditsData?.balance_cents ?? 0) + Math.round(parseFloat(adjAmount || "0") * 100)) / 100).toFixed(2)}
                </Text>
              ) : null}
              {adjError ? <Text style={styles.adjError}>{adjError}</Text> : null}
              <View style={styles.adjBtns}>
                <TouchableOpacity style={styles.adjCancel} onPress={() => { setAdjustOpen(false); setAdjAmount(""); setAdjReason(""); setAdjError(""); }} testID="adjust-cancel">
                  <Text style={styles.adjCancelText}>Cancel</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={[styles.adjSave, (!adjAmount || adjReason.length < 5) && { opacity: 0.4 }]}
                  onPress={submitAdjust}
                  disabled={adjBusy || !adjAmount || adjReason.length < 5}
                  testID="adjust-save"
                >
                  <Text style={styles.adjSaveText}>{adjBusy ? "Saving…" : "Save"}</Text>
                </TouchableOpacity>
              </View>
            </View>
          </KeyboardAvoidingView>
        </Modal>

        <SectionAnchor k="portal" onAnchor={onAnchor} onNode={onNode}>
        {isAdmin ? (
          c.has_login ? (
            <View style={styles.loginBadge} testID="customer-has-login">
              <Ionicons name="checkmark-circle" size={18} color={colors.success} />
              <Text style={styles.loginBadgeText}>Customer login active ({c.email})</Text>
            </View>
          ) : (
            <Pressable style={styles.createLoginBtn} onPress={() => setLoginSheet(true)} testID="create-login-button">
              <Ionicons name="key-outline" size={18} color={colors.brand} />
              <Text style={styles.createLoginText}>Create customer login</Text>
            </Pressable>
          )
        ) : null}

        {/* Dispatch B · Portal Access Panel — admin-only */}
        {isAdmin ? (
          <LightPanel>
            <PortalAccessPanel
              customerId={id as string}
              customerEmail={c?.email}
              customerName={c?.name}
              hasLogin={c?.has_login}
              userRole={user?.role}
              onRefresh={load}
            />
          </LightPanel>
        ) : null}
        </SectionAnchor>

        {c.notes ? (
          <View style={styles.notesBox}>
            <Text style={styles.notesLabel}>Notes</Text>
            <Text style={styles.notes}>{c.notes}</Text>
          </View>
        ) : null}

        <SectionAnchor k="documents" onAnchor={onAnchor} onNode={onNode}>
        {isAdmin ? (
          <>
            <View style={styles.docHeader}>
              <Text style={styles.sectionTitle}>Documents ({docs.length})</Text>
              <Pressable style={styles.shareBtn} onPress={shareDocument} disabled={uploading} testID="share-document-button">
                <Ionicons name="cloud-upload-outline" size={16} color={colors.brand} />
                <Text style={styles.shareText}>{uploading ? "Uploading…" : "Share"}</Text>
              </Pressable>
            </View>
            {docs.length ? (
              docs.map((d) => (
                <View key={d.id} style={styles.docRow} testID={`customer-doc-${d.id}`}>
                  <Ionicons name="document-outline" size={18} color={colors.brand} />
                  <Text style={styles.docName} numberOfLines={1}>{d.name}</Text>
                  <Pressable onPress={() => removeDoc(d.id)} hitSlop={8} testID={`delete-doc-${d.id}`}>
                    <Ionicons name="trash-outline" size={18} color={colors.muted} />
                  </Pressable>
                </View>
              ))
            ) : (
              <Text style={styles.empty}>No documents shared yet.</Text>
            )}
          </>
        ) : null}
        </SectionAnchor>

        <SectionAnchor k="properties" onAnchor={onAnchor} onNode={onNode}>
        {/* Feb-2026 MP2 UI — read-only property list for mobile admins.
            Editing surfaces exist on web only per the ship brief. */}
        <Text style={styles.sectionTitle}>
          Properties ({properties.filter((p: any) => p.active !== false).length})
        </Text>
        {properties.filter((p: any) => p.active !== false).length === 0 ? (
          <Text style={styles.empty}>No properties yet.</Text>
        ) : (
          properties.filter((p: any) => p.active !== false).map((p: any) => (
            <View
              key={p.id}
              style={{
                marginBottom: spacing.sm,
                padding: spacing.md,
                borderRadius: radius.md,
                backgroundColor: colors.surface,
                borderWidth: 1,
                borderColor: colors.border,
              }}
              testID={`mobile-property-${p.id}`}
            >
              <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}>
                <Ionicons name="home-outline" size={16} color={colors.brand} />
                <Text style={{ fontFamily: font.bold, color: colors.onSurface, fontSize: fontSize.md }}>
                  {p.label}
                </Text>
                {p.sort_order === 0 ? (
                  <View
                    style={{
                      paddingHorizontal: 6,
                      paddingVertical: 1,
                      borderRadius: 999,
                      backgroundColor: colors.brand,
                    }}
                  >
                    <Text style={{ color: "#fff", fontSize: 10, fontWeight: "700" }}>Primary</Text>
                  </View>
                ) : null}
              </View>
              <Text style={{ marginTop: 4, color: colors.onSurfaceSecondary, fontSize: fontSize.sm }}>
                {[p.address?.line1, p.address?.city, p.address?.state, p.address?.postal_code]
                  .filter(Boolean).join(", ")}
              </Text>
              {(p.service_types || []).length ? (
                <Text style={{ marginTop: 4, color: colors.onSurfaceSecondary, fontSize: fontSize.xs }}>
                  {(p.service_types || []).join(" · ")}
                </Text>
              ) : null}
              {p.pool_size_gallons ? (
                <Text style={{ marginTop: 2, color: colors.onSurfaceSecondary, fontSize: fontSize.xs }}>
                  Pool: {p.pool_size_gallons.toLocaleString()} gal
                </Text>
              ) : null}
            </View>
          ))
        )}
        </SectionAnchor>

        {/* Phase 56.11-mobile — Equipment photo library section (legacy). */}
        <Text style={styles.sectionTitle}>Equipment Photos</Text>
        <LightPanel anchor="equipment" onAnchor={onAnchor} onNode={onNode}>
          <CustomerEquipmentLibrary customerId={id as string} />
        </LightPanel>

        {/* Equipment Units — structured equipment library (brand/model/serial + S3 photos). */}
        {isAdminOrTech ? (
          <>
            <Text style={styles.sectionTitle}>Equipment Library</Text>
            <LightPanel>
              <CustomerEquipmentUnits customerId={id as string} />
            </LightPanel>
          </>
        ) : null}

        <SectionAnchor k="warranties" onAnchor={onAnchor} onNode={onNode}>
        {/* Warranty Contracts — read-only list (v1, no add/edit on mobile). */}
        {isAdminOrTech ? (
          <>
            <Text style={styles.sectionTitle}>Warranties</Text>
            <LightPanel>
              <CustomerWarrantiesSection customerId={id as string} />
            </LightPanel>
          </>
        ) : null}
        </SectionAnchor>

        {/* Task 1 · Feb-2026 — Outbound-comms Demo whitelist toggle
            with hard-confirm modal. Same contract as web. */}
        <View style={{ marginHorizontal: 16, marginBottom: 12,
                        flexDirection: "row", alignItems: "center", gap: 8 }}>
          <Text style={{ fontSize: 12, color: "#71717A" }}>Comms:</Text>
          <LightPanel>
            <DemoAccountToggle
              recordType="customer"
              recordId={id as string}
              isDemo={!!c.is_demo_account}
              recordLabel={c.name || "this customer"}
              onChange={(next) => setC((prev: any) => (prev ? { ...prev, is_demo_account: next } : prev))}
            />
          </LightPanel>
        </View>

        {/* A5. Tasks tab */}
        <LightPanel anchor="tasks" onAnchor={onAnchor} onNode={onNode}>
          <CustomerTasks customerId={id as string} />
        </LightPanel>

        {/* A8. Service notes */}
        <LightPanel anchor="notes" onAnchor={onAnchor} onNode={onNode}>
          <ServiceNotes customerId={id as string} />
        </LightPanel>

        {/* Phase 9-M — lazy Job History (summary badge + 5-min TTL cache). */}
        <LightPanel anchor="jobs" onAnchor={onAnchor} onNode={onNode}>
          <CustomerJobsSection
            customerId={id as string}
            count={summary?.jobs_count}
            fallbackJobs={c.jobs}
          />
        </LightPanel>

        {/* Phase J2 / I7 — Communication Timeline. Always visible (not tab-gated). */}
        <Text style={styles.sectionTitle}>Communication Timeline</Text>
        <LightPanel anchor="timeline" onAnchor={onAnchor} onNode={onNode}>
          <CommunicationTimeline customerId={id as string} variant="admin" />
        </LightPanel>
      </ScrollView>
      </View>

      <Sheet visible={confirmImp} onClose={() => setConfirmImp(false)} title="Switch to customer view" testID="impersonate-confirm-sheet">
        <Text style={styles.sheetHint}>
          You&apos;ll be switched into {c.name}&apos;s portal to see exactly what they see (services, invoices, documents). An orange banner will let you return to admin anytime. Payments and card changes are disabled while viewing.
        </Text>
        <View style={{ height: spacing.md }} />
        <PrimaryButton title="Switch to customer view" icon="eye-outline" onPress={doImpersonate} loading={impersonating} testID="impersonate-confirm-button" />
      </Sheet>

      <Sheet visible={loginSheet} onClose={() => setLoginSheet(false)} title="Create Customer Login" testID="create-login-sheet">
        <Text style={styles.sheetHint}>The customer will use these credentials to view their jobs and pay invoices.</Text>
        <Text style={styles.inputLabel}>Email</Text>
        <AppTextInput
          testID="login-email-field"
          style={styles.input}
          value={loginEmail}
          onChangeText={setLoginEmail}
          placeholder="customer@email.com"
          placeholderTextColor={colors.muted}
          autoCapitalize="none"
          keyboardType="email-address"
        />
        <Text style={styles.inputLabel}>Temporary Password</Text>
        <AppTextInput
          testID="login-password-field"
          style={styles.input}
          value={loginPw}
          onChangeText={setLoginPw}
          placeholder="8+ chars, upper, lower & number"
          placeholderTextColor={colors.muted}
          secureTextEntry
        />
        {loginErr ? <Text style={styles.error}>{loginErr}</Text> : null}
        <View style={{ height: spacing.md }} />
        <PrimaryButton title="Create Login" onPress={createLogin} loading={loginBusy} testID="submit-create-login" />
      </Sheet>

      {/* A6. Send-Create action sheet + FAB */}
      <TouchableOpacity
        testID="send-create-fab"
        style={styles.fab}
        onPress={() => setActionSheetOpen(true)}
        activeOpacity={0.8}
      >
        <Ionicons name="add" size={26} color="#fff" />
      </TouchableOpacity>
      <SendCreateSheet
        visible={actionSheetOpen}
        onClose={() => setActionSheetOpen(false)}
        customerId={id as string}
        onAddNote={() => setNoteComposerOpen(true)}
        onServiceRecordsLink={() => setServiceRecordsLinkOpen(true)}
      />

      {/* Task 6 · Send Service Records Link modal */}
      <SendServiceRecordsLinkModal
        visible={serviceRecordsLinkOpen}
        customerId={id as string}
        customerEmail={c?.email}
        customerPhone={c?.phone}
        channelOptIn={c?.channel_opt_in}
        isMuted={c?.is_muted}
        onClose={() => setServiceRecordsLinkOpen(false)}
      />

      {/* Ship 2 · Customer Delete UX overhaul — 3-button modal */}
      <CustomerDeleteModal
        visible={confirmDelete}
        customerName={c?.name}
        busyMode={deleteBusyMode}
        onCancel={() => setConfirmDelete(false)}
        onSoftDelete={() => doDelete("soft")}
        onHardDelete={() => doDelete("hard")}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: LIGHT_PAGE_BG },
  card: { backgroundColor: DARK_BG, borderRadius: DARK_TILE_RADIUS, borderWidth: 1, borderColor: DARK_BORDER, overflow: "hidden" },
  contactRow: { flexDirection: "row", alignItems: "center", gap: spacing.md, padding: spacing.md, borderBottomWidth: 1, borderBottomColor: DARK_BORDER },
  contactIcon: { width: 36, height: 36, borderRadius: radius.sm, backgroundColor: colors.brandTertiary, alignItems: "center", justifyContent: "center" },
  contactValue: { flex: 1, fontFamily: font.medium, fontSize: fontSize.base, color: DARK_TEXT },
  notesBox: { backgroundColor: DARK_BG, borderRadius: DARK_TILE_RADIUS, padding: spacing.lg, borderWidth: 1, borderColor: DARK_BORDER, marginTop: spacing.md },
  notesLabel: { fontFamily: font.semibold, fontSize: fontSize.base, color: DARK_TEXT, marginBottom: 4 },
  notes: { fontFamily: font.regular, fontSize: fontSize.base, color: DARK_TEXT_MUTED, lineHeight: 20 },
  sectionTitle: { fontFamily: font.bold, fontSize: fontSize.xl, color: LIGHT_TEXT, marginTop: spacing.xl, marginBottom: spacing.md },
  empty: { fontFamily: font.regular, fontSize: fontSize.base, color: LIGHT_TEXT_MUTED },
  loginBadge: { flexDirection: "row", alignItems: "center", gap: spacing.sm, backgroundColor: "#DCFCE7", borderRadius: radius.md, padding: spacing.md, marginTop: spacing.md },
  loginBadgeText: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.success, flex: 1 },
  createLoginBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.sm, backgroundColor: colors.brandTertiary, borderRadius: radius.md, padding: spacing.md, marginTop: spacing.md },
  createLoginText: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.brand },
  sheetHint: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurfaceSecondary, marginBottom: spacing.md },
  inputLabel: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, marginBottom: spacing.xs, marginTop: spacing.sm },
  input: {
    backgroundColor: colors.surfaceSecondary, borderWidth: 1.5, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: spacing.md, height: 50, fontFamily: font.regular, fontSize: fontSize.lg, color: colors.onSurface,
    ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}),
  },
  error: { color: colors.error, fontFamily: font.medium, fontSize: fontSize.base, marginTop: spacing.sm },
  docHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: spacing.xl, marginBottom: spacing.md },
  shareBtn: { flexDirection: "row", alignItems: "center", gap: 5, backgroundColor: colors.brandTertiary, paddingHorizontal: spacing.md, paddingVertical: 6, borderRadius: radius.pill },
  shareText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand },
  docRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, backgroundColor: DARK_BG, borderRadius: DARK_TILE_RADIUS, padding: spacing.md, borderWidth: 1, borderColor: DARK_BORDER, marginBottom: spacing.sm },
  docName: { flex: 1, fontFamily: font.medium, fontSize: fontSize.base, color: DARK_TEXT },
  impersonateBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.sm, backgroundColor: "#EA580C", borderRadius: radius.md, height: 48, marginTop: spacing.md },
  impersonateText: { fontFamily: font.semibold, fontSize: fontSize.base, color: "#fff" },
  pmCard: { flexDirection: "row", alignItems: "center", gap: spacing.md, backgroundColor: DARK_BG, borderRadius: DARK_TILE_RADIUS, padding: spacing.md, borderWidth: 1, borderColor: DARK_BORDER, marginTop: spacing.md },
  pmIcon: { width: 36, height: 36, borderRadius: radius.sm, backgroundColor: colors.brandTertiary, alignItems: "center", justifyContent: "center" },
  pmLabel: { fontFamily: font.regular, fontSize: fontSize.sm, color: DARK_TEXT_MUTED },
  pmValue: { fontFamily: font.semibold, fontSize: fontSize.base, color: DARK_TEXT, marginTop: 1 },
  pmRequest: { backgroundColor: colors.brandTertiary, paddingHorizontal: spacing.md, paddingVertical: 6, borderRadius: radius.pill },
  pmRequestText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand },
  sendLinkRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    marginTop: spacing.xs,
  },
  sendLinkText: {
    fontFamily: font.medium,
    fontSize: fontSize.sm,
    color: colors.brand,
    textDecorationLine: "underline",
  },
  cardRequiredCard: { backgroundColor: DARK_BG, borderRadius: DARK_TILE_RADIUS, padding: spacing.md, borderWidth: 1, borderColor: DARK_BORDER, marginTop: spacing.sm },
  resetDefaultBtn: { marginTop: 6 },
  resetDefaultText: { fontFamily: font.medium, fontSize: 11, color: colors.brand, textDecorationLine: "underline" },
  creditsBanner: { flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: "#DCFCE7", borderRadius: radius.md, padding: spacing.md, marginTop: spacing.sm, borderWidth: 1, borderColor: "#BBF7D0" },
  creditsText: { fontFamily: font.semibold, fontSize: fontSize.base, color: "#166534" },
  // Credits section styles (Phase 13B)
  creditsSection: { backgroundColor: DARK_BG, borderRadius: DARK_TILE_RADIUS, padding: spacing.lg, marginTop: spacing.md, borderWidth: 1, borderColor: DARK_BORDER },
  creditsSectionHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  creditsLabel: { fontFamily: font.bold, fontSize: 10, color: DARK_TEXT_MUTED, letterSpacing: 1, textTransform: "uppercase" },
  creditsAmount: { fontFamily: font.bold, fontSize: 28, color: "#166534", marginTop: 2 },
  adjustBtn: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 12, paddingVertical: 8, borderRadius: radius.md, borderWidth: 1, borderColor: colors.brand },
  adjustBtnText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand },
  ledgerList: { marginTop: spacing.md, gap: 1 },
  ledgerRow: { flexDirection: "row", alignItems: "center", paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: DARK_BORDER },
  ledgerSource: { fontFamily: font.semibold, fontSize: fontSize.sm, color: DARK_TEXT, textTransform: "capitalize" },
  ledgerNote: { fontFamily: font.regular, fontSize: 11, color: DARK_TEXT_MUTED, marginTop: 1 },
  ledgerActor: { fontFamily: font.regular, fontSize: 10, color: DARK_TEXT_MUTED, fontStyle: "italic" },
  ledgerDelta: { fontFamily: font.bold, fontSize: fontSize.base },
  ledgerDate: { fontFamily: font.regular, fontSize: 10, color: DARK_TEXT_MUTED, marginTop: 1 },
  ledgerEmpty: { fontFamily: font.regular, fontSize: fontSize.sm, color: DARK_TEXT_MUTED, marginTop: spacing.sm },
  loadMoreText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand, textAlign: "center", paddingTop: 8 },
  // Adjust modal
  adjOverlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)", justifyContent: "center", padding: 24 },
  adjCard: { backgroundColor: "#fff", borderRadius: radius.lg, padding: spacing.xl },
  adjTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  adjCurrent: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2, marginBottom: spacing.md },
  adjInput: { backgroundColor: "#F8FAFC", borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, padding: spacing.md, fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, marginBottom: spacing.sm },
  adjPreview: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.brand, marginBottom: spacing.sm },
  adjError: { fontFamily: font.medium, fontSize: fontSize.sm, color: "#DC2626", marginBottom: spacing.sm },
  adjBtns: { flexDirection: "row", justifyContent: "flex-end", gap: spacing.sm, marginTop: spacing.sm },
  adjCancel: { paddingHorizontal: 16, paddingVertical: 10, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border },
  adjCancelText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurface },
  adjSave: { paddingHorizontal: 16, paddingVertical: 10, borderRadius: radius.md, backgroundColor: colors.brand },
  adjSaveText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: "#fff" },
  inactiveBadge: {
    alignSelf: "flex-start",
    backgroundColor: "#E5E7EB", borderColor: "#9CA3AF", borderWidth: 1,
    paddingHorizontal: 10, paddingVertical: 4, borderRadius: radius.pill,
    marginBottom: spacing.md,
  },
  inactiveBadgeText: {
    fontFamily: font.bold, fontSize: fontSize.xs, color: "#4B5563",
    letterSpacing: 1, textTransform: "uppercase",
  },
  fab: {
    position: "absolute", bottom: 24, right: 20,
    width: 52, height: 52, borderRadius: 26,
    backgroundColor: colors.brand,
    alignItems: "center", justifyContent: "center",
    elevation: 6,
    shadowColor: "#000", shadowOffset: { width: 0, height: 3 },
    shadowOpacity: 0.25, shadowRadius: 4,
    zIndex: 40,
  },
});

// Ship 2 · extra styles
const s2 = StyleSheet.create({
  deleteBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    backgroundColor: "#FEE2E2",
    borderColor: "#FCA5A5",
    borderWidth: 1,
    borderRadius: radius.md,
    paddingVertical: 10,
    paddingHorizontal: 16,
    marginTop: spacing.md,
    marginBottom: spacing.xs,
  },
  deleteBtnText: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: "#B91C1C",
  },
  // Phase 25 · Phase-20 action row (full-width, wraps on narrow phones).
  actionRow: {
    flexDirection: "row", flexWrap: "wrap", gap: spacing.sm,
    marginBottom: spacing.md,
  },
  actionBtn: {
    flexGrow: 1, flexBasis: "45%", minHeight: 44, height: undefined,
    marginTop: 0, marginBottom: 0, paddingVertical: 10, paddingHorizontal: 12,
    borderRadius: radius.md, flexDirection: "row", alignItems: "center",
    justifyContent: "center", gap: 6,
  },
  // Phase 40 · web Phase 38 — steel Edit / View-as, emerald Call.
  actionBtnSteel: { backgroundColor: CD_ACTION_BTN_BG, borderWidth: 1, borderColor: CD_ACTION_BTN_BORDER },
  actionBtnCall: { backgroundColor: CD_CALL_BTN_BG, borderWidth: 1, borderColor: CD_CALL_BTN_BG },
  // Phase 32 · light card chassis for the four status/mute controls.
  lightCard: {
    backgroundColor: LIGHT_CARD_BG, borderWidth: 1, borderColor: LIGHT_CARD_BORDER,
    borderRadius: LIGHT_CARD_RADIUS, padding: spacing.md, marginBottom: spacing.sm,
  },
  actionBtnText: { fontFamily: font.semibold, fontSize: fontSize.sm },
});
