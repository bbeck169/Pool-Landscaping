import React from "react";
import Chart from "react-apexcharts";
import { colors } from "@/theme";
import { formatCurrency } from "./formatters";

/**
 * Phase R0.1 · Feb-2026 — Horizontal bar chart used by the two
 * grouped-revenue panels on the Financial tab. ApexCharts driven
 * with the R0 theme palette so no new colors are introduced.
 *
 * @typedef {Object} HorizontalBarChartProps
 * @property {Array<{label: string, value: number, id?: string}>} data
 * @property {"currency"|"number"} [format="currency"]
 * @property {number} [height=340]
 * @property {(row: {label, value, id?}) => void} [onBarClick]
 * @property {string} [testid="horizontal-bar-chart"]
 */
export function HorizontalBarChart({
  data = [],
  format = "currency",
  height = 340,
  onBarClick,
  testid = "horizontal-bar-chart",
}) {
  const categories = data.map((d) => d.label);
  const values = data.map((d) => Number(d.value || 0));

  // React StrictMode + react-apexcharts double-mounts and can hit an
  // internal "reading 'beforeMount'" NPE when the ``events`` object
  // is rebuilt every render. Memoize so ApexCharts sees a stable
  // options reference on re-renders.
  const options = React.useMemo(() => ({
    chart: {
      id: testid,
      toolbar: { show: false },
      zoom: { enabled: false },
      fontFamily: "inherit",
      background: "transparent",
      animations: { enabled: false },
      events: {
        dataPointSelection: (_event, _ctx, config) => {
          if (!onBarClick) return;
          const idx = config?.dataPointIndex;
          if (typeof idx === "number" && data[idx]) onBarClick(data[idx]);
        },
      },
    },
    plotOptions: {
      bar: {
        horizontal: true,
        borderRadius: 4,
        distributed: false,
        barHeight: "70%",
      },
    },
    dataLabels: {
      enabled: true,
      formatter: (v) => (format === "currency" ? formatCurrency(v, { compact: true }) : v),
      style: { colors: [colors.onSurface], fontSize: "11px", fontWeight: 600 },
      offsetX: 24,
    },
    colors: [colors.brand],
    grid: {
      borderColor: colors.border,
      strokeDashArray: 4,
      xaxis: { lines: { show: true } },
      yaxis: { lines: { show: false } },
    },
    xaxis: {
      categories,
      labels: {
        style: { colors: colors.onSurfaceSecondary, fontSize: "11px" },
        formatter: (v) => (format === "currency" ? formatCurrency(v, { compact: true }) : v),
      },
    },
    yaxis: {
      labels: {
        style: { colors: colors.onSurfaceSecondary, fontSize: "12px" },
        maxWidth: 220,
      },
    },
    tooltip: {
      y: {
        formatter: (v) =>
          format === "currency" ? formatCurrency(v) : Number(v).toLocaleString(),
      },
    },
    legend: { show: false },
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }), [JSON.stringify(categories), format, testid]);

  return (
    <div
      className="rounded-xl border p-3"
      style={{ backgroundColor: colors.surface, borderColor: colors.border }}
      data-testid={testid}
    >
      {data.length === 0 ? (
        <div
          className="h-40 flex items-center justify-center text-sm"
          style={{ color: colors.onSurfaceSecondary }}
          data-testid={`${testid}-empty`}
        >
          No data for the current filter set
        </div>
      ) : (
        <Chart options={options} series={[{ name: "Revenue", data: values }]} type="bar" height={height} />
      )}
    </div>
  );
}

export default HorizontalBarChart;
