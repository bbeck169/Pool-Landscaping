/**
 * Feb-2026 · P34 — Automation Quiet Hours settings page.
 *
 * Mirrors the muted-reasons settings page conventions. RBAC gating
 * (super_admin / admin / manager) is enforced at the route layer in
 * ``App.js`` via ``AdminOrManagerForQuietHours``; this component
 * assumes it's already inside the gate.
 *
 * Backend contract (see ``routers/quiet_hours_settings.py``):
 *   GET  /api/settings/quiet-hours   → { enabled, start, end,
 *                                          timezone, tenant_timezone }
 *   PATCH /api/settings/quiet-hours  → same shape as GET
 */
import React, { useCallback, useEffect, useState } from "react";
import { api } from "@/api";


export default function QuietHoursPage() {
  const [cfg, setCfg] = useState({
    enabled: false, start: "08:00", end: "20:00",
    timezone: "", tenant_timezone: "",
  });
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [ok, setOk] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setErr(""); setOk("");
    try {
      const res = await api.get("/settings/quiet-hours");
      setCfg({
        enabled: !!res?.enabled,
        start:   res?.start   || "08:00",
        end:     res?.end     || "20:00",
        timezone: res?.timezone || "",
        tenant_timezone: res?.tenant_timezone || "",
      });
    } catch (e) {
      setErr(e?.message || "Failed to load quiet-hours settings.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const save = useCallback(async () => {
    setErr(""); setOk(""); setBusy(true);
    try {
      const body = {
        enabled: cfg.enabled,
        start: cfg.start,
        end: cfg.end,
        // Empty string clears the override; otherwise send the value.
        timezone: cfg.timezone === cfg.tenant_timezone ? "" : cfg.timezone,
      };
      const res = await api.patch("/settings/quiet-hours", body);
      setCfg({
        enabled: !!res?.enabled,
        start:   res?.start   || "08:00",
        end:     res?.end     || "20:00",
        timezone: res?.timezone || "",
        tenant_timezone: res?.tenant_timezone || "",
      });
      setOk("Saved.");
    } catch (e) {
      const detail = e?.body?.detail?.message || e?.body?.detail
                        || e?.message || "Save failed.";
      setErr(typeof detail === "string" ? detail : "Save failed.");
    } finally {
      setBusy(false);
    }
  }, [cfg]);

  if (loading) {
    return (
      <div className="max-w-2xl mx-auto p-6" data-testid="quiet-hours-page-loading">
        Loading…
      </div>
    );
  }

  return (
    <div className="max-w-2xl mx-auto p-6" data-testid="quiet-hours-page">
      <h1 className="text-2xl font-bold mb-1" style={{ color: "#0F172A" }}>
        Automation Quiet Hours
      </h1>
      <p className="text-sm mb-6" style={{ color: "#64748B" }}>
        Messages generated outside these hours will queue and send when the
        window opens. Applies to SMS and email including transactional
        messages (receipts, appointment confirmations, password resets).
      </p>

      {/* Enabled toggle */}
      <label className="flex items-center gap-3 mb-4 cursor-pointer">
        <input
          type="checkbox"
          checked={cfg.enabled}
          onChange={(e) => setCfg((c) => ({ ...c, enabled: e.target.checked }))}
          data-testid="quiet-hours-enabled-toggle"
        />
        <span className="text-sm font-semibold" style={{ color: "#0F172A" }}>
          Enable quiet hours
        </span>
      </label>

      {/* Time inputs — greyed when disabled but still interactable so tests
          can drive them and future admins can prep the window before flipping. */}
      <div className="grid grid-cols-2 gap-3 mb-4"
            style={{ opacity: cfg.enabled ? 1 : 0.6 }}
            data-testid="quiet-hours-time-inputs">
        <label className="block">
          <span className="text-xs uppercase font-semibold block mb-1"
                  style={{ color: "#64748B" }}>Start</span>
          <input
            type="time"
            value={cfg.start}
            onChange={(e) => setCfg((c) => ({ ...c, start: e.target.value }))}
            data-testid="quiet-hours-start-input"
            className="w-full text-sm px-3 py-2 rounded border"
            style={{ borderColor: "#E5E7EB" }}
          />
        </label>
        <label className="block">
          <span className="text-xs uppercase font-semibold block mb-1"
                  style={{ color: "#64748B" }}>End</span>
          <input
            type="time"
            value={cfg.end}
            onChange={(e) => setCfg((c) => ({ ...c, end: e.target.value }))}
            data-testid="quiet-hours-end-input"
            className="w-full text-sm px-3 py-2 rounded border"
            style={{ borderColor: "#E5E7EB" }}
          />
        </label>
      </div>

      {/* Timezone override */}
      <label className="block mb-4">
        <span className="text-xs uppercase font-semibold block mb-1"
                style={{ color: "#64748B" }}>
          Timezone (defaults to {cfg.tenant_timezone || "tenant default"})
        </span>
        <input
          type="text"
          value={cfg.timezone}
          onChange={(e) => setCfg((c) => ({ ...c, timezone: e.target.value }))}
          placeholder="America/Phoenix"
          data-testid="quiet-hours-timezone-input"
          className="w-full text-sm px-3 py-2 rounded border"
          style={{ borderColor: "#E5E7EB" }}
        />
      </label>

      {err ? (
        <div className="text-sm mb-3 p-2 rounded"
              style={{ background: "rgba(220,38,38,0.06)", color: "#7F1D1D" }}
              data-testid="quiet-hours-error">
          {err}
        </div>
      ) : null}
      {ok ? (
        <div className="text-sm mb-3 p-2 rounded"
              style={{ background: "rgba(16,185,129,0.06)", color: "#065F46" }}
              data-testid="quiet-hours-ok">
          {ok}
        </div>
      ) : null}

      <button
        type="button"
        onClick={save}
        disabled={busy}
        data-testid="quiet-hours-save"
        className="px-4 py-2 text-sm font-semibold rounded"
        style={{ background: "#0EA5E9", color: "#fff",
                   opacity: busy ? 0.6 : 1 }}
      >
        {busy ? "Saving…" : "Save"}
      </button>
    </div>
  );
}
