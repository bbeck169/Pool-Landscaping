/**
 * Phase 23 · Mobile Schedule — Job Tracker Progress Ring Tiles.
 *
 * Two side-by-side circular progress-ring tiles rendered above the
 * existing schedule grid on the mobile Expo app. Left tile = service
 * stops; right tile = repair stops. Fully client-side — classification
 * uses ``job.service_type`` keyword matching, no backend change.
 *
 * Design decisions
 * ----------------
 * - **SVG lib** ``react-native-svg`` (already installed) for the
 *   progress ring. Circle + arc is 4 lines of markup; no dep needed
 *   for a stroke-dasharray approach.
 * - **Gradient** ``expo-linear-gradient`` (already installed) —
 *   purple → blue diagonal per the reference screenshot.
 * - **Classification** keyword match on ``service_type`` — any string
 *   containing "repair"/"fix"/"broken" is a repair; everything else
 *   (including nulls) is a service. Landscape jobs count as services
 *   per the reference — the split is service vs repair, not
 *   pool vs landscape.
 * - **Empty state** — ``0/0`` renders just the track ring, no green
 *   arc.
 * - **Loading state** — parent passes ``loading`` and we render a
 *   50% opacity ring so the layout doesn't jump.
 */
import React, { useMemo } from "react";
import { View, Text, StyleSheet } from "react-native";
import Svg, { Circle } from "react-native-svg";
import { LinearGradient } from "expo-linear-gradient";

type Job = { status?: string | null; service_type?: string | null };

type Props = { jobs: Job[]; loading?: boolean };

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

function ProgressRing({ done, total, size = 132 }: { done: number; total: number; size?: number }) {
  const stroke = 12;
  const r = (size - stroke) / 2;
  const cx = size / 2;
  const cy = size / 2;
  const c = 2 * Math.PI * r;
  const pct = total > 0 ? Math.max(0, Math.min(1, done / total)) : 0;
  return (
    <Svg width={size} height={size}>
      {/* Track */}
      <Circle
        cx={cx} cy={cy} r={r}
        stroke="rgba(255,255,255,0.28)"
        strokeWidth={stroke}
        fill="none"
      />
      {/* Progress arc — omit entirely when total=0 to match "empty ring" spec */}
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
          // ↑ rotate so the arc starts at 12 o'clock instead of 3.
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
        <View style={styles.ringWrap}>
          <ProgressRing done={done} total={total} size={132} />
          <View style={styles.ringCenter} pointerEvents="none">
            <Text style={styles.bigNum} testID={`${testID}-count`}>
              {done}/{total}
            </Text>
          </View>
        </View>
        <Text style={styles.label} testID={`${testID}-label`}>{label}</Text>
      </LinearGradient>
    </View>
  );
}

export default function JobTrackerTiles({ jobs, loading }: Props) {
  const c = useMemo(() => computeCounts(jobs), [jobs]);
  return (
    <View style={styles.row} testID="schedule-tracker-row">
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
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", gap: 12, paddingHorizontal: 12,
          paddingTop: 12, paddingBottom: 8 },
  tileWrap: { flex: 1, aspectRatio: 1 },
  tile: { flex: 1, borderRadius: 16, padding: 16,
           alignItems: "center", justifyContent: "space-between" },
  ringWrap: { alignItems: "center", justifyContent: "center",
               marginTop: 4 },
  ringCenter: { position: "absolute", top: 0, left: 0, right: 0,
                 bottom: 0, alignItems: "center",
                 justifyContent: "center" },
  bigNum: { color: "#fff", fontSize: 28, fontWeight: "700" },
  label: { color: "rgba(255,255,255,0.92)", fontSize: 14,
            fontWeight: "600", marginTop: 6 },
});
