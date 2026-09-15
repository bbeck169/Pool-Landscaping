/**
 * Phase 42 · Tools Hub search box.
 *
 * Controlled `TextInput` with a clear button. Debounces the parent's
 * `onQueryChange` callback by 200ms so filtering 25+ tiles doesn't stutter
 * on every keystroke on lower-end Android.
 */
import React, { useEffect, useRef, useState } from "react";
import { View, Pressable, StyleSheet, Platform } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import AppTextInput from "@/src/components/ui/AppTextInput";

type Props = {
  onQueryChange: (q: string) => void;
  placeholder?: string;
  debounceMs?: number;
  testID?: string;
};

export const SearchBar: React.FC<Props> = ({
  onQueryChange, placeholder = "Search tools…", debounceMs = 200,
  testID = "tools-search",
}) => {
  const [text, setText] = useState("");
  const timer = useRef<any>(null);

  useEffect(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      onQueryChange(text.trim());
    }, debounceMs);
    return () => { if (timer.current) clearTimeout(timer.current); };
    // We intentionally exclude onQueryChange from deps — parent passes a
    // fresh callback every render, and re-registering the timer on each
    // parent render would defeat the debounce.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text, debounceMs]);

  return (
    <View style={styles.wrap}>
      <Ionicons name="search-outline" size={18} color={colors.muted} />
      <AppTextInput
        testID={testID}
        style={styles.input}
        value={text}
        onChangeText={setText}
        placeholder={placeholder}
        placeholderTextColor={colors.muted}
        autoCorrect={false}
        autoCapitalize="none"
        returnKeyType="search"
      />
      {text.length > 0 ? (
        <Pressable
          onPress={() => { setText(""); onQueryChange(""); }}
          testID="tools-search-clear"
          hitSlop={12}
          accessibilityLabel="Clear search"
        >
          <Ionicons name="close-circle" size={18} color={colors.muted} />
        </Pressable>
      ) : null}
    </View>
  );
};

const styles = StyleSheet.create({
  wrap: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    marginHorizontal: spacing.lg,
    marginTop: spacing.md,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    height: 44,
  },
  input: {
    flex: 1,
    fontFamily: font.regular,
    fontSize: fontSize.base,
    color: colors.onSurface,
    ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}),
  },
});
