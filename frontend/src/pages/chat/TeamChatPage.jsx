import React, { useCallback, useEffect, useRef, useState } from "react";
import { Send, Paperclip, Hash, MessageCircle, Search, Plus } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";

const BACKEND = process.env.REACT_APP_BACKEND_URL;

function useChatWS(onEvent) {
  const wsRef = useRef(null);
  useEffect(() => {
    const tok = localStorage.getItem("access_token");
    if (!tok) return;
    const url = `${BACKEND.replace(/^http/, "ws")}/api/ws/notifications?token=${tok}`;
    const ws = new WebSocket(url);
    ws.onmessage = (e) => {
      try {
        const m = JSON.parse(e.data);
        if (m.type?.startsWith("chat.")) onEvent(m);
      } catch {}
    };
    wsRef.current = ws;
    return () => ws.close();
  }, [onEvent]);
}

export default function TeamChatPage() {
  const [convos, setConvos] = useState([]);
  const [selected, setSelected] = useState(null);
  const [messages, setMessages] = useState([]);
  const [draft, setDraft] = useState("");
  const [q, setQ] = useState("");
  const [searchHits, setSearchHits] = useState(null);
  const scrollRef = useRef(null);

  const loadConvos = useCallback(async () => {
    const r = await api.get("/chat/conversations").catch(() => ({ conversations: [] }));
    setConvos(r.conversations || []);
  }, []);
  useEffect(() => { loadConvos(); }, [loadConvos]);

  const loadMessages = useCallback(async (cid) => {
    const r = await api.get(`/chat/conversations/${cid}/messages?limit=100`)
      .catch(() => ({ messages: [] }));
    setMessages((r.messages || []).slice().reverse());
    setTimeout(() => scrollRef.current?.scrollTo(0, 999999), 50);
  }, []);

  const onEvent = useCallback((m) => {
    const p = m.payload || {};
    if (m.type === "chat.message.new" && p.conversation_id === selected?.id) {
      setMessages((cur) => [...cur, p]);
      setTimeout(() => scrollRef.current?.scrollTo(0, 999999), 30);
    }
    if (m.type === "chat.message.updated" || m.type === "chat.message.deleted"
          || m.type === "chat.reaction.updated") {
      if (selected?.id) loadMessages(selected.id);
    }
    if (m.type?.startsWith("chat.")) loadConvos();
  }, [selected?.id, loadMessages, loadConvos]);
  useChatWS(onEvent);

  const openConvo = async (c) => {
    setSelected(c);
    await loadMessages(c.id);
    if (messages[messages.length - 1]) {
      await api.post(`/chat/conversations/${c.id}/read`,
                       { message_id: messages[messages.length - 1].id })
                    .catch(() => null);
    }
    loadConvos();
  };

  const send = async () => {
    if (!draft.trim() || !selected) return;
    try {
      await api.post(`/chat/conversations/${selected.id}/messages`,
                       { body_markdown: draft });
      setDraft("");
      loadMessages(selected.id);
    } catch (e) {
      toast.error(e?.message || "Send failed");
    }
  };

  const react = async (mid, emoji) => {
    await api.post(`/chat/messages/${mid}/reactions`, { emoji }).catch(() => null);
    loadMessages(selected.id);
  };

  const upload = async (file) => {
    if (!file || !selected) return;
    const fd = new FormData(); fd.append("file", file);
    const tok = localStorage.getItem("access_token");
    const r = await fetch(`${BACKEND}/api/chat/attachments/upload`,
                            { method: "POST",
                              headers: { Authorization: `Bearer ${tok}` },
                              body: fd });
    if (!r.ok) { toast.error("Upload failed"); return; }
    const att = await r.json();
    await api.post(`/chat/conversations/${selected.id}/messages`,
                     { body_markdown: `📎 ${att.name}`,
                       attachment_ids: [att.id] });
    loadMessages(selected.id);
  };

  const doSearch = async () => {
    if (!q.trim()) { setSearchHits(null); return; }
    const r = await api.get(`/chat/search?q=${encodeURIComponent(q)}`)
      .catch(() => ({ hits: [] }));
    setSearchHits(r.hits || []);
  };

  const newChannel = async () => {
    const name = window.prompt("Channel name?");
    if (!name) return;
    try {
      const c = await api.post("/chat/conversations",
                                  { type: "channel", name });
      openConvo(c);
      loadConvos();
    } catch (e) { toast.error(e?.message || "Failed"); }
  };

  return (
    <div className="flex h-[calc(100vh-64px)]" data-testid="team-chat">
      {/* Sidebar */}
      <div className="w-80 border-r overflow-y-auto flex flex-col"
            style={{ borderColor: colors.border,
                      backgroundColor: colors.surface }}>
        <div className="p-3 border-b flex items-center gap-2"
              style={{ borderColor: colors.border }}>
          <Input placeholder="Search…" value={q}
                  onChange={(e) => setQ(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && doSearch()}
                  data-testid="chat-search" />
          <button onClick={doSearch} className="p-2 rounded border"
                   style={{ borderColor: colors.border }}>
            <Search className="w-4 h-4" />
          </button>
        </div>
        <div className="p-2 flex items-center justify-between">
          <span className="text-xs font-semibold uppercase tracking-wider"
                 style={{ color: colors.muted }}>
            Conversations
          </span>
          <button onClick={newChannel} className="p-1 rounded"
                   data-testid="chat-new-channel">
            <Plus className="w-4 h-4" />
          </button>
        </div>
        {searchHits ? (
          <div className="p-2 space-y-1">
            <div className="text-xs" style={{ color: colors.muted }}>
              {searchHits.length} hits
            </div>
            {searchHits.map((h) => (
              <div key={h.id} className="text-xs p-2 rounded"
                    style={{ backgroundColor: colors.surfaceSecondary }}>
                {h.body_markdown}
              </div>
            ))}
            <button className="text-xs underline"
                     onClick={() => { setSearchHits(null); setQ(""); }}>
              clear
            </button>
          </div>
        ) : (
          <div className="flex-1 overflow-y-auto">
            {convos.map((c) => (
              <button key={c.id}
                      onClick={() => openConvo(c)}
                      className="w-full text-left px-3 py-2 flex items-center gap-2 border-b"
                      style={{
                        borderColor: colors.border,
                        backgroundColor: selected?.id === c.id
                          ? colors.surfaceSecondary : "transparent",
                      }}
                      data-testid={`chat-convo-${c.id}`}>
                {c.type === "channel"
                  ? <Hash className="w-3 h-3" />
                  : <MessageCircle className="w-3 h-3" />}
                <span className="flex-1 text-sm truncate">
                  {c.name || (c.type === "dm" ? "Direct message" : c.slug)}
                </span>
                {c.unread_count > 0 && (
                  <Badge>{c.unread_count}</Badge>
                )}
              </button>
            ))}
            {convos.length === 0 && (
              <div className="p-4 text-sm text-center"
                    style={{ color: colors.muted }}>
                No conversations yet.
              </div>
            )}
          </div>
        )}
      </div>

      {/* Thread */}
      <div className="flex-1 flex flex-col">
        {selected ? (
          <>
            <div className="p-3 border-b font-semibold"
                  style={{ borderColor: colors.border,
                            backgroundColor: colors.surface }}
                  data-testid="chat-thread-header">
              {selected.name || "Direct message"}
            </div>
            <div ref={scrollRef}
                  className="flex-1 overflow-y-auto p-4 space-y-2"
                  data-testid="chat-messages">
              {messages.map((m) => (
                <div key={m.id} className="rounded-lg p-2"
                      style={{ backgroundColor: colors.surfaceSecondary,
                                border: `1px solid ${colors.border}` }}>
                  <div className="flex items-center gap-2 text-xs mb-0.5"
                        style={{ color: colors.muted }}>
                    <b>{m.author_name || m.author_user_id?.slice(0, 6)}</b>
                    <span>{(m.created_at || "").slice(11, 16)}</span>
                    {m.edited_at && <em>(edited)</em>}
                  </div>
                  <div className={m.deleted_at
                        ? "italic text-sm opacity-60" : "text-sm whitespace-pre-wrap"}>
                    {m.deleted_at ? "(deleted)" : m.body_markdown}
                  </div>
                  {(m.attachments || []).map((a) => (
                    <a key={a.id} href={a.storage_url} target="_blank" rel="noreferrer"
                        className="text-xs underline block mt-1">
                      📎 {a.name}
                    </a>
                  ))}
                  {Object.keys(m.reactions || {}).length > 0 && (
                    <div className="flex gap-1 mt-1">
                      {Object.entries(m.reactions).map(([e, r]) => (
                        <button key={e}
                                onClick={() => react(m.id, e)}
                                className="text-xs px-2 py-0.5 rounded-full border"
                                style={{ borderColor: colors.border }}>
                          {e} {r.count}
                        </button>
                      ))}
                    </div>
                  )}
                  <div className="text-xs mt-1">
                    <button onClick={() => react(m.id, "👍")}
                            className="opacity-60 hover:opacity-100 mr-2">
                      👍
                    </button>
                    <button onClick={() => react(m.id, "❤️")}
                            className="opacity-60 hover:opacity-100">
                      ❤️
                    </button>
                  </div>
                </div>
              ))}
            </div>
            <div className="p-3 border-t flex items-center gap-2"
                  style={{ borderColor: colors.border,
                            backgroundColor: colors.surface }}>
              <label className="p-2 rounded border cursor-pointer"
                      style={{ borderColor: colors.border }}>
                <Paperclip className="w-4 h-4" />
                <input type="file" hidden
                        onChange={(e) => upload(e.target.files?.[0])}
                        data-testid="chat-upload" />
              </label>
              <Input value={draft}
                      onChange={(e) => setDraft(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && send()}
                      placeholder="Type a message… @mention, **bold**, `code`"
                      data-testid="chat-composer" />
              <Button onClick={send} data-testid="chat-send">
                <Send className="w-4 h-4" />
              </Button>
            </div>
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center"
                style={{ color: colors.muted }}>
            Select a conversation to start
          </div>
        )}
      </div>
    </div>
  );
}
