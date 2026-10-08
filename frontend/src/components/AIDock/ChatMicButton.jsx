/**
 * Feb-2026 · MARCO-AI-CHAT Phase B — one-shot dictation button.
 *
 * Marco-only. Click → start SpeechRecognition → on result, APPEND the
 * transcript to the parent-controlled input value and stop. The admin
 * reviews the text before pressing Send; we never auto-send from
 * dictation per Phase A gate P4.
 *
 * Firefox / Safari without SpeechRecognition render nothing
 * (``return null``). Component is self-contained — props are just the
 * controlled input value, change callback, and disabled flag.
 */
import React from "react";
import { Mic, MicOff } from "lucide-react";
import { colors } from "@/theme";

function _getRecognitionCtor() {
  if (typeof window === "undefined") return null;
  return window.SpeechRecognition || window.webkitSpeechRecognition || null;
}

export default function ChatMicButton({ value, onChange, disabled = false }) {
  const [listening, setListening] = React.useState(false);
  const [err, setErr] = React.useState(null);
  const recRef = React.useRef(null);
  const Ctor = _getRecognitionCtor();

  // No API support → render nothing (Firefox / older Safari).
  if (!Ctor) return null;

  const stop = () => {
    const rec = recRef.current;
    if (rec) {
      try { rec.stop(); } catch (_e) { /* noop */ }
    }
    setListening(false);
  };

  const start = () => {
    if (disabled || listening) return;
    setErr(null);
    try {
      const rec = new Ctor();
      rec.continuous = false;
      rec.interimResults = false;
      rec.lang = "en-US";
      rec.maxAlternatives = 1;
      rec.onresult = (ev) => {
        try {
          const transcript = ev?.results?.[0]?.[0]?.transcript || "";
          if (transcript.trim()) {
            const next = (value || "").length > 0
              ? `${value.replace(/\s+$/, "")} ${transcript.trim()}`
              : transcript.trim();
            if (typeof onChange === "function") onChange(next);
          }
        } catch (_e) {
          // swallow — nothing to do.
        }
      };
      rec.onerror = (ev) => {
        setErr(ev?.error || "mic-error");
        setListening(false);
      };
      rec.onend = () => setListening(false);
      recRef.current = rec;
      rec.start();
      setListening(true);
    } catch (e) {
      setErr(String(e?.message || e || "start-failed"));
      setListening(false);
    }
  };

  const toggle = () => (listening ? stop() : start());

  return (
    <button
      type="button"
      onClick={toggle}
      disabled={disabled}
      className="rounded-lg px-2 py-2 flex items-center justify-center transition"
      style={{
        backgroundColor: listening ? colors.danger : colors.surfaceMuted,
        color: listening ? colors.onBrand : colors.onSurface,
        border: `1px solid ${colors.border}`,
        opacity: disabled ? 0.5 : 1,
        cursor: disabled ? "not-allowed" : "pointer",
      }}
      title={listening ? "Stop dictation" : "Dictate (voice to text)"}
      data-testid={listening ? "ai-dock-mic-recording" : "ai-dock-mic-button"}
      data-mic-error={err || undefined}
    >
      {listening ? <MicOff size={14} /> : <Mic size={14} />}
    </button>
  );
}
