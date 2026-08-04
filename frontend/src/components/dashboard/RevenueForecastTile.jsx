/**
 * Revenue Forecast tile · Feb-2026.
 *
 * Two-stat card: Booked jobs + Recurring subscriptions.  Combined
 * total is the prominent stat; a small caption underneath breaks down
 * "X booked jobs + Y active subscriptions × N cycles".
 *
 * Feb-2026 update — inline quick-view tabs (Today · Tomorrow · This
 * Week) live below the hero. Clicking a tab fires a second, tile-local
 * fetch and shows a small stat, WITHOUT mutating the shared range
 * filter that drives the hero number.
 */
import React, { useEffect, useMemo, useState } from "react";
import { CalendarClock, RefreshCw, Loader2 } from "lucide-react";
import { colors, money } from "@/theme";
import { api } from "@/api";
import { Skeleton } from "@/components/ui-kit";

// ────────────────────────────────────────────────────────────────
// Date-range helpers · local time.
// ────────────────────────────────────────────────────────────────
function isoDay(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function startOfDay(d) {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  return x;
}

function todayRange() {
  const s = startOfDay(new Date());
  return { start: isoDay(s), end: isoDay(s) };
}

function tomorrowRange() {
  const s = startOfDay(new Date());
  s.setDate(s.getDate() + 1);
  return { start: isoDay(s), end: isoDay(s) };
}

function thisWeekRange() {
  // Week = current Sunday → Saturday (US pool-service industry default).
  const now = startOfDay(new Date());
  const dow = now.getDay(); // 0 = Sunday
  const sunday = new Date(now);
  sunday.setDate(now.getDate() - dow);
  const saturday = new Date(sunday);
  saturday.setDate(sunday.getDate() + 6);
  return { start: isoDay(sunday), end: isoDay(saturday) };
}

const TABS = [
  { key: "today", label: "Today", build: todayRange },
  { key: "tomorrow", label: "Tomorrow", build: tomorrowRange },
  { key: "week", label: "This Week", build: thisWeekRange },
];

export default function RevenueForecastTile({ range }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");

  // Hero fetch — driven by the shared range filter above.
  useEffect(() => {
    if (!range?.start || !range?.end) return;
    setData(null);
    setErr("");
    api
      .get(
        `/admin/dashboard/revenue-forecast?start=${range.start}&end=${range.end}`,
      )
      .then(setData)
      .catch((e) => setErr(e?.message || "Failed to load."));
  }, [range?.start, range?.end]);

  // Tile-local tab state — does NOT propagate to the shared filter.
  const [activeTab, setActiveTab] = useState(null);
  const [tabData, setTabData] = useState(null);
  const [tabBusy, setTabBusy] = useState(false);
  const [tabErr, setTabErr] = useState("");

  const activeRange = useMemo(() => {
    if (!activeTab) return null;
    const t = TABS.find((x) => x.key === activeTab);
    return t ? t.build() : null;
  }, [activeTab]);

  useEffect(() => {
    if (!activeRange) {
      setTabData(null);
      setTabErr("");
      return;
    }
    setTabBusy(true);
    setTabErr("");
    setTabData(null);
    api
      .get(
        `/admin/dashboard/revenue-forecast?start=${activeRange.start}&end=${activeRange.end}`,
      )
      .then((r) => setTabData(r))
      .catch((e) => setTabErr(e?.message || "Failed to load."))
      .finally(() => setTabBusy(false));
  }, [activeRange?.start, activeRange?.end]); // eslint-disable-line react-hooks/exhaustive-deps -- Phase 41.3: deps 'activeRange' intentionally omitted (mount-only or stable-ref)

  const onTabClick = (key) => {
    setActiveTab((cur) => (cur === key ? null : key));
  };

  const chip = (label, value, colorHex, testid) => (
    <div
      className="rounded-xl px-3 py-2 flex-1"
      style={{
        background: colorHex + "12",
        border: `1px solid ${colorHex}30`,
      }}
      data-testid={testid}
    >
      <div
        className="text-xs uppercase font-bold tracking-wide"
        style={{ color: colorHex }}
      >
        {label}
      </div>
      <div
        className="text-lg font-bold mt-0.5"
        style={{ color: colors.onSurface }}
      >
        {value}
      </div>
    </div>
  );

  return (
    <div
      className="rounded-2xl p-5"
      style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
      data-testid="revenue-forecast-tile"
    >
      <div
        className="text-xs uppercase font-bold tracking-wide mb-3"
        style={{ color: colors.muted }}
      >
        Revenue Forecast
      </div>

      {err ? (
        <div
          className="rounded-xl p-3 text-sm"
          style={{ background: "#FEE2E2", color: "#7F1D1D" }}
          data-testid="revenue-forecast-error"
        >
          {err}
        </div>
      ) : data === null ? (
        <Skeleton
          className="h-32 rounded-xl"
          data-testid="revenue-forecast-loading"
        />
      ) : (
        <>
          <div className="mb-4">
            <div className="flex items-baseline gap-2">
              <div
                className="text-3xl font-black"
                style={{ color: colors.onSurface }}
                data-testid="revenue-forecast-combined"
              >
                {money(data.combined_total)}
              </div>
              <div className="text-xs" style={{ color: colors.muted }}>
                projected in range
              </div>
            </div>
          </div>
          <div className="flex flex-col sm:flex-row gap-2 mb-3">
            {chip(
              <span className="inline-flex items-center gap-1">
                <CalendarClock size={11} /> Booked
              </span>,
              money(data.booked.amount),
              "#0891B2",
              "revenue-forecast-booked",
            )}
            {chip(
              <span className="inline-flex items-center gap-1">
                <RefreshCw size={11} /> Recurring
              </span>,
              money(data.recurring.amount),
              "#7C3AED",
              "revenue-forecast-recurring",
            )}
          </div>
          <div
            className="text-xs"
            style={{ color: colors.muted }}
            data-testid="revenue-forecast-caption"
          >
            Based on {data.booked.job_count} booked job
            {data.booked.job_count === 1 ? "" : "s"} +{" "}
            {data.recurring.subscription_count} active subscription
            {data.recurring.subscription_count === 1 ? "" : "s"} across{" "}
            {data.recurring.cycle_count} billing cycle
            {data.recurring.cycle_count === 1 ? "" : "s"}.
          </div>

          {/* ── Quick-view tabs (tile-local, do not affect shared range) ── */}
          <div
            className="mt-4 pt-3"
            style={{ borderTop: `1px dashed ${colors.border}` }}
            data-testid="revenue-forecast-quick-view"
          >
            <div className="flex items-center gap-1.5 flex-wrap">
              {TABS.map((t) => {
                const active = activeTab === t.key;
                return (
                  <button
                    key={t.key}
                    type="button"
                    onClick={() => onTabClick(t.key)}
                    data-testid={`revenue-forecast-tab-${t.key}`}
                    aria-pressed={active}
                    className="text-[11px] px-2.5 py-1 rounded-full font-semibold transition-colors"
                    style={
                      active
                        ? {
                            background: "#0891B2",
                            color: "#fff",
                            border: "1px solid #0891B2",
                          }
                        : {
                            background: colors.surface,
                            color: colors.muted,
                            border: `1px solid ${colors.border}`,
                          }
                    }
                  >
                    {t.label}
                  </button>
                );
              })}
              {activeTab ? (
                <div
                  className="ml-auto text-[11px] font-semibold inline-flex items-center gap-1"
                  data-testid="revenue-forecast-tab-stat"
                  style={{ color: colors.onSurface }}
                >
                  {tabBusy ? (
                    <>
                      <Loader2
                        size={11}
                        className="animate-spin"
                        data-testid="revenue-forecast-tab-loading"
                      />
                      <span style={{ color: colors.muted }}>Loading…</span>
                    </>
                  ) : tabErr ? (
                    <span
                      style={{ color: "#7F1D1D" }}
                      data-testid="revenue-forecast-tab-error"
                    >
                      Failed
                    </span>
                  ) : tabData ? (
                    <span data-testid="revenue-forecast-tab-value">
                      {TABS.find((x) => x.key === activeTab).label}:{" "}
                      <span style={{ color: "#0891B2" }}>
                        {money(tabData.combined_total)}
                      </span>
                    </span>
                  ) : null}
                </div>
              ) : null}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
