import React from "react";
import {
  FORM_THEME_PRESETS, FORM_FONT_STACKS,
  presetByKey, coerceTheme, fontStackById,
} from "../../lib/formThemes";

/**
 * Phase K34 · Feb-2026 — shared theme editor for every form-builder
 * surface.  Emits a normalized ``theme`` object via ``onChange`` on
 * every user edit; the parent persists.
 *
 *   <ThemePanel value={form.theme} onChange={t => setForm({...form, theme: t})} />
 *
 * The panel exposes 5 curated presets, a "Customize" expand that
 * reveals hex pickers for each color role, and a font-family
 * dropdown backed by ``FORM_FONT_STACKS`` (system fonts only).
 */
export default function ThemePanel({ value, onChange }) {
  const theme = coerceTheme(value);
  const [expanded, setExpanded] = React.useState(theme.preset === "custom");

  const setPreset = (key) => {
    if (key === "custom") {
      onChange({ ...theme, preset: "custom" });
      setExpanded(true);
      return;
    }
    const p = presetByKey(key);
    onChange({
      preset: p.key,
      colors: { ...p.colors },
      font_family: fontStackById(p.font_family_id),
    });
  };

  const setColor = (role, hex) => onChange({
    ...theme,
    preset: "custom",
    colors: { ...theme.colors, [role]: hex },
  });

  const setFont = (stack) => onChange({ ...theme, font_family: stack });

  return (
    <div data-testid="form-theme-panel"
          className="rounded-lg border border-gray-200 p-4 space-y-4">
      <div className="text-sm font-semibold">Theme</div>

      {/* Preset picker — swatches */}
      <div className="grid grid-cols-3 gap-2" data-testid="theme-preset-grid">
        {FORM_THEME_PRESETS.map((p) => {
          const active = theme.preset === p.key;
          return (
            <button
              key={p.key}
              type="button"
              data-testid={`theme-preset-${p.key}`}
              onClick={() => setPreset(p.key)}
              className={
                "text-left rounded-md border p-2 transition "
                + (active
                  ? "border-blue-500 ring-2 ring-blue-200"
                  : "border-gray-200 hover:border-gray-300")
              }
              style={{ background: p.colors.background }}
            >
              <div className="flex gap-1 mb-1">
                {[p.colors.primary, p.colors.accent, p.colors.text,
                    p.colors.border].map((c, i) => (
                    <span key={i}
                          className="inline-block w-4 h-4 rounded-full border"
                          style={{ background: c, borderColor: p.colors.border }} />
                ))}
              </div>
              <div className="text-xs font-medium"
                    style={{ color: p.colors.text }}>{p.name}</div>
            </button>
          );
        })}
        <button
          type="button"
          data-testid="theme-preset-custom"
          onClick={() => setPreset("custom")}
          className={
            "text-left rounded-md border p-2 border-dashed "
            + (theme.preset === "custom"
              ? "border-blue-500 bg-blue-50"
              : "border-gray-300")
          }
        >
          <div className="text-xs font-medium">Custom…</div>
          <div className="text-[10px] text-gray-500">Pick your own colors</div>
        </button>
      </div>

      {/* Font family */}
      <label className="block text-sm">
        <span className="text-gray-700">Font family</span>
        <select
          data-testid="theme-font-select"
          value={FORM_FONT_STACKS.find(f => f.stack === theme.font_family)?.id
                  || ""}
          onChange={(e) => setFont(fontStackById(e.target.value))}
          className="mt-1 block w-full rounded-md border-gray-300"
        >
          {FORM_FONT_STACKS.map((f) => (
            <option key={f.id} value={f.id}>{f.label}</option>
          ))}
        </select>
      </label>

      {/* Customize expand — hex pickers */}
      <div>
        <button
          type="button"
          data-testid="theme-expand-toggle"
          onClick={() => setExpanded((x) => !x)}
          className="text-sm text-blue-600 hover:text-blue-700"
        >
          {expanded ? "Hide" : "Customize colors"}
        </button>
        {expanded && (
          <div className="mt-3 grid grid-cols-2 gap-3"
                data-testid="theme-color-pickers">
            {["primary","background","text","border","accent"].map((role) => (
              <label key={role} className="block text-xs">
                <span className="text-gray-600 capitalize">{role}</span>
                <div className="mt-1 flex items-center gap-2">
                  <input
                    type="color"
                    data-testid={`theme-color-${role}`}
                    value={theme.colors[role]}
                    onChange={(e) => setColor(role, e.target.value)}
                    className="h-8 w-10 rounded border border-gray-300"
                  />
                  <input
                    type="text"
                    value={theme.colors[role]}
                    onChange={(e) => setColor(role, e.target.value)}
                    className="flex-1 rounded-md border-gray-300 text-xs px-2 py-1"
                  />
                </div>
              </label>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
