/**
 * Phase 15 · Feb-2026 — Broadcasts list + drill-in.
 *
 * Route: /marketing/broadcasts (admin only).  Displays every past
 * ``mass_messaging_batches`` row for the tenant with sent / failed /
 * suppressed / no-contact counts.  Selecting a row expands the
 * per-recipient ``marketing_deliveries`` list below.
 */
import React, { useEffect, useState } from "react";
import { Megaphone, RefreshCw, ChevronDown, ChevronRight } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import { Forbidden } from "@/hooks/usePermissions";
import { useAuth } from "@/auth";

function relTime(iso) {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return String(iso);
  const s = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  return `${d}d ago`;
}

function StatPill({ label, value, tone }) {
  const toneMap = {
    sent: { bg: "#DCFCE7", fg: "#166534" },
    failed: { bg: "#FEE2E2", fg: "#991B1B" },
    suppressed: { bg: "#FEF3C7", fg: "#92400E" },
    no_contact: { bg: "#E5E7EB", fg: "#374151" },
  };
  const t = toneMap[tone] || toneMap.no_contact;
  return (
    <span
      className="text-[11px] px-2 py-0.5 rounded-full font-semibold"
      style={{ background: t.bg, color: t.fg }}
      data-testid={`broadcast-stat-${tone}`}
    >
      {label}: {value}
    </span>
  );
}

function BatchRow({ batch, expanded, onToggle }) {
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!expanded || detail) return;
    setLoading(true);
    api.get(`/mass-messaging/batches/${batch.id}`)
      .then(setDetail)
      .catch(() => setDetail(null))
      .finally(() => setLoading(false));
  }, [expanded, batch.id, detail]);

  const s = batch.stats || {};
  return (
    <div
      style={{ borderBottom: `1px solid ${colors.border}` }}
      data-testid={`broadcast-row-${batch.id}`}
    >
      <button
        type="button"
        onClick={onToggle}
        className="w-full px-4 py-3 flex items-center gap-3 text-left"
        style={{ background: colors.surface, cursor: "pointer" }}
      >
        {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        <div className="flex-1 min-w-0">
          <div
            className="text-sm font-semibold"
            style={{ color: colors.onSurface }}
          >
            {batch.custom_subject || batch.template_id || "Broadcast"}
          </div>
          <div
            className="text-[11px] mt-0.5"
            style={{ color: colors.muted }}
          >
            {relTime(batch.started_at)}
            {" · channels "}{(batch.channels || []).join(" + ")}
            {" · status "}{batch.status}
          </div>
        </div>
        <div className="flex items-center gap-1.5 flex-wrap justify-end">
          <StatPill label="sent" value={s.sent || 0} tone="sent" />
          <StatPill label="failed" value={s.failed || 0} tone="failed" />
          <StatPill label="suppressed" value={s.suppressed || 0} tone="suppressed" />
          <StatPill label="no contact" value={s.no_contact || 0} tone="no_contact" />
        </div>
      </button>
      {expanded ? (
        <div
          className="px-4 py-3"
          style={{ background: colors.surfaceSecondary }}
        >
          {loading ? (
            <div className="text-xs" style={{ color: colors.muted }}>
              Loading recipients…
            </div>
          ) : detail?.deliveries?.items?.length ? (
            <div className="grid gap-1.5">
              <div
                className="text-[10px] font-bold uppercase mb-1"
                style={{ color: colors.muted }}
              >
                Recipients ({detail.deliveries.total})
              </div>
              {detail.deliveries.items.map((d) => (
                <div
                  key={d.id}
                  className="text-xs flex items-center gap-2 px-2 py-1 rounded"
                  style={{ background: colors.surface }}
                  data-testid={`broadcast-delivery-${d.id}`}
                >
                  <span
                    className="px-1.5 py-0.5 rounded font-semibold uppercase"
                    style={{
                      background: colors.brandTertiary,
                      color: colors.onBrandTertiary,
                      fontSize: 10,
                    }}
                  >
                    {d.channel}
                  </span>
                  <span style={{ color: colors.onSurface }} className="flex-1">
                    {d.recipient || "(no address)"}
                  </span>
                  <span
                    className="text-[11px] font-semibold"
                    style={{
                      color: d.delivery_status === "sent" ? "#166534"
                        : d.delivery_status === "failed" ? "#991B1B"
                        : colors.muted,
                    }}
                  >
                    {d.delivery_status}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-xs" style={{ color: colors.muted }}>
              No delivery rows yet.
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}

export default function BroadcastsPage() {
  const { user } = useAuth();
  const role = (user?.role || "").toLowerCase();
  const allowed = role === "admin" || role === "super_admin";

  const [batches, setBatches] = useState([]);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState(null);

  const load = () => {
    setLoading(true);
    api.get("/mass-messaging/batches")
      .then((r) => setBatches(r?.items || []))
      .catch(() => setBatches([]))
      .finally(() => setLoading(false));
  };

  useEffect(() => { if (allowed) load(); }, [allowed]);

  if (!allowed) return <Forbidden reason="Broadcasts are admin-only." />;

  return (
    <div
      className="p-4 md:p-6"
      style={{ background: colors.surfaceSecondary, minHeight: "100%" }}
      data-testid="broadcasts-page"
    >
      <div className="flex items-center gap-3 mb-4">
        <Megaphone size={22} color={colors.brand} />
        <div>
          <div
            className="text-xl font-bold"
            style={{ color: colors.onSurface }}
          >
            Broadcasts
          </div>
          <div className="text-xs" style={{ color: colors.muted }}>
            Past mass-messaging batches with sent, failed, suppressed, and
            no-contact counts.
          </div>
        </div>
        <div style={{ flex: 1 }} />
        <button
          type="button"
          onClick={load}
          className="inline-flex items-center gap-1 px-3 py-1.5 rounded-md text-sm font-semibold"
          style={{
            background: colors.surface,
            border: `1px solid ${colors.border}`,
            color: colors.onSurface,
            cursor: "pointer",
          }}
          data-testid="broadcasts-refresh-btn"
        >
          <RefreshCw size={14} /> Refresh
        </button>
      </div>

      <div
        className="rounded-lg overflow-hidden"
        style={{
          background: colors.surface,
          border: `1px solid ${colors.border}`,
        }}
        data-testid="broadcasts-list"
      >
        {loading && batches.length === 0 ? (
          <div className="p-8 text-sm text-center" style={{ color: colors.muted }}>
            Loading broadcasts…
          </div>
        ) : batches.length === 0 ? (
          <div className="p-8 text-sm text-center" style={{ color: colors.muted }}>
            No broadcasts yet. Use the "Compose" button on the Dashboard to send
            your first one.
          </div>
        ) : (
          batches.map((b) => (
            <BatchRow
              key={b.id}
              batch={b}
              expanded={expanded === b.id}
              onToggle={() => setExpanded((cur) => cur === b.id ? null : b.id)}
            />
          ))
        )}
      </div>
    </div>
  );
}
