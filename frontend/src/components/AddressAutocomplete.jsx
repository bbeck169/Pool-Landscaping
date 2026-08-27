import React, { useEffect, useRef, useState, useCallback } from "react";
import { colors } from "@/theme";
import { api } from "@/api";

/**
 * Address autocomplete input backed by Google Places.
 *
 * Feb 2026 fix — the legacy ``google.maps.places.Autocomplete`` widget
 * (which mounts a ``.pac-container`` dropdown) silently stopped
 * surfacing suggestions in ``v=weekly`` for many accounts in early
 * 2025 (Google's deprecation of the widget in favour of
 * ``PlaceAutocompleteElement``). Rather than depend on the Web
 * Component (which mangles the DOM callers pass in), we now render
 * our own dropdown driven by the stable ``AutocompleteService`` +
 * ``PlacesService`` pair. Same public API (`onChange`, `onSelect`)
 * so no caller changes.
 *
 * Feb 2026 · Task B — the API key is now fetched at RUNTIME from
 * ``GET /api/config/maps`` (public, referrer-restricted) instead
 * of being baked into the webpack bundle via ``REACT_APP_*``. The
 * env-var path is preserved as a fallback so consumers running
 * against a backend without the ``/config/maps`` endpoint still
 * work (dev + legacy build compatibility).
 *
 * Emits an `{ address, street, city, state, zip, country, lat, lng,
 * place_id, formatted }` object on selection via `onSelect`.
 */
const BUILD_TIME_KEY =
  process.env.REACT_APP_GOOGLE_MAPS_API_KEY ||
  process.env.REACT_APP_GOOGLE_API_KEY ||
  "";
let googleLoader = null;
// Cached client key resolved by ``resolveMapsClientKey``. Never
// contains a server-side secret — the endpoint only surfaces the
// public referrer-restricted key.
let _cachedRuntimeKey = null;

export async function resolveMapsClientKey() {
  if (_cachedRuntimeKey !== null) return _cachedRuntimeKey;
  // Runtime fetch first — matches the Feb-2026 Task B contract
  // (frontend never bakes the key into source).
  try {
    const res = await api.get("/config/maps");
    const runtimeKey = (res && res.google_maps_client_key) || "";
    if (runtimeKey) {
      _cachedRuntimeKey = runtimeKey;
      return runtimeKey;
    }
  } catch {
    /* backend endpoint absent / offline — fall through */
  }
  _cachedRuntimeKey = BUILD_TIME_KEY;
  return BUILD_TIME_KEY;
}

async function loadGoogleMaps() {
  const key = await resolveMapsClientKey();
  if (!key) throw new Error("no-key");
  if (window.google?.maps?.places?.AutocompleteService) {
    return window.google;
  }
  if (googleLoader) return googleLoader;
  // Feb 2026 fix — with `loading=async` the bootstrap script's onload
  // fires BEFORE the `places` sub-library finishes attaching, so any
  // `new google.maps.places.AutocompleteService()` right after onload
  // hits `undefined`. Per Google's 2025 async-loader spec, `await
  // google.maps.importLibrary("places")` is the supported way to know
  // the library is ready — we chain it after script onload.
  googleLoader = new Promise((resolve, reject) => {
    const finish = async () => {
      try {
        if (window.google?.maps?.importLibrary) {
          await window.google.maps.importLibrary("places");
        }
        // Belt-and-suspenders — poll for AutocompleteService for up to
        // 5 s in case importLibrary is unavailable (older bootstrap).
        const start = Date.now();
        while (!window.google?.maps?.places?.AutocompleteService) {
          if (Date.now() - start > 5000) break;
          await new Promise((r) => setTimeout(r, 50));
        }
        resolve(window.google);
      } catch (e) {
        reject(e);
      }
    };

    const existing = document.querySelector("script[data-google-maps]");
    if (existing) {
      // Script already in flight from a prior mount — either it has
      // already run (finish immediately) or hook onto its onload.
      if (window.google?.maps) finish();
      else {
        existing.addEventListener("load", finish);
        existing.addEventListener("error", reject);
      }
      return;
    }
    const s = document.createElement("script");
    s.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(key)}&libraries=places&loading=async&v=weekly`;
    s.async = true; s.defer = true; s.setAttribute("data-google-maps", "1");
    s.onload = finish;
    s.onerror = reject;
    document.head.appendChild(s);
  });
  // If the promise rejects, allow later mounts to retry rather than
  // permanently keeping the failed singleton.
  googleLoader.catch(() => { googleLoader = null; });
  return googleLoader;
}

export function extractComponents(place) {
  const comps = place.address_components || [];
  const grab = (type, useShort = false) => {
    const c = comps.find((x) => x.types?.includes(type));
    return c ? (useShort ? c.short_name : c.long_name) : "";
  };
  const street = [grab("street_number"), grab("route")].filter(Boolean).join(" ");
  return {
    formatted: place.formatted_address || "",
    street,
    city: grab("locality") || grab("sublocality") || "",
    state: grab("administrative_area_level_1", true),
    zip: grab("postal_code"),
    country: grab("country", true),
    lat: place.geometry?.location?.lat?.(),
    lng: place.geometry?.location?.lng?.(),
    place_id: place.place_id,
  };
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
  const [ready, setReady] = useState(
    !!window.google?.maps?.places?.AutocompleteService
  );
  const [keyAvailable, setKeyAvailable] = useState(
    // Optimistic — assume the runtime endpoint will resolve a key
    // (referrer-restricted client keys are safe to expose in the
    // browser). The mount effect below flips this off when both
    // the runtime endpoint AND the legacy build-time env come up
    // empty, which is the "graceful degrade to manual entry" gate.
    true,
  );
  const [error, setError] = useState("");
  const [suggestions, setSuggestions] = useState([]);
  const [open, setOpen] = useState(false);
  const [activeIdx, setActiveIdx] = useState(-1);
  const inputRef = useRef(null);
  const wrapRef = useRef(null);
  const svcRef = useRef(null);          // AutocompleteService
  const placesRef = useRef(null);       // PlacesService (for details)
  const sessionRef = useRef(null);      // AutocompleteSessionToken
  const debounceRef = useRef(null);
  const pendingInputRef = useRef("");   // latched text if user typed pre-ready

  useEffect(() => { setText(value || ""); }, [value]);

  // Kick off the loader on mount so services are ready by first focus.
  useEffect(() => {
    if (ready) return;
    let cancelled = false;
    loadGoogleMaps()
      .then(() => { if (!cancelled) setReady(true); })
      .catch((exc) => {
        if (cancelled) return;
        // ``no-key`` is a soft-degrade signal — the CustomerForm
        // wrapper still renders the plain input.
        if (exc?.message === "no-key") setKeyAvailable(false);
        else setError("Google Places load failed");
      });
    return () => { cancelled = true; };
  }, [ready]);

  // Bootstrap Google services once the SDK is ready.
  useEffect(() => {
    if (!ready) return;
    const g = window.google?.maps?.places;
    if (!g?.AutocompleteService) return;
    if (!svcRef.current) svcRef.current = new g.AutocompleteService();
    if (!placesRef.current) {
      placesRef.current = new g.PlacesService(document.createElement("div"));
    }
    if (!sessionRef.current) sessionRef.current = new g.AutocompleteSessionToken();
    // If the user already typed something while we were loading, run it now.
    const latched = pendingInputRef.current;
    if (latched && latched.length >= 3) {
      pendingInputRef.current = "";
      fetchPredictions(latched);
    }
  }, [ready]); // eslint-disable-line react-hooks/exhaustive-deps -- Phase 41.3: deps 'fetchPredictions' intentionally omitted (mount-only or stable-ref)

  // Close dropdown on outside click.
  useEffect(() => {
    const onDoc = (e) => {
      if (!wrapRef.current) return;
      if (!wrapRef.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  const fetchPredictions = useCallback((input) => {
    if (!input || input.length < 3) {
      setSuggestions([]);
      return;
    }
    if (!svcRef.current) {
      // Loader still bootstrapping — latch the text so the ready-
      // effect can flush it as soon as AutocompleteService attaches.
      pendingInputRef.current = input;
      return;
    }
    svcRef.current.getPlacePredictions(
      {
        input,
        componentRestrictions: { country: "us" },
        types: ["address"],
        sessionToken: sessionRef.current,
      },
      (preds, status) => {
        const OK = window.google?.maps?.places?.PlacesServiceStatus?.OK;
        if (status !== OK || !preds) {
          setSuggestions([]);
          setOpen(false);
          return;
        }
        setSuggestions(preds.slice(0, 6));
        setOpen(true);
        setActiveIdx(-1);
      }
    );
  }, []);

  const onFocus = async () => {
    if (!ready) {
      try { await loadGoogleMaps(); setReady(true); }
      catch (exc) {
        if (exc?.message === "no-key") setKeyAvailable(false);
        else setError("Google Places load failed");
        return;
      }
    }
    if (text && text.length >= 3) fetchPredictions(text);
  };

  const handleInput = (next) => {
    setText(next);
    onChange?.(next);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => fetchPredictions(next), 180);
  };

  const commitSelection = (pred) => {
    if (!pred || !placesRef.current) return;
    placesRef.current.getDetails(
      {
        placeId: pred.place_id,
        fields: ["address_components", "formatted_address", "geometry", "place_id"],
        sessionToken: sessionRef.current,
      },
      (place, status) => {
        const OK = window.google?.maps?.places?.PlacesServiceStatus?.OK;
        if (status !== OK || !place) return;
        // Refresh session token — one billing session per selection.
        sessionRef.current = new window.google.maps.places.AutocompleteSessionToken();
        const parsed = extractComponents(place);
        setText(parsed.formatted);
        setSuggestions([]);
        setOpen(false);
        onChange?.(parsed.formatted);
        onSelect?.(parsed);
      }
    );
  };

  const onKeyDown = (e) => {
    if (!open || suggestions.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIdx((i) => Math.min(i + 1, suggestions.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const pick = suggestions[activeIdx >= 0 ? activeIdx : 0];
      commitSelection(pick);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  return (
    <div className="w-full relative" ref={wrapRef} data-testid={testid}>
      {label && <label className="text-xs font-semibold block mb-1" style={{ color: colors.onSurfaceSecondary }}>{label}</label>}
      <input
        ref={inputRef}
        type="text"
        value={text}
        placeholder={placeholder}
        onChange={(e) => handleInput(e.target.value)}
        onFocus={onFocus}
        onKeyDown={onKeyDown}
        disabled={disabled}
        className="w-full px-3 py-2 rounded-lg text-sm"
        style={{ border: `1px solid ${colors.border}` }}
        data-testid={`${testid}-input`}
        autoComplete="off"
      />
      {open && suggestions.length > 0 && (
        <ul
          className="absolute z-50 left-0 right-0 mt-1 rounded-lg overflow-hidden"
          style={{
            background: colors.surface,
            border: `1px solid ${colors.border}`,
            boxShadow: "0 10px 25px -8px rgba(15,23,42,0.18)",
            maxHeight: 260,
            overflowY: "auto",
          }}
          data-testid={`${testid}-suggestions`}
        >
          {suggestions.map((s, i) => {
            const main = s.structured_formatting?.main_text || s.description || "";
            const sec = s.structured_formatting?.secondary_text || "";
            const active = i === activeIdx;
            return (
              <li
                key={s.place_id}
                onMouseEnter={() => setActiveIdx(i)}
                onMouseDown={(e) => { e.preventDefault(); commitSelection(s); }}
                className="px-3 py-2 cursor-pointer text-sm"
                style={{
                  background: active ? colors.surfaceSecondary : "transparent",
                  borderBottom: i < suggestions.length - 1 ? `1px solid ${colors.border}` : "none",
                }}
                data-testid={`${testid}-suggestion-${i}`}
              >
                <div className="font-semibold" style={{ color: colors.onSurface }}>{main}</div>
                {sec ? <div className="text-xs" style={{ color: colors.onSurfaceSecondary }}>{sec}</div> : null}
              </li>
            );
          })}
        </ul>
      )}
      {error && <div className="text-xs mt-1" style={{ color: colors.warning }}>{error}</div>}
      {!keyAvailable && (
        <div
          className="text-xs mt-1"
          style={{ color: colors.onSurfaceSecondary }}
          data-testid={`${testid}-unavailable`}
        >
          Autocomplete unavailable — enter the address manually.
        </div>
      )}
    </div>
  );
}
