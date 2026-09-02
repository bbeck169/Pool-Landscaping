import { Stack, Redirect, useSegments } from "expo-router";
import { View } from "react-native";

import { useAuth } from "@/src/auth";
import PaymentMethodPromptBanner from "@/src/components/portal/PaymentMethodPromptBanner";

const BANNER_EXCLUDED = new Set(["home", "payment-method", "add-card"]);

export default function PortalLayout() {
  const { user, loading } = useAuth();
  const segments = useSegments();
  if (loading) return null;
  if (!user) return <Redirect href="/login" />;

  // Last segment identifies the current portal screen. Default to "home".
  const current = segments[segments.length - 1] || "home";
  const showBanner = !BANNER_EXCLUDED.has(current);

  return (
    <View style={{ flex: 1 }}>
      {showBanner && <PaymentMethodPromptBanner />}
      <Stack screenOptions={{ headerShown: false }} />
    </View>
  );
}
