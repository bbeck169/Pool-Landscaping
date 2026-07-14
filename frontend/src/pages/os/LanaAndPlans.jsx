/**
 * Phase 16B · Item H (Lana chat) + Item I (Plans catalog).
 * Small standalone pages that plug into the Business OS layout.
 */
import React, { useEffect, useState, useRef } from "react";
import { api } from "@/api";
import { colors, brandGradientCss } from "@/theme";
import { Send, Sparkles, CheckCircle2, Zap } from "lucide-react";

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
                style={{ background: brandGradientCss }}
                data-testid="lana-send">
          <Send size={14}/> Send
        </button>
      </div>
    </Section>
  );
}

/* ───── Plans Admin (super admin only) ───────────────────── */
export function PlansAdminPage() {
  const [plans, setPlans] = useState([]);
  const [tenants, setTenants] = useState([]);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState("");
  const load = async () => {
    setPlans(await api.get("/plans"));
    try { setTenants(await api.get("/tenants")); } catch { setTenants([]); }
  };
  useEffect(() => { load(); }, []);
  const assign = async (tid, plan_slug) => {
    setBusy(true);
    try {
      await api.post(`/plans/assign/${tid}`, { plan_slug });
      setToast(`Assigned ${plan_slug} to tenant`);
      setTimeout(() => setToast(""), 2500);
      load();
    } catch (e) { alert(e.message); }
    finally { setBusy(false); }
  };
  return (
    <Section
      title="Plans"
      subtitle="Super Admin — assign a tier to any tenant. Feature flags update instantly."
    >
      {toast && (
        <div className="mb-3 px-3 py-2 rounded-lg text-sm font-semibold"
             style={{ backgroundColor: "#DCFCE7", color: colors.success }}
             data-testid="plans-toast">
          <CheckCircle2 size={14} className="inline"/> {toast}
        </div>
      )}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-6">
        {plans.map((p) => (
          <Card key={p.slug} className="p-5" testId={`plans-tier-${p.slug}`}>
            <div className="text-xs font-bold uppercase tracking-wider mb-1"
                 style={{ color: colors.muted }}>{p.slug}</div>
            <div className="text-xl font-bold mb-1" style={{ color: colors.onSurface }}>{p.name}</div>
            <div className="text-2xl font-bold mb-4" style={{ color: colors.brand }}>
              ${p.price_monthly}<span className="text-xs" style={{ color: colors.muted }}>/mo</span>
            </div>
            <ul className="text-sm space-y-1 mb-3">
              {(p.highlights || []).map((h, i) => (
                <li key={i} style={{ color: colors.onSurfaceSecondary }}>
                  <Zap size={12} className="inline mr-1" style={{ color: colors.brand }}/> {h}
                </li>
              ))}
            </ul>
            <div className="text-xs font-mono p-2 rounded-md"
                 style={{ backgroundColor: colors.surfaceSecondary, color: colors.muted }}>
              users: {p.features?.max_users === -1 ? "∞" : p.features?.max_users} ·
              ai/mo: {p.features?.ai_calls_per_month === -1 ? "∞" : p.features?.ai_calls_per_month}
            </div>
          </Card>
        ))}
      </div>

      <Card className="overflow-x-auto" testId="plans-tenants-table">
        <table className="w-full text-sm">
          <thead>
            <tr style={{ color: colors.muted, borderBottom: `1px solid ${colors.border}` }}>
              <th className="text-left p-3 font-semibold">Tenant</th>
              <th className="text-left p-3 font-semibold">Current Plan</th>
              <th className="text-left p-3 font-semibold">Assign</th>
            </tr>
          </thead>
          <tbody>
            {tenants.map((t) => (
              <tr key={t.id} style={{ borderBottom: `1px solid ${colors.border}` }}
                  data-testid={`plans-tenant-${t.slug}`}>
                <td className="p-3" style={{ color: colors.onSurface }}>
                  <span className="font-semibold">{t.name}</span>
                  <span className="text-xs ml-2" style={{ color: colors.muted }}>({t.slug})</span>
                </td>
                <td className="p-3">
                  <span className="px-2 py-0.5 rounded-full text-xs font-bold"
                        style={{ backgroundColor: colors.brandTertiary,
                                 color: colors.onBrandTertiary }}>
                    {t.plan_tier || "—"}
                  </span>
                </td>
                <td className="p-3">
                  <div className="flex gap-1">
                    {plans.map((p) => (
                      <button key={p.slug} onClick={() => assign(t.id, p.slug)}
                              disabled={busy || t.plan_tier === p.slug}
                              className="text-xs px-2 py-1 rounded-md font-semibold disabled:opacity-50"
                              style={{
                                backgroundColor: t.plan_tier === p.slug
                                  ? colors.brandTertiary : colors.surfaceSecondary,
                                color: t.plan_tier === p.slug
                                  ? colors.onBrandTertiary : colors.onSurface,
                                border: `1px solid ${colors.border}`,
                              }}
                              data-testid={`plans-assign-${t.slug}-${p.slug}`}>
                        → {p.name}
                      </button>
                    ))}
                  </div>
                </td>
              </tr>
            ))}
            {tenants.length === 0 && (
              <tr><td colSpan={3} className="p-6 text-center text-sm" style={{ color: colors.muted }}>
                Only Super Admin can list tenants — sign in as super@aquaterra.com.
              </td></tr>
            )}
          </tbody>
        </table>
      </Card>
    </Section>
  );
}
