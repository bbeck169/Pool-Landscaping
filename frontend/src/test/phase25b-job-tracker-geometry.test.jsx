/**
 * Phase 25b · Feb-2026 — JobTrackerTiles geometry contract vitest.
 *
 * The Phase 25 vitest only checked style *values*
 * (lineHeight, paddingBottom, includeFontPadding). It never verified
 * that the tile's outer geometry could actually hold the inner
 * content stack — which is exactly the bug the user's Android
 * screenshot exposed: narrow-phone tiles with ``aspectRatio: 1``
 * were too short and the label spilled past the LinearGradient's
 * corner-radius clip.
 *
 * This suite locks the Phase 25b geometry-first contract:
 *
 *   1. Tile MUST NOT set ``aspectRatio`` (drops the narrow-phone
 *      squish geometry).
 *   2. Tile MUST have ``minHeight`` >= 180 (natural content stack
 *      is ~176 dp — 4 dp safety margin).
 *   3. SVG MUST live inside a fixed-size ``<View>`` wrapper with
 *      ``width === height`` and both <= 100 dp.
 *   4. Label MUST live in its own sibling ``<View>`` (never
 *      nested in a parent ``<Text>``, which would silently
 *      disable ``includeFontPadding`` on Android).
 *   5. Label style: ``lineHeight`` >= ``fontSize + 6``,
 *      ``paddingBottom`` >= 6, ``includeFontPadding: true``.
 *   6. Label ``<Text>`` MUST NOT carry ``numberOfLines``.
 */
import fs from "fs";
import path from "path";
import { describe, it, expect } from "vitest";

const RAW = fs.readFileSync(
  path.resolve(
    __dirname, "../../../mobile/app/(app)/schedule/JobTrackerTiles.tsx",
  ),
  "utf-8",
);

/** Strip block comments and // … line comments so regex
 *  assertions only inspect executable code — not JSDoc that
 *  documents the OLD state (aspectRatio, numberOfLines, etc.).
 */
function stripComments(source) {
  const noBlock = source.replace(/\/\*[\s\S]*?\*\//g, "");
  return noBlock
    .split("\n")
    .map((line) => line.replace(/(^|[^:\\])\/\/.*$/, "$1"))
    .join("\n");
}

const SRC = stripComments(RAW);

function extractStyleBody(key) {
  const rx = new RegExp(`${key}\\s*:\\s*\\{([\\s\\S]*?)\\}\\s*,`, "m");
  const m = SRC.match(rx);
  return m ? m[1] : null;
}

function readNumericProp(body, prop) {
  const m = body.match(new RegExp(`${prop}\\s*:\\s*(\\d+)`));
  return m ? parseInt(m[1], 10) : null;
}

describe("Phase 25b · JobTrackerTiles geometry contract", () => {
  it("tile style block DOES NOT set aspectRatio (regression guard)", () => {
    const tile = extractStyleBody("tile");
    const tileWrap = extractStyleBody("tileWrap");
    expect(tile).not.toBeNull();
    expect(tile).not.toMatch(/aspectRatio\s*:/);
    // The wrap around the LinearGradient — where the previous
    // aspectRatio: 1 lived — must also be aspect-free.
    expect(tileWrap).not.toBeNull();
    expect(tileWrap).not.toMatch(/aspectRatio\s*:/);
  });

  it("tile has minHeight >= 180 dp", () => {
    const tile = extractStyleBody("tile");
    const minH = readNumericProp(tile, "minHeight");
    expect(minH).not.toBeNull();
    expect(minH).toBeGreaterThanOrEqual(180);
  });

  it("SVG lives in a fixed-size wrapper with width === height <= 100", () => {
    // The wrapper is `ringSvgWrap`. Both dimensions must resolve to
    // the same numeric value (or the same identifier — we accept
    // either) and be <= 100 dp.
    const wrap = extractStyleBody("ringSvgWrap");
    expect(wrap).not.toBeNull();
    // Grab both width and height — could be numeric literals OR
    // references to a shared constant (RING_SIZE).
    const wMatch = wrap.match(/width\s*:\s*([A-Za-z_$][\w$]*|\d+)/);
    const hMatch = wrap.match(/height\s*:\s*([A-Za-z_$][\w$]*|\d+)/);
    expect(wMatch).not.toBeNull();
    expect(hMatch).not.toBeNull();
    expect(wMatch[1]).toEqual(hMatch[1]);
    // If the wrapper uses a named constant, resolve it from source.
    const val = wMatch[1];
    let numeric;
    if (/^\d+$/.test(val)) {
      numeric = parseInt(val, 10);
    } else {
      const constMatch = SRC.match(
        new RegExp(`const\\s+${val}\\s*=\\s*(\\d+)`),
      );
      expect(constMatch).not.toBeNull();
      numeric = parseInt(constMatch[1], 10);
    }
    expect(numeric).toBeLessThanOrEqual(100);
  });

  it("label lives in its OWN <View> sibling (labelWrap), not nested in a <Text>", () => {
    // Primary assertion: the label <Text> block is preceded by an
    // opening <View style={styles.labelWrap}> — with only whitespace
    // and props (no other tag) between them. This is the exact
    // guard against the Android ``includeFontPadding`` inheritance
    // trap.
    expect(SRC).toMatch(
      /<View\s+style=\{styles\.labelWrap\}\s*>[\s\n]*<Text\b[\s\S]*?testID=\{`\$\{testID\}-label`\}/,
    );
    // Secondary — the labelWrap style body itself must exist.
    expect(extractStyleBody("labelWrap")).not.toBeNull();
  });

  it("label style: lineHeight >= fontSize + 6, paddingBottom >= 6, includeFontPadding true", () => {
    const body = extractStyleBody("label");
    expect(body).not.toBeNull();
    const fontSize = readNumericProp(body, "fontSize");
    const lineHeight = readNumericProp(body, "lineHeight");
    const paddingBottom = readNumericProp(body, "paddingBottom");
    expect(fontSize).not.toBeNull();
    expect(lineHeight).not.toBeNull();
    expect(paddingBottom).not.toBeNull();
    expect(lineHeight).toBeGreaterThanOrEqual(fontSize + 6);
    expect(paddingBottom).toBeGreaterThanOrEqual(6);
    expect(body).toMatch(/includeFontPadding\s*:\s*true/);
  });

  it("label <Text> element does NOT carry numberOfLines", () => {
    // Extract the label <Text> block explicitly and check the props.
    const labelText = SRC.match(
      /<Text[\s\S]*?testID=\{`\$\{testID\}-label`\}[\s\S]*?\/>|<Text[^>]*?testID=\{`\$\{testID\}-label`\}[^>]*?>[\s\S]*?<\/Text>/,
    );
    expect(labelText).not.toBeNull();
    expect(labelText[0]).not.toMatch(/numberOfLines/);
    // Also — safety net — ``adjustsFontSizeToFit`` stays out too.
    expect(labelText[0]).not.toMatch(/adjustsFontSizeToFit/);
  });

  it("no overflow: 'hidden' anywhere in the tile subtree", () => {
    // Belt-and-suspenders from the Phase 25 brief. The clip mask
    // that eats descenders lives on LinearGradient's borderRadius —
    // adding overflow:hidden to any ancestor would make it worse.
    const tile = extractStyleBody("tile");
    const tileWrap = extractStyleBody("tileWrap");
    const ringSvgWrap = extractStyleBody("ringSvgWrap");
    const labelWrap = extractStyleBody("labelWrap");
    for (const body of [tile, tileWrap, ringSvgWrap, labelWrap]) {
      if (body) expect(body).not.toMatch(/overflow\s*:\s*['"]hidden['"]/);
    }
  });

  it("regression guard — label still lives OUTSIDE the <Svg> viewBox", () => {
    // Phase 24 invariant. A future refactor that moved the label
    // back into SVG text would re-open the corner-clip bug.
    const svgOpen = SRC.indexOf("<Svg");
    const svgClose = SRC.indexOf("</Svg>");
    expect(svgOpen).toBeGreaterThan(-1);
    expect(svgClose).toBeGreaterThan(svgOpen);
    const insideSvg = SRC.slice(svgOpen, svgClose);
    expect(insideSvg.includes("${testID}-label")).toBe(false);
  });

  it("content-stack height math holds: ringSize + gap + label < tile minHeight - padding", () => {
    // The Phase 25b root-cause fix is that the tile's minHeight
    // guarantees enough vertical room for the content stack. We
    // verify the numbers still line up so a future style tweak
    // (e.g. bumping fontSize) doesn't silently re-open the spill.
    const tile = extractStyleBody("tile");
    const label = extractStyleBody("label");
    const labelWrap = extractStyleBody("labelWrap");
    const minH = readNumericProp(tile, "minHeight");
    const pt = readNumericProp(tile, "paddingTop") || 0;
    const pb = readNumericProp(tile, "paddingBottom") || 0;
    const lineHeight = readNumericProp(label, "lineHeight");
    const labelPBottom = readNumericProp(label, "paddingBottom") || 0;
    const wrapPTop = readNumericProp(labelWrap, "paddingTop") || 0;
    const wrapPBottom = readNumericProp(labelWrap, "paddingBottom") || 0;
    // Resolve RING_SIZE from source.
    const constMatch = SRC.match(/const\s+RING_SIZE\s*=\s*(\d+)/);
    const ringSize = parseInt(constMatch[1], 10);

    const contentStack =
      ringSize + wrapPTop + lineHeight + labelPBottom + wrapPBottom;
    const interior = minH - pt - pb;
    // Interior must accommodate the full content stack with room
    // to spare (>= 0). Any negative delta means overflow → spill
    // → clip.
    expect(interior).toBeGreaterThanOrEqual(contentStack);
  });
});
