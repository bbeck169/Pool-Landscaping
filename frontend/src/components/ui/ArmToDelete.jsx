/**
 * ArmToDelete · Feb-2026 · Shared arm-and-execute primitive.
 *
 * Extracted from ``CustomersList.jsx`` so future catastrophic
 * operations (mass invoice void, mass job delete, mass customer
 * archive, etc.) reuse the same UX without duplicating the state
 * machine.
 *
 * Behaviour:
 *   • ``count < catastrophicThreshold`` (default 500)
 *       → Single-click "Delete N" button. One click calls
 *         ``onConfirm``. No arm step.
 *   • ``count >= catastrophicThreshold``
 *       → Two-click arm-and-execute:
 *           idle     → click "Arm delete" → arming (disabled,
 *                      cooldown ticks every 100ms)
 *           armed    → click "Delete N" → executing (spinner)
 *           executing→ ``onConfirm`` awaited. On success the
 *                      primitive resets to idle (the parent
 *                      typically unmounts it). On rejection the
 *                      primitive returns to ``armed`` (still-
 *                      armed) so the operator can retry without
 *                      re-arming.
 *   • Escape key at any pre-execute state resets to ``idle``.
 *
 * Visual style deliberately mirrors the previous inline
 * CustomersList button so this is a pixel-identical drop-in.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";

const SIZES = {
  sm: "px-3 py-1.5 text-xs",
  md: "px-4 py-2 text-sm",
  lg: "px-5 py-2.5 text-base",
};

export default function ArmToDelete({
  count,
  catastrophicThreshold = 500,
  cooldownMs = 3000,
  onConfirm,
  onError,
  label = "Delete",
  armLabel = "Arm delete",
  disabled = false,
  size = "md",
  testIdPrefix = "arm-to-delete",
}) {
  const catastrophic = count >= catastrophicThreshold;
  // Machine states: "idle" | "arming" | "armed" | "executing".
  // Non-catastrophic short-circuits idle → executing.
  const [state, setState] = useState("idle");
  const [cooldownRemaining, setCooldownRemaining] = useState(0);
  const intervalRef = useRef(null);

  const _clearInterval = () => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  };

  const reset = useCallback(() => {
    _clearInterval();
    setState("idle");
    setCooldownRemaining(0);
  }, []);

  // Escape cancels back to idle at any pre-execute state.
  useEffect(() => {
    if (state === "idle" || state === "executing") return undefined;
    const on = (e) => { if (e.key === "Escape") reset(); };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [state, reset]);

  // Cooldown ticker — 100ms cadence for smooth animation, integer
  // seconds surfaced via Math.ceil for the label.
  useEffect(() => {
    if (state !== "arming") return undefined;
    intervalRef.current = setInterval(() => {
      setCooldownRemaining((n) => {
        const next = Math.max(0, n - 100);
        if (next === 0) {
          _clearInterval();
          setState("armed");
        }
        return next;
      });
    }, 100);
    return _clearInterval;
  }, [state]);

  // Cleanup on unmount.
  useEffect(() => () => _clearInterval(), []);

  const runExecute = async () => {
    setState("executing");
    try {
      await onConfirm?.();
      // Success — reset to idle (parent typically unmounts).
      reset();
    } catch (err) {
      // Failure — return to armed for catastrophic, idle otherwise.
      setState(catastrophic ? "armed" : "idle");
      setCooldownRemaining(0);
      if (onError) onError(err);
    }
  };

  const onClick = () => {
    if (disabled) return;
    if (!catastrophic) {
      // Single-click path.
      if (state === "executing") return;
      runExecute();
      return;
    }
    if (state === "idle") {
      setState("arming");
      setCooldownRemaining(cooldownMs);
      return;
    }
    if (state === "arming") return; // still cooling
    if (state === "armed") {
      runExecute();
    }
  };

  const secs = Math.ceil(cooldownRemaining / 1000);
  const labelText = (() => {
    if (state === "executing") return "Deleting…";
    if (!catastrophic || state === "armed") return `${label} ${count}`;
    if (state === "arming") return `Confirm again in ${secs}s`;
    return armLabel; // idle + catastrophic
  })();

  const btnDisabled = disabled || state === "executing" || state === "arming";

  // Accessibility announcement text. ``aria-live="polite"`` so
  // screen readers hear "Delete armed" / "Delete ready" without
  // interrupting focus.
  const ariaAnnouncement = (() => {
    if (state === "arming") return `Delete armed. Confirm again in ${secs} seconds.`;
    if (state === "armed") return `${label} ${count} ready. Press to execute.`;
    if (state === "executing") return "Delete in progress.";
    return "";
  })();

  return (
    <>
      <button
        type="button"
        onClick={onClick}
        disabled={btnDisabled}
        aria-disabled={btnDisabled}
        className={
          "rounded-xl font-bold text-white disabled:opacity-60 transition "
          + (SIZES[size] || SIZES.md)
        }
        style={{ backgroundColor: "#DC2626" }}
        data-testid={`${testIdPrefix}-btn`}
        data-state={state}
        data-cooldown={secs}
        data-catastrophic={catastrophic ? "1" : "0"}
      >
        {labelText}
      </button>
      <span
        aria-live="polite"
        className="sr-only"
        data-testid={`${testIdPrefix}-announce`}
      >
        {ariaAnnouncement}
      </span>
    </>
  );
}
