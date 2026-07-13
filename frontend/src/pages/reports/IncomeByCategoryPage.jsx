import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { api } from "@/api";
import { colors, money, brandGradient } from "@/theme";
import DateRangePicker, { useDateRange } from "@/components/DateRangePicker";

// Simple donut: sum of arcs computed via SVG stroke-dasharray on stacked circles.
function Donut({ rows, size = 200 }) {
  const total = rows.reduce((a, r) => a + Number(r.amount || 0), 0);
  const r = (size / 2) - 14;
  const c = 2 * Math.PI * r;
  const palette = [
    brandGradient[0], brandGradient[1], "#F59E0B", "#8B5CF6",
    "#EC4899", "#06B6D4", "#65A30D", "#EF4444",
  ];
  let offset = 0;
  return (
    <div className="flex items-center justify-center">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle cx={size/2} cy={size/2} r={r} fill="none"
                stroke={colors.surfaceTertiary} strokeWidth={20} />
        {rows.map((row, i) => {
          if (total === 0) return null;
          const frac = Number(row.amount || 0) / total;
          const dash = frac * c;
          const gap = c - dash;
          const seg = (
            <circle key={i} cx={size/2} cy={size/2} r={r} fill="none"
                    stroke={palette[i % palette.length]}
                    strokeWidth={20}
                    strokeDasharray={`${dash} ${gap}`}
                    strokeDashoffset={-offset}
                    transform={`rotate(-90 ${size/2} ${size/2})`} />
          );
          offset += dash;
          return seg;
        })}
        <text x={size/2} y={size/2 - 4} textAnchor="middle"
              fontSize={12} fill={colors.muted}>Total</text>
        <text x={size/2} y={size/2 + 16} textAnchor="middle"
              fontSize={16} fontWeight={700} fill={colors.onSurface}>
          {money(total)}
        </text>
      </svg>
    </div>
  );
}

export default function IncomeByCategory() {
  const nav = useNavigate();
  const { start, end } = useDateRange("this-month");
  const [data, setData] = useState({ rows: [], total: 0 });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let live = true;
    setLoading(true);
    api.get(`/finances/income-by-category?date_from=${start}&date_to=${end}`)
      .then((r) => { if (live) { setData(r); setLoading(false); } })
      .catch(() => live && setLoading(false));
    return () => { live = false; };
  }, [start, end]);

  const palette = [
    brandGradient[0], brandGradient[1], "#F59E0B", "#8B5CF6",
    "#EC4899", "#06B6D4", "#65A30D", "#EF4444",
  ];

  return (
    <div className="p-4 md:p-8 max-w-6xl mx-auto" data-testid="income-by-category-page">
      <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <button onClick={() => nav("/reports")}
                  className="p-2 rounded-lg hover:brightness-95"
                  style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
                  data-testid="back-to-reports">
            <ArrowLeft size={16} />
          </button>
          <div>
            <h1 className="text-2xl md:text-3xl font-bold" style={{ color: colors.onSurface }}>Income by Category</h1>
            <p className="text-xs mt-0.5" style={{ color: colors.muted }}>Line-item paid revenue attributed to categories</p>
          </div>
        </div>
        <DateRangePicker />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="rounded-2xl p-6"
             style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
             data-testid="income-donut-card">
          {loading ? (
            <div className="animate-pulse rounded-xl h-56" style={{ backgroundColor: colors.surfaceTertiary }} />
          ) : (
            <Donut rows={data.rows || []} />
          )}
        </div>

        <div className="rounded-2xl p-4"
             style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
             data-testid="income-table-card">
          <div className="text-sm font-semibold mb-3 px-2" style={{ color: colors.onSurface }}>
            Breakdown
          </div>
          <table className="w-full text-sm">
            <tbody>
              {(data.rows || []).map((r, i) => {
                const pct = data.total ? ((r.amount / data.total) * 100).toFixed(1) : 0;
                return (
                  <tr key={i} style={{ borderTop: i ? `1px solid ${colors.border}` : "none" }}>
                    <td className="py-2.5 px-2 flex items-center gap-2">
                      <span className="w-2.5 h-2.5 rounded-full"
                            style={{ backgroundColor: palette[i % palette.length] }} />
                      <span style={{ color: colors.onSurface }}>{r.category}</span>
                    </td>
                    <td className="py-2.5 text-xs text-right" style={{ color: colors.muted }}>{pct}%</td>
                    <td className="py-2.5 px-2 text-right font-semibold" style={{ color: colors.brand }}>
                      {money(r.amount)}
                    </td>
                  </tr>
                );
              })}
              {(!loading && (data.rows || []).length === 0) && (
                <tr><td colSpan={3} className="py-8 text-center text-sm" style={{ color: colors.muted }}>
                  No paid invoices in this window
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
