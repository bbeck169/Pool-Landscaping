import React, { useEffect, useRef, useState } from "react";
import { colors } from "@/theme";

/**
 * Address autocomplete input backed by Google Places (loaded lazily on first focus).
 * Falls back to a plain text input when GOOGLE_API_KEY is missing.
 * Emits an { address, street, city, state, zip, lat, lng, place_id, formatted } object on selection.
 */
const KEY = process.env.REACT_APP_GOOGLE_API_KEY || "";
let googleLoader = null;

function loadGoogleMaps() {
  if (!KEY) return Promise.reject(new Error("no-key"));
  if (window.google?.maps?.places) return Promise.resolve(window.google);
  if (googleLoader) return googleLoader;
  googleLoader = new Promise((resolve, reject) => {
    const existing = document.querySelector("script[data-google-maps]");
    if (existing) {
      existing.addEventListener("load", () => resolve(window.google));
      existing.addEventListener("error", reject);
      return;
    }
    const s = document.createElement("script");
    s.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(KEY)}&libraries=places&loading=async&v=weekly`;
    s.async = true; s.defer = true; s.setAttribute("data-google-maps", "1");
    s.onload = () => resolve(window.google);
    s.onerror = reject;
    document.head.appendChild(s);
  });
  return googleLoader;
}

export default function AddressAutocomplete({
  value = "",
  onChange,
  onSelect,
  placeholder = "Start typing an address…",
  label,
  testid = "address-autocomplete",
  disabled,
}) {
  const [text, setText] = useState(value || "");
  const [ready, setReady] = useState(!!window.google?.maps?.places);
  const [error, setError] = useState("");
  const inputRef = useRef(null);
  const autoRef = useRef(null);

  useEffect(() => { setText(value || ""); }, [value]);

  const attach = () => {
    if (!ready || !inputRef.current || autoRef.current || !window.google?.maps?.places) return;
    autoRef.current = new window.google.maps.places.Autocomplete(inputRef.current, {
      componentRestrictions: { country: "us" },
      fields: ["address_components", "formatted_address", "geometry", "place_id"],
      types: ["address"],
    });
    autoRef.current.addListener("place_changed", () => {
      const place = autoRef.current.getPlace();
      if (!place || !place.geometry) return;
      const comps = place.address_components || [];
      const grab = (type, useShort = false) => {
        const c = comps.find((x) => x.types?.includes(type));
        return c ? (useShort ? c.short_name : c.long_name) : "";
      };
      const street = [grab("street_number"), grab("route")].filter(Boolean).join(" ");
      const parsed = {
        formatted: place.formatted_address || "",
        street,
        city: grab("locality") || grab("sublocality") || "",
        state: grab("administrative_area_level_1", true),
        zip: grab("postal_code"),
        lat: place.geometry.location?.lat?.(),
        lng: place.geometry.location?.lng?.(),
        place_id: place.place_id,
      };
      setText(parsed.formatted);
      onChange?.(parsed.formatted);
      onSelect?.(parsed);
    });
  };

  useEffect(() => { attach(); /* eslint-disable-next-line */ }, [ready]);

  const onFocus = async () => {
    if (ready) return;
    try { await loadGoogleMaps(); setReady(true); }
    catch (e) { setError(KEY ? "Google Places load failed" : ""); }
  };

  return (
    <div className="w-full" data-testid={testid}>
      {label && <label className="text-xs font-semibold block mb-1" style={{ color: colors.onSurfaceSecondary }}>{label}</label>}
      <input
        ref={inputRef}
        type="text"
        value={text}
        placeholder={placeholder}
        onChange={(e) => { setText(e.target.value); onChange?.(e.target.value); }}
        onFocus={onFocus}
        disabled={disabled}
        className="w-full px-3 py-2 rounded-lg text-sm"
        style={{ border: `1px solid ${colors.border}` }}
        data-testid={`${testid}-input`}
        autoComplete="off"
      />
      {error && <div className="text-xs mt-1" style={{ color: colors.warning }}>{error}</div>}
      {!KEY && (
        <div className="text-xs mt-1" style={{ color: colors.onSurfaceSecondary }}>
          Autocomplete disabled — configure REACT_APP_GOOGLE_API_KEY to enable.
        </div>
      )}
    </div>
  );
}
