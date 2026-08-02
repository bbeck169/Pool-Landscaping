/**
 * Phase 25 · Mobile Schedule JobTrackerTiles — descender-clip fix.
 *
 * The "p" in "Stops" was still being clipped on Android after
 * Phase 24. This suite locks the exact style-contract that keeps
 * descenders visible, so future refactors can't silently regress:
 *
 *   • label `lineHeight` >= `fontSize + 4` (buffer for descenders)
 *   • label `paddingBottom` >= 4 (belt-and-suspenders)
 *   • label `includeFontPadding: true` (Android descender pad)
 *   • label's immediate parent (`tile`) has NO `overflow: "hidden"`
 *   • label's immediate parent (`tile`) `paddingBottom` >= `borderRadius`
 *     so the descender never lands inside the corner-radius clip
 *
 * jsdom cannot render RN SVG + LinearGradient, so — like Phase 23 —
 * we source-inspect the mobile file and pattern-match the style
 * block.
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

const SRC = fs.readFileSync(
  path.resolve(__dirname, "../../../mobile/app/(app)/schedule/JobTrackerTiles.tsx"),
  "utf-8",
);

/** Extract the body of a StyleSheet.create key, e.g. `label: { ... }`.
 *  Returns just the inside of the outermost braces so downstream
 *  regexes don't have to worry about nested objects (the label /
 *  tile style bodies are flat single-level dicts).
 */
function extractStyleBody(key) {
  const rx = new RegExp(`${key}\\s*:\\s*\\{([\\s\\S]*?)\\}\\s*,`, "m");
  const m = SRC.match(rx);
  return m ? m[1] : null;
}

function readNumericProp(styleBody, prop) {
  const m = styleBody.match(new RegExp(`${prop}\\s*:\\s*(\\d+)`));
  return m ? parseInt(m[1], 10) : null;
}

describe("Phase 25 · JobTrackerTiles — label descender-clip contract", () => {
  it("label style block is present in the source", () => {
    const body = extractStyleBody("label");
    expect(body).not.toBeNull();
  });

  it("label has an explicit lineHeight >= fontSize + 4", () => {
    const body = extractStyleBody("label");
    const fontSize = readNumericProp(body, "fontSize");
    const lineHeight = readNumericProp(body, "lineHeight");
    expect(fontSize).not.toBeNull();
    expect(lineHeight).not.toBeNull();
    // fontSize + 4 is the documented minimum for a safe descender
    // buffer on Android RN. We ship fontSize=15 / lineHeight=22 —
    // 7dp buffer, well over spec.
    expect(lineHeight).toBeGreaterThanOrEqual(fontSize + 4);
  });

  it("label has paddingBottom >= 4 OR paddingVertical >= 4", () => {
    const body = extractStyleBody("label");
    const pb = readNumericProp(body, "paddingBottom");
    const pv = readNumericProp(body, "paddingVertical");
    const effective = Math.max(pb || 0, pv || 0);
    expect(effective).toBeGreaterThanOrEqual(4);
  });

  it("label explicitly sets includeFontPadding: true (Android descender pad)", () => {
    const body = extractStyleBody("label");
    expect(body).toMatch(/includeFontPadding\s*:\s*true/);
  });

  it("label's immediate parent (tile) has NO overflow: 'hidden'", () => {
    const body = extractStyleBody("tile");
    expect(body).not.toBeNull();
    // The label <Text> is a direct child of the LinearGradient
    // container styled by `tile`. If `overflow: "hidden"` were set
    // here, RN would clip the descender at the tile boundary; we
    // rely on paddingBottom > borderRadius instead.
    expect(body).not.toMatch(/overflow\s*:\s*['"]hidden['"]/);
  });

  it("tile paddingBottom >= tile borderRadius (descender safe zone)", () => {
    const body = extractStyleBody("tile");
    const br = readNumericProp(body, "borderRadius");
    const pb = readNumericProp(body, "paddingBottom");
    expect(br).not.toBeNull();
    expect(pb).not.toBeNull();
    // If paddingBottom < borderRadius, the label's descender can
    // land inside the corner-radius arc and get clipped by the
    // LinearGradient's implicit corner mask on Android.
    expect(pb).toBeGreaterThanOrEqual(br);
  });

  it("<Text> element for the label does NOT use adjustsFontSizeToFit", () => {
    // adjustsFontSizeToFit + numberOfLines=1 tripped RN's Android
    // shrink-to-fit descender bug — the shrunk text kept the
    // original baseline math, chopping the "p" tail. Phase 25
    // drops the prop.
    const labelBlock = SRC.match(
      /<Text[\s\S]*?testID=\{`\$\{testID\}-label`\}[\s\S]*?>[\s\S]*?<\/Text>/,
    );
    expect(labelBlock).not.toBeNull();
    expect(labelBlock[0]).not.toMatch(/adjustsFontSizeToFit/);
  });

  it("label is still a plain <Text> sibling of the ring (not inside SVG)", () => {
    // Regression guard against Phase 24: descender fix must not
    // move the label back inside the SVG viewBox.
    const svgOpen = SRC.indexOf("<Svg");
    const svgClose = SRC.indexOf("</Svg>");
    const insideSvg = SRC.slice(svgOpen, svgClose);
    expect(insideSvg.includes("${testID}-label")).toBe(false);
  });
});
