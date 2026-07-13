import { Platform } from "react-native";
import * as Print from "expo-print";
import * as Sharing from "expo-sharing";

const money = (n: number) => `$${(Number(n) || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const esc = (s: any) => String(s ?? "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c] as string));
const shortDate = (iso?: string | null) => { if (!iso) return "—"; try { return new Date(iso).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" }); } catch { return String(iso); } };

function buildHtml(inv: any, company: any) {
  const c = company || {};
  const isInvoice = inv.doc_type === "invoice";
  const docLabel = isInvoice ? "INVOICE" : "QUOTE";
  const logo = c.logo ? `<img class="logo" src="${esc(c.logo)}"/>` : "";
  const contact = [c.phone, c.email, c.website].filter(Boolean).map(esc).join(" · ");
  const rows = (inv.line_items || []).map((li: any) => {
    const amt = (Number(li.quantity) || 0) * (Number(li.unit_price) || 0);
    return `<tr><td>${esc(li.description)}</td><td class="r">${Number(li.quantity) || 0}</td><td class="r">${money(li.unit_price)}</td><td class="r">${money(amt)}</td></tr>`;
  }).join("");
  const paid = Number(inv.amount_paid) || 0;
  const balance = (Number(inv.total) || 0) - paid;
  return `<!DOCTYPE html><html><head><meta charset="utf-8"/>
  <style>
    * { font-family: -apple-system, Helvetica, Arial, sans-serif; color:#0f172a; }
    body { padding: 28px; }
    .head { display:flex; align-items:center; gap:14px; border-bottom:2px solid #0284C7; padding-bottom:14px; }
    .logo { width:56px; height:56px; border-radius:10px; object-fit:cover; }
    .co { font-size:20px; font-weight:700; }
    .cotag { font-size:12px; color:#64748b; margin-top:1px; }
    .cocontact { font-size:10px; color:#94a3b8; margin-top:2px; }
    .doclbl { text-align:right; }
    .doclbl .t { font-size:22px; font-weight:800; letter-spacing:1px; color:#0284C7; }
    .doclbl .m { font-size:11px; color:#64748b; }
    .meta { display:flex; justify-content:space-between; margin:18px 0 6px; }
    .meta .b { font-size:10px; color:#94a3b8; text-transform:uppercase; letter-spacing:.5px; }
    .meta .v { font-size:13px; font-weight:600; }
    table { width:100%; border-collapse:collapse; margin-top:10px; }
    th, td { text-align:left; font-size:12px; padding:8px 6px; border-bottom:1px solid #e2e8f0; }
    th { color:#64748b; text-transform:uppercase; font-size:10px; letter-spacing:.5px; }
    .r { text-align:right; }
    .totals { margin-top:14px; width:260px; margin-left:auto; }
    .totals .row { display:flex; justify-content:space-between; font-size:13px; padding:4px 0; }
    .totals .due { border-top:2px solid #0f172a; margin-top:6px; padding-top:8px; font-weight:800; font-size:16px; }
    .paid { color:#16a34a; }
    .notes { margin-top:20px; font-size:12px; color:#475569; }
    .foot { margin-top:26px; color:#94a3b8; font-size:10px; text-align:center; }
  </style></head><body>
    <div class="head">
      ${logo}
      <div style="flex:1">
        <div class="co">${esc(c.name || "Company")}</div>
        ${c.tagline ? `<div class="cotag">${esc(c.tagline)}</div>` : ""}
        ${contact ? `<div class="cocontact">${contact}</div>` : ""}
      </div>
      <div class="doclbl"><div class="t">${docLabel}</div><div class="m">${shortDate(inv.created_at)}</div></div>
    </div>

    <div class="meta">
      <div><div class="b">Bill to</div><div class="v">${esc(inv.customer_name || "")}</div></div>
      <div style="text-align:right"><div class="b">${isInvoice ? "Due date" : "Valid until"}</div><div class="v">${shortDate(inv.due_date)}</div></div>
    </div>
    <div style="font-size:14px;font-weight:700;margin-top:6px">${esc(inv.title || "")}</div>

    <table>
      <thead><tr><th>Description</th><th class="r">Qty</th><th class="r">Unit</th><th class="r">Amount</th></tr></thead>
      <tbody>${rows || `<tr><td colspan="4" style="color:#94a3b8">No line items</td></tr>`}</tbody>
    </table>

    <div class="totals">
      <div class="row"><span>Subtotal</span><span>${money(inv.subtotal)}</span></div>
      <div class="row"><span>Tax (${inv.tax_rate || 0}%)</span><span>${money(inv.tax)}</span></div>
      <div class="row"><span>Total</span><span>${money(inv.total)}</span></div>
      ${paid > 0 ? `<div class="row paid"><span>Paid</span><span>-${money(paid)}</span></div>` : ""}
      <div class="row due"><span>${isInvoice ? "Balance due" : "Estimated total"}</span><span>${money(isInvoice ? balance : inv.total)}</span></div>
    </div>

    ${inv.notes ? `<div class="notes"><b>Notes:</b> ${esc(inv.notes)}</div>` : ""}
    <div class="foot">Thank you for your business${c.name ? ` — ${esc(c.name)}` : ""}.</div>
  </body></html>`;
}

export async function exportInvoicePdf(invoice: any, company: any) {
  const html = buildHtml(invoice, company);
  if (Platform.OS === "web") { await Print.printAsync({ html }); return; }
  const { uri } = await Print.printToFileAsync({ html });
  if (await Sharing.isAvailableAsync()) {
    await Sharing.shareAsync(uri, { mimeType: "application/pdf", dialogTitle: `${invoice.doc_type === "invoice" ? "Invoice" : "Quote"} ${invoice.title || ""}`, UTI: "com.adobe.pdf" });
  }
}
