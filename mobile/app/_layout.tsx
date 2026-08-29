import { Stack, useRouter } from "expo-router";
import * as SplashScreen from "expo-splash-screen";
import * as Notifications from "expo-notifications";
import { useEffect } from "react";
import { LogBox } from "react-native";
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
import { registerOfflineTemplateDraftListeners } from "@/src/utils/offlineTemplateDrafts";
import { SyncManagerProvider } from "@/src/services/SyncManager";
// Phase O2 · Offline sync foundation — boot the sync infra.
import { startListening as startNetBus, wireAutoFlush } from "@/src/services/sync";
import { wirePhotoAutoUpload } from "@/src/services/sync/photoWorker";
import { getSyncDb } from "@/src/services/sync/db";
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

  // Phase O2 · Offline sync foundation — init SQLite schema + net bus + auto-flush.
  // Phase O3 · Wire photo auto-upload on reconnect.
  useEffect(() => {
    getSyncDb().catch((e) => console.warn("[O2] SQLite init failed:", e));
    startNetBus();
    wireAutoFlush();
    wirePhotoAutoUpload();
  }, []);

  // Phase P11c — Mapbox token placeholder guard (__DEV__ only).
  // Warns at startup if the public token is still a placeholder so
  // devs don't waste time debugging blank map screens.
  useEffect(() => {
    if (!__DEV__) return;
    const token = process.env.EXPO_PUBLIC_MAPBOX_TOKEN ?? "";
    if (!token || token.startsWith("pk.REPLACE_ME")) {
      console.warn(
        '[Mapbox] ⚠️  EXPO_PUBLIC_MAPBOX_TOKEN is a placeholder ("pk.REPLACE_ME") or missing.\n' +
          "Map screens will fail. Get a free public token from:\n" +
          "https://account.mapbox.com/access-tokens/",
      );
    }
  }, []);

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
                  <ImpersonationBanner />
                  <PushTapRouter />
                  <Stack screenOptions={{ headerShown: false }} />
                  <ConfirmModalHost />
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
