/**
 * Phase F3 · Feb-2026 — Soshie Publishing Dashboard Tile.
 *
 * At-a-glance summary of today's Soshie autopilot queue: scheduled /
 * published / flagged / blocked / failed counts + the next 3 posts.
 * Clicking through opens the moderation queue.
 *
 * Refreshes every 60 seconds (mirrors the DataIntegrityTile cadence).
 */
import React, { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  Instagram, Facebook, Globe, MessageSquare,
  Video, Sparkles, ArrowRight, RefreshCw,
} from "lucide-react";
import { api } from "../../api";
import { colors } from "../../theme";

const PLATFORM_ICON = {
  facebook: Facebook,
  instagram: Instagram,
  tiktok: Video,
  gbp: Globe,
  wordpress: Globe,
  reddit: MessageSquare,
};

function _fmtTime(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleTimeString(undefined, {
      hour: "numeric", minute: "2-digit",
    });
  } catch { return "—"; }
}

function CountCell({ label, value, tone, testid }) {
  const fg =
    tone === "danger" ? colors.error :
    tone === "warn"   ? "#B45309" :
    tone === "ok"     ? colors.success :
                        colors.onSurface;
  return (
    <div
      className="rounded-lg px-3 py-2"
      style={{ background: colors.surfaceSecondary,
               border: `1px solid ${colors.border}` }}
      data-testid={testid}
    >
      <div className="text-[10px] font-bold uppercase tracking-wider"
           style={{ color: colors.muted }}>
        {label}
      </div>
      <div className="text-lg font-bold mt-0.5" style={{ color: fg }}>
        {value ?? 0}
      </div>
    </div>
  );
}

export default function SoshiePublishingTile() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    setLoading(true); setErr("");
    try {
      const res = await api.get("/soshie/publishing/today-summary");
      setData(res || null);
    } catch (e) {
      setErr(e?.message || "Failed to load");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const int = setInterval(load, 60_000);
    return () => clearInterval(int);
  }, [load]);

  const flagged = data?.flagged || 0;
  const blocked = data?.blocked || 0;
  const failed = data?.failed || 0;
  const attention = flagged > 0 || blocked > 0 || failed > 0;

  return (
    <section
      className="rounded-2xl p-4"
      style={{ background: colors.surface,
               border: `1px solid ${colors.border}` }}
      data-testid="soshie-publishing-tile"
    >
      <header className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Sparkles size={16} style={{ color: colors.brand }} />
          <h3 className="text-sm font-bold"
              style={{ color: colors.onSurface }}
              data-testid="soshie-publishing-tile-title">
            Soshie Publishing (Today)
          </h3>
          {attention ? (
            <span
              className="ml-1 px-1.5 py-0.5 rounded-md text-[10px] font-bold uppercase"
              style={{ background: "#FEF3C7", color: "#78350F",
                       border: "1px solid #FDE68A" }}
              data-testid="soshie-publishing-tile-attention"
            >
              Attention
            </span>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={load}
            aria-label="Refresh"
            className="p-1 rounded-md"
            style={{ color: colors.muted,
                     background: "transparent" }}
            data-testid="soshie-publishing-tile-refresh"
          >
            <RefreshCw size={12}
                       style={{ opacity: loading ? 0.4 : 1 }} />
          </button>
          <Link
            to="/admin/soshie/moderation"
            className="inline-flex items-center gap-1 text-xs font-semibold"
            style={{ color: colors.brand }}
            data-testid="soshie-publishing-tile-link"
          >
            Moderation queue <ArrowRight size={11} />
          </Link>
        </div>
      </header>

      {err ? (
        <div className="p-3 text-sm rounded-lg"
             style={{ background: "#FEE2E2", color: colors.error,
                      border: "1px solid #FCA5A5" }}
             data-testid="soshie-publishing-tile-error">
          {err}
        </div>
      ) : null}

      <div className="grid grid-cols-2 sm:grid-cols-5 gap-2"
           data-testid="soshie-publishing-tile-counts">
        <CountCell label="Scheduled" value={data?.scheduled}
                   testid="soshie-publishing-tile-scheduled" />
        <CountCell label="Published" value={data?.published} tone="ok"
                   testid="soshie-publishing-tile-published" />
        <CountCell label="Flagged"   value={flagged}
                   tone={flagged ? "warn" : undefined}
                   testid="soshie-publishing-tile-flagged" />
        <CountCell label="Blocked"   value={blocked}
                   tone={blocked ? "danger" : undefined}
                   testid="soshie-publishing-tile-blocked" />
        <CountCell label="Failed"    value={failed}
                   tone={failed ? "danger" : undefined}
                   testid="soshie-publishing-tile-failed" />
      </div>

      {(data?.next_up || []).length > 0 ? (
        <div className="mt-4">
          <div className="text-[10px] font-bold uppercase tracking-wider mb-2"
               style={{ color: colors.muted }}>
            Next up
          </div>
          <ul className="flex flex-col gap-1"
              data-testid="soshie-publishing-tile-next">
            {(data.next_up || []).slice(0, 3).map((n) => {
              const Icon = PLATFORM_ICON[(n.platform || "").toLowerCase()]
                        || Sparkles;
              return (
                <li key={n.post_id}
                    className="flex items-center gap-2 text-xs"
                    style={{ color: colors.onSurface }}
                    data-testid={`soshie-publishing-tile-next-${n.post_id}`}>
                  <Icon size={12} style={{ color: colors.muted }} />
                  <span className="font-semibold w-20 shrink-0">
                    {_fmtTime(n.scheduled_at)}
                  </span>
                  <span className="uppercase text-[10px] font-bold w-16 shrink-0"
                        style={{ color: colors.muted }}>
                    {n.platform || "?"}
                  </span>
                  <span className="truncate flex-1"
                        style={{ color: colors.onSurface }}>
                    {n.preview || "(no preview)"}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
