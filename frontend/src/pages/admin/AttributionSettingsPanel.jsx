// Phase G5b · Feb-2026 — Attribution settings panel for GpsSettingsPage.
//
// Self-contained: fetches on mount, PATCH on save. Renders as a
// bordered card so it slots in below the existing GPS settings form
// without touching that form's state.
import React from "react";
import { toast } from "sonner";
import { Save, Loader2 } from "lucide-react";
import { api } from "@/api";

export default function AttributionSettingsPanel() {
  const [initial, setInitial] = React.useState(null);
  const [form, setForm] = React.useState(null);
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await api.get("/admin/gps/attribution/settings");
        if (cancelled) return;
        setInitial(r); setForm(r);
      } catch (e) {
        if (!cancelled) toast.error("Load failed", { description: e?.message });
      }
    })();
    return () => { cancelled = true; };
  }, []);

  if (!form) {
    return (
      <div className="bg-white border border-zinc-200 rounded-lg p-4 shadow-sm"
           data-testid="attr-settings-panel-loading">
        <div className="flex items-center gap-2 text-sm text-zinc-500">
          <Loader2 size={14} className="animate-spin" /> Loading attribution settings…
        </div>
      </div>
    );
  }

  const save = async () => {
    const n = parseInt(form.proximity_threshold_m, 10);
    if (!Number.isFinite(n) || n < 10 || n > 5000) {
      toast.error("Threshold must be 10–5000 m"); return;
    }
    setBusy(true);
    try {
      const r = await api.patch("/admin/gps/attribution/settings", {
        proximity_threshold_m: n,
        same_day_only: !!form.same_day_only,
        require_scheduled_status: !!form.require_scheduled_status,
      });
      setInitial(r); setForm(r);
      toast.success("Attribution settings saved");
    } catch (e) {
      toast.error("Save failed", { description: e?.message });
    } finally { setBusy(false); }
  };

  const dirty = initial && (
    Number(initial.proximity_threshold_m) !== Number(form.proximity_threshold_m)
    || Boolean(initial.same_day_only) !== Boolean(form.same_day_only)
    || Boolean(initial.require_scheduled_status)
        !== Boolean(form.require_scheduled_status));

  return (
    <div className="bg-white border border-zinc-200 rounded-lg p-4 shadow-sm space-y-3"
         data-testid="attr-settings-panel">
      <div>
        <h3 className="text-base font-semibold text-zinc-900">
          Stop → Job attribution (G5b)
        </h3>
        <p className="text-xs text-zinc-500 mt-1">
          Auto-links a technician's driver stop to the nearest scheduled
          job when the stop centroid falls inside the proximity radius.
        </p>
      </div>
      <label className="block text-sm">
        <div className="mb-1 text-zinc-700">Proximity threshold (metres)</div>
        <input type="number" min={10} max={5000}
          value={form.proximity_threshold_m ?? ""}
          onChange={(e) => setForm((f) => ({ ...f,
            proximity_threshold_m: e.target.value }))}
          className="w-32 px-3 py-2 border border-zinc-200 rounded text-sm"
          data-testid="attr-settings-threshold" />
        <span className="ml-2 text-xs text-zinc-500">10–5000 · default 100</span>
      </label>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={!!form.same_day_only}
          onChange={(e) => setForm((f) => ({ ...f,
            same_day_only: e.target.checked }))}
          data-testid="attr-settings-same-day" />
        Only attribute to jobs scheduled the same calendar day
      </label>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={!!form.require_scheduled_status}
          onChange={(e) => setForm((f) => ({ ...f,
            require_scheduled_status: e.target.checked }))}
          data-testid="attr-settings-req-status" />
        Only attribute to jobs in scheduled / assigned / in_progress /
        pending status
      </label>
      <div className="pt-2">
        <button type="button" onClick={save} disabled={busy || !dirty}
          className="inline-flex items-center gap-1 px-3 py-1.5 rounded bg-sky-600 text-white text-sm disabled:opacity-50"
          data-testid="attr-settings-save">
          <Save size={14} /> {busy ? "Saving…" : "Save"}
        </button>
      </div>
    </div>
  );
}
