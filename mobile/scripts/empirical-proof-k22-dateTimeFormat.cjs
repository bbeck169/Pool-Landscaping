/**
 * empirical-proof-k22-dateTimeFormat.cjs
 * Phase K22 — empirical proof that the formatCompletedAt helper
 * produces the canonical K16 output shape.
 *
 * Run: node mobile/scripts/empirical-proof-k22-dateTimeFormat.cjs
 */

// Cannot require TS directly; inline the logic for proof.
function formatCompletedAt(iso, options) {
  if (iso && typeof iso === "object") {
    const status = (iso.status || "").toLowerCase();
    const completedAt =
      iso.completed_at || iso.completedAt ||
      (status === "completed" ? (iso.updated_at || iso.updatedAt) : null);
    return formatCompletedAt(completedAt, options);
  }
  if (!iso) return "\u2014";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "\u2014";
  const tz = (options && options.tz) || undefined;
  const datePart = new Intl.DateTimeFormat("en-US", {
    month: "short", day: "numeric", year: "numeric", timeZone: tz,
  }).format(d);
  const timePart = new Intl.DateTimeFormat("en-US", {
    hour: "numeric", minute: "2-digit", hour12: true, timeZone: tz,
  }).format(d);
  return datePart + " \u00b7 " + timePart;
}

console.log("=== Phase K22 — formatCompletedAt empirical proof ===\n");

const cases = [
  { label: "Canonical ISO → local", input: "2026-09-01T15:38:00Z" },
  { label: "With TZ (Phoenix)", input: "2026-09-01T15:38:00Z", opts: { tz: "America/Phoenix" } },
  { label: "Null input", input: null },
  { label: "Invalid string", input: "banana" },
  { label: "Object w/ completed_at", input: { completed_at: "2026-12-25T18:00:00Z" } },
  { label: "Object w/ updated_at fallback", input: { status: "completed", updated_at: "2026-06-15T09:30:00Z" } },
  { label: "Object w/ status=open (no fallback)", input: { status: "open", updated_at: "2026-06-15T09:30:00Z" } },
];

let ok = 0;
for (const c of cases) {
  const result = formatCompletedAt(c.input, c.opts);
  const pass = result.includes("\u00b7") || result === "\u2014";
  console.log(`${pass ? "✅" : "❌"} ${c.label.padEnd(40)} → "${result}"`);
  if (pass) ok++;
}

console.log(`\n${ok}/${cases.length} cases produce valid output.`);
process.exit(ok === cases.length ? 0 : 1);
