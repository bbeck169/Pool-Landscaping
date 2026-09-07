/**
 * ThemeSettings — Phase I1.5.b · Feb-2026.
 *
 * Admin/manager/super_admin editor for the tenant color palette
 * shipped in I1.5.a. Two-column layout on ≥ md (form left / live
 * preview right); stacked on narrow via the ``useIsWide(768)`` hook
 * shipped in I1.5.a's frontend bonus.
 *
 * Key behaviours:
 *   • Preset picker + confirm modal → POST /api/tenants/me/theme/apply-preset.
 *   • Per-slot solid / gradient mode toggle (hidden on solid-only slots).
 *   • Real-time validation via POST /api/tenants/me/theme/preview
 *     (debounced 400 ms). Save button disabled while errors exist.
 *   • Live preview panel renders sample surfaces (nav, rail, tiles,
 *     buttons, accents) from the *current editor state*, not the
 *     server — no PUT required to see changes.
 *   • Gradient slots surface a soft "contrast not auto-checked"
 *     warning (backend skips gradient contrast validation).
 *
 * All endpoint shapes match the I1.5.a tester-confirmed contract:
 * snake_case slot names, lowercase hex, ``{key: "..."}`` on
 * apply-preset.
 */
import React from "react";
import { toast } from "sonner";
import { Palette, Loader2, RotateCcw, Save, AlertTriangle, Info } from "lucide-react";

import { api } from "@/api";
import { colors } from "@/theme";
import { useIsWide } from "@/hooks/useIsNarrow";
// Phase I1.5.c · Feb-2026 — After the editor saves or applies a
// preset, invalidate the shared ``useTenantTheme`` cache so the
// app-shell reskins in place without a reload. ``applyOverride``
// gives us optimistic-update semantics (the CSS vars flip the
// moment PUT returns 200, before the follow-up GET completes).
import { useTenantTheme } from "@/hooks/useTenantTheme";
import { Button } from "@/components/ui/button";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import { Input } from "@/components/ui/input";
import {
  Accordion, AccordionContent, AccordionItem, AccordionTrigger,
} from "@/components/ui/accordion";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";


// ── Section / slot topology (must match backend validate.py) ──
const SECTIONS = [
  {
    key: "menu",
    label: "Top Navigation",
    hint: "The horizontal category strip at the top of the shell.",
    slots: [
      { key: "bg",   label: "Background", solidOnly: false },
      { key: "text", label: "Text",       solidOnly: true },
    ],
  },
  {
    key: "rail",
    label: "Quick Access Rail",
    hint: "The vertical pin rail on the left side.",
    slots: [
      { key: "bg",   label: "Background", solidOnly: false },
      { key: "text", label: "Text",       solidOnly: true },
    ],
  },
  {
    key: "tiles",
    label: "Dashboard Tiles",
    hint: "KPI, report + drilldown tiles across the app.",
    slots: [
      { key: "bg",     label: "Background", solidOnly: false },
      { key: "text",   label: "Text",       solidOnly: true },
      { key: "border", label: "Border",     solidOnly: true },
    ],
  },
  {
    key: "buttons",
    label: "Buttons",
    hint: "Primary CTAs across the app.",
    slots: [
      { key: "bg",   label: "Background", solidOnly: false },
      { key: "text", label: "Text",       solidOnly: true },
    ],
  },
  {
    key: "accents",
    label: "Accents",
    hint: "Links, focus rings, badges, chart legends.",
    slots: [
      { key: "primary",     label: "Primary fill",   solidOnly: false },
      { key: "secondary",   label: "Secondary fill", solidOnly: false },
      { key: "text",        label: "Accent text",    solidOnly: true },
      { key: "link",        label: "Link",           solidOnly: true },
      { key: "focus_ring",  label: "Focus ring",     solidOnly: true },
      { key: "badge_bg",    label: "Badge fill",     solidOnly: false },
      { key: "badge_text",  label: "Badge text",     solidOnly: true },
    ],
  },
];

const HEX_RE = /^#[0-9a-fA-F]{6}$/;


// ── Slot helpers ────────────────────────────────────────────────
function slotToCss(slot) {
  if (!slot) return "transparent";
  if (slot.mode === "gradient" && slot.gradient) {
    const { from, to, angle } = slot.gradient;
    return `linear-gradient(${angle}deg, ${from} 0%, ${to} 100%)`;
  }
  return slot.solid || "#000000";
}


function coerceHex(s, fallback) {
  const v = (s || "").trim().toLowerCase();
  return HEX_RE.test(v) ? v : fallback;
}


// ── Reducer ─────────────────────────────────────────────────────
function themeReducer(state, action) {
  switch (action.type) {
    case "hydrate":
      return {
        base: action.theme,
        working: action.theme,
        dirty: false,
      };
    case "replace":
      return {
        base: state.base,
        working: action.theme,
        dirty: JSON.stringify(action.theme) !== JSON.stringify(state.base),
      };
    case "slot": {
      const next = structuredClone(state.working);
      next[action.section][action.slot] = action.value;
      return {
        base: state.base,
        working: next,
        dirty: JSON.stringify(next) !== JSON.stringify(state.base),
      };
    }
    case "discard":
      return { base: state.base, working: state.base, dirty: false };
    default:
      return state;
  }
}


// ── Slot editor ──────────────────────────────────────────────────
function SlotEditor({ section, slot, value, onChange, error, warning }) {
  const isGradient = value?.mode === "gradient";
  const testidBase = `theme-slot-${section}-${slot.key}`;
  return (
    <div
      className="rounded-lg p-3 space-y-2"
      style={{ border: `1px solid ${error ? "#dc2626" : colors.border}`,
                background: error ? "#fef2f2" : colors.surfaceSecondary }}
      data-testid={testidBase}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex flex-col">
          <span className="text-sm font-semibold" style={{ color: colors.onSurface }}>
            {slot.label}
          </span>
          {slot.solidOnly && (
            <span className="text-[11px]" style={{ color: colors.muted }}>
              Solid only (text/small element)
            </span>
          )}
        </div>
        {!slot.solidOnly && (
          <div className="inline-flex rounded-md border overflow-hidden"
                style={{ borderColor: colors.border }}
                data-testid={`${testidBase}-mode-toggle`}>
            <button
              type="button"
              className="px-3 py-1 text-xs font-semibold"
              style={{
                background: !isGradient ? colors.brand : "transparent",
                color: !isGradient ? "#ffffff" : colors.onSurface,
              }}
              onClick={() => onChange({
                mode: "solid",
                solid: value?.solid || value?.gradient?.from || "#000000",
              })}
              data-testid={`${testidBase}-mode-solid`}
            >
              Solid
            </button>
            <button
              type="button"
              className="px-3 py-1 text-xs font-semibold"
              style={{
                background: isGradient ? colors.brand : "transparent",
                color: isGradient ? "#ffffff" : colors.onSurface,
              }}
              onClick={() => onChange({
                mode: "gradient",
                gradient: {
                  from: value?.solid || value?.gradient?.from || "#0f172a",
                  to:   value?.gradient?.to   || "#166534",
                  angle: value?.gradient?.angle ?? 135,
                },
              })}
              data-testid={`${testidBase}-mode-gradient`}
            >
              Gradient
            </button>
          </div>
        )}
      </div>

      {isGradient ? (
        <div className="space-y-2">
          <HexPicker
            label="From"
            value={value.gradient.from}
            onChange={(hex) => onChange({
              ...value,
              gradient: { ...value.gradient, from: hex },
            })}
            testid={`${testidBase}-grad-from`}
          />
          <HexPicker
            label="To"
            value={value.gradient.to}
            onChange={(hex) => onChange({
              ...value,
              gradient: { ...value.gradient, to: hex },
            })}
            testid={`${testidBase}-grad-to`}
          />
          <div>
            <label className="text-xs font-medium block mb-1"
                    style={{ color: colors.muted }}>
              Angle: {value.gradient.angle}°
            </label>
            <Slider
              value={[value.gradient.angle]}
              max={360}
              step={1}
              onValueChange={(v) => onChange({
                ...value,
                gradient: { ...value.gradient, angle: v[0] },
              })}
              data-testid={`${testidBase}-grad-angle`}
            />
          </div>
          <div
            className="h-6 rounded-md"
            style={{ background: slotToCss(value),
                      border: `1px solid ${colors.border}` }}
            data-testid={`${testidBase}-grad-preview`}
          />
          {warning && (
            <div className="flex items-start gap-1 text-[11px] leading-tight"
                  style={{ color: "#92400e" }}
                  data-testid={`${testidBase}-grad-warning`}>
              <AlertTriangle size={12} className="mt-0.5 flex-shrink-0" />
              <span>Contrast not auto-checked on gradient — verify legibility visually.</span>
            </div>
          )}
        </div>
      ) : (
        <HexPicker
          value={value?.solid || "#000000"}
          onChange={(hex) => onChange({ mode: "solid", solid: hex })}
          testid={`${testidBase}-solid`}
        />
      )}

      {error && (
        <div className="flex items-start gap-1 text-[11px] leading-tight"
              style={{ color: "#991b1b" }}
              data-testid={`${testidBase}-error`}>
          <AlertTriangle size={12} className="mt-0.5 flex-shrink-0" />
          <span>{error.message}</span>
        </div>
      )}
    </div>
  );
}


function HexPicker({ label, value, onChange, testid }) {
  const [draft, setDraft] = React.useState(value);
  React.useEffect(() => { setDraft(value); }, [value]);
  const commit = (raw) => {
    const hex = coerceHex(raw, value);
    onChange(hex);
    setDraft(hex);
  };
  return (
    <div className="flex items-center gap-2">
      {label && (
        <span className="text-xs font-medium w-12"
               style={{ color: colors.muted }}>
          {label}
        </span>
      )}
      <input
        type="color"
        value={value}
        onChange={(e) => commit(e.target.value)}
        className="h-8 w-10 rounded border cursor-pointer"
        style={{ borderColor: colors.border }}
        data-testid={`${testid}-picker`}
      />
      <Input
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => commit(draft)}
        className="h-8 text-xs font-mono flex-1 max-w-[110px]"
        maxLength={7}
        data-testid={`${testid}-hex`}
      />
    </div>
  );
}


// ── Live preview panel ──────────────────────────────────────────
function LivePreview({ theme }) {
  if (!theme) return null;
  const { menu, rail, tiles, buttons, accents } = theme;

  return (
    <div
      className="rounded-2xl overflow-hidden"
      style={{ border: `1px solid ${colors.border}` }}
      data-testid="theme-live-preview"
    >
      {/* Nav sample */}
      <div
        className="px-4 py-3 flex items-center gap-4"
        style={{ background: slotToCss(menu.bg), color: menu.text.solid }}
        data-testid="theme-preview-nav"
      >
        <span className="text-sm font-bold">Pool &amp; Landscaping</span>
        <span className="text-xs opacity-90">Dashboard</span>
        <span className="text-xs opacity-90">Schedule</span>
        <span className="text-xs opacity-90">Reports</span>
      </div>

      <div className="flex" style={{ minHeight: 300, background: colors.surface }}>
        {/* Rail sample */}
        <div
          className="w-16 py-3 flex flex-col items-center gap-2"
          style={{ background: slotToCss(rail.bg), color: rail.text.solid }}
          data-testid="theme-preview-rail"
        >
          <div className="text-[10px] font-bold rounded px-1.5 py-0.5"
                style={{ background: "rgba(255,255,255,0.15)" }}>
            Pin 1
          </div>
          <div className="text-[10px] rounded px-1.5 py-0.5 opacity-80">
            Pin 2
          </div>
          <div className="text-[10px] rounded px-1.5 py-0.5 opacity-80">
            Pin 3
          </div>
        </div>

        {/* Main sample */}
        <div className="flex-1 p-4 space-y-3">
          {/* Tiles row */}
          <div className="grid grid-cols-3 gap-2" data-testid="theme-preview-tiles">
            {["Revenue", "Jobs", "Leads"].map((t) => (
              <div
                key={t}
                className="rounded-lg p-2"
                style={{
                  background: slotToCss(tiles.bg),
                  color: tiles.text.solid,
                  border: `1px solid ${tiles.border.solid}`,
                }}
              >
                <div className="text-[10px] uppercase opacity-70">{t}</div>
                <div className="text-lg font-bold">42</div>
              </div>
            ))}
          </div>

          {/* Buttons row */}
          <div className="flex gap-2" data-testid="theme-preview-buttons">
            <button
              className="px-3 py-1.5 rounded-md text-xs font-semibold"
              style={{ background: slotToCss(buttons.bg),
                        color: buttons.text.solid }}
            >
              Primary CTA
            </button>
            <button
              className="px-3 py-1.5 rounded-md text-xs font-semibold"
              style={{ background: slotToCss(accents.secondary),
                        color: "#ffffff" }}
            >
              Secondary
            </button>
            <button
              className="px-3 py-1.5 rounded-md text-xs font-semibold"
              style={{ background: "#dc2626", color: "#ffffff" }}
            >
              Delete
            </button>
          </div>

          {/* Accents row */}
          <div className="flex items-center gap-3 text-xs"
                data-testid="theme-preview-accents">
            <a href="#" onClick={(e) => e.preventDefault()}
                style={{ color: accents.link.solid,
                          textDecoration: "underline" }}>
              Sample link
            </a>
            <input
              type="text"
              defaultValue="Focus me"
              className="h-7 px-2 text-xs rounded outline-none"
              style={{
                border: `2px solid ${accents.focus_ring.solid}`,
                background: "#ffffff",
                color: colors.onSurface,
              }}
            />
            <span
              className="text-[11px] font-semibold px-2 py-0.5 rounded-full"
              style={{
                background: slotToCss(accents.badge_bg),
                color: accents.badge_text.solid,
              }}
            >
              Badge
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}


// ── Page ────────────────────────────────────────────────────────
export default function ThemeSettings() {
  const isWide = useIsWide(768);
  const [state, dispatch] = React.useReducer(themeReducer,
    { base: null, working: null, dirty: false });
  const [presets, setPresets] = React.useState([]);
  const [presetKey, setPresetKey] = React.useState("");
  const [pendingPreset, setPendingPreset] = React.useState(null);
  const [previewErrors, setPreviewErrors] = React.useState([]);
  const [saving, setSaving] = React.useState(false);
  const [applying, setApplying] = React.useState(false);
  // Optimistic reskin trigger — see the import comment. ``refetch``
  // is the authoritative post-save invalidation; ``applyOverride``
  // is the pre-GET optimism so the app-shell reflects the new
  // palette the instant PUT returns 200.
  const { refetch: refetchTenantTheme,
            applyOverride: applyTenantThemeOverride } = useTenantTheme();

  // Initial load.
  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [theme, presetsRes] = await Promise.all([
          api.get("/tenants/me/theme"),
          api.get("/theme-presets"),
        ]);
        if (cancelled) return;
        dispatch({ type: "hydrate", theme });
        setPresets(presetsRes.presets || []);
        setPresetKey(theme.preset || "default");
      } catch (e) {
        toast.error(e?.message || "Failed to load theme");
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // Debounced preview.
  React.useEffect(() => {
    if (!state.working) return;
    const h = setTimeout(async () => {
      try {
        const res = await api.post("/tenants/me/theme/preview", state.working);
        setPreviewErrors(res.errors || []);
      } catch (e) {
        // 403 for non-admins — shouldn't happen (route is admin-only)
        // but degrade gracefully.
        setPreviewErrors([]);
      }
    }, 400);
    return () => clearTimeout(h);
  }, [state.working]);

  const errorByPath = React.useMemo(() => {
    const m = {};
    for (const e of previewErrors) {
      if (e.path) m[e.path] = e;
    }
    return m;
  }, [previewErrors]);

  const hasErrors = previewErrors.length > 0;
  const canSave = state.dirty && !hasErrors && !saving;

  const handleSlotChange = (section, slotKey) => (value) => {
    dispatch({ type: "slot", section, slot: slotKey, value });
  };

  const handleSave = async () => {
    if (!canSave) return;
    setSaving(true);
    try {
      const persisted = await api.put("/tenants/me/theme", state.working);
      dispatch({ type: "hydrate", theme: persisted });
      // Optimistic reskin immediately, then reconcile via refetch.
      applyTenantThemeOverride(persisted);
      refetchTenantTheme();
      toast.success("Theme saved");
    } catch (e) {
      const detail = e?.data?.detail;
      const msg = detail?.message || e?.message || "Failed to save theme";
      toast.error(msg);
    } finally {
      setSaving(false);
    }
  };

  const handleApplyPreset = async () => {
    if (!pendingPreset) return;
    setApplying(true);
    try {
      const persisted = await api.post(
        "/tenants/me/theme/apply-preset", { key: pendingPreset });
      dispatch({ type: "hydrate", theme: persisted });
      setPresetKey(pendingPreset);
      applyTenantThemeOverride(persisted);
      refetchTenantTheme();
      toast.success(`Applied preset: ${pendingPreset}`);
    } catch (e) {
      const detail = e?.data?.detail;
      const msg = detail?.message || e?.message || "Failed to apply preset";
      toast.error(msg);
    } finally {
      setApplying(false);
      setPendingPreset(null);
    }
  };

  if (!state.working) {
    return (
      <div className="rounded-2xl p-8 flex items-center justify-center gap-2"
            style={{ background: colors.surface,
                      border: `1px solid ${colors.border}` }}
            data-testid="theme-settings-loading">
        <Loader2 size={16} className="animate-spin" />
        <span className="text-sm" style={{ color: colors.muted }}>
          Loading theme…
        </span>
      </div>
    );
  }

  return (
    <div className="space-y-4" data-testid="theme-settings-page">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Palette size={20} style={{ color: colors.brand }} />
          <h2 className="text-xl font-bold"
               style={{ color: colors.onSurface }}
               data-testid="theme-settings-title">
            Theme
          </h2>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={!state.dirty || saving}
            onClick={() => dispatch({ type: "discard" })}
            data-testid="theme-discard-btn"
          >
            <RotateCcw size={14} className="mr-1" />
            Discard changes
          </Button>
          <Button
            size="sm"
            disabled={!canSave}
            onClick={handleSave}
            data-testid="theme-save-btn"
          >
            {saving ? (
              <Loader2 size={14} className="mr-1 animate-spin" />
            ) : (
              <Save size={14} className="mr-1" />
            )}
            Save
          </Button>
        </div>
      </div>

      {/* Preset picker row */}
      <div
        className="rounded-lg p-3 flex flex-wrap items-center gap-2"
        style={{ background: colors.surface,
                  border: `1px solid ${colors.border}` }}
        data-testid="theme-preset-row"
      >
        <span className="text-sm font-semibold"
               style={{ color: colors.onSurface }}>
          Preset:
        </span>
        <div className="min-w-[220px]">
          <Select value={presetKey} onValueChange={setPresetKey}>
            <SelectTrigger data-testid="theme-preset-select">
              <SelectValue placeholder="Choose a preset" />
            </SelectTrigger>
            <SelectContent data-testid="theme-preset-select-content">
              {presets.map((p) => (
                <SelectItem key={p.key} value={p.key}
                             data-testid={`theme-preset-option-${p.key}`}>
                  {p.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <Button
          size="sm"
          variant="secondary"
          disabled={!presetKey}
          onClick={() => setPendingPreset(presetKey)}
          data-testid="theme-apply-preset-btn"
        >
          Apply preset
        </Button>
        <span className="text-[11px] flex items-center gap-1"
               style={{ color: colors.muted }}>
          <Info size={12} />
          Applying overwrites your current palette.
        </span>
      </div>

      {hasErrors && (
        <div
          className="rounded-lg p-3 space-y-1"
          style={{ background: "#fef2f2",
                    border: "1px solid #fecaca" }}
          data-testid="theme-error-summary"
        >
          <div className="flex items-center gap-2 text-sm font-semibold"
                style={{ color: "#991b1b" }}>
            <AlertTriangle size={14} />
            {previewErrors.length} issue{previewErrors.length === 1 ? "" : "s"} — fix before saving.
          </div>
          <ul className="text-xs space-y-0.5 pl-6 list-disc"
               style={{ color: "#991b1b" }}>
            {previewErrors.map((e, i) => (
              <li key={i}>
                <span className="font-mono">{e.path || "payload"}</span>
                {" — "}{e.message}
                {e.computed_ratio != null && (
                  <span className="ml-1 font-mono">
                    ({e.computed_ratio}:1)
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Editor + preview grid */}
      <div className={isWide ? "grid grid-cols-2 gap-4" : "space-y-4"}
            data-testid="theme-settings-grid">
        <div>
          <Accordion type="single" defaultValue="menu" collapsible
                      data-testid="theme-sections-accordion">
            {SECTIONS.map((section) => (
              <AccordionItem key={section.key} value={section.key}
                              data-testid={`theme-section-${section.key}`}>
                <AccordionTrigger data-testid={`theme-section-${section.key}-trigger`}>
                  <div className="flex flex-col items-start">
                    <span className="text-sm font-semibold">{section.label}</span>
                    <span className="text-[11px]"
                           style={{ color: colors.muted }}>
                      {section.hint}
                    </span>
                  </div>
                </AccordionTrigger>
                <AccordionContent>
                  <div className="space-y-2 pt-2">
                    {section.slots.map((slot) => {
                      const value = state.working[section.key][slot.key];
                      const path = `${section.key}.${slot.key}`;
                      const isGrad = value?.mode === "gradient";
                      return (
                        <SlotEditor
                          key={slot.key}
                          section={section.key}
                          slot={slot}
                          value={value}
                          onChange={handleSlotChange(section.key, slot.key)}
                          error={errorByPath[path]}
                          warning={isGrad && !slot.solidOnly}
                        />
                      );
                    })}
                  </div>
                </AccordionContent>
              </AccordionItem>
            ))}
          </Accordion>
        </div>

        <div className={isWide ? "sticky top-20 self-start" : ""}>
          <LivePreview theme={state.working} />
        </div>
      </div>

      {/* Apply-preset confirm modal */}
      <AlertDialog open={!!pendingPreset}
                    onOpenChange={(open) => !open && setPendingPreset(null)}>
        <AlertDialogContent data-testid="theme-apply-preset-modal">
          <AlertDialogHeader>
            <AlertDialogTitle>Apply preset?</AlertDialogTitle>
            <AlertDialogDescription>
              This will overwrite your current palette with the{" "}
              <span className="font-mono">{pendingPreset}</span> preset.
              Your working changes will be lost.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel data-testid="theme-apply-preset-cancel">
              Cancel
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={handleApplyPreset}
              disabled={applying}
              data-testid="theme-apply-preset-confirm"
            >
              {applying ? "Applying…" : "Apply preset"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
