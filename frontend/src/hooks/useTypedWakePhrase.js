/**
 * Feb-2026 · MARCO-AI-CHAT Phase B — typed wake phrase hook.
 *
 * Catches "heymarco" typed anywhere in the admin UI (even inside a
 * text input) and dispatches ``ai-dock:open-marco``. Enables the
 * wake path on Firefox / Safari where ``SpeechRecognition`` is
 * unavailable.
 *
 * Design:
 *   - Global ``keydown`` listener. Accumulates letter-only
 *     keystrokes into a 15-char rolling buffer.
 *   - Buffer resets after 2 s of keystroke inactivity so a user who
 *     types "hey" then takes a breath doesn't accidentally trigger
 *     later when they type "marco" into a search box an hour later.
 *   - Match pattern: substring ``"heymarco"`` on the collapsed
 *     buffer. 2 s cooldown after a match prevents re-fire from the
 *     admin continuing to type.
 */
import React from "react";

const EVENT_OPEN_MARCO = "ai-dock:open-marco";
const PHRASE = "heymarco";
const BUFFER_SIZE = 15;
const INACTIVITY_RESET_MS = 2000;
const COOLDOWN_MS = 2000;

export default function useTypedWakePhrase({ enabled = true } = {}) {
  React.useEffect(() => {
    if (!enabled || typeof document === "undefined") return undefined;

    let buffer = "";
    let lastKeyAt = 0;
    let cooldownUntil = 0;

    const onKeyDown = (ev) => {
      // Only single-letter visible characters count — ignore
      // modifiers, arrow keys, Enter, Tab, etc.
      const k = ev?.key || "";
      if (!k || k.length !== 1) return;
      if (!/[a-zA-Z]/.test(k)) return;

      const now = Date.now();
      if (now < cooldownUntil) return;
      if (now - lastKeyAt > INACTIVITY_RESET_MS) {
        buffer = "";
      }
      lastKeyAt = now;
      buffer = (buffer + k.toLowerCase()).slice(-BUFFER_SIZE);
      if (buffer.includes(PHRASE)) {
        cooldownUntil = now + COOLDOWN_MS;
        buffer = "";
        try {
          window.dispatchEvent(new CustomEvent(EVENT_OPEN_MARCO, {
            detail: { source: "typed-phrase" },
          }));
        } catch (_e) {
          // swallow — best-effort.
        }
      }
    };

    document.addEventListener("keydown", onKeyDown, true);
    return () => {
      document.removeEventListener("keydown", onKeyDown, true);
    };
  }, [enabled]);
}
