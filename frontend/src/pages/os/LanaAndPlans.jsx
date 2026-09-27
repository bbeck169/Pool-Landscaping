/**
 * Phase 16B · Lana AI chat (Plans admin removed in 16C add-on).
 *
 * Feb-2026 · MARCO Sub-phase C — mic dictation card mounted ABOVE the
 * existing Lana chat surface.  The mic routes to MARCO (the executive
 * assistant AI employee) via the AI Employees conversation API — the
 * Lana chat and its ``/business-os/lana/chat`` endpoint stay
 * untouched (Option Z · Hybrid).
 */
import React, { useEffect, useState, useRef, useCallback } from "react";
import { api, api_base, TOKEN_KEY } from "@/api";
import { colors, gradients } from "@/theme";
import { Mic, MicOff, Send, Sparkles, X } from "lucide-react";

const Card = ({ children, className = "", testId }) => (
  <div className={`rounded-2xl ${className}`}
       style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
       data-testid={testId}>{children}</div>
);

const Section = ({ title, subtitle, right, children }) => (
  <div className="p-4 md:p-8 max-w-5xl mx-auto">
    <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
      <div>
        <h1 className="text-3xl font-bold" style={{ color: colors.onSurface }}>{title}</h1>
        {subtitle && <p className="text-sm mt-1" style={{ color: colors.muted }}>{subtitle}</p>}
      </div>
      {right}
    </div>
    {children}
  </div>
);

/* ═══════════════════════════════════════════════════════════════════
 * MARCO Voice Card · Feb-2026 · Sub-phase C
 * ────────────────────────────────────────
 * Compact card at the TOP of LanaAndPlans.  Click-to-record via
 * MediaRecorder → POST /api/audio/transcribe (existing endpoint,
 * reused instead of a parallel /api/ai/transcribe) → auto-POST the
 * transcript to MARCO's conversation.  Reply renders inline in a
 * dedicated panel — NEVER mingled with the Lana chat below.
 *
 * State machine (recording):
 *   idle → (click mic) → requesting-mic → recording
 *     ├─ click mic again / Escape → cancel (discard audio)
 *     ├─ click mic again after 250ms guard → stop → transcribing
 *     └─ 60 s auto-stop → transcribing (warning toast)
 *   transcribing → sending → replied (idle again)
 *
 * MARCO conversation persistence:
 *   localStorage["marco_conversation:{user_id}"] — reused across
 *   sessions so subsequent dictations continue the same thread.  If
 *   the cached id 404s (deleted / cross-tenant migration) we lazily
 *   create a fresh one and cache the new id.
 * ═══════════════════════════════════════════════════════════════════ */
const MARCO_LS_KEY_PREFIX = "marco_conversation:";
const MARCO_MAX_RECORD_MS = 60_000;

function _marcoLsKey(userId) {
  return `${MARCO_LS_KEY_PREFIX}${userId || "anon"}`;
}

/**
 * Fetch MARCO's admin AI Employee record for the current tenant.
 * Returns {id, name, ...} or null when MARCO isn't seeded (older
 * tenants that predate the Sub-phase A seed migration).
 */
async function _resolveMarcoEmployee() {
  try {
    const rows = await api.get("/ai-employees");
    if (!Array.isArray(rows)) return null;
    const marco = rows.find(r => r && r.key === "marco_executive");
    return marco || null;
  } catch {
    return null;
  }
}

/**
 * Resolve OR create the persistent MARCO conversation for this
 * admin.  On cache miss / 404 the conversation is created fresh.
 */
async function _resolveMarcoConversation(marcoId, userId) {
  const key = _marcoLsKey(userId);
  const cached = typeof localStorage !== "undefined"
    ? localStorage.getItem(key)
    : null;
  if (cached) {
    // Optimistic — trust the cache; if the POST later returns 404
    // we blow it away and retry.  Saves a round-trip on every
    // dictation.
    return cached;
  }
  const conv = await api.post(
    `/ai-employees/${marcoId}/conversations`,
    { title: "MARCO voice dictation",
      participant_employee_ids: [marcoId] },
  );
  if (typeof localStorage !== "undefined") {
    localStorage.setItem(key, conv.id);
  }
  return conv.id;
}

async function _sendToMarco(marcoId, convId, text, userId) {
  try {
    const r = await api.post(
      `/ai-employees/${marcoId}/conversations/${convId}/messages`,
      { text },
    );
    return r;
  } catch (e) {
    // Cached conversation stale (404 / tenant reseat) — drop the
    // cache, mint a new conversation, retry ONCE.
    if (String(e && e.message).match(/^4(0[04]|22)/)) {
      if (typeof localStorage !== "undefined") {
        localStorage.removeItem(_marcoLsKey(userId));
      }
      const freshId = await _resolveMarcoConversation(marcoId, userId);
      return await api.post(
        `/ai-employees/${marcoId}/conversations/${freshId}/messages`,
        { text },
      );
    }
    throw e;
  }
}

/**
 * POST the recorded audio blob to the existing Whisper adapter.
 * Uses raw fetch (not the JSON-shaped ``api.post``) because the
 * FastAPI endpoint demands ``multipart/form-data`` and expects the
 * browser to compute the boundary.  Mirrors the pattern already in
 * ``PdfInvoiceImportPage.jsx::245``.
 */
async function _transcribeBlob(blob) {
  const BASE = process.env.REACT_APP_BACKEND_URL || "";
  const TOKEN = typeof localStorage !== "undefined"
    ? (localStorage.getItem(TOKEN_KEY) || "") : "";
  const fd = new FormData();
  // Whisper accepts webm/opus (MediaRecorder default in Chromium).
  const filename = "marco-voice.webm";
  fd.append("file", new File([blob], filename,
                                { type: blob.type || "audio/webm" }));
  const res = await fetch(`${api_base()}/audio/transcribe`, {
    method: "POST",
    headers: TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {},
    body: fd,
  });
  if (!res.ok) {
    let body = null;
    try { body = await res.json(); } catch { /* empty */ }
    const inner = (body && typeof body === "object"
                     && body.detail !== undefined)
      ? body.detail : body;
    const msg = (inner && typeof inner === "object"
                  ? inner.message : String(inner || ""))
                  || `transcribe HTTP ${res.status}`;
    const err = new Error(msg);
    err.status = res.status;
    throw err;
  }
  return await res.json();
}

export function MarcoVoiceCard({ userId }) {
  const [marco, setMarco] = useState(null);          // resolved employee row
  const [marcoLookedUp, setMarcoLookedUp] = useState(false);
  const [status, setStatus] = useState("idle");
  // idle | recording | transcribing | sending | replied
  const [error, setError] = useState("");
  const [reply, setReply] = useState("");
  const [elapsedMs, setElapsedMs] = useState(0);

  const recorderRef = useRef(null);
  const chunksRef = useRef([]);
  const streamRef = useRef(null);
  const startedAtRef = useRef(0);
  const timerRef = useRef(null);
  const autostopRef = useRef(null);
  // ``cancelled`` prevents an in-flight ``onstop`` handler from
  // firing the transcription after the user hit Escape / clicked
  // the mic to cancel.
  const cancelledRef = useRef(false);

  // Resolve MARCO once on mount.
  useEffect(() => {
    let alive = true;
    (async () => {
      const m = await _resolveMarcoEmployee();
      if (!alive) return;
      setMarco(m);
      setMarcoLookedUp(true);
    })();
    return () => { alive = false; };
  }, []);

  const _stopStream = useCallback(() => {
    if (streamRef.current) {
      try {
        streamRef.current.getTracks().forEach(t => t.stop());
      } catch { /* ignore */ }
      streamRef.current = null;
    }
  }, []);

  const _clearTimers = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    if (autostopRef.current) {
      clearTimeout(autostopRef.current);
      autostopRef.current = null;
    }
  }, []);

  const _cancelRecording = useCallback(() => {
    cancelledRef.current = true;
    _clearTimers();
    if (recorderRef.current
        && recorderRef.current.state !== "inactive") {
      try { recorderRef.current.stop(); } catch { /* ignore */ }
    }
    _stopStream();
    chunksRef.current = [];
    setStatus("idle");
    setElapsedMs(0);
    setError("");
  }, [_clearTimers, _stopStream]);

  // Escape key = cancel while recording.
  useEffect(() => {
    if (status !== "recording") return;
    const onKey = (e) => {
      if (e.key === "Escape") _cancelRecording();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [status, _cancelRecording]);

  const _sendTranscript = useCallback(async (transcript) => {
    if (!marco || !transcript || !transcript.trim()) {
      setStatus("idle");
      return;
    }
    setStatus("sending");
    try {
      const convId = await _resolveMarcoConversation(marco.id, userId);
      const r = await _sendToMarco(marco.id, convId, transcript.trim(), userId);
      const replyText = (r && r.assistant && r.assistant.text)
        ? r.assistant.text
        : (typeof r === "string" ? r
            : "MARCO acknowledged your message.");
      setReply(replyText);
      setStatus("replied");
    } catch (e) {
      setError(`Failed to reach MARCO: ${e.message || e}`);
      setStatus("idle");
    }
  }, [marco, userId]);

  const _startRecording = useCallback(async () => {
    if (!marco || (status !== "idle" && status !== "replied")) return;
    setError("");
    setReply("");
    cancelledRef.current = false;

    // Guard: the platform lacks MediaRecorder (test envs, iOS Safari
    // < 14.4, etc.).
    if (typeof window === "undefined"
        || typeof window.MediaRecorder === "undefined"
        || !navigator.mediaDevices
        || typeof navigator.mediaDevices.getUserMedia !== "function") {
      setError("Voice input isn't supported in this browser.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: true,
      });
      streamRef.current = stream;
      const rec = new window.MediaRecorder(stream);
      recorderRef.current = rec;
      chunksRef.current = [];
      rec.ondataavailable = (ev) => {
        if (ev.data && ev.data.size > 0) {
          chunksRef.current.push(ev.data);
        }
      };
      rec.onstop = async () => {
        _clearTimers();
        _stopStream();
        if (cancelledRef.current) return;
        setStatus("transcribing");
        try {
          const blob = new Blob(chunksRef.current,
                                  { type: rec.mimeType || "audio/webm" });
          if (blob.size === 0) {
            setError("Nothing captured — please try again.");
            setStatus("idle");
            return;
          }
          const result = await _transcribeBlob(blob);
          const transcript = (result && result.transcript) || "";
          if (!transcript.trim()) {
            setError("Couldn't hear anything — please try again.");
            setStatus("idle");
            return;
          }
          await _sendTranscript(transcript);
        } catch (e) {
          setError(`Transcription failed: ${e.message || e}`);
          setStatus("idle");
        }
      };
      rec.start();
      startedAtRef.current = Date.now();
      setElapsedMs(0);
      setStatus("recording");
      timerRef.current = setInterval(() => {
        setElapsedMs(Date.now() - startedAtRef.current);
      }, 250);
      autostopRef.current = setTimeout(() => {
        if (recorderRef.current
            && recorderRef.current.state !== "inactive") {
          setError("Auto-stopped at 60 s — long dictations may drop audio.");
          try { recorderRef.current.stop(); } catch { /* ignore */ }
        }
      }, MARCO_MAX_RECORD_MS);
    } catch (e) {
      setError(`Microphone denied: ${e.message || e}`);
      setStatus("idle");
    }
  }, [marco, status, _clearTimers, _stopStream, _sendTranscript]);

  const _stopRecording = useCallback(() => {
    if (status !== "recording") return;
    if (recorderRef.current
        && recorderRef.current.state !== "inactive") {
      try { recorderRef.current.stop(); } catch { /* ignore */ }
    }
  }, [status]);

  const _onMicClick = useCallback(() => {
    if (status === "idle" || status === "replied") return _startRecording();
    if (status === "recording") return _stopRecording();
    // transcribing / sending — ignore.
  }, [status, _startRecording, _stopRecording]);

  const _secs = Math.floor(elapsedMs / 1000);
  const _secsLabel = `${_secs.toString().padStart(2, "0")}s`;

  // ── UI ─────────────────────────────────────────────────────
  const marcoAvailable = marcoLookedUp && !!marco;
  const marcoMissing = marcoLookedUp && !marco;
  const busy = status === "transcribing" || status === "sending";
  const recording = status === "recording";

  const _btnDisabled = !marcoAvailable || busy;
  const _btnTitle = marcoMissing
    ? "MARCO not available for this tenant — contact super admin"
    : (recording ? "Stop recording (Esc to cancel)"
                  : "Talk to MARCO");

  return (
    <Card className="p-4 mb-6"
          testId="marco-voice-card"
          data-testid="marco-voice-card">
      <div className="flex items-center gap-3 mb-2">
        <div
          className="w-9 h-9 rounded-full flex items-center justify-center"
          style={{ backgroundColor: "#1B1F5C", color: "#fff" }}>
          <Sparkles size={16}/>
        </div>
        <div className="flex-1">
          <div className="text-sm font-bold"
               style={{ color: colors.onSurface }}>
            MARCO · Executive Assistant
          </div>
          <div className="text-xs" style={{ color: colors.muted }}>
            Hold-to-talk. Delegates to the right specialist and comes back
            with a plan.
          </div>
        </div>
        <button
          onClick={_onMicClick}
          disabled={_btnDisabled}
          title={_btnTitle}
          className="w-11 h-11 rounded-full flex items-center justify-center transition disabled:opacity-40"
          style={{
            background: recording
              ? "#DC2626"                      // active recording — red
              : (marcoAvailable ? gradients.navyToGreen.css
                                : colors.surfaceSecondary),
            color: "#fff",
          }}
          data-testid={recording
                          ? "marco-mic-recording"
                          : "marco-mic-button"}>
          {recording ? <MicOff size={18}/> : <Mic size={18}/>}
        </button>
      </div>

      {marcoMissing && (
        <div className="text-xs px-3 py-2 rounded-lg mt-2"
             style={{ backgroundColor: "#FEF3C7", color: "#92400E" }}
             data-testid="marco-mic-error">
          MARCO is not available for this tenant — contact a super admin.
        </div>
      )}

      {recording && (
        <div className="flex items-center gap-2 mt-2">
          <span
            className="inline-block w-2 h-2 rounded-full animate-pulse"
            style={{ backgroundColor: "#DC2626" }}
          />
          <span className="text-xs font-semibold"
                style={{ color: "#DC2626" }}
                data-testid="marco-mic-timer">
            Recording · {_secsLabel} (Esc to cancel)
          </span>
        </div>
      )}

      {busy && (
        <div className="text-xs mt-2" style={{ color: colors.muted }}>
          <Sparkles size={11} className="inline mr-1"/>
          {status === "transcribing"
            ? "Transcribing…"
            : "Sending to MARCO…"}
        </div>
      )}

      {error && !marcoMissing && (
        <div
          className="text-xs px-3 py-2 rounded-lg mt-2 flex items-start gap-2"
          style={{ backgroundColor: "#FEF2F2", color: "#991B1B" }}
          data-testid="marco-mic-error">
          <span className="flex-1">{error}</span>
          <button onClick={() => setError("")}
                  className="opacity-60 hover:opacity-100">
            <X size={12}/>
          </button>
        </div>
      )}

      {status === "replied" && reply && (
        <div
          className="mt-3 p-3 rounded-xl text-sm whitespace-pre-wrap"
          style={{
            backgroundColor: "#F5F7FF",
            border: `1px solid ${colors.border}`,
            color: colors.onSurface,
          }}
          data-testid="marco-reply-panel">
          <div className="text-xs font-bold mb-1"
               style={{ color: "#1B1F5C" }}>
            MARCO
          </div>
          <div data-testid="marco-reply-message">{reply}</div>
        </div>
      )}
    </Card>
  );
}


/* ───── Lana Chat ─────────────────────────────────────────── */
export function LanaChatPage() {
  const [messages, setMessages] = useState([]);
  const [convId, setConvId] = useState(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [mocked, setMocked] = useState(false);
  const boxRef = useRef(null);
  // Feb-2026 · MARCO Sub-phase C — MARCO voice card sits ABOVE the
  // Lana chat.  Pull the current admin's user id from the same
  // localStorage token pattern the api client uses so the MARCO
  // conversation cache is scoped per-admin.
  const [userId, setUserId] = useState(null);
  useEffect(() => {
    try {
      const raw = typeof localStorage !== "undefined"
        ? localStorage.getItem("user") : null;
      if (raw) {
        const parsed = JSON.parse(raw);
        setUserId(parsed && parsed.id);
      }
    } catch { /* ignore */ }
  }, []);
  useEffect(() => {
    boxRef.current?.scrollTo({ top: boxRef.current.scrollHeight });
  }, [messages]);

  const send = async () => {
    const text = input.trim();
    if (!text) return;
    setBusy(true);
    setMessages((m) => [...m, { role: "user", text }]);
    setInput("");
    try {
      const r = await api.post("/business-os/lana/chat",
                                { message: text, conversation_id: convId });
      setConvId(r.conversation_id);
      setMocked(!!r.mocked);
      setMessages(r.messages);
    } catch (e) {
      setMessages((m) => [...m, { role: "assistant", text: `Error: ${e.message}` }]);
    } finally { setBusy(false); }
  };

  return (
    <Section
      title="Lana"
      subtitle="Your COO-in-a-box — draft SOPs, retros, huddle agendas from your live tenant data."
      right={mocked && (
        <span className="px-2 py-1 rounded-full text-xs font-bold"
              style={{ backgroundColor: "#FEF3C7", color: "#92400E" }}
              data-testid="lana-mocked-badge">MOCK MODE</span>
      )}
    >
      {/* Feb-2026 · MARCO Sub-phase C — Voice card at the TOP of
          the page.  Renders above the Lana chat card so admins hit
          it first.  Uses a distinct visual bracket (Deep Navy
          background on the mic + separate reply panel) so
          transcripts never commingle with the Lana chat below. */}
      <MarcoVoiceCard userId={userId}/>
      <Card className="p-4 mb-4" testId="lana-chat-card">
        <div ref={boxRef} style={{ maxHeight: 480, overflowY: "auto" }} className="space-y-3">
          {messages.length === 0 && (
            <div className="text-sm py-8 text-center" style={{ color: colors.muted }}
                 data-testid="lana-empty">
              Ask Lana anything — try “draft a huddle agenda for Monday” or
              “what KPIs matter most for our sales rep?”.
            </div>
          )}
          {messages.map((m, i) => (
            <div key={i}
                 className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}
                 data-testid={`lana-msg-${i}`}>
              <div className="max-w-lg px-3 py-2 rounded-2xl text-sm whitespace-pre-wrap"
                   style={{
                     backgroundColor: m.role === "user" ? colors.brand : colors.surfaceSecondary,
                     color: m.role === "user" ? "#fff" : colors.onSurface,
                   }}>
                {m.text}
              </div>
            </div>
          ))}
          {busy && (
            <div className="text-xs" style={{ color: colors.muted }} data-testid="lana-typing">
              <Sparkles size={12} className="inline"/> Lana is thinking…
            </div>
          )}
        </div>
      </Card>
      <div className="flex gap-2">
        <input value={input} onChange={(e) => setInput(e.target.value)}
               onKeyDown={(e) => e.key === "Enter" && send()}
               placeholder="Ask Lana…"
               className="flex-1 px-4 py-3 rounded-xl text-sm"
               style={{ border: `1px solid ${colors.border}` }}
               data-testid="lana-input"/>
        <button onClick={send} disabled={busy || !input.trim()}
                className="px-4 py-3 rounded-xl text-white font-bold flex items-center gap-1 disabled:opacity-50"
                style={{ background: gradients.navyToGreen.css }}
                data-testid="lana-send">
          <Send size={14}/> Send
        </button>
      </div>
    </Section>
  );
}

// PlansAdminPage removed — pricing tier system deleted (Phase 16C add-on).
