/**
 * Phase 17B.3 · Atlas Agent chat.
 */
import React, { useEffect, useRef, useState } from "react";
import { Bot, Send, Wrench } from "lucide-react";
import { api } from "@/api";
import { colors, brandGradientCss } from "@/theme";

export default function AtlasAgent() {
  const [messages, setMessages] = useState([]);
  const [convId, setConvId] = useState(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState([]);
  const scrollRef = useRef(null);

  useEffect(() => {
    api.get("/seo/atlas/conversations").then(setHistory);
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo(0, 9e9);
  }, [messages.length]);

  const send = async () => {
    if (!text.trim() || busy) return;
    const userMsg = { role: "user", content: text, at: new Date().toISOString() };
    setMessages([...messages, userMsg]);
    const question = text; setText(""); setBusy(true);
    try {
      const r = await api.post("/seo/atlas/chat", {
        message: question, conversation_id: convId,
      });
      setConvId(r.conversation_id);
      setMessages((m) => [...m, r.assistant]);
    } catch (e) {
      setMessages((m) => [...m, { role: "assistant",
                                    content: `Error: ${e.message}`,
                                    tool_calls: [], at: new Date().toISOString() }]);
    }
    finally { setBusy(false); }
  };

  const openConv = async (c) => {
    const full = await api.get(`/seo/atlas/conversations/${c.id}`);
    setConvId(full.id);
    setMessages(full.messages || []);
  };

  return (
    <div className="max-w-6xl mx-auto p-4 md:p-6" data-testid="atlas-page">
      <div className="mb-4">
        <div className="flex items-center gap-2 mb-1">
          <Bot size={22} style={{ color: colors.brand }}/>
          <h1 className="text-3xl font-bold" style={{ color: colors.onSurface }}>
            Atlas · SEO Agent
          </h1>
        </div>
        <p className="text-sm" style={{ color: colors.muted }}>
          Ask in plain English. Atlas runs audits, scores content, generates
          topical maps, and pulls up your data.
        </p>
      </div>

      <div className="grid md:grid-cols-4 gap-4">
        <div className="rounded-2xl p-3 space-y-1"
             style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
             data-testid="atlas-history">
          <div className="text-[10px] font-bold uppercase mb-2"
               style={{ color: colors.muted }}>Recent chats</div>
          <button onClick={() => { setConvId(null); setMessages([]); }}
                  className="w-full text-left p-2 text-xs font-semibold rounded"
                  style={{ backgroundColor: !convId ? colors.brandTertiary : "transparent",
                           color: colors.brand }}
                  data-testid="atlas-new-chat">
            + New chat
          </button>
          {history.map((c) => (
            <button key={c.id} onClick={() => openConv(c)}
                    className="w-full text-left p-2 text-xs rounded truncate"
                    style={{
                      backgroundColor: convId === c.id ? colors.brandTertiary : "transparent",
                      color: colors.onSurface,
                    }}
                    data-testid={`atlas-conv-${c.id}`}>
              {(c.last_message_at || c.created_at || "").slice(0, 10)}
            </button>
          ))}
        </div>

        <div className="md:col-span-3 rounded-2xl flex flex-col"
             style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}`, height: "70vh" }}
             data-testid="atlas-chat">
          <div ref={scrollRef} className="flex-1 overflow-auto p-4 space-y-3">
            {messages.length === 0 && (
              <div className="text-sm text-center py-16" style={{ color: colors.muted }}>
                Try: "Run an audit on https://example.com" or "Generate a topical map for pool cleaning phoenix"
              </div>
            )}
            {messages.map((m, i) => (
              <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
                <div className="max-w-[80%] rounded-2xl p-3"
                     style={{
                       backgroundColor: m.role === "user" ? colors.brand : colors.background,
                       color: m.role === "user" ? "#fff" : colors.onSurface,
                       border: m.role === "assistant" ? `1px solid ${colors.border}` : "none",
                     }}
                     data-testid={`atlas-msg-${i}`}>
                  <div className="text-[10px] font-bold opacity-70 mb-1 uppercase">
                    {m.role}
                  </div>
                  <div className="text-sm whitespace-pre-wrap">{m.content}</div>
                  {(m.tool_calls || []).length > 0 && (
                    <div className="mt-2 space-y-1">
                      {m.tool_calls.map((t, j) => (
                        <div key={j} className="rounded p-2 text-xs"
                             style={{
                               backgroundColor: m.role === "user"
                                 ? "rgba(255,255,255,0.15)" : colors.surface,
                               border: `1px solid ${m.role === "user" ? "rgba(255,255,255,0.3)" : colors.border}`,
                             }}
                             data-testid={`atlas-tool-${i}-${j}`}>
                          <div className="flex items-center gap-1 font-bold">
                            <Wrench size={11}/> {t.name}
                          </div>
                          <div className="text-[10px] opacity-80 mt-1">
                            {JSON.stringify(t.args || {})}
                          </div>
                          <div className="text-[10px] opacity-80 mt-0.5">
                            {t.status} · {JSON.stringify(t.result || {}).slice(0, 200)}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
          <div className="p-3 flex gap-2 border-t" style={{ borderColor: colors.border }}>
            <input value={text} onChange={(e) => setText(e.target.value)}
                   onKeyDown={(e) => e.key === "Enter" && send()}
                   placeholder="Ask Atlas anything…"
                   className="flex-1 p-2.5 text-sm rounded-lg"
                   style={{ backgroundColor: colors.background,
                            border: `1px solid ${colors.border}`,
                            color: colors.onSurface }}
                   data-testid="atlas-input" />
            <button onClick={send} disabled={busy}
                    className="p-2.5 rounded-lg disabled:opacity-60"
                    style={{ backgroundColor: colors.brand, color: "#fff" }}
                    data-testid="atlas-send">
              <Send size={16}/>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
