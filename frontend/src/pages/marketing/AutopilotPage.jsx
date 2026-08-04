import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, Bot, Sparkles, Wand2, PlayCircle, Check } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { toast } from "sonner";

const TONES = ["friendly", "professional", "urgent", "casual"];
const USE_CASES = ["generic", "seasonal", "invoice_followup"];
const CHANNELS = ["email", "sms"];
const SEASONS = ["spring", "summer", "fall", "winter"];

// ─── Copy Generator ─────────────────────────────────────────────────────

function CopyGenerator({ _balance, refreshBalance }) {
  const [rules, setRules] = useState([]);
  const [selected, setSelected] = useState(null);
  const [tone, setTone] = useState("friendly");
  const [channel, setChannel] = useState("");
  const [useCase, setUseCase] = useState("generic");
  const [brandVoice, setBrandVoice] = useState("");
  const [extra, setExtra] = useState("");
  const [busy, setBusy] = useState(false);
  const [copy, setCopy] = useState(null);

  const loadRules = useCallback(async () => {
    const rs = await api.get("/comms/automations").catch(() => []);
    setRules(Array.isArray(rs) ? rs : []);
  }, []);
  useEffect(() => { loadRules(); }, [loadRules]);

  const rule = useMemo(
    () => rules.find((r) => r.code === selected) || null,
    [rules, selected],
  );

  const generate = async () => {
    if (!selected) { toast.error("Pick an automation rule"); return; }
    setBusy(true);
    try {
      const r = await api.post(
        `/comms/automations/${selected}/generate-copy`,
        {
          tone, use_case: useCase,
          channel: channel || null,
          brand_voice_snippet: brandVoice || null,
          extra_context: extra,
        },
      );
      setCopy(r.ai_generated_copy);
      toast.success("Copy generated (3 credits)");
      refreshBalance();
      loadRules();
    } catch (e) {
      toast.error(e?.message || "Generation failed");
    } finally {
      setBusy(false);
    }
  };

  const history = rule?.ai_generated_history || [];

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4"
          data-testid="autopilot-copy-generator">
      <div className="rounded-2xl p-4 md:p-5 space-y-3"
            style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}>
        <div className="flex items-center gap-2">
          <Wand2 className="w-4 h-4" />
          <h2 className="font-semibold">Rule + inputs</h2>
        </div>
        <div>
          <Label>Automation rule</Label>
          <select className="w-full border rounded p-2 text-sm mt-1"
                  value={selected || ""}
                  onChange={(e) => setSelected(e.target.value)}
                  data-testid="ap-rule-select">
            <option value="">— pick a rule —</option>
            {rules.map((r) => (
              <option key={r.code} value={r.code}>
                {r.name || r.code} · {r.channel}
              </option>
            ))}
          </select>
          {rule && (
            <div className="text-xs mt-1" style={{ color: colors.muted }}>
              Trigger: <b>{rule.trigger_event}</b> · Channel default:{" "}
              <b>{rule.channel}</b>{rule.is_system && " · system rule (won't persist)"}
            </div>
          )}
        </div>
        <div className="grid grid-cols-3 gap-2">
          <div>
            <Label>Tone</Label>
            <select value={tone} onChange={(e) => setTone(e.target.value)}
                    className="w-full border rounded p-2 text-sm mt-1"
                    data-testid="ap-tone">
              {TONES.map((t) => <option key={t}>{t}</option>)}
            </select>
          </div>
          <div>
            <Label>Channel</Label>
            <select value={channel}
                    onChange={(e) => setChannel(e.target.value)}
                    className="w-full border rounded p-2 text-sm mt-1"
                    data-testid="ap-channel">
              <option value="">(rule default)</option>
              {CHANNELS.map((c) => <option key={c}>{c}</option>)}
            </select>
          </div>
          <div>
            <Label>Use-case</Label>
            <select value={useCase}
                    onChange={(e) => setUseCase(e.target.value)}
                    className="w-full border rounded p-2 text-sm mt-1"
                    data-testid="ap-usecase">
              {USE_CASES.map((u) => <option key={u}>{u}</option>)}
            </select>
          </div>
        </div>
        <div>
          <Label>Brand voice snippet (optional)</Label>
          <Textarea rows={2} value={brandVoice}
                     onChange={(e) => setBrandVoice(e.target.value)}
                     placeholder="e.g. Warm, plain-spoken, no jargon."
                     data-testid="ap-brand-voice" />
        </div>
        <div>
          <Label>Extra context</Label>
          <Textarea rows={2} value={extra}
                     onChange={(e) => setExtra(e.target.value)}
                     placeholder="e.g. Emphasize the free water test on this visit."
                     data-testid="ap-extra" />
        </div>
        <div className="flex items-center justify-between pt-2">
          <div className="text-xs" style={{ color: colors.muted }}>
            3 credits per generation.
          </div>
          <Button onClick={generate} disabled={busy}
                    data-testid="ap-generate">
            <Sparkles className="w-4 h-4 mr-1" />
            {busy ? "Generating…" : "Generate copy"}
          </Button>
        </div>
      </div>

      <div className="rounded-2xl p-4 md:p-5 space-y-3"
            style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}>
        <div className="flex items-center gap-2">
          <Bot className="w-4 h-4" />
          <h2 className="font-semibold">Suggested copy</h2>
        </div>
        {!copy && !rule?.ai_generated_copy && (
          <div className="text-sm text-center py-8"
                style={{ color: colors.muted }}>
            Nothing generated yet.
          </div>
        )}
        {(copy || rule?.ai_generated_copy) && (() => {
          const c = copy || rule.ai_generated_copy;
          return (
            <div className="space-y-2 text-sm" data-testid="ap-copy-preview">
              {c.subject && (
                <div>
                  <div className="text-xs uppercase tracking-wider mb-0.5"
                        style={{ color: colors.muted }}>
                    Subject
                  </div>
                  <div className="font-semibold">{c.subject}</div>
                </div>
              )}
              {c.body_text && (
                <div>
                  <div className="text-xs uppercase tracking-wider mb-0.5"
                        style={{ color: colors.muted }}>
                    Body {c.body_sms ? "(SMS)" : "(email)"}
                  </div>
                  <pre className="whitespace-pre-wrap text-sm rounded-md p-3"
                        style={{ backgroundColor: colors.surfaceSecondary,
                                  border: `1px solid ${colors.border}` }}>
                    {c.body_sms || c.body_text}
                  </pre>
                  {c.body_sms && (
                    <div className="text-xs mt-1" style={{ color: colors.muted }}>
                      {c.body_sms.length} chars
                    </div>
                  )}
                </div>
              )}
              <div className="flex gap-2 text-xs mt-2"
                    style={{ color: colors.muted }}>
                <Badge variant="outline">{c.tone}</Badge>
                <Badge variant="outline">{c.use_case}</Badge>
                <Badge variant="outline">{c.channel}</Badge>
              </div>
            </div>
          );
        })()}

        {history.length > 0 && (
          <div className="border-t pt-3"
                style={{ borderColor: colors.border }}>
            <div className="text-xs font-semibold mb-2"
                  style={{ color: colors.muted }}>
              History ({history.length})
            </div>
            <div className="space-y-2 max-h-64 overflow-auto">
              {history.map((h, i) => (
                <div key={i} className="rounded-md p-2 text-xs"
                      style={{ backgroundColor: colors.surfaceSecondary,
                                border: `1px solid ${colors.border}` }}>
                  <div className="flex gap-2 items-center mb-1">
                    <Badge variant="outline" className="text-[10px]">
                      {h.tone}
                    </Badge>
                    <Badge variant="outline" className="text-[10px]">
                      {h.use_case}
                    </Badge>
                    <span style={{ color: colors.muted }}>
                      {h.generated_at}
                    </span>
                  </div>
                  {h.subject && <div className="font-semibold">{h.subject}</div>}
                  <div className="line-clamp-2 opacity-80">
                    {h.body_sms || h.body_text}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Planners ────────────────────────────────────────────────────────────

function PlannerCard({ title, subtitle, children, testId }) {
  return (
    <div className="rounded-2xl p-4 md:p-5 space-y-3"
          style={{ backgroundColor: colors.surface,
                    border: `1px solid ${colors.border}` }}
          data-testid={testId}>
      <div>
        <h3 className="font-semibold">{title}</h3>
        <p className="text-xs" style={{ color: colors.muted }}>{subtitle}</p>
      </div>
      {children}
    </div>
  );
}

function StepEditor({ steps, setSteps }) {
  const toggle = (i) => {
    const copy = [...steps];
    copy[i] = { ...copy[i], _keep: !(copy[i]._keep ?? true) };
    setSteps(copy);
  };
  return (
    <div className="space-y-2">
      {steps.map((s, i) => (
        <div key={i}
              className="rounded-md p-3"
              style={{ backgroundColor: colors.surfaceSecondary,
                        border: `1px solid ${colors.border}` }}
              data-testid={`planner-step-${i}`}>
          <div className="flex items-center gap-2 mb-1 flex-wrap">
            <input type="checkbox"
                    checked={s._keep ?? true}
                    onChange={() => toggle(i)}
                    data-testid={`planner-step-keep-${i}`} />
            <span className="font-semibold text-sm">{s.name}</span>
            <Badge variant="outline">
              {s.trigger_event}
            </Badge>
            <Badge variant="outline">{s.channel}</Badge>
            {s.delay_days !== undefined && (
              <Badge variant="outline">
                {s.delay_days >= 0 ? `+${s.delay_days}d` : `${s.delay_days}d`}
              </Badge>
            )}
          </div>
          {s.subject && (
            <div className="text-xs mt-1">
              <b>Subject:</b> {s.subject}
            </div>
          )}
          <pre className="whitespace-pre-wrap text-xs mt-1 opacity-90">
            {s.body_sms || s.body_text}
          </pre>
        </div>
      ))}
    </div>
  );
}

function PlannersTab({ refreshBalance }) {
  const [season, setSeason] = useState("spring");
  const [services, setServices] = useState("pool_open");
  const [seasonChannel, setSeasonChannel] = useState("email");
  const [seasonTone, setSeasonTone] = useState("friendly");
  const [seasonSteps, setSeasonSteps] = useState([]);
  const [seasonBusy, setSeasonBusy] = useState(false);

  const [ladder, setLadder] = useState("7,14,30");
  const [invChannel, setInvChannel] = useState("email");
  const [invTone, setInvTone] = useState("professional");
  const [invSteps, setInvSteps] = useState([]);
  const [invBusy, setInvBusy] = useState(false);

  const draftSeasonal = async () => {
    setSeasonBusy(true);
    try {
      const r = await api.post("/comms/planners/seasonal/draft", {
        season,
        service_types: services.split(",").map((s) => s.trim()).filter(Boolean),
        channel: seasonChannel, tone: seasonTone,
      });
      setSeasonSteps(r.steps.map((s) => ({ ...s, _keep: true })));
      toast.success(`Drafted ${r.steps.length} steps (${r.total_credits_debited} credits)`);
      refreshBalance();
    } catch (e) {
      toast.error(e?.message || "Draft failed");
    } finally {
      setSeasonBusy(false);
    }
  };

  const approveSeasonal = async () => {
    const kept = seasonSteps.filter((s) => s._keep !== false)
      .map(({ _keep, ...rest }) => rest);
    if (!kept.length) { toast.error("No steps kept"); return; }
    try {
      const r = await api.post("/comms/planners/seasonal/approve",
                                  { steps: kept });
      toast.success(`Created ${r.count} automation rules`);
      setSeasonSteps([]);
    } catch (e) {
      toast.error(e?.message || "Approve failed");
    }
  };

  const draftInvoice = async () => {
    const days = ladder.split(",").map((x) => parseInt(x, 10))
      .filter((n) => !isNaN(n));
    if (!days.length) { toast.error("Enter days (comma-separated)"); return; }
    setInvBusy(true);
    try {
      const r = await api.post("/comms/planners/invoice-followup/draft", {
        days_ladder: days,
        channel: invChannel, tone: invTone,
      });
      setInvSteps(r.steps.map((s) => ({ ...s, _keep: true })));
      toast.success(`Drafted ${r.steps.length} steps (${r.total_credits_debited} credits)`);
      refreshBalance();
    } catch (e) {
      toast.error(e?.message || "Draft failed");
    } finally {
      setInvBusy(false);
    }
  };

  const approveInvoice = async () => {
    const kept = invSteps.filter((s) => s._keep !== false)
      .map(({ _keep, ...rest }) => rest);
    if (!kept.length) { toast.error("No steps kept"); return; }
    try {
      const r = await api.post("/comms/planners/invoice-followup/approve",
                                  { steps: kept });
      toast.success(`Created ${r.count} automation rules`);
      setInvSteps([]);
    } catch (e) {
      toast.error(e?.message || "Approve failed");
    }
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4"
          data-testid="autopilot-planners">
      <PlannerCard
          title="Seasonal Planner"
          subtitle="Draft an open/close ladder per service. 3 credits per drafted step."
          testId="planner-seasonal">
        <div className="grid grid-cols-2 gap-2">
          <div>
            <Label>Season</Label>
            <select value={season}
                    onChange={(e) => setSeason(e.target.value)}
                    className="w-full border rounded p-2 text-sm mt-1"
                    data-testid="planner-seasonal-season">
              {SEASONS.map((s) => <option key={s}>{s}</option>)}
            </select>
          </div>
          <div>
            <Label>Channel</Label>
            <select value={seasonChannel}
                    onChange={(e) => setSeasonChannel(e.target.value)}
                    className="w-full border rounded p-2 text-sm mt-1">
              {CHANNELS.map((c) => <option key={c}>{c}</option>)}
            </select>
          </div>
          <div className="col-span-2">
            <Label>Service types (comma-separated)</Label>
            <Input value={services}
                    onChange={(e) => setServices(e.target.value)}
                    placeholder="pool_open, landscape"
                    className="mt-1"
                    data-testid="planner-seasonal-services" />
          </div>
          <div>
            <Label>Tone</Label>
            <select value={seasonTone}
                    onChange={(e) => setSeasonTone(e.target.value)}
                    className="w-full border rounded p-2 text-sm mt-1">
              {TONES.map((t) => <option key={t}>{t}</option>)}
            </select>
          </div>
        </div>
        <Button onClick={draftSeasonal} disabled={seasonBusy}
                data-testid="planner-seasonal-draft">
          <PlayCircle className="w-4 h-4 mr-1" />
          {seasonBusy ? "Drafting…" : "Draft ladder"}
        </Button>
        {seasonSteps.length > 0 && (
          <>
            <StepEditor steps={seasonSteps} setSteps={setSeasonSteps} />
            <Button onClick={approveSeasonal} className="w-full"
                     data-testid="planner-seasonal-approve">
              <Check className="w-4 h-4 mr-1" />
              Approve &amp; create rules
            </Button>
          </>
        )}
      </PlannerCard>

      <PlannerCard
          title="Invoice Follow-up Ladder"
          subtitle="Days past due → automation steps. 3 credits per drafted step."
          testId="planner-invoice">
        <div className="grid grid-cols-2 gap-2">
          <div className="col-span-2">
            <Label>Days ladder (comma-separated)</Label>
            <Input value={ladder}
                    onChange={(e) => setLadder(e.target.value)}
                    placeholder="7, 14, 30"
                    className="mt-1"
                    data-testid="planner-invoice-ladder" />
          </div>
          <div>
            <Label>Channel</Label>
            <select value={invChannel}
                    onChange={(e) => setInvChannel(e.target.value)}
                    className="w-full border rounded p-2 text-sm mt-1">
              {CHANNELS.map((c) => <option key={c}>{c}</option>)}
            </select>
          </div>
          <div>
            <Label>Tone</Label>
            <select value={invTone}
                    onChange={(e) => setInvTone(e.target.value)}
                    className="w-full border rounded p-2 text-sm mt-1">
              {TONES.map((t) => <option key={t}>{t}</option>)}
            </select>
          </div>
        </div>
        <Button onClick={draftInvoice} disabled={invBusy}
                data-testid="planner-invoice-draft">
          <PlayCircle className="w-4 h-4 mr-1" />
          {invBusy ? "Drafting…" : "Draft ladder"}
        </Button>
        {invSteps.length > 0 && (
          <>
            <StepEditor steps={invSteps} setSteps={setInvSteps} />
            <Button onClick={approveInvoice} className="w-full"
                     data-testid="planner-invoice-approve">
              <Check className="w-4 h-4 mr-1" />
              Approve &amp; create rules
            </Button>
          </>
        )}
      </PlannerCard>
    </div>
  );
}

// ─── Page shell ─────────────────────────────────────────────────────────

export default function AutopilotPage() {
  const nav = useNavigate();
  const [balance, setBalance] = useState(null);

  const refreshBalance = useCallback(async () => {
    const b = await api.get("/ai-credits/balance").catch(() => null);
    setBalance(b);
  }, []);
  useEffect(() => { refreshBalance(); }, [refreshBalance]);

  return (
    <div className="p-4 md:p-8 max-w-6xl mx-auto space-y-4"
          data-testid="autopilot-page">
      <div className="flex items-center gap-3 mb-4">
        <button onClick={() => nav(-1)}
                className="p-2 rounded-lg hover:brightness-95"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}>
          <ArrowLeft size={16} />
        </button>
        <div className="flex-1">
          <h1 className="text-2xl md:text-3xl font-bold"
              style={{ color: colors.onSurface }}>
            AI Autopilot
          </h1>
          <p className="text-xs mt-0.5" style={{ color: colors.muted }}>
            Draft channel-aware copy for automation rules · plan seasonal + invoice ladders.
          </p>
        </div>
        {balance && (
          <Badge variant="outline" data-testid="ap-balance">
            Balance: <span className="ml-1 font-bold">{balance.balance}</span>
          </Badge>
        )}
      </div>

      <Tabs defaultValue="copy" className="w-full">
        <TabsList data-testid="ap-tabs">
          <TabsTrigger value="copy" data-testid="ap-tab-copy">
            Copy Generator
          </TabsTrigger>
          <TabsTrigger value="planners" data-testid="ap-tab-planners">
            Campaign Planners
          </TabsTrigger>
        </TabsList>
        <TabsContent value="copy" className="mt-4">
          <CopyGenerator balance={balance}
                          refreshBalance={refreshBalance} />
        </TabsContent>
        <TabsContent value="planners" className="mt-4">
          <PlannersTab refreshBalance={refreshBalance} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
