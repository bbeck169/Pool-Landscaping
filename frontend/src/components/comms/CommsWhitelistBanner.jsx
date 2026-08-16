/**
 * Queue Item 4 · Feb-2026 — Comms Whitelist status banner.
 *
 * Reads GET /api/comms/whitelist/status and renders a red safety
 * banner communicating that outbound communications are currently
 * demo-only. Shows live counts of:
 *   • Users flagged is_demo_account
 *   • Customers flagged is_demo_account
 *   • Comms suppressed in the last 24h
 *
 * Fails silently on network error — the banner is informational
 * and the underlying comms gate is fail-closed on the backend, so
 * an inability to fetch the status is not a data-loss surface.
 */
import React, { useEffect, useState } from "react";
import { ShieldAlert } from "lucide-react";
import { api } from "@/api";

export default function CommsWhitelistBanner() {
  const [status, setStatus] = useState(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api.get("/comms/whitelist/status")
      .then((r) => { if (!cancelled) setStatus(r || {}); })
      .catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; };
  }, []);

  if (failed || !status?.whitelist_active) return null;

  return (
    <div
      className="rounded-xl p-4 mb-4"
      style={{
        backgroundColor: "#FEF2F2",
        border: "1px solid #FECACA",
        color: "#991B1B",
      }}
      data-testid="comms-whitelist-banner"
      role="alert"
    >
      <div className="flex items-start gap-3">
        <ShieldAlert
          size={18}
          style={{ marginTop: 2, color: "#B91C1C" }}
          aria-hidden="true"
        />
        <div className="flex-1">
          <div className="font-bold text-sm">
            Outbound communications are gated (demo-only mode).
          </div>
          <p className="text-xs mt-1" style={{ color: "#7F1D1D" }}>
            Emails and SMS only send to recipients explicitly flagged{" "}
            <b>is_demo_account = true</b>. Everything else is
            suppressed and audit-logged.
          </p>
          <div
            className="mt-3 flex flex-wrap items-center gap-2"
            data-testid="comms-whitelist-banner-counts"
          >
            <Chip
              label="Users flagged demo"
              value={status.users_flagged_demo}
              testid="comms-whitelist-users-count"
            />
            <Chip
              label="Customers flagged demo"
              value={status.customers_flagged_demo}
              testid="comms-whitelist-customers-count"
            />
            <Chip
              label="Suppressed last 24h"
              value={status.suppressed_last_24h}
              testid="comms-whitelist-suppressed-count"
              danger
            />
          </div>
        </div>
      </div>
    </div>
  );
}

function Chip({ label, value, testid, danger }) {
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold"
      style={{
        backgroundColor: danger ? "#FEE2E2" : "#FFF",
        border: `1px solid ${danger ? "#FCA5A5" : "#FECACA"}`,
        color: danger ? "#7F1D1D" : "#991B1B",
      }}
      data-testid={testid}
    >
      {label}
      <span
        className="rounded px-1.5 py-0.5 font-bold"
        style={{
          backgroundColor: danger ? "#B91C1C" : "#F87171",
          color: "#FFF",
        }}
      >
        {typeof value === "number" ? value : 0}
      </span>
    </span>
  );
}
