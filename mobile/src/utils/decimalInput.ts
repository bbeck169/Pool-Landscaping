/**
 * iOS decimal entry for chemistry readings.
 *
 * `keyboardType="decimal-pad"` on iOS shows the DEVICE-LOCALE decimal
 * separator — "," on de/fr/es/pt-BR/… devices — so a tech typing pH 7,6
 * produced a draft our "."-only validators rejected (reading never saved;
 * parseFloat("7,6") → 7 in calculators). Android's decimal keypad still
 * offers "." and web uses its own keyboard, which is why only iOS broke.
 *
 * Use as `onChangeText={(t) => setDraft((prev) => sanitizeDecimalInput(t, prev))}`.
 *   - "," → "."   (locale separator)
 *   - whitespace dropped
 *   - any other non-digit (letters, "-", "e", …) → keep previous value (no-op)
 *   - a second "." → keep previous value (7.6 → 7.6. rejected)
 *   - partials ("7.", ".5", "") pass through untouched; parse on commit
 */
export function sanitizeDecimalInput(next: string | null | undefined, prev: string = ""): string {
  const s = String(next ?? "").replace(/\s+/g, "").replace(/,/g, ".");
  if (!/^[0-9.]*$/.test(s)) return prev;
  if (s.split(".").length > 2) return prev;
  return s;
}
