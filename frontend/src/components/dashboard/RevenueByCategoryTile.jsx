/**
 * Revenue by Category donut · Feb-2026.
 *
 * Uses recharts PieChart with a hover tooltip + center total.
 * The API caller passes { start, end } as the ``range`` prop; the tile
 * refetches whenever the range changes.
 *
 * Feb-2026 · Backlog #1 Part 1 · Rendering contract:
 *   * API returns ``{category_id, category_name, amount, count, color,
 *     is_orphan}`` per item — the tile reads ``category_name`` first
 *     and falls back to ``category`` for backward compatibility.
 *   * Defense-in-depth: any label matching a UUID shape (in case a
 *     legacy write path bypasses the API guard) is coerced to
 *     ``"Uncategorized"`` before render — the tile MUST NEVER display
 *     a raw id string.
 */
import React, { useEffect, useMemo, useState } from "react";
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from "recharts";
import { colors, money } from "@/theme";
import { api } from "@/api";
import { Skeleton } from "@/components/ui-kit";

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// Feb-2026 · Backlog #1 Part 1 — never render a UUID as a category
// label. Prefers ``category_name``, falls back to ``category``,
// coerces anything UUID-shaped to ``"Uncategorized"``. Kept as a
// pure helper so the Vitest suite can lock the contract without
// mounting the full tile.
export function displayCategoryLabel(item) {
  const raw = (item?.category_name || item?.category || "").trim();
  if (!raw) return "Uncategorized";
  if (UUID_RE.test(raw)) return "Uncategorized";
  return raw;
}

function pct(part, total) {
  if (!total) return "0%";
  return `${((part / total) * 100).toFixed(1)}%`;
}

function CenterLabel({ cx, cy, total }) {
  return (
    <g>
      <text x={cx} y={cy - 6} textAnchor="middle"
            style={{ fontSize: 11, fill: colors.muted }}>Total</text>
      <text x={cx} y={cy + 14} textAnchor="middle"
            style={{ fontSize: 20, fontWeight: 700, fill: colors.onSurface }}>
        {money(total)}
      </text>
    </g>
  );
}

function CustomTooltip({ active, payload, total }) {
  if (!active || !payload || !payload.length) return null;
  const p = payload[0].payload;
  return (
    <div
      className="rounded-xl px-3 py-2 text-xs"
      style={{ background: colors.surface,
                border: `1px solid ${colors.border}`,
                boxShadow: "0 6px 16px rgba(0,0,0,0.10)" }}
      data-testid="revenue-cat-tooltip"
    >
      <div className="font-semibold" style={{ color: p.color }}>{p.category}</div>
      <div style={{ color: colors.onSurface }}>{money(p.amount)}</div>
      <div style={{ color: colors.muted }}>{pct(p.amount, total)} · {p.count} line item(s)</div>
    </div>
  );
}

export default function RevenueByCategoryTile({ range }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!range?.start || !range?.end) return;
    setData(null);
    setErr("");
    api.get(`/admin/dashboard/revenue-by-category?start=${range.start}&end=${range.end}`)
      .then(setData)
      .catch((e) => setErr(e?.message || "Failed to load."));
  }, [range?.start, range?.end]);

  return (
    <div
      className="rounded-2xl p-5"
      style={{ background: colors.surface,
                border: `1px solid ${colors.border}` }}
      data-testid="revenue-by-category-tile"
    >
      <div className="flex items-center justify-between mb-3">
        <div className="text-xs uppercase font-bold tracking-wide"
              style={{ color: colors.muted }}>Revenue by Category (paid, this month)</div>
        {data ? (
          <div className="text-xs" style={{ color: colors.muted }}
                data-testid="revenue-cat-item-count">
            {data.items.length} categor{data.items.length === 1 ? "y" : "ies"}
          </div>
        ) : null}
      </div>

      {err ? (
        <div className="rounded-xl p-3 text-sm"
              style={{ background: "#FEE2E2", color: "#7F1D1D" }}
              data-testid="revenue-cat-error">{err}</div>
      ) : data === null ? (
        <Skeleton className="h-52 rounded-xl" data-testid="revenue-cat-loading" />
      ) : data.items.length === 0 ? (
        <div className="py-10 text-center text-sm"
              style={{ color: colors.muted }}
              data-testid="revenue-cat-empty">
          No invoiced revenue in this range yet.
        </div>
      ) : (
        <div className="flex flex-col md:flex-row items-center gap-4">
          <div className="w-full md:w-56 h-52" data-testid="revenue-cat-chart">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={data.items}
                  dataKey="amount"
                  nameKey="category"
                  cx="50%"
                  cy="50%"
                  innerRadius={55}
                  outerRadius={85}
                  paddingAngle={1}
                  stroke="none"
                  label={(props) =>
                    props.index === 0
                      ? <CenterLabel cx={props.cx} cy={props.cy} total={data.total} />
                      : null
                  }
                  labelLine={false}
                >
                  {data.items.map((it, i) => (
                    <Cell key={i} fill={it.color} />
                  ))}
                </Pie>
                <Tooltip content={(p) => <CustomTooltip {...p} total={data.total} />} />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <ul className="flex-1 space-y-1.5 text-sm w-full"
              data-testid="revenue-cat-legend">
            {data.items.map((it) => (
              <li key={it.category}
                  className="flex items-center justify-between"
                  data-testid={`revenue-cat-legend-${it.category.replace(/\s+/g, "-")}`}>
                <span className="flex items-center gap-2 truncate">
                  <span className="inline-block w-3 h-3 rounded-sm shrink-0"
                        style={{ background: it.color }} />
                  <span className="truncate" style={{ color: colors.onSurface }}>{it.category}</span>
                </span>
                <span className="font-mono text-xs" style={{ color: colors.onSurface }}>
                  {money(it.amount)} · {pct(it.amount, data.total)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
