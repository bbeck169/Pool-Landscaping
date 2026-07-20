import React from "react";
import { View, Text } from "react-native";
import { StarRatingDisplayNative } from "./StarRatingDisplayNative";
import { PlatformIconNative } from "./PlatformIconNative";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";

/** Compact review tile — reused across recent list, leaderboard,
 *  and the widget-preview screens. */
export function ReviewCardNative({
  review,
  testID,
}: {
  review: any;
  testID?: string;
}) {
  const r = review || {};
  const when = (r.created_at || "").slice(0, 10);
  return (
    <View
      style={{
        backgroundColor: colors.surfaceSecondary,
        borderColor: colors.border,
        borderWidth: 1,
        borderRadius: radius.md,
        padding: spacing.lg,
        marginBottom: spacing.sm,
      }}
      testID={testID}
    >
      <View
        style={{
          flexDirection: "row",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 8,
        }}
      >
        <StarRatingDisplayNative value={r.star_rating || 0} size={14} />
        {r.platform ? (
          <View style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
            <PlatformIconNative code={r.platform} size={12} />
            <Text
              style={{
                fontFamily: font.medium,
                fontSize: 11,
                color: colors.muted,
                textTransform: "capitalize",
              }}
            >
              {r.platform}
            </Text>
          </View>
        ) : null}
      </View>
      {r.review_text ? (
        <Text
          style={{
            fontFamily: font.regular,
            fontSize: fontSize.sm,
            color: colors.onSurface,
            lineHeight: 18,
            marginBottom: 8,
          }}
        >
          {r.review_text}
        </Text>
      ) : (
        <Text
          style={{
            fontFamily: font.regular,
            fontSize: fontSize.sm,
            fontStyle: "italic",
            color: colors.muted,
            marginBottom: 8,
          }}
        >
          Rating only.
        </Text>
      )}
      <Text
        style={{ fontFamily: font.regular, fontSize: 10, color: colors.muted }}
      >
        {r.reviewer_name || "Anonymous"}
        {when ? ` · ${when}` : ""}
      </Text>
    </View>
  );
}

export default ReviewCardNative;
