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
import { StripeConfigProvider } from "@/src/config/stripe";
import { registerOfflineTemplateDraftListeners } from "@/src/utils/offlineTemplateDrafts";
import { SyncManagerProvider } from "@/src/services/SyncManager";
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

  // If the CDN is unreachable we fall through on error rather than wedging
  // the app — icons will tofu, but the app still boots.
  if (!ready) return null;

  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <SafeAreaProvider>
        <KeyboardProvider>
          <AuthProvider>
            <SyncManagerProvider>
              <StripeConfigProvider>
                <ImpersonationBanner />
                <PushTapRouter />
                <Stack screenOptions={{ headerShown: false }} />
              </StripeConfigProvider>
            </SyncManagerProvider>
          </AuthProvider>
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
