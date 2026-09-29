import { Stack, useRouter } from "expo-router";
import * as SplashScreen from "expo-splash-screen";
import * as Notifications from "expo-notifications";
import { useEffect, useRef } from "react";
import { LogBox, AppState, type AppStateStatus } from "react-native";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { KeyboardProvider } from "react-native-keyboard-controller";
import { useFonts } from "expo-font";

import { useIconFonts } from "@/src/hooks/use-icon-fonts";
import { AuthProvider, useAuth } from "@/src/auth";
import { ImpersonationBanner } from "@/src/components/ImpersonationBanner";
// Feb-2026 · P2→P0 tech-cluster diagnostic — root error boundary so
// any uncaught JS throw during render surfaces as a visible diagnostic
// screen instead of the silent blank-white that hid the Android home
// crash from us in the field.
import { RootErrorBoundary } from "@/src/components/RootErrorBoundary";
// Phase 30.4 · Feb-2026 — global destructive-confirmation modal host.
// Mount once at the root so ``showConfirm({...})`` from any screen
// opens an in-app modal we can guarantee renders (vs
// ``Alert.alert(...)`` which silently no-ops on some Android/Expo Go
// builds — root cause of the Phase 30.3 portal sign-out P0).
import { ConfirmModalHost } from "@/src/components/ConfirmModal";
import { StripeConfigProvider } from "@/src/config/stripe";
import { ToastProvider } from "@/src/components/ToastProvider";
import { registerOfflineTemplateDraftListeners } from "@/src/utils/offlineTemplateDrafts";
import { SyncManagerProvider } from "@/src/services/SyncManager";
// FLEET-B · Hook that initializes foreground GPS emission for fleet techs.
import { useFleetEmitter } from "@/src/hooks/useFleetEmitter";
// TB-1 · Wake-word listener for "Hey MARCO".
import { useMarcoWakeWord } from "@/src/hooks/useMarcoWakeWord";
// OTA auto-update listener — background check + subtle "update ready" toast.
import { useOtaUpdateListener } from "@/src/hooks/useOtaUpdateListener";
// Phase O2 · Offline sync foundation — boot the sync infra.
import { startListening as startNetBus, wireAutoFlush, flush as flushSyncQueue } from "@/src/services/sync";
import { wirePhotoAutoUpload, flushPhotos } from "@/src/services/sync/photoWorker";
import { wireVideoAutoUpload, flushVideos } from "@/src/services/sync/videoWorker";
import { getSyncDb } from "@/src/services/sync/db";
// P37c · Geofence region sync — register active job geofences on boot.
import { syncJobGeofencesP37c } from "@/src/background/jobGeofence";
// Phase O6 · Sync UI components.
import { OfflineBanner, ConflictSheet, SyncToast, StoragePressureBanner } from "@/src/components/sync";
// Phase 20 · Feb-2026 · Sub-item B — role-aware push tap-through.
import { resolveNotificationRoute } from "@/src/services/notificationRoutes";

// Disable logbox errors etc so that users can see the app
// and agent works as expected.
LogBox.ignoreAllLogs(true);

// Keep the native splash visible from cold start until icon fonts register.
// Required because @expo/vector-icons' componentDidMount fallback fires
// Font.loadAsync against a broken vendor path if any <Icon> mounts before
// the family is registered — which throws on Android Expo Go.
SplashScreen.preventAutoHideAsync();

export default function RootLayout() {
  const [iconsLoaded, iconError] = useIconFonts();
  const [fontsLoaded] = useFonts({
    "PlusJakarta-Regular": require("../assets/fonts/PlusJakartaSans-Regular.ttf"),
    "PlusJakarta-Medium": require("../assets/fonts/PlusJakartaSans-Medium.ttf"),
    "PlusJakarta-SemiBold": require("../assets/fonts/PlusJakartaSans-SemiBold.ttf"),
    "PlusJakarta-Bold": require("../assets/fonts/PlusJakartaSans-Bold.ttf"),
  });

  const ready = (iconsLoaded || iconError) && fontsLoaded;

  useEffect(() => {
    if (ready) {
      SplashScreen.hideAsync();
    }
  }, [ready]);

  // Register global offline template-draft sync listeners (NetInfo + AppState)
  useEffect(() => {
    const unsub = registerOfflineTemplateDraftListeners();
    return unsub;
  }, []);

  // OTA auto-update listener — checks for updates on cold start and foreground.
  // Never auto-reloads mid-session; shows a subtle alert instead.
  useOtaUpdateListener();

  // FLEET-B · Start the foreground GPS emitter for fleet-enrolled techs.
  useFleetEmitter();

  // TB-1 · Start the "Hey MARCO" wake-word listener for techs.
  useMarcoWakeWord();

  // Phase O2 · Offline sync foundation — init SQLite schema + net bus + auto-flush.
  // Phase O3 · Wire photo auto-upload on reconnect.
  // K36 · Every boot-sync side-effect now runs inside try/catch with
  // a diagnostic breadcrumb so a native module init failure never
  // crashes the shell before the first frame renders.
  useEffect(() => {
    (async () => {
      // Late-bind the diagnostic helpers so a bad module init here
      // can't cascade into the layout module itself.
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      const { logNav } = require("@/src/utils/diagnostics");
      logNav("boot.sync.start");
      try { await getSyncDb(); } catch (e: any) {
        console.warn("[O2] SQLite init failed:", e?.message || e);
        logNav("boot.sync.sqlite_failed", { err: String(e?.message || e).slice(0, 120) });
      }
      try { startNetBus(); } catch (e: any) {
        console.warn("[boot] startNetBus failed:", e?.message || e);
        logNav("boot.sync.netbus_failed", { err: String(e?.message || e).slice(0, 120) });
      }
      try { wireAutoFlush(); } catch (e: any) {
        console.warn("[boot] wireAutoFlush failed:", e?.message || e);
        logNav("boot.sync.autoflush_failed", { err: String(e?.message || e).slice(0, 120) });
      }
      try { wirePhotoAutoUpload(); } catch (e: any) {
        console.warn("[boot] wirePhotoAutoUpload failed:", e?.message || e);
        logNav("boot.sync.photo_failed", { err: String(e?.message || e).slice(0, 120) });
      }
      // Phase 2 · Wire video auto-upload on reconnect.
      try { wireVideoAutoUpload(); } catch (e: any) {
        console.warn("[boot] wireVideoAutoUpload failed:", e?.message || e);
        logNav("boot.sync.video_failed", { err: String(e?.message || e).slice(0, 120) });
      }
      // K36 · best-effort crash upload from prior session's persisted
      // slot. Never blocks boot; never surfaces errors.
      try {
        // eslint-disable-next-line @typescript-eslint/no-require-imports
        const { uploadPendingCrash } = require("@/src/utils/crashReporter");
        uploadPendingCrash().catch(() => {});
      } catch { /* swallow */ }
      // P37c · Register geofences for active jobs on boot.
      // Fire-and-forget; never blocks boot; silent on failure.
      try { syncJobGeofencesP37c().catch(() => {}); } catch { /* swallow */ }
      logNav("boot.sync.done");
    })();
  }, []);

  // Phase 2 · AppState foreground trigger — flush sync queue when the
  // app returns from background. This ensures pending writes sync
  // within seconds of the tech switching back to the app.
  const appStateRef = useRef<AppStateStatus>(AppState.currentState);
  useEffect(() => {
    const sub = AppState.addEventListener("change", (nextState: AppStateStatus) => {
      if (
        appStateRef.current.match(/inactive|background/) &&
        nextState === "active"
      ) {
        // App came to foreground — trigger sync.
        flushSyncQueue().catch(() => {});
        flushPhotos().catch(() => {});
        flushVideos().catch(() => {});
      }
      appStateRef.current = nextState;
    });
    return () => sub.remove();
  }, []);

  // Phase K46 · Feb-2026 — Mapbox token dev-mode placeholder guard
  // removed. Mapbox is no longer a runtime dependency of this app
  // (see ``memory/PHASE_K46_GOOGLE_MAPS_MIGRATION.md``). Google
  // Maps keys are validated at every map surface via
  // ``hasGoogleMapsKey()`` from ``@/src/utils/mapsKey``.

  // If the CDN is unreachable we fall through on error rather than wedging
  // the app — icons will tofu, but the app still boots.
  if (!ready) return null;

  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <SafeAreaProvider>
        <KeyboardProvider>
          <RootErrorBoundary>
            <AuthProvider>
              <SyncManagerProvider>
                <StripeConfigProvider>
                  <ToastProvider>
                  <OfflineBanner />
                  <StoragePressureBanner />
                  <ImpersonationBanner />
                  <PushTapRouter />
                  <Stack screenOptions={{ headerShown: false }} />
                  <ConfirmModalHost />
                  <ConflictSheet />
                  <SyncToast />
                  </ToastProvider>
                </StripeConfigProvider>
              </SyncManagerProvider>
            </AuthProvider>
          </RootErrorBoundary>
        </KeyboardProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}

/**
 * Phase 20 · Feb-2026 · Sub-item B — push tap-through listener.
 *
 * When a user taps a push notification (either while the app is
 * backgrounded or from a cold-start "opened by notification" event),
 * consume ``notification.request.content.data`` (which we set on the
 * server side alongside every ``notifications.emit`` call), resolve
 * a role-aware route via the shared resolver, and navigate. Safe to
 * mount even when the user hasn't granted push permissions — the
 * subscription just never fires.
 */
function PushTapRouter() {
  const router = useRouter();
  const { user } = useAuth();
  useEffect(() => {
    const sub = Notifications.addNotificationResponseReceivedListener(
      (resp) => {
        try {
          const data: any = resp.notification.request.content.data || {};
          const path = resolveNotificationRoute(data, user);
          if (path) router.push(path as any);
        } catch (e) {
          // Never let a bad payload crash the shell.
          console.warn("[push] tap-through failed:", e);
        }
      },
    );
    return () => sub.remove();
  }, [router, user]);
  return null;
}
