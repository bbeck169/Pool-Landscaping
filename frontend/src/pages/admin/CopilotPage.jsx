// Feb-2026 · Item 4 — Admin AI Copilot chat page.
//
// Single-thread chat UI. Read-only tools are executed server-side;
// the LLM cannot mutate data. Tool calls appear as collapsed pills
// under the assistant's reply for transparency + auditability.
import React from "react";
import { toast } from "sonner";
import { Send, Sparkles, Bot, User as UserIcon, Loader2, Wrench } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

export default function CopilotPage() {
  const [messages, setMessages] = React.useState([]);
  const [input, setInput] = React.useState("");
  const [sending, setSending] = React.useState(false);
  const [threadId, setThreadId] = React.useState(null);
  const scrollRef = React.useRef(null);

  React.useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, sending]);

  const send = async () => {
    const txt = input.trim();
    if (!txt || sending) return;
    setInput("");
    setMessages((prev) => [...prev, { role: "user", text: txt }]);
    setSending(true);
    try {
      const res = await api.post("/ai/copilot/message", {
        message: txt, thread_id: threadId || null,
      });
      setThreadId(res.thread_id || threadId);
      setMessages((prev) => [...prev, {
        role: "assistant",
        text: res.reply || "…",
        tool_calls: res.tool_calls || [],
      }]);
    } catch (e) {
      toast.error(`Copilot failed: ${e.message || e}`);
      setMessages((prev) => [...prev, {
        role: "assistant", error: true,
        text: `Sorry — the Copilot's LLM backend is unavailable. ${e.message || ""}`,
      }]);
    } finally { setSending(false); }
  };

  return (
    <div className="p-4 md:p-8 max-w-4xl mx-auto"
         data-testid="copilot-page">
      <div className="mb-4">
        <h1 className="text-2xl md:text-3xl font-bold tracking-tight"
            style={{ color: colors.onSurface }}
            data-testid="copilot-title">
          <Sparkles size={20} className="inline mr-2 -mt-0.5"
                     style={{ color: colors.brand }} />
          AI Copilot
        </h1>
        <p className="text-sm" style={{ color: colors.muted }}>
          Read-only assistant that knows your company + can query customers, jobs, comms, and forecasts.
        </p>
      </div>

      <div
        ref={scrollRef}
        className="rounded-xl p-4 space-y-3 mb-3 overflow-y-auto"
        style={{
          backgroundColor: colors.surface,
          border: `1px solid ${colors.border}`,
          minHeight: "48vh", maxHeight: "60vh",
        }}
        data-testid="copilot-messages"
      >
        {messages.length === 0 ? (
          <div className="text-sm p-6 text-center"
               style={{ color: colors.muted }}
               data-testid="copilot-empty">
            Try: <em>"How many active customers do we have?"</em> or{" "}
            <em>"What does our revenue look like this week?"</em>
          </div>
        ) : (
          messages.map((m, i) => (
            <div key={i}
                 className={`flex gap-2 ${m.role === "user" ? "justify-end" : ""}`}
                 data-testid={`copilot-msg-${i}`}>
              {m.role === "assistant" && (
                <div className="mt-0.5 flex-shrink-0">
                  <Bot size={16} style={{ color: colors.brand }} />
                </div>
              )}
              <div
                className="rounded-2xl px-3 py-2 max-w-[80%] whitespace-pre-wrap break-words text-sm"
                style={{
                  backgroundColor: m.role === "user" ? colors.brand
                                    : (m.error ? "#FEF2F2" : colors.surfaceSecondary),
                  color: m.role === "user" ? "#fff"
                          : (m.error ? "#991B1B" : colors.onSurface),
                  border: m.error ? "1px solid #FECACA" : `1px solid ${colors.border}`,
                }}
              >
                {m.text}
                {m.tool_calls?.length ? (
                  <div className="mt-2 space-y-1"
                       data-testid={`copilot-tools-${i}`}>
                    {m.tool_calls.map((tc, ti) => (
                      <div key={ti}
                           className="text-[11px] rounded-md px-2 py-1"
                           style={{
                             backgroundColor: "#EFF6FF", color: "#1E3A8A",
                             border: "1px solid #BFDBFE",
                           }}>
                        <Wrench size={10} className="inline mr-1" />
                        <strong>{tc.name}</strong>({JSON.stringify(tc.args || {})})
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>
              {m.role === "user" && (
                <div className="mt-0.5 flex-shrink-0">
                  <UserIcon size={16} style={{ color: colors.brand }} />
                </div>
              )}
            </div>
          ))
        )}
        {sending && (
          <div className="flex items-center gap-2 text-xs"
               style={{ color: colors.muted }}
               data-testid="copilot-thinking">
            <Loader2 size={12} className="animate-spin" /> Thinking…
          </div>
        )}
      </div>

      <div className="flex items-center gap-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") send(); }}
          placeholder="Ask about customers, jobs, revenue, comms…"
          className="flex-1 rounded-lg px-3 py-2 text-sm focus:outline-none"
          style={{
            backgroundColor: colors.surface,
            color: colors.onSurface,
            border: `1px solid ${colors.border}`,
          }}
          data-testid="copilot-input"
          disabled={sending}
        />
        <button
          type="button"
          onClick={send}
          disabled={sending || !input.trim()}
          className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-semibold text-white hover:brightness-95 disabled:opacity-50"
          style={{ backgroundColor: colors.brand }}
          data-testid="copilot-send-btn"
        >
          <Send size={13} /> Send
        </button>
      </div>
    </div>
  );
}
