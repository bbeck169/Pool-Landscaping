/**
 * Phase B2 · Feb 2026 — Portal chat threads (customer + admin, same shell).
 *
 * Attachment parity with TeamChatPage — customers can upload files
 * via the F0 pipeline scoped to their own customer_id, then attach
 * the resulting file ids to the outgoing message. Staff viewing the
 * thread sees the hydrated tiles inline.
 */
import React, { useEffect, useRef, useState } from 'react';
import { MessageSquare, Plus, Send, X, Paperclip } from "lucide-react";
import { api } from "@/api";
import { colors, brandGradientCss } from "@/theme";
import { useAuth } from "@/auth";
import { ChatAttachmentTile } from "@/components/chat/ChatAttachmentTile";

const BACKEND = process.env.REACT_APP_BACKEND_URL || "";

export default function PortalChatsPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin" || user?.role === "super_admin";
  const [threads, setThreads] = useState([]);
  const [selected, setSelected] = useState(null);
  const [messages, setMessages] = useState([]);
  const [text, setText] = useState("");
  const [showNew, setShowNew] = useState(false);
  const [subject, setSubject] = useState("");
  const [firstMsg, setFirstMsg] = useState("");
  // ── B2 attachments state ─────────────────────────────────────
  const [pending, setPending] = useState([]);   // uploaded file ids awaiting send
  const [uploading, setUploading] = useState(false);
  const scrollRef = useRef(null);

  const loadThreads = () => api.get("/portal/chats").then(setThreads);
  useEffect(() => { loadThreads(); }, []);

  useEffect(() => {
    if (!selected) return;
    api.get(`/portal/chats/${selected.id}/messages`).then((d) => {
      setMessages(d.messages || []);
      setTimeout(() => {
        // Guard for jsdom (no `.scrollTo` on plain <div>) — optional chain
        // catches null but not "method missing on truthy element".
        const el = scrollRef.current;
        if (el && typeof el.scrollTo === "function") el.scrollTo(0, 9e9);
      }, 50);
    });
    api.post(`/portal/chats/${selected.id}/read`).catch(() => {});
    setPending([]);  // reset pending on thread switch
  }, [selected?.id]);

  const uploadFiles = async (fileList) => {
    if (!fileList || fileList.length === 0) return;
    setUploading(true);
    const tok = localStorage.getItem("access_token");
    const uploaded = [];
    try {
      for (const file of Array.from(fileList)) {
        const fd = new FormData();
        fd.append("file", file);
        fd.append("purpose", "portal_chat_attachment");
        // Scope the file to the current customer so the ownership
        // check on POST accepts it. Admins uploading through this
        // page shouldn't happen (paperclip is customer-only), but
        // the linked_entity fields are harmless if it does.
        if (user?.customer_id) {
          fd.append("linked_entity_type", "customer");
          fd.append("linked_entity_id", user.customer_id);
        }
        const r = await fetch(`${BACKEND}/api/files/upload`, {
          method: "POST",
          headers: { Authorization: `Bearer ${tok}` },
          body: fd,
        });
        if (!r.ok) {
          // eslint-disable-next-line no-console
          console.error("[portal-chat] upload failed", r.status);
          continue;
        }
        const doc = await r.json();
        uploaded.push({
          id: doc.id,
          filename: doc.original_filename || file.name,
          mime: doc.content_type || file.type,
          size: doc.size || file.size,
        });
      }
      if (uploaded.length) setPending((p) => [...p, ...uploaded]);
    } finally {
      setUploading(false);
    }
  };

  const removePending = (id) =>
    setPending((p) => p.filter((x) => x.id !== id));

  const send = async () => {
    if ((!text.trim() && pending.length === 0) || !selected) return;
    const body = { body: text, attachment_ids: pending.map((p) => p.id) };
    const m = await api.post(`/portal/chats/${selected.id}/messages`, body);
    setMessages([...messages, m]);
    setText("");
    setPending([]);
    setTimeout(() => scrollRef.current?.scrollTo(0, 9e9), 50);
    loadThreads();
  };

  const createThread = async () => {
    if (!subject.trim()) return;
    const c = await api.post("/portal/chats", {
      subject,
      first_message: firstMsg,
      attachment_ids: pending.map((p) => p.id),
    });
    setShowNew(false); setSubject(""); setFirstMsg(""); setPending([]);
    loadThreads(); setSelected(c);
  };

  return (
    <div className="max-w-6xl mx-auto p-4 md:p-6" data-testid="portal-chats-page">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <MessageSquare size={22} style={{ color: colors.brand }} />
          <h1 className="text-2xl font-bold" style={{ color: colors.onSurface }}>
            {isAdmin ? "Customer Inbox" : "Messages"}
          </h1>
        </div>
        {!isAdmin && (
          <button onClick={() => setShowNew(true)}
                  className="flex items-center gap-1 px-3 py-2 text-sm font-bold rounded-xl"
                  style={{ background: brandGradientCss, color: "#fff" }}
                  data-testid="portal-chats-new">
            <Plus size={13}/> New Message
          </button>
        )}
      </div>

      <div className="grid md:grid-cols-3 gap-4 h-[70vh]">
        <div className="rounded-2xl p-2 overflow-auto"
             style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
             data-testid="portal-chats-list">
          {threads.length === 0 ? (
            <div className="p-4 text-xs text-center" style={{ color: colors.muted }}>
              {isAdmin ? "No customer threads yet." : "Start a new conversation."}
            </div>
          ) : threads.map((t) => (
            <button key={t.id} onClick={() => setSelected(t)}
                    className="w-full text-left p-3 rounded-lg mb-1 transition"
                    style={{
                      backgroundColor: selected?.id === t.id ? colors.brand + "22" : "transparent",
                    }}
                    data-testid={`chat-thread-${t.id}`}>
              <div className="text-sm font-semibold truncate" style={{ color: colors.onSurface }}>
                {isAdmin ? t.customer_name : t.subject}
              </div>
              <div className="text-xs truncate" style={{ color: colors.muted }}>
                {isAdmin ? t.subject : (t.last_message_at || "").slice(0, 10)}
              </div>
              {(isAdmin ? t.unread_by_admin : t.unread_by_customer) > 0 && (
                <span className="text-[9px] font-bold rounded-full px-1.5"
                      style={{ backgroundColor: colors.brand, color: "#fff" }}>
                  {isAdmin ? t.unread_by_admin : t.unread_by_customer}
                </span>
              )}
            </button>
          ))}
        </div>

        <div className="md:col-span-2 rounded-2xl flex flex-col"
             style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
             data-testid="portal-chats-pane">
          {selected ? (
            <>
              <div className="p-3 text-sm font-semibold border-b"
                   style={{ color: colors.onSurface, borderColor: colors.border }}>
                {isAdmin ? selected.customer_name : "Support"} · {selected.subject}
              </div>
              <div ref={scrollRef} className="flex-1 p-3 overflow-auto space-y-2"
                   data-testid="portal-chats-messages">
                {messages.map((m) => {
                  const mine = m.sender_role === (isAdmin ? "admin" : "customer");
                  return (
                    <div key={m.id} className={`flex ${mine ? "justify-end" : "justify-start"}`}>
                      <div className="rounded-2xl px-3 py-2 text-sm max-w-[75%]"
                           style={{
                             backgroundColor: mine ? colors.brand : colors.background,
                             color: mine ? "#fff" : colors.onSurface,
                           }}
                           data-testid={`portal-chat-msg-${m.id}`}>
                        <div className="text-[10px] opacity-75 mb-1 font-semibold">
                          {m.sender_name || m.sender_role}
                        </div>
                        {m.body}
                        {(m.attachments || []).map((a) => (
                          <ChatAttachmentTile
                            key={a.id}
                            attachment={a}
                            testid={`portal-chat-att-${a.id}`}
                          />
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Pending attachment strip */}
              {pending.length > 0 && (
                <div className="px-3 pt-2 flex flex-wrap gap-2"
                     data-testid="portal-chats-pending-strip">
                  {pending.map((p) => (
                    <span key={p.id}
                          className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-full border"
                          style={{ borderColor: colors.border, backgroundColor: colors.surfaceSecondary }}
                          data-testid={`portal-chats-pending-${p.id}`}>
                      📎 {p.filename}
                      <button type="button" onClick={() => removePending(p.id)}
                              aria-label="Remove attachment"
                              className="text-xs opacity-60 hover:opacity-100">×</button>
                    </span>
                  ))}
                </div>
              )}

              <div className="p-2 flex gap-2 border-t items-center" style={{ borderColor: colors.border }}>
                {!isAdmin && (
                  <label className="p-2 rounded-lg cursor-pointer border"
                         style={{ borderColor: colors.border, color: colors.brand }}
                         data-testid="portal-chats-upload-label"
                         aria-label="Attach file">
                    <Paperclip size={16}/>
                    <input type="file" hidden multiple
                           accept="image/*,application/pdf"
                           onChange={(e) => uploadFiles(e.target.files)}
                           data-testid="portal-chats-upload" />
                  </label>
                )}
                <input value={text} onChange={(e) => setText(e.target.value)}
                       onKeyDown={(e) => e.key === "Enter" && send()}
                       placeholder="Type a message…"
                       className="flex-1 p-2.5 text-sm rounded-lg"
                       style={{ backgroundColor: colors.background, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                       data-testid="portal-chats-input" />
                <button onClick={send}
                        disabled={uploading || (!text.trim() && pending.length === 0)}
                        className="p-2.5 rounded-lg disabled:opacity-50"
                        style={{ backgroundColor: colors.brand, color: "#fff" }}
                        data-testid="portal-chats-send">
                  <Send size={16}/>
                </button>
              </div>
            </>
          ) : (
            <div className="flex-1 flex items-center justify-center text-sm"
                 style={{ color: colors.muted }}>
              Select a conversation to view.
            </div>
          )}
        </div>
      </div>

      {showNew && (
        <div className="fixed inset-0 z-40 flex items-center justify-center p-4"
             style={{ background: "rgba(0,0,0,0.5)" }}
             onClick={() => setShowNew(false)}>
          <div className="max-w-md w-full p-6 rounded-2xl"
               onClick={(e) => e.stopPropagation()}
               style={{ backgroundColor: colors.surface }}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-bold" style={{ color: colors.onSurface }}>
                New Message
              </h3>
              <button onClick={() => setShowNew(false)} style={{ color: colors.muted }}>
                <X size={18}/>
              </button>
            </div>
            <input value={subject} onChange={(e) => setSubject(e.target.value)}
                   placeholder="Subject"
                   className="w-full p-2.5 text-sm rounded-lg mb-2"
                   style={{ backgroundColor: colors.background, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                   data-testid="chat-new-subject" />
            <textarea value={firstMsg} onChange={(e) => setFirstMsg(e.target.value)}
                      rows={4}
                      placeholder="Your message…"
                      className="w-full p-2.5 text-sm rounded-lg mb-4"
                      style={{ backgroundColor: colors.background, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                      data-testid="chat-new-body" />
            <button onClick={createThread}
                    className="w-full py-2 text-sm font-bold rounded-lg"
                    style={{ background: brandGradientCss, color: "#fff" }}
                    data-testid="chat-new-submit">
              Send
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
