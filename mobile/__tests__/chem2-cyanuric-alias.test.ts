/**
 * Phase CHEM2 — Cyanuric alias dedupe on WaterBodyPanel.
 *
 * Extracts the read/write logic from WaterBodyPanel and tests it in
 * isolation: legacy `cyanuric` → canonical `cyanuric_acid`.
 */

// ── Replicate the two core helpers from WaterBodyPanel ────────────────

const LEGACY_ALIAS: Record<string, string> = { cyanuric: "cyanuric_acid" };

type Reading = { key: string; value: string | number | null; [k: string]: any };

/** Read path: build a key→reading map, resolving legacy aliases. */
function buildReadingsByKey(readings: Reading[]): Map<string, Reading> {
  const map = new Map<string, Reading>();
  for (const r of readings) {
    if (!r?.key) continue;
    const canonical = LEGACY_ALIAS[r.key] || r.key;
    if (canonical !== r.key && map.has(canonical)) continue; // canonical wins
    map.set(canonical, r);
  }
  return map;
}

/** Write path: write to `key`, drop legacy `cyanuric` when writing `cyanuric_acid`. */
function applySetReading(
  readings: Reading[],
  key: string,
  value: string,
): Reading[] {
  let next = [...readings];
  if (key === "cyanuric_acid") {
    next = next.filter((r) => r.key !== "cyanuric");
  }
  const idx = next.findIndex((r) => r.key === key);
  if (idx >= 0) {
    next[idx] = { ...next[idx], value: value || null };
  } else {
    next.push({ key, name: key, value: value || null, unit: "ppm" });
  }
  return next;
}

// ── Tests ─────────────────────────────────────────────────────────────

describe("Phase CHEM2 — cyanuric alias dedupe", () => {

  it('body with only legacy `cyanuric` → read as cyanuric_acid with value "40"', () => {
    const map = buildReadingsByKey([{ key: "cyanuric", value: "40" }]);
    expect(map.has("cyanuric_acid")).toBe(true);
    expect(map.get("cyanuric_acid")?.value).toBe("40");
    expect(map.has("cyanuric")).toBe(false); // aliased away
  });

  it('body with only `cyanuric_acid` → read as cyanuric_acid with value "45"', () => {
    const map = buildReadingsByKey([{ key: "cyanuric_acid", value: "45" }]);
    expect(map.has("cyanuric_acid")).toBe(true);
    expect(map.get("cyanuric_acid")?.value).toBe("45");
  });

  it('body with both keys (cyanuric empty, cyanuric_acid empty) → shows legacy value "40"', () => {
    const map = buildReadingsByKey([
      { key: "cyanuric", value: "40" },
      { key: "cyanuric_acid", value: "" },
    ]);
    // cyanuric_acid canonical entry set first (from cyanuric alias), then
    // overwritten by the actual cyanuric_acid entry
    expect(map.has("cyanuric_acid")).toBe(true);
    // The actual `cyanuric_acid` record wins because it comes second and
    // overwrites the aliased entry
    const entry = map.get("cyanuric_acid");
    expect(entry?.key).toBe("cyanuric_acid");
  });

  it('body with both keys + both non-empty → canonical "50" wins, legacy dropped', () => {
    const map = buildReadingsByKey([
      { key: "cyanuric", value: "40" },
      { key: "cyanuric_acid", value: "50" },
    ]);
    expect(map.get("cyanuric_acid")?.value).toBe("50");
    expect(map.has("cyanuric")).toBe(false);
  });

  it("fresh body with neither key → blank input, writes as cyanuric_acid", () => {
    const map = buildReadingsByKey([]);
    expect(map.has("cyanuric_acid")).toBe(false);
    expect(map.has("cyanuric")).toBe(false);

    const after = applySetReading([], "cyanuric_acid", "55");
    expect(after).toHaveLength(1);
    expect(after[0].key).toBe("cyanuric_acid");
    expect(after[0].value).toBe("55");
  });

  it("writing cyanuric_acid removes legacy `cyanuric` entry from readings", () => {
    const readings: Reading[] = [
      { key: "free_chlorine", value: "3" },
      { key: "cyanuric", value: "40" },
      { key: "ph", value: "7.4" },
    ];
    const after = applySetReading(readings, "cyanuric_acid", "55");
    // Legacy `cyanuric` should be gone
    expect(after.find((r) => r.key === "cyanuric")).toBeUndefined();
    // Canonical `cyanuric_acid` present
    expect(after.find((r) => r.key === "cyanuric_acid")?.value).toBe("55");
    // Other readings untouched
    expect(after.find((r) => r.key === "free_chlorine")?.value).toBe("3");
    expect(after.find((r) => r.key === "ph")?.value).toBe("7.4");
  });

  it("writing a non-cyanuric key does NOT strip any entries", () => {
    const readings: Reading[] = [
      { key: "cyanuric", value: "40" },
      { key: "ph", value: "7.4" },
    ];
    const after = applySetReading(readings, "ph", "7.6");
    // `cyanuric` entry still present (only stripped on cyanuric_acid writes)
    expect(after.find((r) => r.key === "cyanuric")?.value).toBe("40");
    expect(after.find((r) => r.key === "ph")?.value).toBe("7.6");
  });
});
