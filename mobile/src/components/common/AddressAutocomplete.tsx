/**
 * AddressAutocomplete — React Native address input with Google Places
 * suggestions via the anonymous backend proxy.
 *
 * Mirrors ``frontend/src/components/common/AddressAutocomplete.jsx``.
 *
 * Props:
 *   value — current display string
 *   onChange({street, city, state, zip, latitude, longitude, formatted}) —
 *     fired on suggestion selection AND on manual typing.
 *   placeholder, disabled, error — standard input plumbing.
 *   testID — root testID for the component.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  View, Text, Pressable, StyleSheet, ActivityIndicator,
  Platform } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import AppTextInput from "@/src/components/ui/AppTextInput";

const API = process.env.EXPO_PUBLIC_BACKEND_URL || "";
const DEBOUNCE_MS = 250;
const MIN_QUERY = 3;
const MAX_ROWS = 5;

// ── Helpers ─────────────────────────────────────────────────────────
function buildQs(params: Record<string, string | undefined | null>): string {
  return Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null && v !== "")
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v!)}`)
    .join("&");
}

async function fetchSuggestions(
  query: string,
  sessionToken: string,
): Promise<Suggestion[]> {
  const qs = buildQs({ input: query, session_token: sessionToken });
  const res = await fetch(`${API}/api/public/places/autocomplete?${qs}`);
  if (!res.ok) return [];
  const data = await res.json().catch(() => []);
  if (!Array.isArray(data)) return [];
  return data.slice(0, MAX_ROWS);
}

async function fetchDetails(
  placeId: string,
  sessionToken: string,
): Promise<PlaceDetails | null> {
  const qs = buildQs({ place_id: placeId, session_token: sessionToken });
  const res = await fetch(`${API}/api/public/places/details?${qs}`);
  if (!res.ok) return null;
  return await res.json().catch(() => null);
}

function makeSessionToken(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

// ── Types ───────────────────────────────────────────────────────────
type Suggestion = {
  place_id: string;
  description: string;
  main_text: string;
  secondary_text?: string;
};

type PlaceDetails = {
  street?: string;
  city?: string;
  state?: string;
  zip?: string;
  country?: string;
  latitude?: number;
  longitude?: number;
};

export type AddressSelection = {
  street: string;
  city: string;
  state: string;
  zip: string;
  latitude: number | null;
  longitude: number | null;
  formatted: string;
  place_id?: string;
};

type Props = {
  value?: string;
  onChange?: (sel: AddressSelection) => void;
  placeholder?: string;
  disabled?: boolean;
  error?: string;
  testID?: string;
};

// ── Component ───────────────────────────────────────────────────────
export default function AddressAutocomplete({
  value = "",
  onChange,
  placeholder = "Start typing your address…",
  disabled = false,
  error = "",
  testID = "address-autocomplete",
}: Props) {
  const [query, setQuery] = useState(value || "");
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [remoteErr, setRemoteErr] = useState("");
  const sessionTokenRef = useRef(makeSessionToken());
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const justSelectedRef = useRef(false);

  // Sync with parent value resets.
  useEffect(() => { setQuery(value || ""); }, [value]);

  // Debounced suggestions fetch.
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    // Skip fetch right after a suggestion was selected — the query
    // changed to the full address string, not a manual keystroke.
    if (justSelectedRef.current) {
      justSelectedRef.current = false;
      return;
    }
    const trimmed = (query || "").trim();
    if (trimmed.length < MIN_QUERY) {
      setSuggestions([]);
      setOpen(false);
      return;
    }
    debounceRef.current = setTimeout(async () => {
      setLoading(true);
      setRemoteErr("");
      try {
        const rows = await fetchSuggestions(trimmed, sessionTokenRef.current);
        setSuggestions(rows.slice(0, MAX_ROWS));
        setOpen(rows.length > 0);
      } catch {
        setRemoteErr("Suggestions unavailable — type manually.");
        setSuggestions([]);
        setOpen(false);
      } finally {
        setLoading(false);
      }
    }, DEBOUNCE_MS);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query]);

  const emitManual = useCallback(
    (raw: string) => {
      onChange?.({
        street: raw,
        city: "",
        state: "",
        zip: "",
        latitude: null,
        longitude: null,
        formatted: raw,
      });
    },
    [onChange],
  );

  const handleChangeText = (text: string) => {
    setQuery(text);
    emitManual(text);
  };

  const handleSelect = useCallback(
    async (row: Suggestion) => {
      if (!row?.place_id) return;
      setLoading(true);
      setRemoteErr("");
      try {
        const details = await fetchDetails(
          row.place_id,
          sessionTokenRef.current,
        );
        // Recycle session token per Google billing guidance.
        sessionTokenRef.current = makeSessionToken();

        if (!details) {
          justSelectedRef.current = true;
          setQuery(row.description || "");
          setSuggestions([]);
          setOpen(false);
          emitManual(row.description || "");
          return;
        }

        const formatted = [
          details.street,
          details.city,
          details.state,
          details.zip,
        ]
          .filter(Boolean)
          .join(", ");

        justSelectedRef.current = true;
        setQuery(formatted || row.description || "");
        setSuggestions([]);
        setOpen(false);
        onChange?.({
          street: details.street || "",
          city: details.city || "",
          state: details.state || "",
          zip: details.zip || "",
          latitude: details.latitude ?? null,
          longitude: details.longitude ?? null,
          formatted,
          place_id: row.place_id,
        });
      } catch {
        setRemoteErr("Address lookup failed — type manually.");
      } finally {
        setLoading(false);
      }
    },
    [onChange, emitManual],
  );

  const errText = error || remoteErr;

  return (
    <View style={s.root} testID={`${testID}-wrapper`}>
      {/* Input */}
      <View style={s.inputRow}>
        <AppTextInput
          style={[s.input, errText ? s.inputError : null]}
          value={query}
          onChangeText={handleChangeText}
          placeholder={placeholder}
          placeholderTextColor={colors.muted}
          editable={!disabled}
          autoCapitalize="words"
          autoCorrect={false}
          returnKeyType="search"
          onFocus={() => {
            if (suggestions.length > 0) setOpen(true);
          }}
          testID={testID}
          {...(Platform.OS === "web"
            ? { outlineStyle: "none" as any }
            : {})}
        />
        {loading ? (
          <ActivityIndicator
            size="small"
            color={colors.brand}
            style={s.spinner}
            testID={`${testID}-loading`}
          />
        ) : null}
      </View>

      {/* Error */}
      {errText ? (
        <Text style={s.errText} testID={`${testID}-error`}>
          {errText}
        </Text>
      ) : null}

      {/* Suggestions dropdown */}
      {open && suggestions.length > 0 ? (
        <View style={s.dropdown} testID={`${testID}-listbox`}>
          {suggestions.map((row, i) => (
            <Pressable
              key={row.place_id}
              style={s.row}
              onPress={() => handleSelect(row)}
              testID={`${testID}-option-${i}`}
            >
              <Ionicons
                name="location-outline"
                size={16}
                color={colors.brand}
                style={s.rowIcon}
              />
              <View style={s.rowTextWrap}>
                <Text style={s.rowMain} numberOfLines={1}>
                  {row.main_text}
                </Text>
                {row.secondary_text ? (
                  <Text style={s.rowSecondary} numberOfLines={1}>
                    {row.secondary_text}
                  </Text>
                ) : null}
              </View>
            </Pressable>
          ))}
        </View>
      ) : null}
    </View>
  );
}

// ── Styles ──────────────────────────────────────────────────────────
const s = StyleSheet.create({
  root: { position: "relative", zIndex: 50 },
  inputRow: { position: "relative" },
  input: {
    backgroundColor: colors.surface,
    borderWidth: 1.5,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    height: 50,
    fontFamily: font.regular,
    fontSize: fontSize.base,
    color: colors.onSurface,
    ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}),
  },
  inputError: { borderColor: "#FCA5A5" },
  spinner: { position: "absolute", right: 12, top: 16 },
  errText: {
    fontFamily: font.regular,
    fontSize: fontSize.xs,
    color: "#B91C1C",
    marginTop: 4,
  },
  dropdown: {
    position: "absolute",
    top: 54,
    left: 0,
    right: 0,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    overflow: "hidden",
    // Elevation for Android, shadow for iOS
    elevation: 8,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.15,
    shadowRadius: 12,
    zIndex: 999,
  },
  row: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: spacing.md,
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    minHeight: 48,
  },
  rowIcon: { marginRight: spacing.sm },
  rowTextWrap: { flex: 1 },
  rowMain: {
    fontFamily: font.medium,
    fontSize: fontSize.sm,
    color: colors.onSurface,
  },
  rowSecondary: {
    fontFamily: font.regular,
    fontSize: 11,
    color: colors.muted,
    marginTop: 1,
  },
});
