import React from "react";
import { View, TouchableOpacity } from "react-native";
import { Ionicons } from "@expo/vector-icons";

/** Interactive 5-star picker; taps commit immediately (mobile UX). */
export function StarRatingInputNative({
  value = 0,
  onChange,
  size = 32,
  color = "#F59E0B",
  bgColor = "#D1D5DB",
  disabled = false,
  testID = "star-input",
}: {
  value?: number;
  onChange?: (n: number) => void;
  size?: number;
  color?: string;
  bgColor?: string;
  disabled?: boolean;
  testID?: string;
}) {
  const stars = [1, 2, 3, 4, 5];
  return (
    <View
      style={{ flexDirection: "row", gap: 4, alignItems: "center" }}
      testID={testID}
    >
      {stars.map((i) => {
        const active = i <= value;
        return (
          <TouchableOpacity
            key={i}
            testID={`${testID}-btn-${i}`}
            disabled={disabled}
            activeOpacity={0.7}
            onPress={() => !disabled && onChange && onChange(i)}
            style={{ padding: 4, opacity: disabled ? 0.4 : 1 }}
          >
            <Ionicons
              name={active ? "star" : "star-outline"}
              size={size}
              color={active ? color : bgColor}
            />
          </TouchableOpacity>
        );
      })}
    </View>
  );
}

export default StarRatingInputNative;
