import React from "react";
import { View, Text } from "react-native";
import { Ionicons } from "@expo/vector-icons";

/** Read-only star row supporting fractional averages. */
export function StarRatingDisplayNative({
  value = 0,
  size = 14,
  color = "#F59E0B",
  bgColor = "#D1D5DB",
  showValue = false,
  testID,
}: {
  value?: number;
  size?: number;
  color?: string;
  bgColor?: string;
  showValue?: boolean;
  testID?: string;
}) {
  const v = Math.max(0, Math.min(5, Number(value) || 0));
  const pct = (v / 5) * 100;
  const stars = [0, 1, 2, 3, 4];
  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }} testID={testID}>
      <View style={{ position: "relative" }}>
        <View style={{ flexDirection: "row", gap: 2 }}>
          {stars.map((i) => (
            <Ionicons key={i} name="star-outline" size={size} color={bgColor} />
          ))}
        </View>
        <View
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            flexDirection: "row",
            gap: 2,
            width: `${pct}%`,
            overflow: "hidden",
          }}
        >
          {stars.map((i) => (
            <Ionicons key={i} name="star" size={size} color={color} />
          ))}
        </View>
      </View>
      {showValue ? (
        <Text style={{ fontSize: 12, fontWeight: "600", color: "#0F172A" }}>
          {v.toFixed(1)}
        </Text>
      ) : null}
    </View>
  );
}

export default StarRatingDisplayNative;
