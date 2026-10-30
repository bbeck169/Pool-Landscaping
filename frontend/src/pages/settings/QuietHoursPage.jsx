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

      {/* Phase 2 UX — queued-message viewer + per-row cancel +
          release-now. Lives inside the same page so admins get a
          one-stop surface for everything quiet-hours. */}
      <QuietHoursQueueSection />
    </div>
  );
}


function _fmtAbs(iso) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString(); } catch { return iso; }
}


function _fmtRel(iso) {
  if (!iso) return "";
  try {
    const diffMs = new Date(iso).getTime() - Date.now();
    const absMin = Math.round(Math.abs(diffMs) / 60000);
    if (absMin < 1) return "any moment";
    if (absMin < 60) return `in ${absMin} min`;
    const h = Math.round(absMin / 60);
    if (h < 24) return `in ${h} h`;
    const d = Math.round(h / 24);
    return `in ${d} d`;
  } catch {
    return "";
  }
}


export function QuietHoursQueueSection() {
  const [state, setState] = useState({ loading: true });
  const [confirmFlush, setConfirmFlush] = useState(false);
  const [busy, setBusy] = useState(false);
  const [actionErr, setActionErr] = useState("");

  const load = useCallback(async () => {
    setState({ loading: true });
    try {
      const res = await api.get("/quiet-hours/queue");
      setState({ loading: false, data: res });
    } catch (e) {
      setState({ loading: false, error: e?.message || "Load failed." });
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const onCancel = useCallback(async (rowId) => {
    setActionErr(""); setBusy(true);
    try {
      await api.delete(`/quiet-hours/queue/${encodeURIComponent(rowId)}`);
      await load();
    } catch (e) {
      setActionErr(e?.message || "Cancel failed.");
    } finally {
      setBusy(false);
    }
  }, [load]);

  const onFlush = useCallback(async () => {
    setActionErr(""); setBusy(true);
    try {
      await api.post("/quiet-hours/queue/release-now", {});
      setConfirmFlush(false);
      await load();
    } catch (e) {
      setActionErr(e?.message || "Release-now failed.");
    } finally {
      setBusy(false);
    }
  }, [load]);

  const d = state.data || {};
  const items = d.items || [];
  const count = typeof d.count === "number" ? d.count : items.length;

  return (
    <section
      className="mt-8 pt-6 border-t"
      style={{ borderColor: "#E5E7EB" }}
      data-testid="quiet-hours-queue-section"
    >
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-lg font-bold" style={{ color: "#0F172A" }}>
          Queued messages
        </h2>
        {count > 0 ? (
          <button
            type="button"
            onClick={() => setConfirmFlush(true)}
            disabled={busy}
            data-testid="quiet-hours-release-now-btn"
            className="text-xs font-semibold px-3 py-1.5 rounded"
            style={{
              background: "#0EA5E9", color: "#fff",
              opacity: busy ? 0.6 : 1,
            }}
          >
            Release all now
          </button>
        ) : null}
      </div>

      {state.loading ? (
        <div data-testid="quiet-hours-queue-loading"
             style={{ color: "#64748B" }}>
          Loading queue…
        </div>
      ) : null}

      {state.error && !state.loading ? (
        <div
          data-testid="quiet-hours-queue-error"
          className="text-sm p-2 rounded"
          style={{
            background: "rgba(220,38,38,0.06)", color: "#7F1D1D",
          }}
        >
          {state.error}
        </div>
      ) : null}

      {!state.loading && !state.error && count === 0 ? (
        <div
          data-testid="quiet-hours-queue-empty"
          className="text-sm p-4 rounded border border-dashed text-center"
          style={{ borderColor: "#E5E7EB", color: "#64748B" }}
        >
          Nothing queued right now.
        </div>
      ) : null}

      {!state.loading && !state.error && count > 0 ? (
        <>
          <div
            className="text-xs mb-3"
            style={{ color: "#64748B" }}
            data-testid="quiet-hours-queue-summary"
          >
            {count.toLocaleString()} pending ·{" "}
            next release {_fmtRel(d.next_release_at)}
            {" "}({_fmtAbs(d.next_release_at)})
          </div>
          {actionErr ? (
            <div
              className="text-sm mb-3 p-2 rounded"
              style={{
                background: "rgba(220,38,38,0.06)",
                color: "#7F1D1D",
              }}
              data-testid="quiet-hours-queue-action-error"
            >
              {actionErr}
            </div>
          ) : null}
          <ul className="divide-y" style={{ borderColor: "#E5E7EB" }}>
            {items.map((it) => (
              <li
                key={it.id}
                className="py-2 flex items-center gap-3 text-sm"
                data-testid={`quiet-hours-queue-row-${it.id}`}
              >
                <span
                  className="uppercase text-xs font-semibold px-2 py-0.5 rounded"
                  style={{
                    background: it.channel === "email"
                      ? "rgba(14,165,233,0.1)" : "rgba(16,185,129,0.1)",
                    color: it.channel === "email" ? "#0369A1" : "#065F46",
                  }}
                >
                  {it.channel}
                </span>
                <span className="flex-1 truncate"
                      style={{ color: "#0F172A" }}>
                  <span className="font-medium">{it.recipient || "—"}</span>
                  {it.subject ? (
                    <>
                      {" · "}
                      <span style={{ color: "#64748B" }}>{it.subject}</span>
                    </>
                  ) : null}
                </span>
                <span className="text-xs"
                      style={{ color: "#64748B" }}>
                  {_fmtAbs(it.scheduled_release_at)}
                </span>
                <button
                  type="button"
                  onClick={() => onCancel(it.id)}
                  disabled={busy}
                  data-testid={`quiet-hours-queue-cancel-${it.id}`}
                  className="text-xs font-semibold px-2 py-1 rounded"
                  style={{
                    background: "rgba(220,38,38,0.08)",
                    color: "#7F1D1D",
                    opacity: busy ? 0.6 : 1,
                  }}
                >
                  Cancel
                </button>
              </li>
            ))}
          </ul>
        </>
      ) : null}

      {confirmFlush ? (
        <div
          data-testid="quiet-hours-release-now-confirm"
          className="mt-4 p-4 rounded border"
          style={{ borderColor: "#F59E0B",
                   background: "rgba(245,158,11,0.06)" }}
        >
          <div className="text-sm mb-3" style={{ color: "#92400E" }}>
            Release every pending message right now? This bypasses
            the quiet-hours window for the current queue.
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={onFlush}
              disabled={busy}
              data-testid="quiet-hours-release-now-confirm-btn"
              className="text-xs font-semibold px-3 py-1.5 rounded"
              style={{
                background: "#F59E0B", color: "#fff",
                opacity: busy ? 0.6 : 1,
              }}
            >
              Yes, release all
            </button>
            <button
              type="button"
              onClick={() => setConfirmFlush(false)}
              disabled={busy}
              data-testid="quiet-hours-release-now-cancel-btn"
              className="text-xs font-semibold px-3 py-1.5 rounded"
              style={{
                background: "#E5E7EB", color: "#0F172A",
                opacity: busy ? 0.6 : 1,
              }}
            >
              Not now
            </button>
          </div>
        </div>
      ) : null}
    </section>
  );
}
