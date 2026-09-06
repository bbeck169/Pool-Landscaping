/**
 * Phase R0.1 · Feb-2026 — CSV download helper.
 *
 * Zero-dependency client-side CSV builder + <a>-click trigger.
 * Used by the Revenue by Customer / Revenue by City exports on
 * the new Financial tab. Legacy CSV exports listed in
 * REPORTING_LEGACY_EXPORTS_AUDIT.md remain untouched — R0.1's
 * exports are net-new for the two new reports.
 *
 * @param {string} filename
 * @param {Array<string>} headers  — CSV header row
 * @param {Array<Array<string|number|null>>} rows
 */
export function downloadCsv(filename, headers, rows) {
  const esc = (v) => {
    if (v === null || v === undefined) return "";
    const s = typeof v === "string" ? v : String(v);
    if (/[,"\n\r]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
    return s;
  };
  const lines = [
    headers.map(esc).join(","),
    ...rows.map((r) => r.map(esc).join(",")),
  ];
  const blob = new Blob(["\uFEFF" + lines.join("\r\n")], {
    type: "text/csv;charset=utf-8;",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.setAttribute("href", url);
  link.setAttribute("download", filename);
  link.style.visibility = "hidden";
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
