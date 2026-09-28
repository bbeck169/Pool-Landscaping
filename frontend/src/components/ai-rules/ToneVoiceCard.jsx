/**
 * MTH-B · Feb-2026 — Tone & Voice category card.
 *
 * Radio group (Formal / Friendly / Technical) + optional
 * ``custom_directive`` textarea (500 char cap on-screen; backend
 * validator caps at 2000, so 500 keeps the UI compact without
 * bumping the backend limit).  Save opens the shared reason modal.
 *
 * Preview strip renders a MARCO-styled sample response with the
 * currently-selected tone applied client-side — no server call in
 * this phase (that lands in MTH-D "test surface").
 */
import React, { useMemo, useState } from "react";
import { toast } from "sonner";
import { RotateCcw, Save, Sparkles } from "lucide-react";
import { api } from "@/api";
import { Button, TextInput, Chip } from "@/components/ui-kit";
import RulesReasonModal from "./RulesReasonModal";
import OverrideDiff from "./OverrideDiff";

const STYLE_OPTIONS = [
  { value: "formal",    label: "Formal",    hint: "Precise, professional, neutral." },
  { value: "friendly",  label: "Friendly",  hint: "Warm, first-name, upbeat." },
  { value: "technical", label: "Technical", hint: "Detail-first, jargon OK." },
];

const CUSTOM_DIRECTIVE_MAX = 500;

const SAMPLES = {
  formal:
    "Good afternoon, Mrs. Nguyen. Your service report is attached. Please review the water chemistry summary and reach out with any questions.",
  friendly:
    "Hey Lisa! Just wrapped up at your pool — everything's balanced and swim-ready. Photo + report attached, ping me if anything looks off. 🙂",
  technical:
    "Lisa — Free chlorine 3.2 ppm (target 2–4), pH 7.6 (target 7.4–7.6), TA 90 ppm. Cyanuric 42 ppm; recommend a partial drain by mid-June. Report attached.",
};

export default function ToneVoiceCard({
  value,
  overrideMap,
  platformValue,
  onSaved,
  onReset,
  readOnly = false,
  endpointPrefix = "/tenant-ai-rules",
  showReset = true,
  showDiff = true,
}) {
  const [style, setStyle] = useState(value?.style || "friendly");
  const [directive, setDirective] = useState(value?.custom_directive || "");
  const [saveOpen, setSaveOpen] = useState(false);
  const [resetOpen, setResetOpen] = useState(false);

  React.useEffect(() => {
    setStyle(value?.style || "friendly");
    setDirective(value?.custom_directive || "");
  }, [value]);

  const isOverridden =
    (overrideMap?.["tone_voice.style"] === "tenant") ||
    (overrideMap?.["tone_voice.custom_directive"] === "tenant");
  const overrideCount = [
    overrideMap?.["tone_voice.style"] === "tenant",
    overrideMap?.["tone_voice.custom_directive"] === "tenant",
  ].filter(Boolean).length;

  const preview = useMemo(() => {
    const base = SAMPLES[style] || SAMPLES.friendly;
    if (directive && directive.trim().length > 0) {
      return `${base}\n\n(Custom directive applied: "${directive.trim()}")`;
    }
    return base;
  }, [style, directive]);

  const doSave = async (reason) => {
    try {
      await api.put(`${endpointPrefix}/tone_voice`, {
        value: {
          style,
          custom_directive: directive.slice(0, CUSTOM_DIRECTIVE_MAX),
        },
        reason,
      });
      toast.success("Tone & voice saved.");
      setSaveOpen(false);
      if (onSaved) await onSaved();
    } catch (e) {
      toast.error(
        `Save failed: ${e?.data?.detail?.message || e?.message || "unknown"}`,
      );
    }
  };

  const doReset = async (reason) => {
    try {
      await api.post(`${endpointPrefix}/reset/tone_voice`, { reason });
      toast.success("Tone & voice reset to platform default.");
      setResetOpen(false);
      if (onReset) await onReset();
    } catch (e) {
      toast.error(
        `Reset failed: ${e?.data?.detail?.message || e?.message || "unknown"}`,
      );
    }
  };

  return (
    <div
      className="rounded-2xl bg-white border p-5 space-y-4"
      style={{ borderColor: "#E2E8F0" }}
      data-testid="ai-rules-tone-voice-card"
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <div
            className="w-8 h-8 rounded-lg flex items-center justify-center"
            style={{ background: "#EDE9FE", color: "#6D28D9" }}
          >
            <Sparkles size={16} />
          </div>
          <div>
            <div className="text-sm font-bold">Tone & Voice</div>
            <div className="text-xs opacity-60">
              Drives every AI-drafted email, SMS, and voice reply.
            </div>
          </div>
        </div>
        {isOverridden ? (
          <Chip
            label={`${overrideCount} tenant override${overrideCount === 1 ? "" : "s"}`}
            tone="brand"
            testid="ai-rules-tone-voice-override-pill"
          />
        ) : null}
      </div>

      <OverrideDiff
        category="tone_voice"
        overrideMap={overrideMap}
        tenantValue={value}
        platformValue={platformValue}
        testid="ai-rules-tone-voice-diff"
        readOnly={!showDiff}
      />

      {!showDiff ? null : null}

      <div>
        <div
          className="text-xs font-semibold tracking-wide mb-2"
          style={{ color: "#334155" }}
        >
          STYLE
        </div>
        <div
          className="flex flex-wrap gap-2"
          role="radiogroup"
          data-testid="ai-rules-tone-voice-style"
        >
          {STYLE_OPTIONS.map((opt) => {
            const active = style === opt.value;
            return (
              <label
                key={opt.value}
                className="cursor-pointer flex-1 min-w-[180px]"
              >
                <input
                  type="radio"
                  className="sr-only"
                  name="ai-rules-tone-voice-style"
                  value={opt.value}
                  checked={active}
                  onChange={() => setStyle(opt.value)}
                  disabled={readOnly}
                  data-testid={`ai-rules-tone-voice-style-${opt.value}`}
                />
                <div
                  className="rounded-xl p-3 border"
                  style={{
                    background: active ? "#EDE9FE" : "#F8FAFC",
                    borderColor: active ? "#8B5CF6" : "#E2E8F0",
                    color: "#1F2937",
                  }}
                >
                  <div className="text-sm font-semibold">{opt.label}</div>
                  <div className="text-xs opacity-70 mt-0.5">{opt.hint}</div>
                </div>
              </label>
            );
          })}
        </div>
      </div>

      <div>
        <div
          className="text-xs font-semibold tracking-wide mb-1 flex justify-between"
          style={{ color: "#334155" }}
        >
          <span>CUSTOM DIRECTIVE (optional)</span>
          <span className="opacity-60">
            {directive.length}/{CUSTOM_DIRECTIVE_MAX}
          </span>
        </div>
        <textarea
          value={directive}
          maxLength={CUSTOM_DIRECTIVE_MAX}
          onChange={(e) => setDirective(e.target.value)}
          placeholder="e.g. Always mention our free winterization visit for Platinum tier customers."
          className="w-full px-3 py-2 rounded-lg text-sm bg-white border border-slate-200 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none"
          rows={3}
          disabled={readOnly}
          data-testid="ai-rules-tone-voice-directive"
        />
      </div>

      <div
        className="rounded-lg p-3 text-sm"
        style={{
          background: "#F8FAFC",
          color: "#334155",
          border: "1px dashed #CBD5E1",
        }}
        data-testid="ai-rules-tone-voice-preview"
      >
        <div className="text-xs font-semibold mb-1 opacity-70">
          MARCO PREVIEW
        </div>
        <div className="whitespace-pre-wrap">{preview}</div>
      </div>

      <div className="flex flex-wrap items-center justify-end gap-2 pt-1">
        {showReset ? (
          <Button
            variant="ghost"
            onClick={() => setResetOpen(true)}
            disabled={readOnly}
            testid="ai-rules-tone-voice-reset"
          >
            <RotateCcw size={14} /> Reset to Platform Default
          </Button>
        ) : null}
        <Button
          variant="primary"
          onClick={() => setSaveOpen(true)}
          disabled={readOnly}
          testid="ai-rules-tone-voice-save"
        >
          <Save size={14} /> Save
        </Button>
      </div>

      <RulesReasonModal
        open={saveOpen}
        onClose={() => setSaveOpen(false)}
        title="Save Tone & Voice override"
        description="This tenant's outbound AI drafts will use the new tone immediately after save."
        onConfirm={doSave}
        confirmLabel="Save Override"
        testidPrefix="ai-rules-tone-voice-save-reason"
      />
      <RulesReasonModal
        open={resetOpen}
        onClose={() => setResetOpen(false)}
        title="Reset Tone & Voice to Platform Default"
        description="This clears every tenant-level tone override and falls back to the platform-wide setting."
        onConfirm={doReset}
        confirmLabel="Reset to Default"
        confirmVariant="danger"
        testidPrefix="ai-rules-tone-voice-reset-reason"
      />
    </div>
  );
}
