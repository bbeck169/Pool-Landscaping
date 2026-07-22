/**
 * Push notification registration service.
 * Requests permission, obtains Expo push token, and registers with backend.
 */
import { Platform } from "react-native";
import * as Notifications from "expo-notifications";
import * as Device from "expo-device";
import { registerPushToken, deletePushToken } from "@/src/api/pushTokens";

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldPlaySound: true,
    shouldSetBadge: true,
    shouldShowBanner: true,
    shouldShowList: true,
  }),
});

/**
 * Request push permissions, get Expo push token, register with backend.
 * Returns the token string or null if unavailable (e.g. simulator).
 */
export async function registerForPushNotifications(): Promise<string | null> {
  // Push tokens are only available on physical devices
  if (Platform.OS !== "web" && !Device.isDevice) {
    console.log("[push] Not a physical device — skipping token registration");
    return null;
  }

  try {
    const { status: existing } = await Notifications.getPermissionsAsync();
    let finalStatus = existing;

    if (existing !== "granted") {
      const { status } = await Notifications.requestPermissionsAsync();
      finalStatus = status;
    }

    if (finalStatus !== "granted") {
      console.log("[push] Permission denied");
      return null;
    }

    const tokenData = await Notifications.getExpoPushTokenAsync();
    const token = tokenData.data;

    if (!token || token.length < 8) {
      console.log("[push] Token unavailable (simulator?)");
      return null;
    }

    const platform = Platform.OS === "ios" ? "ios" : Platform.OS === "android" ? "android" : "web";
    await registerPushToken(token, platform, Device.modelName || undefined);
    console.log("[push] Registered token:", token.slice(0, 20) + "...");
    return token;
  } catch (err) {
    console.warn("[push] Registration failed:", err);
    return null;
  }
}

/**
 * Deregister the current push token from the backend.
 */
export async function deregisterPushToken(): Promise<void> {
  try {
    const tokenData = await Notifications.getExpoPushTokenAsync();
    if (tokenData.data) {
      await deletePushToken(tokenData.data);
    }
  } catch (err) {
    console.warn("[push] Deregistration failed:", err);
  }
}
