/**
 * Phase 51b · Feb 2026 — Walkie-Talkie web UI.
 *
 * Async voice-clip messaging with role-scoped channels. Backend
 * routes live under ``/api/walkie/*`` (see ``backend/routers/walkie.py``).
 *
 * UX contract:
 * - Left rail: channels (all-hands, dept, directs) with unread badges.
 * - Right pane: message timeline, hold-to-record button.
 * - Auto-play new incoming messages in the currently-open channel.
 * - Persistent mute toggle (``localStorage['walkie_muted']``).
 * - Admin-only broadcast gate for the ``all_hands`` channel (mirrors
 *   the server enforcement in ``routers/walkie.py``).
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Mic, Radio, Users, User, Volume2, VolumeX, Play, Pause, Plus, CheckCircle2, Pin, PinOff, Reply, X } from "lucide-react";
import { api, api_base, TOKEN_KEY } from "@/api";
import { useAuth } from "@/auth";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import { toast } from "sonner";
import LivePanel, { liveModeKey } from "./LivePanel";
import {
  canPinInChannel,
  canRecordInChannel,
  canReplyInChannel,
  isMuted,
  isOwnMessage,
  pickAudioMime,
  replyPreviewLabel,
  setMuted,
  shouldAutoPlay,
  sortChannels,
} from "./walkie-helpers";

const POLL_MS = 15_000;
const MAX_RECORD_MS = 30_000;

function fmtTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function channelLabel(c) {
  if (!c) return "";
  if (c.kind === "all_hands") return "All-Hands";
  if (c.kind === "department") return `${(c.department || "").replace(/^\w/, (m) => m.toUpperCase())} Team`;
  return "Direct message";
}

function ChannelIcon({ kind }) {
  if (kind === "all_hands") return <Radio className="h-4 w-4" data-testid="walkie-icon-all_hands" />;
  if (kind === "department") return <Users className="h-4 w-4" data-testid="walkie-icon-department" />;
  return <User className="h-4 w-4" data-testid="walkie-icon-direct" />;
}

function Waveform({ peaks, playing, "data-testid": tid = "walkie-waveform" }) {
  const list = Array.isArray(peaks) && peaks.length > 0 ? peaks : null;
  if (!list) {
    return (
      <div
        data-testid={`${tid}-fallback`}
        className={`h-6 flex-1 rounded-full ${playing ? "bg-emerald-500/60" : "bg-slate-200"}`}
      />
    );
  }
  return (
    <div data-testid={tid} className="h-6 flex-1 flex items-center gap-[2px]">
      {list.slice(0, 60).map((p, i) => (
        <span
          key={i}
          className={`inline-block w-[3px] rounded-full ${playing ? "bg-emerald-500" : "bg-slate-400"}`}
          style={{ height: `${Math.max(4, Math.min(24, Number(p) * 24 || 6))}px` }}
        />
      ))}
    </div>
  );
}

function MessageRow({ msg, user, onListened, mutedRef, canPin, canReply, onPin, onUnpin, onReply, onScrollToParent }) {
  const own = isOwnMessage(user, msg);
  const audioRef = useRef(null);
  const [playing, setPlaying] = useState(false);
  const [listened, setListened] = useState(!!msg.listened_at);

  useEffect(() => { setListened(!!msg.listened_at); }, [msg.listened_at]);

  // Auto-play newly-arrived messages that pass the gate. The parent
  // controls WHICH message is "fresh" by passing ``msg.autoplay = true``.
  useEffect(() => {
    if (!msg.autoplay) return;
    if (!shouldAutoPlay({ user, message: msg, muted: !!mutedRef.current })) return;
    audioRef.current?.play().catch(() => { /* browser autoplay blocked */ });
  }, [msg.autoplay, msg, user, mutedRef]);

  const play = () => audioRef.current?.play();
  const pause = () => audioRef.current?.pause();

  const onEnded = async () => {
    setPlaying(false);
    if (own || listened) return;
    try {
      await api.post(`/walkie/messages/${msg.id}/listened`);
      setListened(true);
      onListened?.(msg.id);
    } catch { /* silent — retry on next poll */ }
  };

  const secs = Math.max(1, Math.round((msg.duration_ms || 0) / 1000));
  const audioUrl = `${api_base()}${msg.audio_url}`.replace("/api/api/", "/api/");

  return (
    <div
      data-testid="walkie-message-row"
      data-msg-id={msg.id}
      data-own={own ? "1" : "0"}
      data-pinned={msg.is_pinned ? "1" : "0"}
      className={`flex items-center gap-3 px-3 py-2 rounded-lg ${msg.is_pinned ? "border-l-4 border-amber-500 bg-amber-50/60" : own ? "bg-slate-100 flex-row-reverse text-right" : "bg-white"}`}
    >
      <button
        type="button"
        onClick={playing ? pause : play}
        data-testid="walkie-play-btn"
        className="h-9 w-9 rounded-full bg-slate-900 text-white grid place-items-center hover:bg-slate-800"
      >
        {playing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
      </button>
      <div className="flex-1 min-w-0">
        {msg.reply_preview && (
          <button
            type="button"
            data-testid="walkie-reply-preview"
            data-deleted={msg.reply_preview.deleted ? "1" : "0"}
            onClick={() => !msg.reply_preview.deleted && msg.reply_preview.id && onScrollToParent?.(msg.reply_preview.id)}
            className="mb-1 text-left w-full text-xs border-l-2 border-slate-300 bg-slate-50 rounded px-2 py-1 text-slate-600 hover:bg-slate-100"
          >
            <Reply className="inline h-3 w-3 mr-1" />
            <span>{replyPreviewLabel(msg.reply_preview)}</span>
          </button>
        )}
        <div className="flex items-center gap-2 text-xs text-slate-500">
          {msg.is_pinned && (
            <span
              data-testid="walkie-pinned-badge"
              className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wider font-semibold text-amber-700 bg-amber-100 rounded-full px-2 py-0.5"
            >
              <Pin className="h-3 w-3" /> Pinned
            </span>
          )}
          <span className="truncate">{msg.sender_name || (own ? "you" : "teammate")}</span>
          {own && (
            <span data-testid="walkie-own-tag" className="text-[10px] px-1.5 py-0.5 rounded bg-slate-200 text-slate-700">you</span>
          )}
          <span>· {fmtTime(msg.created_at)} · {secs}s</span>
          {listened && !own && <CheckCircle2 className="h-3 w-3 text-emerald-500" data-testid="walkie-listened-check" />}
        </div>
        <Waveform peaks={msg.waveform_peaks} playing={playing} />
      </div>
      {canReply && (
        <button
          type="button"
          onClick={() => onReply?.(msg.id)}
          data-testid={`walkie-reply-btn-${msg.id}`}
          title="Reply"
          className="h-8 w-8 rounded-full grid place-items-center text-slate-400 hover:text-slate-900 hover:bg-slate-100"
        >
          <Reply className="h-4 w-4" />
        </button>
      )}
      {canPin && (
        msg.is_pinned ? (
          <button
            type="button"
            onClick={() => onUnpin?.(msg.id)}
            data-testid={`walkie-unpin-btn-${msg.id}`}
            title="Unpin"
            className="h-8 w-8 rounded-full grid place-items-center text-slate-500 hover:text-slate-900 hover:bg-slate-100"
          >
            <PinOff className="h-4 w-4" />
          </button>
        ) : (
          <button
            type="button"
            onClick={() => onPin?.(msg.id)}
            data-testid={`walkie-pin-btn-${msg.id}`}
            title="Pin to channel"
            className="h-8 w-8 rounded-full grid place-items-center text-slate-400 hover:text-amber-600 hover:bg-amber-50"
          >
            <Pin className="h-4 w-4" />
          </button>
        )
      )}
      <audio
        ref={audioRef}
        src={audioUrl}
        preload="none"
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={onEnded}
      />
    </div>
  );
}

function RecordButton({ disabled, disabledReason, onRecorded }) {
  const [recording, setRecording] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const recRef = useRef(null);
  const chunksRef = useRef([]);
  const startTs = useRef(0);
  const timerRef = useRef(null);
  const cancelledRef = useRef(false);

  const stop = useCallback((cancel = false) => {
    cancelledRef.current = cancel;
    try { recRef.current?.stop(); } catch { /* noop */ }
  }, []);

  const start = async () => {
    if (disabled) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mime = pickAudioMime();
      const rec = new MediaRecorder(stream, { mimeType: mime });
      chunksRef.current = [];
      rec.ondataavailable = (e) => { if (e.data.size) chunksRef.current.push(e.data); };
      rec.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        clearInterval(timerRef.current);
        setRecording(false);
        const duration = Math.max(500, Date.now() - startTs.current);
        setElapsed(0);
        if (cancelledRef.current) return;
        const type = mime.split(";")[0] || "audio/webm";
        const blob = new Blob(chunksRef.current, { type });
        onRecorded?.({ blob, duration_ms: duration, mime: type });
      };
      recRef.current = rec;
      cancelledRef.current = false;
      startTs.current = Date.now();
      rec.start();
      setRecording(true);
      setElapsed(0);
      timerRef.current = setInterval(() => {
        const e = Date.now() - startTs.current;
        setElapsed(e);
        if (e >= MAX_RECORD_MS) stop(false);
      }, 100);
    } catch {
      toast.error("Microphone access denied. Enable it in your browser settings.");
    }
  };

  // Escape to cancel while recording (mobile parity ships in Phase 51c).
  useEffect(() => {
    if (!recording) return;
    const onKey = (e) => { if (e.key === "Escape") stop(true); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [recording, stop]);

  if (disabled) {
    return (
      <button
        type="button"
        data-testid="walkie-record-btn"
        data-disabled="1"
        disabled
        title={disabledReason || "You can't broadcast here"}
        className="h-14 w-14 rounded-full bg-slate-200 text-slate-400 grid place-items-center cursor-not-allowed"
      >
        <Mic className="h-6 w-6" />
      </button>
    );
  }

  return (
    <div className="flex items-center gap-3">
      <button
        type="button"
        data-testid="walkie-record-btn"
        data-recording={recording ? "1" : "0"}
        onMouseDown={start}
        onMouseUp={() => stop(false)}
        onMouseLeave={() => recording && stop(false)}
        onTouchStart={(e) => { e.preventDefault(); start(); }}
        onTouchEnd={(e) => { e.preventDefault(); stop(false); }}
        className={`h-14 w-14 rounded-full grid place-items-center text-white transition-colors ${recording ? "bg-red-600 animate-pulse" : "bg-slate-900 hover:bg-slate-800"}`}
      >
        <Mic className="h-6 w-6" />
      </button>
      {recording && (
        <div className="flex items-center gap-2" data-testid="walkie-record-elapsed">
          <span className="text-red-600 font-mono text-sm">
            {(elapsed / 1000).toFixed(1)}s
          </span>
          <button
            type="button"
            onClick={() => stop(true)}
            data-testid="walkie-record-cancel"
            className="text-xs text-slate-500 hover:text-slate-800 underline"
          >
            cancel (Esc)
          </button>
        </div>
      )}
    </div>
  );
}

function NewDirectDialog({ onOpen }) {
  const [open, setOpen] = useState(false);
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(false);
  const { user } = useAuth();

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    api.get("/users").then((r) => {
      const rows = (r?.users || r || []).filter((u) => u.id && u.id !== user?.id
        && (u.role || "").toLowerCase() !== "customer");
      setUsers(rows);
    }).catch(() => setUsers([])).finally(() => setLoading(false));
  }, [open, user]);

  const pick = async (u) => {
    try {
      const r = await api.post("/walkie/channels/direct", { user_id: u.id });
      onOpen?.(r.channel);
      setOpen(false);
    } catch (e) {
      toast.error(e.message || "Failed to open direct channel");
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          data-testid="walkie-new-direct-btn"
          variant="outline"
          size="sm"
          className="w-full justify-start gap-2"
        >
          <Plus className="h-4 w-4" /> New Direct
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Start a direct walkie chat</DialogTitle>
        </DialogHeader>
        {loading ? (
          <div className="p-4 text-sm text-slate-500">Loading teammates…</div>
        ) : (
          <div className="max-h-72 overflow-y-auto divide-y">
            {users.length === 0 && (
              <div className="p-4 text-sm text-slate-500">No teammates available.</div>
            )}
            {users.map((u) => (
              <button
                key={u.id}
                onClick={() => pick(u)}
                data-testid={`walkie-direct-target-${u.id}`}
                className="w-full text-left p-3 hover:bg-slate-50 flex items-center gap-3"
              >
                <div className="h-8 w-8 rounded-full bg-slate-200 grid place-items-center text-xs text-slate-700">
                  {(u.name || u.email || "?").slice(0, 2).toUpperCase()}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium truncate">{u.name || u.email}</div>
                  <div className="text-xs text-slate-500 truncate">{u.role} · {u.department || "unassigned"}</div>
                </div>
              </button>
            ))}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

export default function Walkie() {
  const { user } = useAuth();
  const [channels, setChannels] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [loadingMsgs, setLoadingMsgs] = useState(false);
  const [muted, setMutedState] = useState(() => isMuted());
  const [replyTarget, setReplyTarget] = useState(null);
  const mutedRef = useRef(muted);
  useEffect(() => { mutedRef.current = muted; }, [muted]);
  const lastSeenIdsRef = useRef(new Set());

  // Phase 52.1b · Feb-2026 — Live-mode toggle state. Persisted per
  // channel in localStorage. Only surfaced on channels whose backend
  // row has ``supports_live !== false`` (default true for legacy
  // rows via Phase 52.1a's WalkieChannel.from_mongo coercion).
  const [liveMode, setLiveMode] = useState(false);
  const currentChannelIdRef = useRef(null);
  useEffect(() => {
    currentChannelIdRef.current = selectedId;
    if (!selectedId) { setLiveMode(false); return; }
    try {
      const raw = localStorage.getItem(liveModeKey(selectedId));
      setLiveMode(raw === "1");
    } catch { setLiveMode(false); }
  }, [selectedId]);
  const toggleLiveMode = useCallback(() => {
    const cid = currentChannelIdRef.current;
    setLiveMode((cur) => {
      const next = !cur;
      try {
        if (cid) localStorage.setItem(liveModeKey(cid), next ? "1" : "0");
      } catch { /* ignore */ }
      return next;
    });
  }, []);

  // Clear the reply target whenever the caller switches channels —
  // a "replying to X" banner leaked across channels would confuse
  // more than it helps.
  useEffect(() => { setReplyTarget(null); }, [selectedId]);

  const selected = useMemo(() => channels.find((c) => c.id === selectedId), [channels, selectedId]);
  const recordGate = useMemo(() => canRecordInChannel(user, selected), [user, selected]);
  const replyGate = useMemo(() => canReplyInChannel(user, selected), [user, selected]);

  const replyTargetPreview = useMemo(() => {
    if (!replyTarget) return null;
    const t = messages.find((m) => m.id === replyTarget);
    if (!t) return null;
    return {
      id: t.id,
      sender_display_name: t.sender_name || (isOwnMessage(user, t) ? "you" : "Teammate"),
      duration_ms: t.duration_ms,
      deleted: false,
    };
  }, [replyTarget, messages, user]);

  const scrollToParent = useCallback((mid) => {
    try {
      const el = document.querySelector(`[data-testid="walkie-message-row"][data-msg-id="${mid}"]`);
      el?.scrollIntoView({ behavior: "smooth", block: "center" });
    } catch { /* jsdom no-op */ }
  }, []);

  const loadChannels = useCallback(async () => {
    try {
      const r = await api.get("/walkie/channels");
      const rows = sortChannels(r.channels || []);
      setChannels(rows);
      if (!selectedId && rows.length > 0) setSelectedId(rows[0].id);
    } catch { /* silent */ }
  }, [selectedId]);

  const loadMessages = useCallback(async (chId, { markFresh = false } = {}) => {
    if (!chId) return;
    setLoadingMsgs(true);
    try {
      const r = await api.get(`/walkie/messages?channel_id=${chId}`);
      const rows = (r.messages || []).slice().reverse();
      if (markFresh) {
        const prev = lastSeenIdsRef.current;
        rows.forEach((m) => { m.autoplay = !prev.has(m.id); });
      } else {
        rows.forEach((m) => { m.autoplay = false; });
      }
      lastSeenIdsRef.current = new Set(rows.map((m) => m.id));
      setMessages(rows);
    } catch { /* silent */ } finally {
      setLoadingMsgs(false);
    }
  }, []);

  useEffect(() => { loadChannels(); }, [loadChannels]);
  useEffect(() => {
    if (!selectedId) return;
    lastSeenIdsRef.current = new Set();
    loadMessages(selectedId, { markFresh: false });
  }, [selectedId, loadMessages]);

  // Polling — refresh channels (unread counts) + messages every POLL_MS.
  useEffect(() => {
    const iv = setInterval(() => {
      loadChannels();
      if (selectedId) loadMessages(selectedId, { markFresh: true });
    }, POLL_MS);
    return () => clearInterval(iv);
  }, [loadChannels, loadMessages, selectedId]);

  const toggleMute = () => {
    const next = !muted;
    setMuted(next);
    setMutedState(next);
  };

  const onRecorded = async ({ blob, duration_ms, mime }) => {
    if (!selectedId || !recordGate.allowed) return;
    const ext = mime.includes("mp4") ? "m4a" : mime.includes("mpeg") ? "mp3" : mime.includes("ogg") ? "ogg" : mime.includes("aac") ? "aac" : "webm";
    const fd = new FormData();
    fd.append("channel_id", selectedId);
    fd.append("duration_ms", String(duration_ms));
    fd.append("audio_file", new File([blob], `clip.${ext}`, { type: mime }));
    if (replyTarget) fd.append("reply_to_message_id", replyTarget);
    try {
      const token = localStorage.getItem(TOKEN_KEY) || "";
      const res = await fetch(`${api_base()}/walkie/messages`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: fd,
      });
      if (!res.ok) {
        const t = await res.text();
        toast.error(`Send failed (${res.status}) — ${t.slice(0, 120)}`);
        return;
      }
      toast.success(replyTarget ? "Reply sent" : "Clip sent");
      setReplyTarget(null);
      loadMessages(selectedId, { markFresh: false });
    } catch (e) {
      toast.error(e.message || "Upload failed");
    }
  };

  return (
    <div className="p-4 sm:p-6 max-w-6xl mx-auto" data-testid="walkie-page">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-2xl font-semibold flex items-center gap-2">
          <Radio className="h-6 w-6" /> Walkie-Talkie
        </h1>
        <button
          type="button"
          onClick={toggleMute}
          data-testid="walkie-mute-toggle"
          aria-pressed={muted}
          className="flex items-center gap-2 text-sm text-slate-600 hover:text-slate-900"
        >
          {muted ? <VolumeX className="h-4 w-4" /> : <Volume2 className="h-4 w-4" />}
          {muted ? "Muted" : "Sound on"}
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-[260px_1fr] gap-4">
        {/* Left rail — channel list */}
        <aside className="border rounded-lg bg-white overflow-hidden" data-testid="walkie-channel-list">
          <div className="p-3 border-b">
            <NewDirectDialog onOpen={(ch) => {
              setChannels((cur) => sortChannels([ch, ...cur.filter((c) => c.id !== ch.id)]));
              setSelectedId(ch.id);
            }} />
          </div>
          <ul>
            {channels.map((c) => {
              const active = c.id === selectedId;
              const unread = Number(c.unread_count) || 0;
              return (
                <li key={c.id}>
                  <button
                    type="button"
                    onClick={() => setSelectedId(c.id)}
                    data-testid={`walkie-channel-${c.kind}${c.department ? "-" + c.department : ""}`}
                    className={`w-full text-left px-3 py-2 flex items-center gap-2 border-b hover:bg-slate-50 ${active ? "bg-slate-100" : ""}`}
                  >
                    <ChannelIcon kind={c.kind} />
                    <span className="flex-1 truncate text-sm">{channelLabel(c)}</span>
                    {unread > 0 && (
                      <Badge
                        variant="destructive"
                        data-testid={`walkie-channel-unread-${c.id}`}
                      >{unread}</Badge>
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
        </aside>

        {/* Right pane — timeline + recorder */}
        <section className="border rounded-lg bg-white flex flex-col min-h-[70vh]">
          {!selected ? (
            <div className="flex-1 grid place-items-center text-sm text-slate-500">
              Select a channel to start.
            </div>
          ) : (
            <>
              <header className="px-4 py-3 border-b flex items-center gap-2">
                <ChannelIcon kind={selected.kind} />
                <span className="font-medium">{channelLabel(selected)}</span>
                {!recordGate.allowed && (
                  <Badge variant="outline" className="ml-auto text-xs" data-testid="walkie-record-locked-badge">
                    read-only
                  </Badge>
                )}
              </header>
              <div className="flex-1 overflow-y-auto p-3 space-y-2" data-testid="walkie-timeline">
                {loadingMsgs && messages.length === 0 ? (
                  <div className="text-sm text-slate-500 text-center py-8">Loading…</div>
                ) : messages.length === 0 ? (
                  <div className="text-sm text-slate-500 text-center py-8">No messages yet. Hold the mic to send the first clip.</div>
                ) : (
                  messages.map((m) => (
                    <MessageRow
                      key={m.id}
                      msg={m}
                      user={user}
                      mutedRef={mutedRef}
                      canPin={canPinInChannel(user, selected)}
                      canReply={replyGate.allowed}
                      onReply={(id) => setReplyTarget(id)}
                      onScrollToParent={scrollToParent}
                      onPin={async (id) => {
                        try {
                          await api.post(`/walkie/channels/${selectedId}/pin`, { message_id: id });
                          // Optimistic: mark this message pinned, unpin any prior.
                          setMessages((cur) => cur.map((x) => ({ ...x, is_pinned: x.id === id })));
                          toast.success("Pinned to channel");
                          loadMessages(selectedId, { markFresh: false });
                        } catch (e) {
                          toast.error(e?.message || "Pin failed");
                        }
                      }}
                      onUnpin={async () => {
                        try {
                          await api.del(`/walkie/channels/${selectedId}/pin`);
                          setMessages((cur) => cur.map((x) => ({ ...x, is_pinned: false })));
                          toast.success("Unpinned");
                          loadMessages(selectedId, { markFresh: false });
                        } catch (e) {
                          toast.error(e?.message || "Unpin failed");
                        }
                      }}
                      onListened={(id) => {
                        setMessages((cur) => cur.map((x) => x.id === id ? { ...x, listened_at: new Date().toISOString() } : x));
                      }}
                    />
                  ))
                )}
              </div>
              <footer className="border-t p-4 flex flex-col gap-2" data-testid="walkie-footer">
                {replyTarget && (
                  <div
                    data-testid="walkie-reply-banner"
                    className="flex items-center gap-2 text-sm bg-slate-100 border-l-2 border-slate-400 rounded px-2 py-1 text-slate-700"
                  >
                    <Reply className="h-3 w-3" />
                    <span className="flex-1 truncate">
                      Replying to{" "}
                      <span data-testid="walkie-reply-banner-label" className="font-medium">
                        {replyPreviewLabel(replyTargetPreview) || "message"}
                      </span>
                    </span>
                    <button
                      type="button"
                      onClick={() => setReplyTarget(null)}
                      data-testid="walkie-reply-banner-cancel"
                      title="Cancel reply"
                      className="h-6 w-6 rounded grid place-items-center text-slate-500 hover:text-slate-900 hover:bg-slate-200"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </div>
                )}
                {selected?.supports_live !== false && recordGate.allowed && (
                  <div className="flex items-center justify-end">
                    <label className="flex items-center gap-2 text-xs text-slate-600 select-none">
                      <input
                        type="checkbox"
                        data-testid="walkie-live-mode-toggle"
                        checked={liveMode}
                        onChange={toggleLiveMode}
                        className="h-3 w-3"
                      />
                      Live channel
                    </label>
                  </div>
                )}
                {liveMode && selected?.supports_live !== false ? (
                  <LivePanel
                    channel={selected}
                    user={user}
                    onExit={() => toggleLiveMode()}
                  />
                ) : (
                  <div className="flex items-center gap-3">
                    <RecordButton
                      disabled={!recordGate.allowed}
                      disabledReason={recordGate.reason}
                      onRecorded={onRecorded}
                    />
                    <div className="text-xs text-slate-500">
                      {recordGate.allowed
                        ? "Hold to record · release to send · Esc to cancel · max 30s"
                        : recordGate.reason || "You can't send in this channel"}
                    </div>
                  </div>
                )}
              </footer>
            </>
          )}
        </section>
      </div>
    </div>
  );
}
