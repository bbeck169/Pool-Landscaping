/**
 * Feb-2026 · Ticket #4 · AI Configuration settings tab.
 *
 * Admin-only sidebar tab in SettingsHub. Three controls:
 *   1. AI Persona Name (text, ≤ 60 chars) → settings.ai.persona_name
 *   2. Knowledge Base document uploads (toggle) → kb_uploads_enabled
 *   3. Enable AI Analytics (toggle)             → analytics_enabled
 *
 * Backend: GET/PATCH /api/tenants/mine/settings/ai.  Persona name
 * saves on blur (or Save button); toggles auto-save on change.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Bot, FileUp, BarChart3, Save } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import { useAuth } from "@/auth";

const PERSONA_MAX = 60;

export default function AIConfigurationSettings() {
  const { user } = useAuth() || {};
  const isAdmin = ["admin", "super_admin"].includes(
    (user?.role || "").toLowerCase(),
  );
  const [cfg, setCfg] = useState(null);
  const [personaDraft, setPersonaDraft] = useState("");
  const [busy, setBusy] = useState(null);
  const [loadErr, setLoadErr] = useState("");
  const initialPersona = useRef("");

  const load = useCallback(async () => {
    try {
      const r = await api.get("/tenants/mine/settings/ai");
      setCfg(r || {});
      setPersonaDraft(r?.persona_name || "");
      initialPersona.current = r?.persona_name || "";
      setLoadErr("");
    } catch (e) {
      setLoadErr(e?.message || "Failed to load AI configuration");
    }
  }, []);

  useEffect(() => { if (isAdmin) load(); }, [load, isAdmin]);

  const flipToggle = async (key) => {
    if (!cfg || busy) return;
    const next = !cfg[key];
    setBusy(key);
    setCfg((prev) => ({ ...prev, [key]: next }));
    try {
      const r = await api.patch(
        "/tenants/mine/settings/ai", { [key]: next },
      );
      setCfg(r || {});
      const label = key === "kb_uploads_enabled"
        ? "Knowledge Base uploads"
        : "AI analytics";
      toast.success(`${label} — ${next ? "ON" : "OFF"}`);
    } catch (e) {
      setCfg((prev) => ({ ...prev, [key]: !next }));
      toast.error(e?.message || "Failed to update AI setting");
    } finally {
      setBusy(null);
    }
  };

  const savePersona = async () => {
    if (!cfg || busy) return;
    const trimmed = (personaDraft || "").trim();
    if (trimmed === (initialPersona.current || "").trim()) return;
    setBusy("persona_name");
    try {
      const r = await api.patch(
        "/tenants/mine/settings/ai",
        { persona_name: trimmed },
      );
      setCfg(r || {});
      setPersonaDraft(r?.persona_name || "");
      initialPersona.current = r?.persona_name || "";
      toast.success("AI persona name saved");
    } catch (e) {
      toast.error(e?.message || "Failed to save AI persona name");
    } finally {
      setBusy(null);
    }
  };

  if (!isAdmin) {
    return (
      <div className="rounded-2xl p-6"
            style={{ background: colors.surface,
                      border: `1px solid ${colors.border}` }}
            data-testid="ai-config-forbidden">
        <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>
          Admin access required
        </div>
        <div className="text-xs mt-1" style={{ color: colors.muted }}>
          Only admins can view or change AI configuration.
        </div>
      </div>
    );
  }

  const remaining = PERSONA_MAX - (personaDraft || "").length;

  return (
    <div className="rounded-2xl p-5 space-y-5"
          style={{ background: colors.surface,
                    border: `1px solid ${colors.border}` }}
          data-testid="ai-config-card">
      <div>
        <h2 className="text-lg font-semibold"
             style={{ color: colors.onSurface }}
             data-testid="ai-config-title">
          AI Configuration
        </h2>
        <p className="text-sm mt-1" style={{ color: colors.muted }}>
          Personalize the AI assistant and control which optional
          features are enabled for this organization.
        </p>
      </div>

      {loadErr ? (
        <div className="rounded-lg px-3 py-2 text-sm"
              style={{ background: "#FEF2F2", color: "#991B1B",
                        border: "1px solid #FECACA" }}
              data-testid="ai-config-error">
          {loadErr}
        </div>
      ) : null}

      {!cfg && !loadErr ? (
        <div className="text-sm" style={{ color: colors.muted }}
              data-testid="ai-config-loading">
          Loading…
        </div>
      ) : null}

      {cfg ? (
        <>
          <div className="space-y-2" data-testid="ai-persona-row">
            <div className="flex items-center gap-2">
              <Bot size={16} style={{ color: colors.brand }} />
              <label className="text-sm font-semibold"
                      htmlFor="ai-persona-name-input"
                      style={{ color: colors.onSurface }}>
                AI Persona Name
              </label>
            </div>
            <p className="text-xs" style={{ color: colors.muted }}>
              Displayed in the AI assistant header, chat greeting, and
              KB tooltips.
            </p>
            <div className="flex items-center gap-2">
              <input
                id="ai-persona-name-input"
                type="text"
                maxLength={PERSONA_MAX}
                value={personaDraft}
                onChange={(e) => setPersonaDraft(e.target.value)}
                onBlur={savePersona}
                className="flex-1 px-3 py-2 rounded-lg text-sm"
                style={{ background: colors.surfaceSecondary,
                          border: `1px solid ${colors.border}`,
                          color: colors.onSurface }}
                placeholder="e.g., Ask AquaTerra"
                data-testid="ai-persona-name-input"
              />
              <button
                type="button"
                onClick={savePersona}
                disabled={busy === "persona_name"}
                className="inline-flex items-center gap-1 px-3 py-2 rounded-lg text-sm font-bold"
                style={{ background: colors.brand, color: "#fff",
                          opacity: busy === "persona_name" ? 0.6 : 1 }}
                data-testid="ai-persona-name-save"
              >
                <Save size={14} /> Save
              </button>
            </div>
            <div className="text-[11px]" style={{ color: colors.muted }}
                  data-testid="ai-persona-name-remaining">
              {remaining} characters remaining
            </div>
          </div>

          <div className="divide-y" style={{ borderColor: colors.border }}>
            <ToggleRow
              testKey="kb_uploads_enabled"
              label="Knowledge Base document uploads"
              hint="Allow admins to upload PDF/DOCX/TXT/MD files that feed the AI assistant's knowledge base."
              Icon={FileUp}
              value={cfg.kb_uploads_enabled}
              busy={busy === "kb_uploads_enabled"}
              onFlip={() => flipToggle("kb_uploads_enabled")}
            />
            <ToggleRow
              testKey="analytics_enabled"
              label="Enable AI Analytics"
              hint="Telemetry only. When OFF, AI usage-analytics emission is suppressed; core AI functionality is unchanged."
              Icon={BarChart3}
              value={cfg.analytics_enabled}
              busy={busy === "analytics_enabled"}
              onFlip={() => flipToggle("analytics_enabled")}
            />
          </div>
        </>
      ) : null}
    </div>
  );
}


function ToggleRow({ testKey, label, hint, Icon, value, busy, onFlip }) {
  const isOn = !!value;
  return (
    <div className="flex items-start justify-between gap-4 py-3"
          data-testid={`ai-row-${testKey}`}>
      <div className="flex items-start gap-3 flex-1 min-w-0">
        <Icon size={18} style={{ color: colors.brand, marginTop: 2 }} />
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold"
                style={{ color: colors.onSurface }}>{label}</div>
          <div className="text-xs mt-0.5" style={{ color: colors.muted }}>
            {hint}
          </div>
        </div>
      </div>
      <button
        type="button"
        onClick={onFlip}
        disabled={busy}
        aria-pressed={isOn}
        className="inline-flex items-center justify-center w-11 h-6 rounded-full transition-colors"
        style={{ background: isOn ? "#10B981" : "#D1D5DB",
                  cursor: busy ? "wait" : "pointer",
                  opacity: busy ? 0.6 : 1 }}
        data-testid={`ai-toggle-${testKey}`}
      >
        <span
          className="block w-5 h-5 rounded-full bg-white transition-transform"
          style={{ transform: isOn ? "translateX(10px)" : "translateX(-10px)" }}
        />
      </button>
    </div>
  );
}
