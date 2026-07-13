import { Stack, Redirect } from "expo-router";

import { useAuth } from "@/src/auth";

export default function PortalLayout() {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (!user) return <Redirect href="/login" />;
  return <Stack screenOptions={{ headerShown: false }} />;
}
