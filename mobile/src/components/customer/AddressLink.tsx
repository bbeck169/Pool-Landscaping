/**
 * <AddressLink> — tappable address that opens the OS-appropriate maps app.
 *
 * - iOS:     maps://?q=<encoded>  (fallback → Apple Maps HTTPS)
 * - Android: geo:0,0?q=<encoded>  (fallback → Google Maps HTTPS)
 * - Web:     Google Maps HTTPS
 *
 * Empty / invalid → plain <Text>.
 */
import React, { useCallback, useMemo } from "react";
import { Pressable, Text, Linking, Platform, StyleSheet, type TextStyle } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors } from "@/src/theme";

export interface AddressObject {
  line1?: string | null;
  line2?: string | null;
  city?: string | null;
  state?: string | null;
  zip?: string | null;
  postal_code?: string | null;
  country?: string | null;
}

export interface AddressLinkProps {
  address: string | AddressObject | null | undefined;
  style?: TextStyle;
  children?: React.ReactNode;
  showIcon?: boolean;
  testID?: string;
}

function assembleAddress(addr: string | AddressObject | null | undefined): string {
  if (!addr) return "";
  if (typeof addr === "string") return addr.trim();
  const parts = [addr.line1, addr.line2, addr.city, addr.state, addr.zip || addr.postal_code, addr.country].filter(Boolean);
  return parts.join(", ").trim();
}

export default function AddressLink({ address, style, children, showIcon = true, testID }: AddressLinkProps) {
  const text = useMemo(() => assembleAddress(address), [address]);

  const handlePress = useCallback(async () => {
    if (!text) return;
    const encoded = encodeURIComponent(text);
    const os = Platform.OS;
    try {
      if (os === "ios") {
        const mapsUrl = `maps://?q=${encoded}`;
        const canOpen = await Linking.canOpenURL(mapsUrl);
        if (canOpen) {
          await Linking.openURL(mapsUrl);
        } else {
          await Linking.openURL(`https://maps.apple.com/?q=${encoded}`);
        }
      } else if (os === "android") {
        const geoUrl = `geo:0,0?q=${encoded}`;
        const canOpen = await Linking.canOpenURL(geoUrl);
        if (canOpen) {
          await Linking.openURL(geoUrl);
        } else {
          await Linking.openURL(`https://www.google.com/maps/search/?api=1&query=${encoded}`);
        }
      } else {
        // Web / unknown
        await Linking.openURL(`https://www.google.com/maps/search/?api=1&query=${encoded}`);
      }
    } catch (e) {
      // eslint-disable-next-line no-console
      console.warn("[AddressLink] Could not open maps:", e);
    }
  }, [text]);

  if (!text) {
    return <Text style={style} testID={testID}>{children || "—"}</Text>;
  }

  return (
    <Pressable
      onPress={handlePress}
      hitSlop={8}
      accessibilityLabel={`Open in maps: ${text}`}
      accessibilityRole="link"
      style={s.row}
      testID={testID}
    >
      {showIcon ? <Ionicons name="location-outline" size={14} color={colors.brand} /> : null}
      <Text style={[s.linkText, style]} numberOfLines={1}>{children || text}</Text>
    </Pressable>
  );
}

const s = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "center", gap: 4 },
  linkText: { textDecorationLine: "underline", textDecorationColor: colors.brand, color: colors.brand },
});
