import { Platform } from "react-native";
import * as Print from "expo-print";
import * as Sharing from "expo-sharing";

const money = (n: number) => `$${(Number(n) || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const esc = (s: any) => String(s ?? "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c] as string));

function kpiCards(k: any) {
  const items = [
    ["Revenue collected", money(k.revenue)],
    ["Outstanding", money(k.outstanding)],
    ["Avg ticket", money(k.avg_ticket)],
    ["Completion rate", `${k.completion_rate}%`],
    ["Total jobs", k.total_jobs],
    ["Customers", k.total_customers],
    ["Open leads", k.open_leads],
    ["Labor hrs (wk)", k.labor_hours_week],
  ];
  return `<div class="kpis">${items.map(([l, v]) => `<div class="kpi"><div class="kv">${esc(v)}</div><div class="kl">${esc(l)}</div></div>`).join("")}</div>`;
}

function barTable(title: string, rows: { label: string; value: number }[], asMoney = true) {
  if (!rows || rows.length === 0) return `<h3>${esc(title)}</h3><p class="muted">No data.</p>`;
  const max = Math.max(...rows.map((r) => r.value), 1);
  const body = rows.map((r) => `<tr><td>${esc(r.label)}</td><td class="bar"><span style="width:${Math.max(2, (r.value / max) * 100)}%"></span></td><td class="r">${asMoney ? money(r.value) : r.value}</td></tr>`).join("");
  return `<h3>${esc(title)}</h3><table>${body}</table>`;
}

export type BusinessSummary = any;

function buildHtml(d: BusinessSummary) {
  const k = d.kpis || {};
  const c = d.company || {};
  const income = (d.income_by_category || []).map((r: any) => ({ label: r.category, value: r.amount }));
  const pool = d.pool_service || {};
  const poolRows = (pool.rows || []).map((r: any) => `<tr><td>${esc(r.technician_name)}</td><td class="r">${r.completed}</td><td class="r">${r.skipped}</td></tr>`).join("");
  const period = d.date_from && d.date_to ? `${esc(d.date_from)} to ${esc(d.date_to)}` : "All time";
  const logo = c.logo ? `<img class="logo" src="${esc(c.logo)}"/>` : "";
  const contact = [c.phone, c.email, c.website].filter(Boolean).map(esc).join(" · ");
  return `<!DOCTYPE html><html><head><meta charset="utf-8"/>
  <style>
    * { font-family: -apple-system, Helvetica, Arial, sans-serif; color:#0f172a; }
    body { padding: 28px; }
    .head { display:flex; align-items:center; gap:14px; border-bottom:2px solid #0284C7; padding-bottom:14px; margin-bottom:16px; }
    .logo { width:56px; height:56px; border-radius:10px; object-fit:cover; }
    .co { font-size:20px; font-weight:700; }
    .cotag { font-size:12px; color:#64748b; margin-top:1px; }
    .cocontact { font-size:10px; color:#94a3b8; margin-top:2px; }
    h1 { font-size: 16px; margin: 0 0 2px; }
    .sub { color:#64748b; font-size:12px; margin-bottom:14px; }
    .kpis { display:flex; flex-wrap:wrap; gap:8px; }
    .kpi { flex:1 1 22%; min-width:110px; border:1px solid #e2e8f0; border-radius:8px; padding:10px; }
    .kv { font-size:17px; font-weight:700; color:#0284C7; }
    .kl { font-size:10px; color:#64748b; text-transform:uppercase; letter-spacing:.4px; margin-top:2px; }
    h3 { font-size: 14px; margin: 22px 0 6px; }
    table { width:100%; border-collapse:collapse; }
    td { font-size:12px; padding:6px 6px; border-bottom:1px solid #eef2f6; }
    td.r { text-align:right; font-weight:600; white-space:nowrap; }
    td.bar { width:55%; } td.bar span { display:inline-block; height:9px; border-radius:5px; background:#0284C7; }
    .muted { color:#94a3b8; font-size:12px; }
    .foot { margin-top:26px; color:#94a3b8; font-size:10px; }
  </style></head><body>
    <div class="head">
      ${logo}
      <div style="flex:1">
        <div class="co">${esc(c.name || "Business Report")}</div>
        ${c.tagline ? `<div class="cotag">${esc(c.tagline)}</div>` : ""}
        ${contact ? `<div class="cocontact">${contact}</div>` : ""}
      </div>
    </div>
    <h1>Business Report</h1>
    <div class="sub">Period: ${period} · Generated ${new Date(d.generated_at || Date.now()).toLocaleString()}</div>
    ${kpiCards(k)}
    ${barTable("Revenue Trend (6 months)", d.revenue_series || [])}
    ${barTable("Income by Category", income)}
    ${barTable("Revenue by Service", d.revenue_by_service || [])}
    ${barTable("Top Customers", d.top_customers || [])}
    <h3>Pool Service — ${esc(pool.week_start)} to ${esc(pool.week_end)} (completed ${pool.total_completed || 0}, skipped ${pool.total_skipped || 0})</h3>
    <table><tr><td><b>Technician</b></td><td class="r">Completed</td><td class="r">Skipped</td></tr>${poolRows || `<tr><td class="muted">No visits.</td></tr>`}</table>
    ${barTable("Labor Hours (this week)", d.labor_hours || [], false)}
    <div class="foot">Confidential — internal business report.</div>
  </body></html>`;
}

export async function exportReportPdf(summary: BusinessSummary) {
  const html = buildHtml(summary);
  if (Platform.OS === "web") { await Print.printAsync({ html }); return; }
  const { uri } = await Print.printToFileAsync({ html });
  if (await Sharing.isAvailableAsync()) {
    await Sharing.shareAsync(uri, { mimeType: "application/pdf", dialogTitle: "Business report", UTI: "com.adobe.pdf" });
  }
}
