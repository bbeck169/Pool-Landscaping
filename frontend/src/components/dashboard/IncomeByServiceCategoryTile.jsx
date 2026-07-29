/**
 * Income by Service Category donut · Feb-2026.
 *
 * Sibling of RevenueByCategoryTile but grouped by the pricebook
 * business-unit taxonomy (Pool / Landscaping / …).  Reuses the same
 * shared range picker at the parent level — do NOT create a second
 * filter here.
 */
import React, { useEffect, useState } from "react";
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from "recharts";
import { colors, money } from "@/theme";
import { api } from "@/api";
import { Skeleton } from "@/components/ui-kit";

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
    <div className="rounded-xl px-3 py-2 text-xs"
          style={{ background: colors.surface,
                    border: `1px solid ${colors.border}`,
                    boxShadow: "0 6px 16px rgba(0,0,0,0.10)" }}
          data-testid="income-svc-tooltip">
      <div className="font-semibold" style={{ color: p.color }}>{p.category}</div>
      <div style={{ color: colors.onSurface }}>{money(p.amount)}</div>
      <div style={{ color: colors.muted }}>
        {pct(p.amount, total)} · {p.count} line item(s)
      </div>
    </div>
  );
}

export default function IncomeByServiceCategoryTile({ range }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!range?.start || !range?.end) return;
    setData(null); setErr("");
    api.get(`/admin/dashboard/income-by-service-category?start=${range.start}&end=${range.end}`)
      .then(setData)
      .catch((e) => setErr(e?.message || "Failed to load."));
  }, [range?.start, range?.end]);

  return (
    <div className="rounded-2xl p-5"
          style={{ background: colors.surface,
                    border: `1px solid ${colors.border}` }}
          data-testid="income-by-service-category-tile">
      <div className="flex items-center justify-between mb-3">
        <div className="text-xs uppercase font-bold tracking-wide"
              style={{ color: colors.muted }}>Income by Service Category</div>
        {data ? (
          <div className="text-xs" style={{ color: colors.muted }}
                data-testid="income-svc-item-count">
            {data.items.length} unit{data.items.length === 1 ? "" : "s"}
          </div>
        ) : null}
      </div>

      {err ? (
        <div className="rounded-xl p-3 text-sm"
              style={{ background: "#FEE2E2", color: "#7F1D1D" }}
              data-testid="income-svc-error">{err}</div>
      ) : data === null ? (
        <Skeleton className="h-52 rounded-xl"
                    data-testid="income-svc-loading" />
      ) : data.items.length === 0 ? (
        <div className="py-10 text-center text-sm"
              style={{ color: colors.muted }}
              data-testid="income-svc-empty">
          No invoiced revenue in this range yet.
        </div>
      ) : (
        <div className="flex flex-col md:flex-row items-center gap-4">
          <div className="w-full md:w-56 h-52" data-testid="income-svc-chart">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={data.items} dataKey="amount" nameKey="category"
                      cx="50%" cy="50%" innerRadius={55} outerRadius={85}
                      paddingAngle={1} stroke="none"
                      label={(p) => p.index === 0
                        ? <CenterLabel cx={p.cx} cy={p.cy} total={data.total} />
                        : null}
                      labelLine={false}>
                  {data.items.map((it, i) => <Cell key={i} fill={it.color} />)}
                </Pie>
                <Tooltip content={(p) => <CustomTooltip {...p} total={data.total} />} />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <ul className="flex-1 space-y-1.5 text-sm w-full"
              data-testid="income-svc-legend">
            {data.items.map((it) => (
              <li key={it.category}
                  className="flex items-center justify-between"
                  data-testid={`income-svc-legend-${it.category.replace(/\s+/g, "-")}`}>
                <span className="flex items-center gap-2 truncate">
                  <span className="inline-block w-3 h-3 rounded-sm shrink-0"
                        style={{ background: it.color }} />
                  <span className="truncate"
                        style={{ color: colors.onSurface }}>{it.category}</span>
                </span>
                <span className="font-mono text-xs"
                      style={{ color: colors.onSurface }}>
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
