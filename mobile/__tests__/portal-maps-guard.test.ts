/**
 * Phase K39b AMENDMENT · Feb-2026 — Customer-portal maps guard.
 *
 * Static scan: no file under ``mobile/app/portal/**`` may import
 * from ``@/src/lib/maps``, ``react-native-maps``, or
 * ``react-native-here-explore``. This makes the "bad Maps key /
 * missing HERE binary blanks the customer portal" class of bug
 * structurally impossible on mobile — same shape as the K39a web
 * amendment. If a portal screen ever needs a map, it MUST mount a
 * locally-scoped component with its own error boundary.
 */
import fs from "fs";
import path from "path";

const _PORTAL_ROOT = path.resolve(__dirname, "..", "app", "portal");
const _FORBIDDEN = [
  '"@/src/lib/maps"',
  "'@/src/lib/maps'",
  '"react-native-maps"',
  "'react-native-maps'",
  '"react-native-here-explore"',
  "'react-native-here-explore'",
];

function _walk(dir: string): string[] {
  if (!fs.existsSync(dir)) return [];
  const out: string[] = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(..._walk(full));
    else if (/\.(t|j)sx?$/.test(entry.name)) out.push(full);
  }
  return out;
}

describe("K39b AMENDMENT · Customer portal must NOT import maps at shell", () => {
  const files = _walk(_PORTAL_ROOT);

  it("has at least one portal file (sanity — the scan needs a corpus)", () => {
    expect(files.length).toBeGreaterThan(0);
  });

  it.each(files)("no forbidden maps import in %s", (file) => {
    const src = fs.readFileSync(file, "utf-8");
    for (const needle of _FORBIDDEN) {
      const line = src.split("\n").findIndex((l) => l.includes(needle));
      if (line !== -1) {
        throw new Error(
          `[K39b amendment] Customer-portal file ${path.relative(
            path.resolve(__dirname, ".."),
            file,
          )} imports maps at shell level (line ${line + 1}: ${needle}). ` +
            "Customer portal MUST NOT mount react-native-maps or " +
            "react-native-here-explore. Move the map inside a locally " +
            "scoped component with its own error boundary — see " +
            "mobile/heresdk/README.md.",
        );
      }
    }
    // At least one assertion so the test isn't a no-op.
    expect(src).toBeTruthy();
  });
});
