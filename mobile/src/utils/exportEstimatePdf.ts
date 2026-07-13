import { Platform } from "react-native";
import * as Print from "expo-print";
import * as Sharing from "expo-sharing";
import { computeEstimate, EstimateLine } from "./estimate";

const fmt = (n: number) => `$${(Number(n) || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const esc = (s: any) => String(s ?? "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c] as string));

export type EstimatePdfInput = {
  title: string;
  customerName: string;
  lines: EstimateLine[];
  overheadPct: number;
  marginPct: number;
};

function buildHtml({ title, customerName, lines, overheadPct, marginPct }: EstimatePdfInput) {
  const c = computeEstimate(lines, overheadPct, marginPct);
  const rows = lines.map((l) => {
    const amt = (Number(l.quantity) || 0) * (Number(l.unit_cost) || 0);
    return `<tr>
      <td>${esc(l.category)}</td>
      <td>${esc(l.description)}</td>
      <td class="r">${Number(l.quantity) || 0}</td>
      <td class="r">${fmt(l.unit_cost)}</td>
      <td class="r">${fmt(amt)}</td>
    </tr>`;
  }).join("");

  return `<!DOCTYPE html><html><head><meta charset="utf-8"/>
  <style>
    * { font-family: -apple-system, Helvetica, Arial, sans-serif; }
    body { padding: 28px; color: #0f172a; }
    .watermark { display:inline-block; background:#fee2e2; color:#b91c1c; font-weight:700; font-size:11px; letter-spacing:1px; padding:4px 10px; border-radius:6px; }
    h1 { font-size: 22px; margin: 10px 0 2px; }
    .sub { color:#64748b; font-size:13px; margin-bottom:18px; }
    table { width:100%; border-collapse:collapse; margin-top:6px; }
    th, td { text-align:left; font-size:12px; padding:8px 6px; border-bottom:1px solid #e2e8f0; }
    th { color:#64748b; text-transform:uppercase; font-size:10px; letter-spacing:.5px; }
    .r { text-align:right; }
    .totals { margin-top:18px; width:280px; margin-left:auto; }
    .totals .row { display:flex; justify-content:space-between; font-size:13px; padding:5px 0; }
    .totals .sell { border-top:2px solid #0f172a; margin-top:6px; padding-top:8px; font-weight:700; font-size:16px; }
    .gm { text-align:right; color:#16a34a; font-weight:600; font-size:12px; }
    .foot { margin-top:26px; color:#94a3b8; font-size:10px; }
  </style></head><body>
    <span class="watermark">INTERNAL — COST BREAKDOWN (DO NOT SHARE WITH CUSTOMER)</span>
    <h1>${esc(title || "Estimate")}</h1>
    <div class="sub">Customer: ${esc(customerName || "—")}</div>
    <table>
      <thead><tr><th>Category</th><th>Description</th><th class="r">Qty</th><th class="r">Unit cost</th><th class="r">Line cost</th></tr></thead>
      <tbody>${rows || `<tr><td colspan="5" style="color:#94a3b8">No line items</td></tr>`}</tbody>
    </table>
    <div class="totals">
      <div class="row"><span>Direct cost</span><span>${fmt(c.directCost)}</span></div>
      <div class="row"><span>Overhead (${overheadPct || 0}%)</span><span>${fmt(c.overheadAmount)}</span></div>
      <div class="row"><span>Burdened cost</span><span>${fmt(c.totalCost)}</span></div>
      <div class="row"><span>Profit</span><span>${fmt(c.profitAmount)}</span></div>
      <div class="row sell"><span>Sell price</span><span>${fmt(c.sellPrice)}</span></div>
      <div class="gm">Gross margin ${c.grossMarginPct}%</div>
    </div>
    <div class="foot">Generated ${new Date().toLocaleString()} · Internal job-costing document.</div>
  </body></html>`;
}

/** Generate an itemized internal cost PDF. Web opens the print dialog; native shares the PDF file. */
export async function exportEstimatePdf(input: EstimatePdfInput) {
  const html = buildHtml(input);
  if (Platform.OS === "web") {
    await Print.printAsync({ html });
    return;
  }
  const { uri } = await Print.printToFileAsync({ html });
  if (await Sharing.isAvailableAsync()) {
    await Sharing.shareAsync(uri, { mimeType: "application/pdf", dialogTitle: "Internal cost breakdown", UTI: "com.adobe.pdf" });
  }
}
