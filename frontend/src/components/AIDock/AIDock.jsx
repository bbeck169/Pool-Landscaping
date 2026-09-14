/**
 * AE Dock UI — global slide-out drawer that lets the admin chat with
 * any of the 8 AI employees (Casey, Emmie, Buddy, Vizzy, Dexter,
 * Soshie, Scouty, Commet).
 *
 * Mounted from AppLayout so it's reachable from every route. All
 * endpoints below already ship in AE1-AE4 — this component adds no
 * new backend surface.
 */
import React from "react";
import { Bot, X, Send, Sparkles, Check, Copy, AlertTriangle, BookOpen, ChevronDown, ChevronRight } from "lucide-react";
import { api } from "@/api";
// Feb-2026 · AI Dock avatar parity — share the same <AIAvatar>
// component the /ai-employees page uses so each persona shows the
// same human portrait in both surfaces (was rendering emoji here,
// portraits there → visual disconnect).
import AIAvatar from "@/components/ai/AIAvatar";
import { colors } from "@/theme";
import { Button, Chip } from "@/components/ui-kit";
import { EMPLOYEE_ACTIONS, ACTION_LABELS } from "./actionCatalog";

const LATEST_CONV_KEY = "ai_dock_latest_convs";

function getLatestConvs() {
  try { return JSON.parse(localStorage.getItem(LATEST_CONV_KEY) || "{}"); }
  catch { return {}; }
}
function saveLatestConv(eid, cid) {
  const map = getLatestConvs();
  map[eid] = cid;
  localStorage.setItem(LATEST_CONV_KEY, JSON.stringify(map));
}

// Phase Feb-2026 · KB RAG — inline "Sources referenced" block that
// hangs off an assistant message when the backend returned matched
// knowledge base docs.  Collapsed by default so long chats stay
// scannable; each source expands its snippet inline on click.
function SourcesBlock({ sources, messageId }) {
  const [open, setOpen] = React.useState(false);
  const [expanded, setExpanded] = React.useState({});
  if (!Array.isArray(sources) || sources.length === 0) return null;
  const toggle = (i) => setExpanded((s) => ({ ...s, [i]: !s[i] }));
  return (
    <div
      className="mt-2 pt-2"
      style={{ borderTop: `1px solid ${colors.border}` }}
      data-testid="ai-response-sources"
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="text-xs flex items-center gap-1 font-semibold opacity-80 hover:opacity-100"
        style={{ color: colors.onSurface, background: "transparent", border: 0, cursor: "pointer", padding: 0 }}
        data-testid={`ai-response-sources-toggle-${messageId}`}
      >
        {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        <BookOpen size={12} />
        Sources referenced ({sources.length})
      </button>
      {open ? (
        <ul className="mt-1 space-y-1">
          {sources.map((s, i) => (
            <li
              key={s.doc_id || i}
              className="text-xs rounded p-1.5"
              style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
              data-testid={`ai-source-${i}`}
            >
              <button
                type="button"
                onClick={() => toggle(i)}
                className="w-full text-left flex items-center gap-1 font-semibold"
                style={{ color: colors.onSurface, background: "transparent", border: 0, cursor: "pointer", padding: 0 }}
                data-testid={`ai-source-${i}-toggle`}
              >
                {expanded[i] ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
                <span className="truncate">{s.title || "(untitled)"}</span>
                {s.kind ? (
                  <span
                    className="ml-auto text-[10px] uppercase px-1 py-0.5 rounded"
                    style={{ backgroundColor: colors.surfaceMuted, color: colors.onSurfaceSecondary }}
                  >
                    {s.kind}
                  </span>
                ) : null}
              </button>
              {expanded[i] && s.snippet ? (
                <div
                  className="mt-1 text-[11px] whitespace-pre-wrap"
                  style={{ color: colors.onSurfaceSecondary }}
                  data-testid={`ai-source-${i}-snippet`}
                >
                  {s.snippet}
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export default function AIDock({ user }) {
  const [open, setOpen] = React.useState(false);
  const [employees, setEmployees] = React.useState([]);
  const [activeEid, setActiveEid] = React.useState(null);
  const [balance, setBalance] = React.useState(null);
  const [loading, setLoading] = React.useState(false);

  const isAdmin = (user?.role || "").toLowerCase() === "admin"
    || (user?.role || "").toLowerCase() === "super_admin";

  const loadRoster = React.useCallback(async () => {
    setLoading(true);
    try {
      const [rows, bal] = await Promise.all([
        api.get("/ai-employees"),
        api.get("/ai-credits/balance").catch(() => null),
      ]);
      setEmployees((rows || []).filter((e) => e.active !== false));
      setBalance(bal?.balance ?? null);
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    if (open && isAdmin) loadRoster();
  }, [open, isAdmin, loadRoster]);

  // Feb-2026 — allow other admin surfaces (e.g. CreditsBudgetChip in
  // the top bar) to open the dock via a window event.
  React.useEffect(() => {
    if (!isAdmin) return undefined;
    const onOpen = () => setOpen(true);
    window.addEventListener("ai-dock:open", onOpen);
    return () => window.removeEventListener("ai-dock:open", onOpen);
  }, [isAdmin]);

  const refreshBalance = React.useCallback(async () => {
    try {
      const bal = await api.get("/ai-credits/balance");
      setBalance(bal?.balance ?? null);
    } catch { /* ignore */ }
  }, []);

  if (!isAdmin) return null;

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="fixed bottom-24 md:bottom-6 right-6 z-40 rounded-full shadow-lg p-3 flex items-center gap-2 transition"
        style={{
          backgroundColor: colors.brand,
          color: colors.onBrand,
          border: `2px solid ${colors.surface}`,
        }}
        title="Open AI Dock"
        data-testid="ai-dock-fab"
      >
        <Bot size={20} />
        <span className="hidden sm:inline text-xs font-bold">AI Dock</span>
      </button>

      {open ? (
        <div
          className="fixed inset-0 z-50 flex justify-end"
          style={{ backgroundColor: "rgba(0,0,0,0.45)" }}
          onClick={() => setOpen(false)}
          data-testid="ai-dock-drawer"
        >
          <aside
            className="w-full max-w-md h-full flex flex-col"
            style={{
              backgroundColor: colors.surface,
              borderLeft: `1px solid ${colors.border}`,
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <header
              className="px-4 py-3 flex items-center justify-between"
              style={{ borderBottom: `1px solid ${colors.border}` }}
            >
              <div className="flex items-center gap-2">
                <Bot size={18} style={{ color: colors.brand }} />
                <div className="text-base font-bold" style={{ color: colors.onSurface }}>
                  AI Dock
                </div>
                <CreditPill balance={balance} testid="ai-dock-credits" />
              </div>
              <button
                onClick={() => setOpen(false)}
                style={{ color: colors.muted }}
                data-testid="ai-dock-close"
              >
                <X size={18} />
              </button>
            </header>

            {activeEid ? (
              <ChatPane
                employee={employees.find((e) => e.id === activeEid)}
                onBack={() => setActiveEid(null)}
                onBalanceChange={refreshBalance}
                balance={balance}
              />
            ) : (
              <RosterView
                employees={employees}
                loading={loading}
                onPick={(eid) => setActiveEid(eid)}
              />
            )}
          </aside>
        </div>
      ) : null}
    </>
  );
}

function CreditPill({ balance, testid }) {
  if (balance == null) return null;
  const low = balance < 100;
  const zero = balance <= 0;
  const tone = zero ? "danger" : low ? "warning" : "brandTertiary";
  return (
    <Chip
      label={zero ? `${balance} — top up!` : `${balance} credits`}
      tone={tone}
      testid={testid}
    />
  );
}

function RosterView({ employees, loading, onPick }) {
  if (loading) {
    return (
      <div className="p-4 text-sm" style={{ color: colors.onSurfaceSecondary }}>
        Loading roster…
      </div>
    );
  }
  return (
    <ul className="flex-1 overflow-y-auto p-3 space-y-2" data-testid="ai-dock-roster">
      {employees.map((e) => (
        <li key={e.id}>
          <button
            onClick={() => onPick(e.id)}
            className="w-full flex items-start gap-3 p-3 rounded-xl text-left transition hover:brightness-95"
            style={{
              backgroundColor: colors.surfaceMuted,
              border: `1px solid ${colors.border}`,
            }}
            data-testid={`ai-dock-pick-${e.key}`}
          >
            {/* Feb-2026 · AI Dock avatar parity — same <AIAvatar> the
                /ai-employees page uses; falls back to an initial in
                a pastel circle when the persona has no avatar_url. */}
            <AIAvatar
              size={40}
              src={e.avatar_url || undefined}
              name={e.name}
              alt={e.name || "AI persona"}
              testId={`ai-dock-avatar-${e.key || e.slug || e.id}`}
            />
            <span className="flex-1 min-w-0">
              <span className="block text-sm font-semibold" style={{ color: colors.onSurface }}>
                {e.name}
              </span>
              <span className="block text-xs" style={{ color: colors.onSurfaceSecondary }}>
                {e.role}
              </span>
            </span>
          </button>
        </li>
      ))}
      {employees.length === 0 ? (
        <li className="text-sm" style={{ color: colors.onSurfaceSecondary }}>
          No AI employees available yet.
        </li>
      ) : null}
    </ul>
  );
}

function ChatPane({ employee, onBack, onBalanceChange, balance }) {
  const [conversation, setConversation] = React.useState(null);
  const [messages, setMessages] = React.useState([]);
  const [input, setInput] = React.useState("");
  const [sending, setSending] = React.useState(false);
  const [actionKey, setActionKey] = React.useState("");
  const [actionParams, setActionParams] = React.useState({});
  const [pendingActions, setPendingActions] = React.useState([]);
  const [error, setError] = React.useState(null);
  const scrollRef = React.useRef(null);

  const actionsCatalog = EMPLOYEE_ACTIONS[employee?.key] || [];
  const zeroBalance = (balance ?? 0) <= 0;

  const loadConv = React.useCallback(async () => {
    if (!employee) return;
    setError(null);
    try {
      const existing = getLatestConvs()[employee.id];
      let conv = null;
      if (existing) {
        try {
          const msgs = await api.get(
            `/ai-employees/${employee.id}/conversations/${existing}/messages`
          );
          setMessages(msgs || []);
          conv = { id: existing };
        } catch {
          conv = null;
        }
      }
      if (!conv) {
        conv = await api.post(
          `/ai-employees/${employee.id}/conversations`,
          { title: `${employee.name} chat` }
        );
        setMessages([]);
      }
      setConversation(conv);
      saveLatestConv(employee.id, conv.id);
      // Load pending actions for this employee (all users' — filter by
      // employee_key so the list is scoped).
      const acts = await api.get(
        `/ai-employees/actions?status=pending&employee_key=${employee.key}`
      );
      setPendingActions(acts || []);
    } catch (e) {
      setError(e.message || "Failed to load conversation.");
    }
  }, [employee]);

  React.useEffect(() => { loadConv(); }, [loadConv]);

  React.useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const send = async () => {
    if (!input.trim() || !conversation || sending) return;
    if (zeroBalance) {
      setError("Out of credits — top up before sending.");
      return;
    }
    setSending(true);
    setError(null);
    const body = { text: input.trim() };
    if (actionKey) {
      body.action = actionKey;
      body.action_params = actionParams;
    }
    try {
      const r = await api.post(
        `/ai-employees/${employee.id}/conversations/${conversation.id}/messages`,
        body,
      );
      setMessages((m) => [...m, r.user_message, r.assistant_message]);
      setInput("");
      setActionKey("");
      setActionParams({});
      if (r.action) {
        setPendingActions((p) => [r.action, ...p]);
      }
      onBalanceChange();
    } catch (e) {
      setError(e.message || "Send failed.");
    } finally {
      setSending(false);
    }
  };

  const decide = async (aid, decision) => {
    try {
      const r = await api.post(
        `/ai-employees/actions/${aid}/${decision}`,
        {},
      );
      setPendingActions((p) => p.filter((a) => a.id !== aid));
      const kind = r.result?.kind || decision;
      const draft = r.result?.draft?.text || r.result?.draft || "";
      setMessages((m) => [
        ...m,
        {
          id: `${aid}-decision`,
          role: "assistant",
          text: `[${kind}]` + (draft ? `\n\n${typeof draft === "string" ? draft : JSON.stringify(draft, null, 2)}` : ""),
          created_at: new Date().toISOString(),
        },
      ]);
      onBalanceChange();
    } catch (e) {
      setError(e.message || `${decision} failed.`);
    }
  };

  return (
    <div className="flex-1 flex flex-col min-h-0" data-testid="ai-dock-chat">
      <div
        className="px-3 py-2 flex items-center gap-2"
        style={{ borderBottom: `1px solid ${colors.border}` }}
      >
        <button
          onClick={onBack}
          className="text-xs px-2 py-1 rounded"
          style={{ backgroundColor: colors.surfaceMuted, color: colors.onSurface }}
          data-testid="ai-dock-back"
        >
          ← Back
        </button>
        {/* Feb-2026 · AI Dock avatar parity — same shared <AIAvatar>
            component used by the roster row + the /ai-employees
            page. Slightly smaller here so it fits the chat header. */}
        <AIAvatar
          size={32}
          src={employee?.avatar_url || undefined}
          name={employee?.name}
          alt={employee?.name || "AI persona"}
          testId={`ai-dock-chat-avatar-${employee?.key || employee?.slug || employee?.id || "unknown"}`}
        />
        <div className="flex-1">
          <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>
            {employee?.name}
          </div>
          <div className="text-xs" style={{ color: colors.onSurfaceSecondary }}>
            {employee?.role}
          </div>
        </div>
      </div>

      {pendingActions.length > 0 ? (
        <div className="px-3 py-2" style={{ borderBottom: `1px solid ${colors.border}` }}>
          <div className="text-xs uppercase font-semibold mb-1" style={{ color: colors.muted }}>
            Pending approval ({pendingActions.length})
          </div>
          <ul className="space-y-1">
            {pendingActions.slice(0, 3).map((a) => (
              <li
                key={a.id}
                className="flex items-center gap-2 p-2 rounded-lg"
                style={{ backgroundColor: colors.surfaceMuted }}
                data-testid={`ai-dock-pending-${a.id}`}
              >
                <span className="flex-1 min-w-0 text-xs" style={{ color: colors.onSurface }}>
                  {a.title || a.action}
                </span>
                <button
                  onClick={() => decide(a.id, "approve")}
                  className="text-xs px-2 py-1 rounded flex items-center gap-1"
                  style={{ backgroundColor: colors.brand, color: colors.onBrand }}
                  data-testid={`ai-dock-approve-${a.id}`}
                >
                  <Check size={12} /> Approve
                </button>
                <button
                  onClick={() => decide(a.id, "reject")}
                  className="text-xs px-2 py-1 rounded"
                  style={{ color: colors.danger, border: `1px solid ${colors.border}` }}
                  data-testid={`ai-dock-reject-${a.id}`}
                >
                  Discard
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div ref={scrollRef} className="flex-1 overflow-y-auto p-3 space-y-2" data-testid="ai-dock-messages">
        {messages.length === 0 ? (
          <div className="text-sm" style={{ color: colors.onSurfaceSecondary }}>
            Say hi — {employee?.name} is ready.
          </div>
        ) : (
          messages.map((m) => (
            <div
              key={m.id}
              className={`p-2 rounded-lg text-sm max-w-[85%] ${m.role === "user" ? "ml-auto" : ""}`}
              style={{
                backgroundColor: m.role === "user" ? colors.brand : colors.surfaceMuted,
                color: m.role === "user" ? colors.onBrand : colors.onSurface,
                whiteSpace: "pre-wrap",
              }}
              data-testid={`ai-dock-msg-${m.role}`}
            >
              {m.text}
              {m.role === "assistant" ? (
                <button
                  onClick={() => navigator.clipboard.writeText(m.text || "")}
                  className="mt-1 text-xs flex items-center gap-1 opacity-70 hover:opacity-100"
                  title="Copy"
                >
                  <Copy size={12} /> Copy
                </button>
              ) : null}
              {m.role === "assistant" && Array.isArray(m.sources) && m.sources.length > 0 ? (
                <SourcesBlock sources={m.sources} messageId={m.id} />
              ) : null}
            </div>
          ))
        )}
      </div>

      {error ? (
        <div
          className="mx-3 mb-2 p-2 rounded text-xs flex items-center gap-2"
          style={{ backgroundColor: colors.surfaceMuted, color: colors.danger }}
          data-testid="ai-dock-error"
        >
          <AlertTriangle size={14} /> {error}
        </div>
      ) : null}

      <ActionForm
        actionsCatalog={actionsCatalog}
        actionKey={actionKey}
        setActionKey={setActionKey}
        actionParams={actionParams}
        setActionParams={setActionParams}
      />

      <div
        className="px-3 py-2 flex items-end gap-2"
        style={{ borderTop: `1px solid ${colors.border}` }}
      >
        <textarea
          rows={2}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={`Message ${employee?.name}…`}
          className="flex-1 px-3 py-2 rounded-lg text-sm resize-none"
          style={{
            backgroundColor: colors.surface,
            border: `1px solid ${colors.border}`,
            color: colors.onSurface,
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
          data-testid="ai-dock-input"
        />
        <Button
          onClick={send}
          disabled={sending || !input.trim() || zeroBalance}
          testid="ai-dock-send"
        >
          {sending ? <Sparkles size={14} /> : <Send size={14} />}
        </Button>
      </div>
    </div>
  );
}

function ActionForm({ actionsCatalog, actionKey, setActionKey, actionParams, setActionParams }) {
  if (actionsCatalog.length === 0) return null;
  const current = actionsCatalog.find((a) => a.key === actionKey);
  return (
    <div className="px-3 py-2" style={{ borderTop: `1px solid ${colors.border}` }}>
      <label className="text-xs uppercase font-semibold" style={{ color: colors.muted }}>
        Action (optional)
      </label>
      <select
        value={actionKey}
        onChange={(e) => { setActionKey(e.target.value); setActionParams({}); }}
        className="w-full mt-1 px-2 py-1.5 rounded-lg text-sm"
        style={{
          backgroundColor: colors.surface,
          border: `1px solid ${colors.border}`,
          color: colors.onSurface,
        }}
        data-testid="ai-dock-action-picker"
      >
        <option value="">— free-form chat —</option>
        {actionsCatalog.map((a) => (
          <option key={a.key} value={a.key}>
            {ACTION_LABELS[a.key] || a.key}{a.approveGated ? " • approve-gated" : ""}
          </option>
        ))}
      </select>
      {current && current.params.length > 0 ? (
        <div className="mt-2 space-y-2">
          {current.params.map((p) => (
            <div key={p.name}>
              <label className="text-xs" style={{ color: colors.onSurfaceSecondary }}>
                {p.label || p.name}
                {p.required ? " *" : ""}
              </label>
              <input
                value={actionParams[p.name] || ""}
                onChange={(e) => setActionParams((prev) => ({ ...prev, [p.name]: e.target.value }))}
                placeholder={p.placeholder || ""}
                className="w-full mt-0.5 px-2 py-1 rounded text-sm"
                style={{
                  backgroundColor: colors.surface,
                  border: `1px solid ${colors.border}`,
                  color: colors.onSurface,
                }}
                data-testid={`ai-dock-param-${p.name}`}
              />
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
