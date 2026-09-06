import React from "react";
import Chart from "react-apexcharts";
import { colors } from "@/theme";

/**
 * Phase R0 · Feb-2026 — TrendChart wraps ApexCharts for the
 * reporting suite. Every consumer passes normalized series so the
 * chart component itself owns no domain logic — R1 onward can drop
 * in new dashboards without re-configuring ApexCharts from scratch.
 *
 * @typedef {Object} TrendChartProps
 * @property {Array<{name: string, data: Array<number>}>} series
 * @property {Array<string>} xLabels
 * @property {number} [height=260]
 * @property {"brand"|"success"|"warning"|"error"} [colorToken="brand"]
 * @property {"currency"|"number"|"percent"} [valueFormat="number"]
 * @property {"line"|"area"|"bar"} [type="area"]
 * @property {string} [testid="trend-chart"]
 */
export function TrendChart({
  series = [],
  xLabels = [],
  height = 260,
  colorToken = "brand",
  valueFormat = "number",
  type = "area",
  testid = "trend-chart",
}) {
  const paletteMap = {
    brand: colors.brand,
    success: colors.success,
    warning: colors.warning,
    error: colors.error,
  };
  const stroke = paletteMap[colorToken] || colors.brand;

  const options = {
    chart: {
      id: testid,
      toolbar: { show: false },
      zoom: { enabled: false },
      fontFamily: "inherit",
      background: "transparent",
    },
    grid: {
      borderColor: colors.border,
      strokeDashArray: 4,
      xaxis: { lines: { show: false } },
    },
    dataLabels: { enabled: false },
    stroke: { curve: "smooth", width: 2 },
    fill: {
      type: type === "area" ? "gradient" : "solid",
      gradient: { opacityFrom: 0.35, opacityTo: 0.02, stops: [0, 90, 100] },
    },
    colors: [stroke],
    xaxis: {
      categories: xLabels,
      labels: { style: { colors: colors.onSurfaceSecondary, fontSize: "11px" } },
      axisBorder: { color: colors.border },
      axisTicks: { color: colors.border },
    },
    yaxis: {
      labels: {
        style: { colors: colors.onSurfaceSecondary, fontSize: "11px" },
        formatter: (v) => {
          if (valueFormat === "currency") return `$${Number(v).toLocaleString()}`;
          if (valueFormat === "percent") return `${Number(v).toFixed(0)}%`;
          return Number(v).toLocaleString();
        },
      },
    },
    tooltip: {
      x: { show: true },
      y: {
        formatter: (v) => {
          if (valueFormat === "currency")
            return Number(v).toLocaleString("en-US", { style: "currency", currency: "USD" });
          if (valueFormat === "percent") return `${Number(v).toFixed(1)}%`;
          return Number(v).toLocaleString();
        },
      },
    },
    legend: { show: series.length > 1, position: "top", horizontalAlign: "right" },
  };

  return (
    <div
      className="rounded-xl border p-3"
      style={{ backgroundColor: colors.surface, borderColor: colors.border }}
      data-testid={testid}
    >
      <Chart options={options} series={series} type={type} height={height} />
    </div>
  );
}

export default TrendChart;
