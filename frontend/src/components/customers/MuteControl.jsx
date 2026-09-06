// Feb-2026 · P27 — Mute / Unmute a customer.
//
// * Mark Muted — visible to admin + super_admin. Modal warns the
//   operator that all marketing / autobilling / route optimization /
//   P18 lead alerts will be suppressed. Admin OR super_admin can
//   undo (see P27 addendum).
// * Unmute — visible to admin + super_admin on rows that are muted.
//
// Component renders a single pill button whose label + confirm-modal
// copy depend on the row's ``is_muted`` state.

import React, { useState, useCallback } from "react";
import { api } from "@/api";


export default function MuteControl({
  customer,
  canMute = true,     // admin || super_admin
  canUnmute = true,   // admin || super_admin (P27 addendum)
  onChange,           // (payload) => void
  onError,            // (message) => void
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  // Feb-2026 · P29 — reason picker state. Loaded lazily on modal open.
  const [reasons, setReasons] = useState([]);
  const [selectedReasonId, setSelectedReasonId] = useState("");
  const [customReason, setCustomReason] = useState("");
  const isMuted = Boolean(customer?.is_muted);

  const gated = isMuted ? !canUnmute : !canMute;
  const label = isMuted ? "Unmute" : "Mark Muted";
  const cid = customer.id;

  const stop = useCallback((e) => {
    e.stopPropagation();
    e.preventDefault();
  }, []);

  const openModal = useCallback((e) => {
    stop(e);
    if (gated || busy) return;
    setOpen(true);
    // Feb-2026 · P29 — lazily load the reason list only when the
    // operator opens the modal on the MUTE path. Unmute doesn't
    // need reasons. Silent-fail on network error — the picker just
    // renders with only the "Custom…" option available.
    if (!isMuted && reasons.length === 0) {
      api.get("/settings/muted-reasons").then((res) => {
        const rows = Array.isArray(res?.items) ? res.items : [];
        setReasons(rows);
      }).catch(() => { /* silent */ });
    }
  }, [gated, busy, stop, isMuted, reasons.length]);

  const closeModal = useCallback((e) => {
    if (e) stop(e);
    if (busy) return;
    setOpen(false);
  }, [busy, stop]);

  const confirm = useCallback(async (e) => {
    stop(e);
    setBusy(true);
    try {
      const path = isMuted ? "unmute" : "mute";
      // Feb-2026 · P29 — resolve reason: dropdown selection wins
      // unless "Custom" was chosen. Empty string / whitespace → null
      // (backend also trims + normalises).
      let body = {};
      if (!isMuted) {
        let reasonText = "";
        if (selectedReasonId === "__custom__") {
          reasonText = customReason.trim();
        } else if (selectedReasonId) {
          const r = reasons.find((x) => x.id === selectedReasonId);
          reasonText = r?.label || "";
        }
        if (reasonText) body = { muted_reason: reasonText.slice(0, 500) };
      }
      const res = await api.patch(`/customers/${cid}/${path}`, body);
      setOpen(false);
      setSelectedReasonId("");
      setCustomReason("");
      // Feb-2026 · P32 — after a successful mute, drop the cached
      // reason list so the next open re-fetches. This picks up any
      // reason auto-created server-side (see P32 auto-persist in
      // ``mute_customer``).
      if (!isMuted) setReasons([]);
      onChange?.(res);
    } catch (err) {
      onError?.(err?.message || `Failed to ${isMuted ? "unmute" : "mute"} customer`);
    } finally {
      setBusy(false);
    }
  }, [cid, isMuted, reasons, selectedReasonId, customReason, onChange, onError, stop]);

  if (gated) return null;

  return (
    <>
      <button
        type="button"
        onClick={openModal}
        disabled={busy}
        data-testid={`mute-control-btn-${cid}`}
        className="text-xs font-semibold px-2 py-1 rounded border transition"
        style={{
          borderColor: isMuted ? "#0EA5E9" : "#DC2626",
          color: isMuted ? "#0EA5E9" : "#DC2626",
          background: "transparent",
          opacity: busy ? 0.5 : 1,
        }}
      >
        {busy ? (isMuted ? "Unmuting…" : "Muting…") : label}
      </button>

      {open ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center"
          style={{ background: "rgba(15, 23, 42, 0.55)" }}
          onClick={closeModal}
          data-testid={`mute-control-modal-${cid}`}
        >
          <div
            className="max-w-md w-full mx-4 rounded-lg shadow-xl p-6"
            style={{ background: "#fff" }}
            onClick={stop}
          >
            <h2
              className="text-lg font-bold mb-2"
              style={{ color: isMuted ? "#0F172A" : "#7F1D1D" }}
            >
              {isMuted ? "Unmute this customer?" : "Mute this customer?"}
            </h2>

            {isMuted ? (
              <p className="text-sm mb-3" style={{ color: "#334155" }}>
                They&apos;ll return to normal activity: marketing,
                autobilling, and route optimization will resume.
              </p>
            ) : (
              <>
                <div
                  className="text-sm mb-3 p-3 rounded border"
                  style={{
                    borderColor: "#FCA5A5",
                    background: "rgba(220, 38, 38, 0.06)",
                    color: "#7F1D1D",
                  }}
                  data-testid={`mute-control-warning-${cid}`}
                >
                  <b>Silent-mode warning.</b> Muting this customer stops
                  all marketing, reactivation, autobilling, and lead
                  alerts from their contact info. Only an admin or
                  super_admin can undo this.
                </div>
                {/* Feb-2026 · P29 — optional reason picker. */}
                <div className="text-sm mb-2" style={{ color: "#334155" }}>
                  Reason (optional)
                </div>
                <select
                  value={selectedReasonId}
                  onChange={(e) => setSelectedReasonId(e.target.value)}
                  data-testid={`mute-control-reason-select-${cid}`}
                  className="w-full text-sm px-3 py-2 rounded border mb-2"
                  style={{ borderColor: "#E5E7EB", background: "#fff" }}
                >
                  <option value="">— No reason —</option>
                  {reasons.map((r) => (
                    <option key={r.id} value={r.id}>{r.label}</option>
                  ))}
                  <option value="__custom__">Custom…</option>
                </select>
                {selectedReasonId === "__custom__" ? (
                  <input
                    type="text"
                    maxLength={500}
                    placeholder="Type a reason (max 500 chars)…"
                    value={customReason}
                    onChange={(e) => setCustomReason(e.target.value)}
                    data-testid={`mute-control-reason-custom-${cid}`}
                    className="w-full text-sm px-3 py-2 rounded border mb-2"
                    style={{ borderColor: "#E5E7EB", background: "#fff" }}
                  />
                ) : null}
              </>
            )}

            <div className="flex items-center justify-end gap-2 mt-4">
              <button
                type="button"
                onClick={closeModal}
                disabled={busy}
                data-testid={`mute-control-cancel-${cid}`}
                className="px-3 py-2 text-sm font-semibold rounded border"
                style={{
                  borderColor: "#E5E7EB", color: "#334155",
                  background: "#fff",
                }}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={confirm}
                disabled={busy}
                data-testid={`mute-control-confirm-${cid}`}
                className="px-3 py-2 text-sm font-semibold rounded"
                style={{
                  background: isMuted ? "#0EA5E9" : "#DC2626",
                  color: "#fff",
                  opacity: busy ? 0.6 : 1,
                }}
              >
                {busy
                  ? (isMuted ? "Unmuting…" : "Muting…")
                  : (isMuted ? "Yes, unmute" : "Yes, mute")}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
