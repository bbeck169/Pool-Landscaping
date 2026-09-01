/**
 * Phase S2 · Feb-2026 — Autopilot Schedules tab.
 *
 * Renders:
 *   * Global kill switch card (GET/PATCH /soshie/autopilot/global)
 *   * 8-platform grid (GET /soshie/autopilot/config, PATCH per row)
 *     + inline connection status (GET /soshie/platforms)
 *     + Reddit toggle DISABLED (manual-only badge + tooltip)
 *   * Recent autopilot actions feed
 *     (GET /soshie/autopilot/recent-actions)
 */
import React, { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import { CheckCircle2, Clock, XCircle,
           Info } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import { Skeleton, Chip } from "@/components/ui-kit";


const PLATFORM_LABELS = {
  gbp: "Google Business Profile",
  wordpress: "WordPress",
  facebook: "Facebook",
  instagram: "Instagram",
  linkedin: "LinkedIn",
  youtube: "YouTube",
  tiktok: "TikTok",
  reddit: "Reddit",
};


function Card({ children, className = "", testId }) {
  return (
    <div className={`rounded-2xl p-5 ${className}`}
         style={{ backgroundColor: colors.surface,
                    border: `1px solid ${colors.border}` }}
         data-testid={testId}>
      {children}
    </div>
  );
}


function StatusBadge({ status }) {
  // status: {ok: bool, detail: str, manual_only: bool}
  // Phase H5.5 · Feb-2026 — ``manual_only`` is now a first-class
  // status derived from the platform's autopilot_config row.
  // Previously this only fired for Reddit; the H5.5 flip put 5
  // more platforms (Facebook, Instagram, LinkedIn, YouTube,
  // TikTok, GBP) on the same rail so operators can enable a
  // draft-only autopilot flow without waiting on OAuth wiring.
  if (status?.manual_only) {
    return <Chip label="Manual Only" tone="warning"
                    testid="platform-badge-manual" />;
  }
  if (status?.ok) {
    return <Chip label="Connected" tone="success"
                    testid="platform-badge-connected" />;
  }
  const detail = status?.detail || "";
  if (detail.includes("Pending operator setup")
        || detail.includes("Coming Soon")) {
    return <Chip label="Coming Soon" tone="neutral"
                    testid="platform-badge-coming-soon" />;
  }
  return <Chip label="Not Connected" tone="neutral"
                  testid="platform-badge-not-connected" />;
}


function GlobalKillSwitch() {
  const [enabled, setEnabled] = useState(true);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get("/soshie/autopilot/global")
      .then((r) => { setEnabled(!!r?.enabled); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  const toggle = async () => {
    const next = !enabled;
    setEnabled(next);                                       // optimistic
    try {
      await api.patch("/soshie/autopilot/global",
                             { enabled: next });
      toast.success(next ? "Autopilot enabled tenant-wide"
                             : "Autopilot paused tenant-wide");
    } catch (e) {
      setEnabled(!next);                                    // revert
      toast.error(e?.message || "Failed to update autopilot state");
    }
  };

  if (loading) return <Skeleton className="h-24 rounded-2xl mb-4" />;
  return (
    <Card testId="global-kill-switch" className="mb-6">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-lg font-semibold"
                style={{ color: colors.onSurface }}>Autopilot</h2>
            {enabled ? (
              <Chip label="On" tone="success"
                       testid="global-status-on" />
            ) : (
              <Chip label="Paused" tone="danger"
                       testid="global-status-off" />
            )}
          </div>
          <p className="text-xs mt-1" style={{ color: colors.muted }}>
            Tenant-wide kill switch. When off, all platforms below
            are paused regardless of per-row settings.
          </p>
        </div>
        <button onClick={toggle}
                   data-testid="global-kill-switch-toggle"
                   aria-label="Toggle autopilot"
                   role="switch"
                   aria-checked={enabled}
                   className="relative inline-flex h-7 w-12 items-center rounded-full"
                   style={{
                     backgroundColor: enabled ? colors.brand : "#94a3b8",
                     transition: "background-color 0.15s",
                   }}>
          <span className="inline-block h-5 w-5 rounded-full bg-white"
                   style={{
                     transform: enabled ? "translateX(24px)"
                                            : "translateX(4px)",
                     transition: "transform 0.15s",
                   }} />
        </button>
      </div>
    </Card>
  );
}


function CadenceInput({ value, onSubmit, testid, disabled }) {
  const [v, setV] = useState(value ?? "");
  useEffect(() => { setV(value ?? ""); }, [value]);
  return (
    <input
      type="number"
      min={0} max={10}
      value={v}
      disabled={disabled}
      onChange={(e) => setV(e.target.value)}
      onBlur={(e) => {
        const n = e.target.value === "" ? null
                    : Math.max(0, Math.min(10, parseInt(e.target.value, 10) || 0));
        onSubmit(n);
      }}
      onKeyDown={(e) => { if (e.key === "Enter") e.target.blur(); }}
      className="w-16 px-2 py-1 rounded-md text-sm"
      style={{ backgroundColor: colors.surfaceSecondary,
                 border: `1px solid ${colors.border}`,
                 color: colors.onSurface,
                 opacity: disabled ? 0.5 : 1 }}
      data-testid={testid}
      aria-label="Cadence"
    />
  );
}


function PlatformRow({ cfg, status, onPatch }) {
  const platform = cfg.platform;
  // Phase H5.5 · Feb-2026 — Reddit remains hard-blocked at the UI
  // layer (S2 defence-in-depth + product decision not to automate
  // Reddit). The other 5 manual-only platforms (Facebook,
  // Instagram, LinkedIn, YouTube, TikTok, GBP) got their toggles
  // + cadence fields ENABLED so operators can queue drafts into
  // the manual review flow. Only the Reddit ``disabled`` guard
  // survives.
  const isReddit = platform === "reddit";
  const isDaily = platform === "gbp";
  const isManualOnly = !!cfg.manual_only;
  const [busy, setBusy] = useState(false);

  const patch = async (delta, revertKey, revertValue) => {
    setBusy(true);
    try {
      const next = await api.patch(
        `/soshie/autopilot/config/${platform}`, delta);
      onPatch(next);
    } catch (e) {
      onPatch({ ...cfg, [revertKey]: revertValue });        // revert
      toast.error(e?.message || `Failed to update ${platform}`);
    } finally {
      setBusy(false);
    }
  };

  const toggleEnabled = () => {
    if (isReddit) return;   // hard-blocked (S2)
    const prev = cfg.enabled;
    onPatch({ ...cfg, enabled: !prev });                    // optimistic
    patch({ enabled: !prev }, "enabled", prev);
  };

  return (
    <div
      className="rounded-xl p-4 flex flex-col md:flex-row md:items-center gap-3"
      style={{ backgroundColor: colors.surfaceSecondary,
                 border: `1px solid ${colors.border}` }}
      data-testid={`platform-row-${platform}`}
    >
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-semibold"
                   style={{ color: colors.onSurface }}
                   data-testid={`platform-name-${platform}`}>
            {PLATFORM_LABELS[platform] || platform}
          </span>
          <StatusBadge status={{
            ...status,
            manual_only: isManualOnly,
          }} />
        </div>
        <div className="text-xs mt-1"
                style={{ color: colors.muted }}
                data-testid={`platform-timezone-${platform}`}>
          {cfg.timezone || "America/Phoenix"}
        </div>
      </div>
      <div className="flex items-center gap-3">
        <label className="flex items-center gap-1 text-xs"
                    style={{ color: colors.muted }}>
          {isDaily ? "per day" : "per week"}
          <CadenceInput
            value={isDaily ? cfg.posts_per_day : cfg.posts_per_week}
            disabled={isReddit || busy}
            onSubmit={(n) => {
              const key = isDaily ? "posts_per_day"
                                       : "posts_per_week";
              const prev = cfg[key];
              onPatch({ ...cfg, [key]: n });
              patch({ [key]: n }, key, prev);
            }}
            testid={`platform-cadence-${platform}`}
          />
        </label>
        <button
          onClick={toggleEnabled}
          disabled={isReddit || busy}
          data-testid={`platform-toggle-${platform}`}
          role="switch"
          aria-checked={!!cfg.enabled}
          aria-label={`Toggle ${platform} autopilot`}
          title={isReddit
            ? "Manual only — Reddit does not allow autopilot publishing"
            : (isManualOnly
                ? "Manual Only — drafts land in the review queue for hand-paste"
                : "")}
          className="relative inline-flex h-6 w-11 items-center rounded-full"
          style={{
            backgroundColor: cfg.enabled ? colors.brand : "#94a3b8",
            opacity: isReddit ? 0.5 : 1,
            cursor: isReddit ? "not-allowed" : "pointer",
            transition: "background-color 0.15s",
          }}>
          <span className="inline-block h-4 w-4 rounded-full bg-white"
                   style={{
                     transform: cfg.enabled ? "translateX(24px)"
                                                 : "translateX(4px)",
                     transition: "transform 0.15s",
                   }} />
        </button>
      </div>
    </div>
  );
}


function RecentActionsFeed() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get("/soshie/autopilot/recent-actions?limit=20")
      .then((r) => { setRows(r?.items || []); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  if (loading) return <Skeleton className="h-32 rounded-2xl" />;
  return (
    <Card testId="autopilot-recent-actions">
      <h3 className="text-sm font-semibold mb-3"
          style={{ color: colors.onSurface }}>
        Recent autopilot activity
      </h3>
      {!rows.length ? (
        <p className="text-sm" style={{ color: colors.muted }}
              data-testid="autopilot-recent-empty">
          Nothing yet. Once autopilot fires, you'll see the last 20 dispatches here.
        </p>
      ) : (
        <ul className="space-y-2" data-testid="autopilot-recent-list">
          {rows.map((r) => {
            const kind = r.result?.kind || r.status;
            const icon = kind === "soshie_autopilot_published"
              ? <CheckCircle2 size={14}
                                 style={{ color: colors.success }} />
              : kind === "soshie_autopilot_failed"
                ? <XCircle size={14}
                              style={{ color: colors.error }} />
                : <Clock size={14}
                            style={{ color: colors.muted }} />;
            return (
              <li key={r.id}
                    className="flex items-start gap-2 text-sm"
                    data-testid={`autopilot-action-${r.id}`}>
                {icon}
                <div className="flex-1 min-w-0">
                  <div style={{ color: colors.onSurface }}>
                    <span className="font-medium">
                      {r.action}
                    </span>
                    {" — "}
                    <span style={{ color: colors.muted }}>
                      {kind}
                    </span>
                  </div>
                  <div className="text-xs"
                          style={{ color: colors.muted }}>
                    {r.updated_at
                      ? new Date(r.updated_at).toLocaleString()
                      : ""}
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}


export default function AutopilotSchedulesTab() {
  const [configs, setConfigs] = useState([]);
  const [platforms, setPlatforms] = useState({});
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [cfg, plat] = await Promise.all([
        api.get("/soshie/autopilot/config"),
        api.get("/soshie/platforms"),
      ]);
      setConfigs(cfg?.items || []);
      const byName = {};
      for (const p of (plat?.platforms || [])) {
        byName[p.platform] = p;
      }
      setPlatforms(byName);
    } catch (e) {
      toast.error(e?.message || "Couldn't load autopilot schedules");
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const patchRow = (next) => {
    setConfigs((rows) => rows.map((r) => (
      r.platform === next.platform ? { ...r, ...next } : r
    )));
  };

  return (
    <div data-testid="autopilot-schedules">
      <GlobalKillSwitch />

      <Card testId="autopilot-platform-grid" className="mb-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-lg font-semibold"
                style={{ color: colors.onSurface }}>Platforms</h2>
            <p className="text-xs mt-1" style={{ color: colors.muted }}>
              Per-platform cadence + connection status. Changes save
              inline.
            </p>
          </div>
          <Info size={16} style={{ color: colors.muted }} />
        </div>
        {loading ? (
          <div className="space-y-2" data-testid="autopilot-loading">
            <Skeleton className="h-16 rounded-xl" />
            <Skeleton className="h-16 rounded-xl" />
            <Skeleton className="h-16 rounded-xl" />
          </div>
        ) : (
          <div className="space-y-2">
            {configs.map((cfg) => (
              <PlatformRow key={cfg.platform}
                             cfg={cfg}
                             status={platforms[cfg.platform]}
                             onPatch={patchRow} />
            ))}
            {!configs.length ? (
              <p className="text-sm" style={{ color: colors.muted }}
                    data-testid="autopilot-empty">
                No autopilot config yet — refreshing…
              </p>
            ) : null}
          </div>
        )}
      </Card>

      <RecentActionsFeed />
    </div>
  );
}
