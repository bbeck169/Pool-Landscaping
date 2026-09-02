/**
 * Phase 23 · Mobile Schedule — Job Tracker Progress Ring Tiles.
 * Phase 25b · Feb-2026 — geometry rewrite.
 *
 * # Root cause the previous fixes missed
 *
 * Phase 25 hardened label typography (lineHeight, includeFontPadding,
 * paddingBottom, removed adjustsFontSizeToFit) but did not touch tile
 * geometry. The real bug was ``tileWrap: { flex: 1, aspectRatio: 1 }``
 * — on a narrow Android phone (≤ ~370dp), the aspect-locked height
 * (≈ 162dp) can't fit ``ring(108) + gap(10) + label(28) = 146dp`` of
 * content inside the ``paddingTop 14 + paddingBottom 20`` interior
 * (128dp usable). The label spilled past the tile's bottom edge
 * straight into the LinearGradient's implicit corner-radius clip
 * mask — exactly what the user's screenshot shows.
 *
 * Phase 25's source-inspection vitest never caught this because it
 * verified style *values* (lineHeight, paddingBottom, borderRadius)
 * without ever checking whether the tile's outer dimensions could
 * actually hold the inner content.
 *
 * # Phase 25b fixes
 *
 * 1. **Drop aspectRatio.** Tile now sizes to its natural content
 *    height. Row still uses ``flex: 1`` for equal column widths.
 * 2. **Hard-clamp the SVG** to 96 dp inside a fixed-size ``<View>``
 *    wrapper so nothing can grow it, ever.
 * 3. **"X/Y" numeric stays OUT of the SVG viewBox** (rendered as an
 *    absolutely-positioned ``<Text>`` overlay on the fixed-size
 *    ring wrapper — no SVG glyph clipping possible).
 * 4. **Label lives in its own sibling ``<View>``** — never nested in
 *    another ``<Text>``, so ``includeFontPadding`` cannot be
 *    silently disabled by parent-text inheritance.
 * 5. **Label prop hardening** — no ``numberOfLines``. Two-line wrap
 *    on narrow phones is acceptable and expected.
 * 6. **Explicit ``minHeight: 180`` on the tile** so the tile can
 *    never be shorter than the natural content stack even under
 *    hypothetical parent flex collapse.
 *
 * No ``overflow: "hidden"`` anywhere in the tile subtree.
 */
import React, { useMemo } from "react";
import { View, Text, StyleSheet } from "react-native";
import Svg, { Circle } from "react-native-svg";
import { LinearGradient } from "expo-linear-gradient";

type Job = { status?: string | null; service_type?: string | null };

type Props = { jobs: Job[]; loading?: boolean; listError?: string };

const _REPAIR_RX = /(repair|fix|broken|leak|replace)/i;

export function classifyJob(job: Job): "repair" | "service" {
  const st = (job.service_type || "").toString();
  return _REPAIR_RX.test(st) ? "repair" : "service";
}

export function computeCounts(jobs: Job[]) {
  let svcTotal = 0, svcDone = 0, repTotal = 0, repDone = 0;
  for (const j of jobs || []) {
    const isDone = (j.status || "").toLowerCase() === "completed";
    if (classifyJob(j) === "repair") {
      repTotal += 1;
      if (isDone) repDone += 1;
    } else {
      svcTotal += 1;
      if (isDone) svcDone += 1;
    }
  }
  return { svcTotal, svcDone, repTotal, repDone };
}

// Phase 25b · SVG size is hard-clamped to 96 dp. The wrapper <View>
// below fixes its parent box to the same dimensions so nothing
// downstream can inflate the ring.
const RING_SIZE = 96;

function ProgressRing({ done, total }: { done: number; total: number }) {
  const size = RING_SIZE;
  const stroke = 10;
  const r = (size - stroke) / 2;
  const cx = size / 2;
  const cy = size / 2;
  const c = 2 * Math.PI * r;
  const pct = total > 0 ? Math.max(0, Math.min(1, done / total)) : 0;
  return (
    <Svg width={size} height={size}>
      <Circle
        cx={cx} cy={cy} r={r}
        stroke="rgba(255,255,255,0.28)"
        strokeWidth={stroke}
        fill="none"
      />
      {total > 0 && pct > 0 ? (
        <Circle
          cx={cx} cy={cy} r={r}
          stroke="#22c55e"
          strokeWidth={stroke}
          strokeLinecap="round"
          fill="none"
          strokeDasharray={`${c * pct} ${c * (1 - pct)}`}
          strokeDashoffset={c * 0.25}
          transform={`rotate(-90 ${cx} ${cy})`}
        />
      ) : null}
    </Svg>
  );
}

function Tile({ label, done, total, gradient, testID, loading }: {
  label: string;
  done: number;
  total: number;
  gradient: readonly [string, string, ...string[]];
  testID: string;
  loading?: boolean;
}) {
  return (
    <View style={styles.tileWrap} testID={testID}>
      <LinearGradient
        colors={gradient}
        start={{ x: 0, y: 0 }}
        end={{ x: 1, y: 1 }}
        style={[styles.tile, loading && { opacity: 0.5 }]}
      >
        {/* Phase 25b · fixed-size SVG wrapper. RING_SIZE x RING_SIZE
            hard-clamp so no ancestor flex can grow the ring past 96
            dp — that was the geometry bug driving label spill on
            narrow Android devices. */}
        <View style={styles.ringSvgWrap}>
          <ProgressRing done={done} total={total} />
          <View style={styles.ringCenter} pointerEvents="none">
            <Text style={styles.bigNum} testID={`${testID}-count`}>
              {done}/{total}
            </Text>
          </View>
        </View>
        {/* Phase 25b · label lives in its OWN sibling <View>, not
            nested inside a parent <Text>. Guarantees
            ``includeFontPadding`` on the <Text> takes effect
            (a parent <Text> would silently disable it on Android).
            paddingTop/Bottom is scoped to this wrapper so the tile's
            own padding numbers stay independent. */}
        <View style={styles.labelWrap}>
          <Text
            style={styles.label}
            testID={`${testID}-label`}
          >
            {label}
          </Text>
        </View>
      </LinearGradient>
    </View>
  );
}

export default function JobTrackerTiles({ jobs, loading, listError }: Props) {
  const c = useMemo(() => computeCounts(jobs), [jobs]);
  return (
    <View testID="schedule-tracker-row">
      <View style={styles.row}>
        <Tile
          label="Service Stops"
          done={c.svcDone}
          total={c.svcTotal}
          gradient={["#7c3aed", "#3b82f6"]}
          testID="schedule-tile-service"
          loading={loading}
        />
        <Tile
          label="Repair Stops"
          done={c.repDone}
          total={c.repTotal}
          gradient={["#7c3aed", "#3b82f6"]}
          testID="schedule-tile-repair"
          loading={loading}
        />
      </View>
      {/* K15 · list-vs-tile coordination: when list failed but tiles
          have stale counters, explain why the list is empty. */}
      {listError ? (
        <Text
          style={styles.listErrorHint}
          testID="schedule-tiles-list-error-hint"
        >
          ⚠ Schedule list failed to load. Tap Retry above to load jobs.
        </Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", gap: 12, paddingHorizontal: 12,
          paddingTop: 12, paddingBottom: 8 },
  // Phase 25b · no aspectRatio! Tiles compute their own natural
  // height from the content stack (paddingTop + ring + label
  // wrapper + paddingBottom). Row still shares column width evenly
  // via flex:1.
  tileWrap: { flex: 1 },
  // Phase 25b · minHeight 180 is the belt-and-suspenders guard so
  // any hypothetical parent-flex collapse can't shorten the tile
  // below the natural content stack (~176 dp).
  // Explicitly NO ``overflow: "hidden"`` — the label's box needs to
  // sit inside the LinearGradient's rounded clip mask, and the
  // paddingBottom + labelWrap paddingBottom together guarantee the
  // descender never touches the corner-radius arc.
  tile: {
    flex: 1,
    minHeight: 180,
    borderRadius: 16,
    paddingHorizontal: 12,
    paddingTop: 14,
    paddingBottom: 6,
    alignItems: "center",
    justifyContent: "flex-start",
  },
  // Phase 25b · fixed-size wrapper. Enforces the ring bounding box
  // regardless of ancestor flex. All ring rendering (SVG + centered
  // numeric overlay) is confined to this 96 x 96 box.
  ringSvgWrap: {
    width: RING_SIZE, height: RING_SIZE,
    alignItems: "center", justifyContent: "center",
    marginTop: 2,
  },
  // Absolute overlay lives INSIDE ringSvgWrap; positioning is
  // relative to that fixed 96 x 96 box, so the "X/Y" text is always
  // vertically + horizontally centered on the ring.
  ringCenter: {
    position: "absolute", top: 0, left: 0, right: 0, bottom: 0,
    alignItems: "center", justifyContent: "center",
  },
  bigNum: { color: "#fff", fontSize: 22, fontWeight: "700" },
  // Phase 25b · label wrapper is a sibling <View> — NOT nested in
  // another <Text>. paddingTop separates it from the ring; the
  // paddingBottom (10) inside the wrapper is on top of the tile's
  // own paddingBottom (6), giving the descender a full 16 dp gap
  // from the tile bottom edge.
  labelWrap: {
    paddingTop: 4,
    paddingBottom: 10,
    alignSelf: "stretch",
    alignItems: "center",
  },
  // Phase 25b · typography stays hardened from Phase 25:
  //   • explicit lineHeight (22) — 8 dp buffer over fontSize (14).
  //   • paddingBottom on the Text (6) — belt-and-suspenders atop the
  //     wrapper's own paddingBottom.
  //   • includeFontPadding: true — Android descender pad guaranteed.
  //   • NO numberOfLines / NO adjustsFontSizeToFit — 2-line wrap on
  //     very narrow phones is acceptable and preserves the descender.
  label: {
    color: "rgba(255,255,255,0.95)",
    fontSize: 14,
    fontWeight: "600",
    lineHeight: 22,
    paddingBottom: 6,
    includeFontPadding: true,
    textAlign: "center",
    letterSpacing: 0.2,
  },
  // K15 · list-vs-tile state coordination hint
  listErrorHint: {
    fontWeight: "500",
    fontSize: 12,
    color: "#991B1B",
    textAlign: "center",
    paddingHorizontal: 12,
    paddingVertical: 6,
  },
});
