/**
 * Feb-2026 · CHECKLIST-DECIMAL-INPUT-FIX (parity sweep) — shared
 * ``<DecimalInput>`` primitive.
 *
 * The HTML5 ``type="number"`` input intercepts intermediate decimal
 * states (``"7."``, ``"."``, ``".5"``) and most browsers return
 * ``e.target.value === ""`` while the user is still typing — the
 * caller's ``onChange`` handler then blanks the stored value,
 * effectively locking users into integer entry.
 *
 * This primitive implements the same workaround ``PoolChecklistForm``
 * already uses for pH / chlorine / salt readings, generalised so
 * every chemistry-reading surface in the app can reuse it:
 *
 *   - ``type="text"`` + ``inputMode="decimal"`` → mobile numeric
 *     keypad stays, but the browser doesn't eat intermediate
 *     dots.
 *   - Internal string state so ``"7."`` round-trips through the
 *     DOM intact.
 *   - Keystroke-level regex guard (``/^\d*\.?\d*$/``) rejects
 *     anything that isn't digits + at most one decimal point.
 *   - ``parseFloat`` conversion fires ONLY on blur / Enter /
 *     explicit ``commit()`` so parent state receives a number
 *     (or ``null`` for empty / lone dot).
 *   - External ``value`` changes DO sync into the raw buffer, but
 *     only when the input is not currently focused — avoids
 *     clobbering what the user is typing from a parent re-render.
 *
 * Props mirror the small set of attributes the existing
 * chemistry inputs rely on; everything else passes through via
 * ``...rest`` so this is a drop-in swap for a plain ``<input>``.
 */
import React from "react";

const _DECIMAL_RE = /^\d*\.?\d*$/;

function _stringify(v) {
  if (v == null) return "";
  // Avoid "0" when caller passes 0 deliberately — show it.
  // ``Number.isFinite`` protects against NaN sneaking in from a
  // stale parent state.
  if (typeof v === "number" && Number.isFinite(v)) return String(v);
  if (typeof v === "string") return v;
  return "";
}

function _parse(raw) {
  if (raw === "" || raw === ".") return null;
  const n = Number.parseFloat(raw);
  return Number.isFinite(n) ? n : null;
}

/**
 * Controlled decimal input.
 *
 * @param {object} props
 * @param {number|string|null|undefined} props.value — committed value.
 * @param {(v: number|null) => void} props.onChange — fired on blur /
 *   Enter / ``onCommit`` prop firing with the parsed number (or
 *   ``null`` for empty / lone dot).
 * @param {string} [props.testid] — becomes ``data-testid``.
 * @param {boolean} [props.disabled] — pass-through.
 * @param {string} [props.placeholder]
 * @param {string} [props.className]
 * @param {object} [props.style]
 * @param {string} [props.ariaLabel] — accessibility label.
 */
export default function DecimalInput({
  value,
  onChange,
  testid,
  disabled = false,
  placeholder,
  className,
  style,
  ariaLabel,
  autoComplete = "off",
  ...rest
}) {
  const [raw, setRaw] = React.useState(() => _stringify(value));
  const focusedRef = React.useRef(false);

  // Sync external value → raw buffer when it changes AND the user
  // isn't typing. Prevents parent re-renders from clobbering an
  // in-progress "7." state while preserving reset-to-null and
  // programmatic value swaps.
  React.useEffect(() => {
    if (focusedRef.current) return;
    const next = _stringify(value);
    setRaw((prev) => (prev === next ? prev : next));
  }, [value]);

  const handleChange = (e) => {
    const v = e.target.value;
    if (v === "" || _DECIMAL_RE.test(v)) {
      setRaw(v);
    }
    // ``v`` that fails the regex (letters, multiple dots) is
    // silently dropped — the input stays on the last valid raw.
  };

  const commit = () => {
    const parsed = _parse(raw);
    // Call parent even when parsed === current to keep the
    // behavior predictable (useful for explicit "Reset" buttons
    // that pass the same value back in).
    if (typeof onChange === "function") onChange(parsed);
    // Normalize visible text: trailing dot stripped, empty stays
    // empty. Leading-dot numbers (``".5"``) render as ``"0.5"``
    // via parseFloat → stringify.
    setRaw(parsed == null ? "" : String(parsed));
  };

  const handleFocus = () => { focusedRef.current = true; };
  const handleBlur = () => { focusedRef.current = false; commit(); };
  const handleKeyDown = (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      commit();
    }
  };

  return (
    <input
      type="text"
      inputMode="decimal"
      autoComplete={autoComplete}
      value={raw}
      disabled={disabled}
      placeholder={placeholder}
      onChange={handleChange}
      onFocus={handleFocus}
      onBlur={handleBlur}
      onKeyDown={handleKeyDown}
      className={className}
      style={style}
      aria-label={ariaLabel}
      data-testid={testid}
      {...rest}
    />
  );
}
