/**
 * Feb-2026 · P0 · Lead form address autofill (Google Places).
 *
 * Reusable street-address input backed by the anonymous public
 * ``/api/public/places/autocomplete`` + ``/api/public/places/details``
 * server-side proxy. Used by:
 *
 *   1. ``pages/public/PublicLeadIntake.jsx`` (the embedded lead
 *      widget served on tenant marketing sites).
 *   2. ``pages/marketing/MarketingFormsPage.jsx`` (admin builder —
 *      renders a live preview of the ``address_google`` field so
 *      tenants can see what the widget will show visitors).
 *
 * The Google API key stays server-side; the browser never sees it.
 *
 * Contract
 * --------
 *
 * Props:
 *   - ``value``: current display string.
 *   - ``onChange({street, city, state, zip, latitude, longitude, formatted})``:
 *     fired on suggestion selection AND on manual typing (in the
 *     manual case only ``formatted`` + ``street`` carry the raw
 *     input so the host form can persist a lead even if the
 *     autocomplete API is down).
 *   - ``placeholder``, ``disabled``, ``error``: standard input plumbing.
 *
 * Accessibility
 * -------------
 *
 * ARIA combobox pattern (``role="combobox"`` on the wrapper,
 * ``role="listbox"`` on the suggestions, ``role="option"`` on rows).
 * Keyboard: ↑ / ↓ / Enter / Esc.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";

const API = process.env.REACT_APP_BACKEND_URL || "";
const DEBOUNCE_MS = 250;
const MIN_QUERY = 3;
const MAX_ROWS = 5;

function _buildQs(params) {
  return Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null && v !== "")
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
    .join("&");
}

async function _fetchSuggestions(query, sessionToken) {
  const qs = _buildQs({ input: query, session_token: sessionToken });
  const res = await fetch(`${API}/api/public/places/autocomplete?${qs}`,
                             { method: "GET" });
  if (!res.ok) return [];
  const data = await res.json().catch(() => []);
  if (!Array.isArray(data)) return [];
  return data.slice(0, MAX_ROWS);
}

async function _fetchDetails(placeId, sessionToken) {
  const qs = _buildQs({ place_id: placeId, session_token: sessionToken });
  const res = await fetch(`${API}/api/public/places/details?${qs}`,
                             { method: "GET" });
  if (!res.ok) return null;
  return await res.json().catch(() => null);
}

// Simple session token — Google recommends recycling one token
// across an autocomplete → details cycle. Regenerated after each
// selection so the next lookup starts a fresh billing session.
function _makeSessionToken() {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

export default function AddressAutocomplete({
  value = "",
  onChange,
  placeholder = "Start typing your address…",
  disabled = false,
  error = "",
  testId = "address-autocomplete",
  // Feb-2026 · P0 · pass-through standard input props so the
  // component drops into forms that rely on ``id`` / ``name`` /
  // ``required`` / ``minLength`` / ``aria-label`` (a11y + browser
  // autofill + native form validation still work as usual).
  id,
  name,
  required = false,
  minLength,
  ariaLabel,
  ariaDescribedBy,
}) {
  const [query, setQuery] = useState(value || "");
  const [suggestions, setSuggestions] = useState([]);
  const [open, setOpen] = useState(false);
  const [activeIdx, setActiveIdx] = useState(-1);
  const [loading, setLoading] = useState(false);
  const [remoteErr, setRemoteErr] = useState("");
  const sessionTokenRef = useRef(_makeSessionToken());
  const debounceRef = useRef(null);
  const wrapperRef = useRef(null);

  // Keep the input in sync when the parent resets the field
  // (e.g. after a successful lead submit).
  useEffect(() => { setQuery(value || ""); }, [value]);

  // Debounced fetch on every keystroke ≥ MIN_QUERY chars.
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    const trimmed = (query || "").trim();
    if (trimmed.length < MIN_QUERY) {
      setSuggestions([]); setOpen(false); setActiveIdx(-1);
      return;
    }
    debounceRef.current = setTimeout(async () => {
      setLoading(true); setRemoteErr("");
      try {
        const rows = await _fetchSuggestions(trimmed, sessionTokenRef.current);
        // Enforce the ≤ 5 cap on the client too so a rogue backend
        // response can never blow up the dropdown.
        setSuggestions(rows.slice(0, MAX_ROWS));
        setOpen(rows.length > 0);
        setActiveIdx(rows.length > 0 ? 0 : -1);
      } catch (_e) {
        setRemoteErr("Suggestions unavailable — you can still type manually.");
        setSuggestions([]); setOpen(false); setActiveIdx(-1);
      } finally {
        setLoading(false);
      }
    }, DEBOUNCE_MS);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [query]);

  // Close on outside click.
  useEffect(() => {
    const onDoc = (e) => {
      if (!wrapperRef.current) return;
      if (!wrapperRef.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  const _emitManual = useCallback((raw) => {
    // On free-form typing (no selection yet) bubble a minimal shape
    // so the host form can still persist a lead if the visitor
    // submits before picking a suggestion.
    if (typeof onChange === "function") {
      onChange({
        street: raw, city: "", state: "", zip: "",
        latitude: null, longitude: null,
        formatted: raw,
      });
    }
  }, [onChange]);

  const _handleChange = (e) => {
    const next = e.target.value;
    setQuery(next);
    _emitManual(next);
  };

  const _select = useCallback(async (row) => {
    if (!row || !row.place_id) return;
    setLoading(true); setRemoteErr("");
    try {
      const details = await _fetchDetails(row.place_id, sessionTokenRef.current);
      // Recycle the session token per Google's billing guidance.
      sessionTokenRef.current = _makeSessionToken();
      if (!details) {
        // Fall back to the suggestion's raw description so the user
        // still has *something* typed.
        setQuery(row.description || "");
        _emitManual(row.description || "");
        setOpen(false);
        return;
      }
      const formatted = [details.street, details.city, details.state, details.zip]
        .filter(Boolean).join(", ");
      setQuery(formatted || row.description || "");
      if (typeof onChange === "function") {
        onChange({
          street: details.street || "",
          city: details.city || "",
          state: details.state || "",
          zip: details.zip || "",
          latitude: details.latitude ?? null,
          longitude: details.longitude ?? null,
          formatted,
          place_id: row.place_id,
        });
      }
      setOpen(false);
      setActiveIdx(-1);
    } catch (_e) {
      setRemoteErr("Address lookup failed — you can still type manually.");
    } finally {
      setLoading(false);
    }
  }, [onChange, _emitManual]);

  const _onKeyDown = (e) => {
    if (!open || suggestions.length === 0) {
      if (e.key === "ArrowDown" && suggestions.length > 0) {
        e.preventDefault();
        setOpen(true); setActiveIdx(0);
      }
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIdx((i) => (i + 1) % suggestions.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIdx((i) => (i <= 0 ? suggestions.length - 1 : i - 1));
    } else if (e.key === "Enter") {
      if (activeIdx >= 0 && activeIdx < suggestions.length) {
        e.preventDefault();
        _select(suggestions[activeIdx]);
      }
    } else if (e.key === "Escape") {
      setOpen(false); setActiveIdx(-1);
    }
  };

  const listboxId = useMemo(() => `${testId}-listbox`, [testId]);
  const activeId = activeIdx >= 0 ? `${testId}-opt-${activeIdx}` : undefined;

  return (
    <div
      ref={wrapperRef}
      className="relative"
      role="combobox"
      aria-expanded={open}
      aria-owns={listboxId}
      aria-haspopup="listbox"
      data-testid={`${testId}-wrapper`}
    >
      <input
        type="text"
        value={query}
        disabled={disabled}
        id={id}
        name={name}
        required={required}
        minLength={minLength}
        onChange={_handleChange}
        onKeyDown={_onKeyDown}
        onFocus={() => { if (suggestions.length > 0) setOpen(true); }}
        placeholder={placeholder}
        autoComplete="street-address"
        aria-autocomplete="list"
        aria-controls={listboxId}
        aria-activedescendant={activeId}
        aria-invalid={error ? "true" : "false"}
        aria-label={ariaLabel}
        aria-required={required ? "true" : undefined}
        aria-describedby={ariaDescribedBy}
        className="w-full border border-slate-300 rounded px-3 py-2 text-sm"
        data-testid={testId}
      />
      {(error || remoteErr) ? (
        <div
          role="alert"
          className="mt-1 text-xs"
          style={{ color: "#B91C1C" }}
          data-testid={`${testId}-error`}
        >
          {error || remoteErr}
        </div>
      ) : null}
      {open && suggestions.length > 0 ? (
        <ul
          id={listboxId}
          role="listbox"
          data-testid={`${testId}-listbox`}
          className="absolute z-30 mt-1 w-full bg-white border border-slate-200 rounded shadow-lg max-h-60 overflow-auto"
        >
          {suggestions.map((s, i) => (
            <li
              id={`${testId}-opt-${i}`}
              key={s.place_id}
              role="option"
              aria-selected={i === activeIdx}
              data-testid={`${testId}-option-${i}`}
              className="px-3 py-2 text-sm cursor-pointer"
              style={{ background: i === activeIdx ? "#F0F9FF" : "#fff" }}
              onMouseDown={(e) => { e.preventDefault(); _select(s); }}
              onMouseEnter={() => setActiveIdx(i)}
            >
              <div className="font-medium text-slate-900">{s.main_text}</div>
              {s.secondary_text ? (
                <div className="text-[11px] text-slate-500">{s.secondary_text}</div>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      {loading ? (
        <div className="absolute right-2 top-2 text-[10px] text-slate-400"
              data-testid={`${testId}-loading`}>…</div>
      ) : null}
    </div>
  );
}
