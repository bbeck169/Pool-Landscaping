/**
 * DecimalInput — numeric TextInput that accepts in-progress decimals.
 *
 * Mobile mirror of web `frontend/src/components/common/DecimalInput.jsx`.
 * Keeps the raw string ("7.", ".", ".5") in local state so typing a
 * decimal point is never stripped, and propagates the parsed number on
 * every keystroke (so a Submit tap without blur still sees "7.5" → 7.5).
 * On blur the display is normalized ("7." → "7", "." → "").
 */
import React, { useEffect, useState } from "react";
import { TextInputProps } from "react-native";
import AppTextInput from "@/src/components/ui/AppTextInput";

/** Accepts "", digits, one decimal point (comma from EU keypads → "."). Returns null when rejected. */
export function sanitizeDecimal(text: string): string | null {
  const s = (text ?? "").replace(",", ".");
  return s === "" || /^\d*\.?\d*$/.test(s) ? s : null;
}

export function parseDecimal(raw: string): number | null {
  if (raw === "" || raw === ".") return null;
  const n = parseFloat(raw);
  return Number.isFinite(n) ? n : null;
}

const toRaw = (v: number | null | undefined) => (v == null ? "" : String(v));

type Props = Omit<TextInputProps, "value" | "onChangeText" | "keyboardType"> & {
  value: number | null | undefined;
  onChangeValue: (n: number | null) => void;
};

export default function DecimalInput({ value, onChangeValue, onBlur, ...rest }: Props) {
  const [raw, setRaw] = useState<string>(toRaw(value));

  // Resync only when the parent value genuinely differs from what we're showing.
  useEffect(() => {
    setRaw((cur) => (parseDecimal(cur) === (value ?? null) ? cur : toRaw(value)));
  }, [value]);

  const handleChange = (t: string) => {
    const s = sanitizeDecimal(t);
    if (s === null) return;
    setRaw(s);
    onChangeValue(parseDecimal(s));
  };

  const handleBlur: TextInputProps["onBlur"] = (e) => {
    const n = parseDecimal(raw);
    setRaw(toRaw(n));
    onChangeValue(n);
    onBlur?.(e);
  };

  return (
    <AppTextInput
      {...rest}
      keyboardType="decimal-pad"
      value={raw}
      onChangeText={handleChange}
      onBlur={handleBlur}
    />
  );
}
