import React, { useMemo, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, TextInput, Platform } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { Header } from "@/src/components/widgets";
import { Sheet } from "@/src/components/ui";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";

type Tool = "dosing" | "volume" | "salt" | "lsi";

const TOOLS: { key: Tool; icon: any; title: string; desc: string }[] = [
  { key: "dosing", icon: "flask-outline", title: "Chemical Dosing", desc: "Enter water readings and get recommended chemical doses — no job required." },
  { key: "volume", icon: "cube-outline", title: "Pool Volume", desc: "Estimate gallons from pool shape & dimensions." },
  { key: "salt", icon: "beaker-outline", title: "Salt / Salinity", desc: "How much salt to add to reach your target salinity." },
  { key: "lsi", icon: "water-outline", title: "LSI — Water Balance", desc: "Langelier Saturation Index to keep water balanced and equipment safe." },
];

function NumInput({ label, unit, value, onChangeText, testID }: any) {
  return (
    <View style={{ flex: 1 }}>
      <Text style={styles.inputLabel}>{label}</Text>
      <View style={styles.inputWrap}>
        <TextInput
          testID={testID}
          style={styles.input}
          value={value}
          onChangeText={onChangeText}
          keyboardType="decimal-pad"
          placeholder="0"
          placeholderTextColor={colors.muted}
        />
        {unit ? <Text style={styles.unit}>{unit}</Text> : null}
      </View>
    </View>
  );
}

function Result({ label, value, hint, tone = "brand" }: { label: string; value: string; hint?: string; tone?: "brand" | "success" | "warning" | "error" }) {
  const bg = tone === "success" ? "#DCFCE7" : tone === "warning" ? "#FEF9C3" : tone === "error" ? "#FEE2E2" : colors.brandTertiary;
  const fg = tone === "success" ? colors.success : tone === "warning" ? "#A16207" : tone === "error" ? colors.error : colors.onBrandTertiary;
  return (
    <View style={[styles.resultBox, { backgroundColor: bg }]} testID="calc-result">
      <Text style={[styles.resultLabel, { color: fg }]}>{label}</Text>
      <Text style={[styles.resultValue, { color: fg }]}>{value}</Text>
      {hint ? <Text style={[styles.resultHint, { color: fg }]}>{hint}</Text> : null}
    </View>
  );
}

const n = (s: string) => parseFloat(s) || 0;

function VolumeCalc() {
  const [shape, setShape] = useState<"rect" | "circle" | "oval">("rect");
  const [l, setL] = useState("");
  const [w, setW] = useState("");
  const [d, setD] = useState("");
  const [depth, setDepth] = useState("");
  const gallons = useMemo(() => {
    const avg = n(depth);
    if (shape === "rect") return n(l) * n(w) * avg * 7.48;
    if (shape === "circle") return Math.PI * Math.pow(n(d) / 2, 2) * avg * 7.48;
    return n(l) * n(w) * avg * 7.48 * 0.785; // oval
  }, [shape, l, w, d, depth]);
  return (
    <View style={{ gap: spacing.md }}>
      <Text style={styles.inputLabel}>SHAPE</Text>
      <View style={styles.segRow}>
        {(["rect", "circle", "oval"] as const).map((s) => (
          <Pressable key={s} style={[styles.seg, shape === s && styles.segActive]} onPress={() => setShape(s)} testID={`shape-${s}`}>
            <Text style={[styles.segText, shape === s && { color: "#fff" }]}>{s === "rect" ? "Rectangle" : s === "circle" ? "Circle" : "Oval"}</Text>
          </Pressable>
        ))}
      </View>
      <View style={styles.row}>
        {shape === "circle" ? (
          <NumInput label="DIAMETER" unit="ft" value={d} onChangeText={setD} testID="vol-diameter" />
        ) : (
          <>
            <NumInput label="LENGTH" unit="ft" value={l} onChangeText={setL} testID="vol-length" />
            <NumInput label="WIDTH" unit="ft" value={w} onChangeText={setW} testID="vol-width" />
          </>
        )}
      </View>
      <NumInput label="AVERAGE DEPTH" unit="ft" value={depth} onChangeText={setDepth} testID="vol-depth" />
      <Result label="ESTIMATED VOLUME" value={gallons ? `${Math.round(gallons).toLocaleString()} gal` : "—"} hint="Volume = area × avg depth × 7.48" />
    </View>
  );
}

function SaltCalc() {
  const [gal, setGal] = useState("");
  const [cur, setCur] = useState("");
  const [tgt, setTgt] = useState("3200");
  const lbs = useMemo(() => {
    const delta = n(tgt) - n(cur);
    if (delta <= 0) return 0;
    return (delta * n(gal) * 8.34) / 1_000_000;
  }, [gal, cur, tgt]);
  return (
    <View style={{ gap: spacing.md }}>
      <NumInput label="POOL VOLUME" unit="gal" value={gal} onChangeText={setGal} testID="salt-gal" />
      <View style={styles.row}>
        <NumInput label="CURRENT" unit="ppm" value={cur} onChangeText={setCur} testID="salt-cur" />
        <NumInput label="TARGET" unit="ppm" value={tgt} onChangeText={setTgt} testID="salt-tgt" />
      </View>
      <Result
        label="SALT TO ADD"
        value={lbs > 0 ? `${lbs.toFixed(1)} lbs (${(lbs / 40).toFixed(1)} bags)` : n(tgt) <= n(cur) && n(cur) > 0 ? "At/above target" : "—"}
        hint="Based on 40 lb bags"
        tone={lbs > 0 ? "brand" : "success"}
      />
    </View>
  );
}

function DosingCalc() {
  const [gal, setGal] = useState("10000");
  const [fcCur, setFcCur] = useState("");
  const [fcTgt, setFcTgt] = useState("3");
  const [cya, setCya] = useState("");
  const [taCur, setTaCur] = useState("");
  const [taTgt, setTaTgt] = useState("100");
  const factor = n(gal) / 10000;
  const fcOz = useMemo(() => Math.max(0, (n(fcTgt) - n(fcCur))) * factor * 10.7, [fcCur, fcTgt, factor]);
  // 3" trichlor tabs (~8 oz, 90% available Cl): ~1.7 oz of trichlor raises 1 ppm FAC per 10k gal.
  const tabs = useMemo(() => Math.max(0, (n(fcTgt) - n(fcCur))) * factor * 1.7 / 8, [fcCur, fcTgt, factor]);
  const taLbs = useMemo(() => Math.max(0, (n(taTgt) - n(taCur)) / 10) * factor * 1.5, [taCur, taTgt, factor]);
  // Trichlor tabs add cyanuric acid (stabilizer). Above ~70 ppm chlorine gets "locked";
  // at/above 100 ppm, steer off tabs entirely to avoid over-stabilizing the pool.
  const cyaVal = n(cya);
  const cyaBlock = cya !== "" && cyaVal >= 100;
  const cyaWarn = cya !== "" && cyaVal >= 70 && cyaVal < 100;
  return (
    <View style={{ gap: spacing.md }}>
      <NumInput label="POOL VOLUME" unit="gal" value={gal} onChangeText={setGal} testID="dose-gal" />
      <Text style={styles.groupLabel}>Free Chlorine</Text>
      <View style={styles.row}>
        <NumInput label="CURRENT" unit="ppm" value={fcCur} onChangeText={setFcCur} testID="dose-fc-cur" />
        <NumInput label="TARGET" unit="ppm" value={fcTgt} onChangeText={setFcTgt} testID="dose-fc-tgt" />
      </View>
      <NumInput label="CYANURIC ACID (STABILIZER)" unit="ppm" value={cya} onChangeText={setCya} testID="dose-cya" />
      {fcOz > 0 ? (
        <>
          {cyaBlock ? (
            <Result
              label="⚠ CYA TOO HIGH FOR TABS"
              value="Use liquid chlorine"
              hint={`Stabilizer is ${cyaVal} ppm (ideal 30–50). Trichlor tabs add more CYA and would over-stabilize the pool — use liquid only.`}
              tone="warning"
            />
          ) : (
            <Text style={styles.orHead}>Choose one option to raise chlorine:</Text>
          )}
          <Result
            label={cyaBlock ? "LIQUID CHLORINE (12.5%) · RECOMMENDED" : "OPTION 1 · LIQUID CHLORINE (12.5%)"}
            value={`${fcOz.toFixed(0)} fl oz`}
            hint="Raises chlorine immediately and adds no stabilizer."
            tone="brand"
          />
          {!cyaBlock ? (
            <>
              <Text style={styles.orText}>— or —</Text>
              <Result
                label={'OPTION 2 · 3" TRICHLOR TABS (8 oz)'}
                value={`${tabs < 1 ? tabs.toFixed(1) : Math.ceil(tabs)} tab${Math.ceil(tabs) === 1 && tabs >= 1 ? "" : "s"}`}
                hint={
                  cyaWarn
                    ? `⚠ CYA is ${cyaVal} ppm — getting high. Tabs add more stabilizer; prefer liquid until CYA drops below 50.`
                    : "Dissolve slowly in a floater/feeder — best for steady maintenance. Tabs also lower pH & add stabilizer (CYA)."
                }
                tone={cyaWarn ? "warning" : "success"}
              />
            </>
          ) : null}
        </>
      ) : (
        <Result label="FREE CHLORINE" value={n(fcCur) > 0 ? "At/above target ✓" : "—"} tone="success" />
      )}
      <Text style={styles.groupLabel}>Total Alkalinity (baking soda)</Text>
      <View style={styles.row}>
        <NumInput label="CURRENT" unit="ppm" value={taCur} onChangeText={setTaCur} testID="dose-ta-cur" />
        <NumInput label="TARGET" unit="ppm" value={taTgt} onChangeText={setTaTgt} testID="dose-ta-tgt" />
      </View>
      <Result label="ADD BAKING SODA" value={taLbs > 0 ? `${taLbs.toFixed(1)} lbs` : "—"} tone="success" />
    </View>
  );
}

const TF_TABLE: [number, number][] = [[32, 0.0], [37, 0.1], [46, 0.2], [53, 0.3], [60, 0.4], [66, 0.5], [76, 0.6], [84, 0.7], [94, 0.8], [105, 0.9]];
function tempFactor(f: number) {
  if (f <= 32) return 0;
  if (f >= 105) return 0.9;
  for (let i = 0; i < TF_TABLE.length - 1; i++) {
    const [t0, v0] = TF_TABLE[i];
    const [t1, v1] = TF_TABLE[i + 1];
    if (f >= t0 && f <= t1) return v0 + ((f - t0) / (t1 - t0)) * (v1 - v0);
  }
  return 0.6;
}

function LsiCalc() {
  const [ph, setPh] = useState("7.5");
  const [temp, setTemp] = useState("78");
  const [ch, setCh] = useState("");
  const [ta, setTa] = useState("");
  const [cya, setCya] = useState("");
  const [tds, setTds] = useState("1000");
  const [corr, setCorr] = useState<"third" | "quarter" | "none">("third");
  const lsi = useMemo(() => {
    if (!n(ch) || !n(ta) || !n(ph)) return null;
    const cyaAdj = corr === "third" ? n(cya) / 3 : corr === "quarter" ? n(cya) / 4 : 0;
    const carbAlk = Math.max(1, n(ta) - cyaAdj);
    const cf = Math.log10(n(ch)) - 0.4;
    const af = Math.log10(carbAlk);
    const tf = tempFactor(n(temp));
    const tdsConst = n(tds) >= 1000 ? 12.2 : 12.1;
    return n(ph) + tf + cf + af - tdsConst;
  }, [ph, temp, ch, ta, cya, tds, corr]);
  const interp = lsi === null ? null : lsi < -0.3 ? { t: "Corrosive — add alkalinity/calcium", tone: "error" as const } : lsi > 0.3 ? { t: "Scaling — lower pH/alkalinity", tone: "warning" as const } : { t: "Balanced water ✓", tone: "success" as const };
  return (
    <View style={{ gap: spacing.md }}>
      <View style={styles.row}>
        <NumInput label="PH" value={ph} onChangeText={setPh} testID="lsi-ph" />
        <NumInput label="WATER TEMP" unit="°F" value={temp} onChangeText={setTemp} testID="lsi-temp" />
      </View>
      <View style={styles.row}>
        <NumInput label="CALCIUM HARDNESS" unit="ppm" value={ch} onChangeText={setCh} testID="lsi-ch" />
        <NumInput label="TOTAL ALKALINITY" unit="ppm" value={ta} onChangeText={setTa} testID="lsi-ta" />
      </View>
      <View style={styles.row}>
        <NumInput label="CYANURIC ACID" unit="ppm" value={cya} onChangeText={setCya} testID="lsi-cya" />
        <NumInput label="TDS" unit="ppm" value={tds} onChangeText={setTds} testID="lsi-tds" />
      </View>
      <Text style={styles.inputLabel}>CYA ALKALINITY CORRECTION</Text>
      <View style={styles.segRow}>
        {([["third", "− ⅓ CYA"], ["quarter", "− ¼ CYA"], ["none", "None"]] as const).map(([k, lbl]) => (
          <Pressable key={k} style={[styles.seg, corr === k && styles.segActive]} onPress={() => setCorr(k)} testID={`lsi-corr-${k}`}>
            <Text style={[styles.segText, corr === k && { color: "#fff" }]}>{lbl}</Text>
          </Pressable>
        ))}
      </View>
      <Result
        label="SATURATION INDEX (LSI)"
        value={lsi === null ? "—" : lsi.toFixed(2)}
        hint={interp ? interp.t : "Enter pH, calcium hardness, alkalinity & temp"}
        tone={interp ? interp.tone : "brand"}
      />
    </View>
  );
}

export default function Tools() {
  const [open, setOpen] = useState<Tool | null>(null);
  const active = TOOLS.find((t) => t.key === open);
  return (
    <View style={styles.root}>
      <Header title="Calculators" subtitle="Pool chemistry & sizing tools" />
      <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}>
        {TOOLS.map((t) => (
          <Pressable key={t.key} style={styles.card} onPress={() => setOpen(t.key)} testID={`tool-${t.key}`}>
            <View style={styles.cardIcon}>
              <Ionicons name={t.icon} size={22} color={colors.brand} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.cardTitle}>{t.title}</Text>
              <Text style={styles.cardDesc}>{t.desc}</Text>
            </View>
            <Ionicons name="chevron-forward" size={18} color={colors.muted} />
          </Pressable>
        ))}
      </ScrollView>

      <Sheet visible={!!open} onClose={() => setOpen(null)} title={active?.title} testID="calc-sheet">
        {open === "volume" ? <VolumeCalc /> : null}
        {open === "salt" ? <SaltCalc /> : null}
        {open === "dosing" ? <DosingCalc /> : null}
        {open === "lsi" ? <LsiCalc /> : null}
      </Sheet>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  card: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.lg,
    borderWidth: 1,
    borderColor: colors.border,
    marginBottom: spacing.md,
  },
  cardIcon: { width: 44, height: 44, borderRadius: radius.md, backgroundColor: colors.brandTertiary, alignItems: "center", justifyContent: "center" },
  cardTitle: { fontFamily: font.semibold, fontSize: fontSize.lg, color: colors.onSurface },
  cardDesc: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  row: { flexDirection: "row", gap: spacing.md },
  inputLabel: { fontFamily: font.semibold, fontSize: 11, letterSpacing: 0.8, color: colors.onSurfaceSecondary, marginBottom: spacing.xs },
  groupLabel: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.brand, marginTop: spacing.xs },
  inputWrap: { flexDirection: "row", alignItems: "center", backgroundColor: colors.surfaceSecondary, borderWidth: 1.5, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: spacing.md, height: 50 },
  input: { flex: 1, fontFamily: font.regular, fontSize: fontSize.lg, color: colors.onSurface, ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}) },
  unit: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted },
  segRow: { flexDirection: "row", gap: spacing.sm },
  seg: { flex: 1, height: 40, borderRadius: radius.md, alignItems: "center", justifyContent: "center", backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border },
  segActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  segText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  resultBox: { borderRadius: radius.md, padding: spacing.lg, marginTop: spacing.sm },
  resultLabel: { fontFamily: font.semibold, fontSize: 11, letterSpacing: 0.8 },
  resultValue: { fontFamily: font.bold, fontSize: fontSize["2xl"], marginTop: 2 },
  resultHint: { fontFamily: font.regular, fontSize: fontSize.sm, marginTop: 2 },
  orHead: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, marginTop: spacing.xs },
  orText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.muted, textAlign: "center", marginVertical: 2 },
});
