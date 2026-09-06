/**
 * Phase 16B · Lana AI chat (Plans admin removed in 16C add-on).
 */
import React, { useEffect, useState, useRef } from "react";
import { api } from "@/api";
import { colors, gradients } from "@/theme";
import { Send, Sparkles } from "lucide-react";

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

/* ───── Lana Chat ─────────────────────────────────────────── */
export function LanaChatPage() {
  const [messages, setMessages] = useState([]);
  const [convId, setConvId] = useState(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [mocked, setMocked] = useState(false);
  const boxRef = useRef(null);
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
