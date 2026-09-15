/**
 * Phase T1 — Sitewide input theme wrapper.
 *
 * Drop-in replacement for React Native's `TextInput` that applies the
 * canonical white-bg / navy-text / muted-navy-placeholder theme.
 *
 * Usage: import AppTextInput from "@/src/components/ui/AppTextInput";
 *        <AppTextInput style={styles.myInput} placeholder="Type…" />
 *
 * Existing style props are preserved (spread BEFORE the theme overrides
 * so the theme always wins for bg + text color).
 */
import React, { forwardRef } from "react";
import { TextInput, TextInputProps, StyleSheet } from "react-native";
import { inputColors } from "@/src/theme";

const AppTextInput = forwardRef<TextInput, TextInputProps>((props, ref) => (
  <TextInput
    placeholderTextColor={props.placeholderTextColor ?? inputColors.placeholder}
    {...props}
    ref={ref}
    style={[props.style, themed.base]}
  />
));

AppTextInput.displayName = "AppTextInput";
export default AppTextInput;

const themed = StyleSheet.create({
  base: {
    backgroundColor: inputColors.bg,
    color: inputColors.text,
  },
});
