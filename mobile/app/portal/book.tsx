// DEPRECATED — Phase 34 · Task H
// "Book Service" has been retired. This route redirects to Request Service.
import React, { useEffect } from "react";
import { View, Text } from "react-native";
import { useRouter } from "expo-router";
import { colors, font, fontSize } from "@/src/theme";

export default function PortalBook() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/request-service" as any);
  }, [router]);
  return (
    <View style={{ flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface }}>
      <Text style={{ fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted }}>
        Redirecting to Request Service…
      </Text>
    </View>
  );
}
