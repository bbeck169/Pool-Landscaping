import React, { useCallback, useMemo, useRef, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  Platform,
  Alert,
  Animated,
  PanResponder } from "react-native";
import { Ionicons, MaterialCommunityIcons } from "@expo/vector-icons";
import Svg, { Line, Polygon, Circle, Defs, Pattern, Rect, Path } from "react-native-svg";
import ViewShot, { captureRef } from "react-native-view-shot";
import * as Sharing from "expo-sharing";
import * as FileSystem from "expo-file-system/legacy";
import { useLocalSearchParams, useRouter, useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { AdminOnly } from "@/src/components/AdminOnly";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import { Sheet, PrimaryButton } from "@/src/components/ui";
import AppTextInput from "@/src/components/ui/AppTextInput";

type El = {
  id: string;
  kind: string;
  label: string;
  x: number; // normalized top-left 0..1
  y: number;
  w: number; // normalized (fraction of canvas width)
  h: number; // normalized (fraction of canvas height)
  rotation: number;
  color: string;
  icon: string;
  set?: "mci" | "ion"; // icon family (default MaterialCommunityIcons)
  fill?: "grass" | "pavers" | "water" | "gravel" | "mulch" | "wood" | "concrete"; // textured surface fill
  round?: boolean;
};

type Pt = { x: number; y: number };

/** Photo-realistic-style textured fill for surface elements (SmartDraw-like). */
function TextureFill({ kind, w, h, color }: { kind: string; w: number; h: number; color: string }) {
  const id = `tex-${kind}`;
  let pattern: React.ReactNode = null;
  let size = 14;
  let bg = color + "40";
  if (kind === "grass") {
    size = 12; bg = "#DCFCE7";
    pattern = (
      <>
        <Path d="M2,12 L2,5 M4,12 L5,3 M6,12 L6,6 M8,12 L9,4 M10,12 L10,7" stroke="#16A34A" strokeWidth={1} fill="none" strokeLinecap="round" />
      </>
    );
  } else if (kind === "pavers") {
    size = 20; bg = "#EAE0D5";
    pattern = (
      <>
        <Rect x={0} y={0} width={20} height={10} fill="none" stroke="#B4A08A" strokeWidth={1} />
        <Rect x={0} y={10} width={20} height={10} fill="none" stroke="#B4A08A" strokeWidth={1} />
        <Line x1={10} y1={0} x2={10} y2={10} stroke="#B4A08A" strokeWidth={1} />
        <Line x1={0} y1={10} x2={0} y2={20} stroke="#B4A08A" strokeWidth={1} />
        <Line x1={20} y1={10} x2={20} y2={20} stroke="#B4A08A" strokeWidth={1} />
      </>
    );
  } else if (kind === "water") {
    size = 18; bg = "#BAE6FD";
    pattern = <Path d="M0,6 Q4.5,2 9,6 T18,6" stroke="#38BDF8" strokeWidth={1.3} fill="none" />;
  } else if (kind === "gravel") {
    size = 14; bg = "#E7E5E4";
    pattern = (
      <>
        <Circle cx={3} cy={4} r={1.3} fill="#8A8580" />
        <Circle cx={9} cy={3} r={1} fill="#8A8580" />
        <Circle cx={6} cy={9} r={1.4} fill="#8A8580" />
        <Circle cx={11} cy={10} r={1} fill="#8A8580" />
        <Circle cx={2} cy={11} r={1} fill="#8A8580" />
      </>
    );
  } else if (kind === "mulch") {
    size = 16; bg = "#D6C0A8";
    pattern = <Path d="M1,4 l4,-1 M7,7 l4,1 M2,11 l4,0 M9,3 l3,1" stroke="#7C4A1E" strokeWidth={1.4} strokeLinecap="round" />;
  } else if (kind === "wood") {
    size = 24; bg = "#E4CBA6";
    pattern = (
      <>
        <Line x1={0} y1={0} x2={24} y2={0} stroke="#B98C57" strokeWidth={1} />
        <Line x1={0} y1={6} x2={24} y2={6} stroke="#B98C57" strokeWidth={1} />
        <Line x1={0} y1={12} x2={24} y2={12} stroke="#B98C57" strokeWidth={1} />
        <Line x1={0} y1={18} x2={24} y2={18} stroke="#B98C57" strokeWidth={1} />
      </>
    );
  } else {
    // concrete
    size = 22; bg = "#E5E7EB";
    pattern = (
      <>
        <Line x1={0} y1={0} x2={22} y2={0} stroke="#C3C7CD" strokeWidth={1} />
        <Line x1={0} y1={0} x2={0} y2={22} stroke="#C3C7CD" strokeWidth={1} />
      </>
    );
  }
  return (
    <Svg width={w} height={h} style={StyleSheet.absoluteFill}>
      <Defs>
        <Pattern id={id} patternUnits="userSpaceOnUse" width={size} height={size}>
          <Rect width={size} height={size} fill={bg} />
          {pattern}
        </Pattern>
      </Defs>
      <Rect width={w} height={h} fill={`url(#${id})`} />
    </Svg>
  );
}

/** Icon renderer that mirrors freecads-style top-view blocks via MaterialCommunityIcons. */
function Glyph({ name, set, size, color }: { name: string; set?: "mci" | "ion"; size: number; color: string }) {
  if (set === "ion") return <Ionicons name={name as any} size={size} color={color} />;
  return <MaterialCommunityIcons name={name as any} size={size} color={color} />;
}

type PalItem = Omit<El, "id" | "x" | "y" | "rotation">;

// Mirrors freecads.com element categories (top-view CAD blocks) relevant to site/landscape plans.
const PALETTE: { group: string; items: PalItem[] }[] = [
  {
    group: "Pool & Water",
    items: [
      { kind: "pool", label: "Pool", icon: "pool", color: "#38BDF8", w: 0.34, h: 0.42, fill: "water" },
      { kind: "spa", label: "Spa / Hot tub", icon: "hot-tub", color: "#22D3EE", w: 0.14, h: 0.2, round: true },
      { kind: "fountain", label: "Fountain", icon: "fountain", color: "#60A5FA", w: 0.14, h: 0.14, round: true },
      { kind: "pond", label: "Pond", icon: "water", color: "#0EA5E9", w: 0.2, h: 0.16, round: true, fill: "water" },
      { kind: "stream", label: "Water feature", icon: "waves", color: "#38BDF8", w: 0.24, h: 0.1, fill: "water" },
    ],
  },
  {
    group: "Trees",
    items: [
      { kind: "tree", label: "Tree", icon: "tree", color: "#16A34A", w: 0.13, h: 0.17, round: true },
      { kind: "pine", label: "Pine", icon: "pine-tree", color: "#15803D", w: 0.12, h: 0.17, round: true },
      { kind: "palm", label: "Palm", icon: "palm-tree", color: "#65A30D", w: 0.12, h: 0.18, round: true },
      { kind: "cactus", label: "Cactus", icon: "cactus", color: "#4D7C0F", w: 0.08, h: 0.14, round: true },
      { kind: "cluster", label: "Tree cluster", icon: "forest", color: "#166534", w: 0.2, h: 0.18, round: true },
      { kind: "fruit", label: "Fruit tree", icon: "fruit-cherries", color: "#15803D", w: 0.12, h: 0.16, round: true },
      { kind: "sapling", label: "Sapling", icon: "tree-outline", color: "#22C55E", w: 0.08, h: 0.12, round: true },
    ],
  },
  {
    group: "Plants & Beds",
    items: [
      { kind: "flowerbed", label: "Flower bed", icon: "flower", color: "#F472B6", w: 0.22, h: 0.12 },
      { kind: "tulips", label: "Tulips", icon: "flower-tulip", color: "#EC4899", w: 0.14, h: 0.1 },
      { kind: "shrub", label: "Shrub", icon: "sprout", color: "#22C55E", w: 0.09, h: 0.1, round: true },
      { kind: "bush", label: "Bush", icon: "nature", color: "#16A34A", w: 0.1, h: 0.1, round: true },
      { kind: "hedge", label: "Hedge", icon: "leaf", color: "#15803D", w: 0.28, h: 0.06 },
      { kind: "turf", label: "Turf / Lawn", icon: "grass", color: "#4ADE80", w: 0.36, h: 0.3, fill: "grass" },
      { kind: "planter", label: "Planter", icon: "pot", color: "#84CC16", w: 0.08, h: 0.08, round: true },
      { kind: "veg", label: "Veg garden", icon: "sprout", color: "#65A30D", w: 0.22, h: 0.16, fill: "mulch" },
    ],
  },
  {
    group: "Ground & Hardscape",
    items: [
      { kind: "deck", label: "Deck / Patio", icon: "texture-box", color: "#D6BCA0", w: 0.42, h: 0.26, fill: "wood" },
      { kind: "paver", label: "Pavers", icon: "checkerboard", color: "#C4B5A5", w: 0.26, h: 0.2, fill: "pavers" },
      { kind: "gravel", label: "Gravel", icon: "dots-grid", color: "#A8A29E", w: 0.26, h: 0.2, fill: "gravel" },
      { kind: "mulch", label: "Mulch", icon: "grain", color: "#92400E", w: 0.24, h: 0.18, fill: "mulch" },
      { kind: "walkway", label: "Walkway", icon: "road-variant", color: "#CBD5E1", w: 0.32, h: 0.07, fill: "pavers" },
      { kind: "driveway", label: "Driveway", icon: "road", color: "#94A3B8", w: 0.3, h: 0.22, fill: "concrete" },
      { kind: "retwall", label: "Retaining wall", icon: "wall", color: "#78716C", w: 0.3, h: 0.05, fill: "concrete" },
      { kind: "stairs", label: "Steps", icon: "stairs", color: "#B0A08E", w: 0.14, h: 0.14 },
    ],
  },
  {
    group: "Structures",
    items: [
      { kind: "house", label: "House", icon: "home", color: "#64748B", w: 0.42, h: 0.32 },
      { kind: "roof", label: "Roof", icon: "home-roof", color: "#475569", w: 0.36, h: 0.28 },
      { kind: "garage", label: "Garage", icon: "garage", color: "#78716C", w: 0.26, h: 0.24 },
      { kind: "shed", label: "Shed", icon: "warehouse", color: "#92400E", w: 0.16, h: 0.16 },
      { kind: "greenhouse", label: "Greenhouse", icon: "greenhouse", color: "#0D9488", w: 0.18, h: 0.16 },
      { kind: "pergola", label: "Pergola", icon: "tent", color: "#B45309", w: 0.22, h: 0.2 },
      { kind: "gate", label: "Gate", icon: "gate", color: "#57534E", w: 0.12, h: 0.06 },
      { kind: "fence", label: "Fence", icon: "fence", color: "#57534E", w: 0.3, h: 0.05 },
    ],
  },
  {
    group: "Outdoor Living",
    items: [
      { kind: "patiotable", label: "Patio table", icon: "table-picnic", color: "#D97706", w: 0.16, h: 0.16, round: true },
      { kind: "diningset", label: "Dining set", icon: "table-chair", color: "#B45309", w: 0.2, h: 0.2 },
      { kind: "outsofa", label: "Outdoor sofa", icon: "sofa", color: "#EA580C", w: 0.22, h: 0.12 },
      { kind: "chair", label: "Chair", icon: "seat-outline", color: "#F59E0B", w: 0.07, h: 0.08 },
      { kind: "lounge", label: "Lounge chair", icon: "seat-recline-normal", color: "#F59E0B", w: 0.1, h: 0.14 },
      { kind: "bench", label: "Bench", icon: "bench", color: "#A16207", w: 0.16, h: 0.06 },
      { kind: "grill", label: "BBQ grill", icon: "grill", color: "#334155", w: 0.1, h: 0.1, round: true },
      { kind: "umbrella", label: "Umbrella", icon: "umbrella-beach", color: "#F97316", w: 0.14, h: 0.14, round: true },
      { kind: "firepit", label: "Fire pit", icon: "campfire", color: "#EA580C", w: 0.11, h: 0.11, round: true },
      { kind: "fireplace", label: "Fireplace", icon: "fireplace", color: "#B45309", w: 0.14, h: 0.1 },
    ],
  },
  {
    group: "Play & Sport",
    items: [
      { kind: "playset", label: "Playset", icon: "slide", color: "#8B5CF6", w: 0.2, h: 0.18 },
      { kind: "hoop", label: "Basketball", icon: "basketball-hoop", color: "#F97316", w: 0.12, h: 0.12, round: true },
      { kind: "tennis", label: "Tennis court", icon: "tennis", color: "#10B981", w: 0.36, h: 0.24 },
      { kind: "soccer", label: "Sport field", icon: "soccer", color: "#16A34A", w: 0.4, h: 0.26 },
    ],
  },
  {
    group: "Vehicles",
    items: [
      { kind: "car", label: "Car", icon: "car", color: "#475569", w: 0.14, h: 0.22 },
      { kind: "truck", label: "Truck", icon: "truck", color: "#334155", w: 0.16, h: 0.26 },
      { kind: "van", label: "Van", icon: "van-utility", color: "#475569", w: 0.15, h: 0.24 },
      { kind: "rv", label: "RV", icon: "rv-truck", color: "#334155", w: 0.18, h: 0.3 },
      { kind: "boat", label: "Boat", icon: "sail-boat", color: "#0EA5E9", w: 0.14, h: 0.28 },
      { kind: "bike", label: "Bicycle", icon: "bicycle", color: "#64748B", w: 0.08, h: 0.14 },
    ],
  },
  {
    group: "Animals & Symbols",
    items: [
      { kind: "dog", label: "Dog", icon: "dog", color: "#A16207", w: 0.07, h: 0.07, round: true },
      { kind: "person", label: "Person", icon: "human", color: "#6B7280", w: 0.05, h: 0.08, round: true },
      { kind: "north", label: "North arrow", icon: "compass", color: "#0369A1", w: 0.09, h: 0.09, round: true },
      { kind: "marker", label: "Marker", icon: "map-marker", color: "#DC2626", w: 0.06, h: 0.08, round: true },
      { kind: "dim", label: "Dimension", icon: "ruler-square", color: "#0369A1", w: 0.12, h: 0.05 },
      { kind: "label", label: "Text note", icon: "format-text", color: "#6B7280", w: 0.1, h: 0.06 },
      { kind: "light", label: "Light", icon: "lightbulb", color: "#F59E0B", w: 0.05, h: 0.06, round: true },
      { kind: "spigot", label: "Faucet / Spigot", icon: "faucet", color: "#0EA5E9", w: 0.05, h: 0.06, round: true },
    ],
  },
];

const COLORS = ["#38BDF8", "#22D3EE", "#4ADE80", "#16A34A", "#65A30D", "#F97316", "#F472B6", "#D6BCA0", "#C4B5A5", "#A8A29E", "#CBD5E1", "#94A3B8"];

// kind -> palette definition (for instantiating template elements)
const PAL_BY_KIND: Record<string, PalItem> = {};
PALETTE.forEach((g) => g.items.forEach((it) => { PAL_BY_KIND[it.kind] = it; }));

type TplEl = { kind: string; x: number; y: number; w?: number; h?: number };
const TEMPLATES: { name: string; icon: string; canvas_w_ft: number; canvas_h_ft: number; els: TplEl[] }[] = [
  {
    name: "Backyard with Pool", icon: "pool", canvas_w_ft: 60, canvas_h_ft: 40,
    els: [
      { kind: "deck", x: 0.1, y: 0.08, w: 0.8, h: 0.22 },
      { kind: "pool", x: 0.28, y: 0.34, w: 0.44, h: 0.42 },
      { kind: "spa", x: 0.74, y: 0.36 },
      { kind: "turf", x: 0.04, y: 0.34, w: 0.2, h: 0.5 },
      { kind: "patiotable", x: 0.12, y: 0.12 },
      { kind: "grill", x: 0.7, y: 0.12 },
      { kind: "tree", x: 0.02, y: 0.02 },
      { kind: "tree", x: 0.9, y: 0.82 },
      { kind: "palm", x: 0.82, y: 0.02 },
    ],
  },
  {
    name: "Front Yard", icon: "home", canvas_w_ft: 60, canvas_h_ft: 40,
    els: [
      { kind: "house", x: 0.1, y: 0.04, w: 0.8, h: 0.28 },
      { kind: "driveway", x: 0.6, y: 0.34, w: 0.3, h: 0.6 },
      { kind: "walkway", x: 0.4, y: 0.34, w: 0.08, h: 0.55 },
      { kind: "turf", x: 0.04, y: 0.36, w: 0.32, h: 0.55 },
      { kind: "flowerbed", x: 0.12, y: 0.34, w: 0.5, h: 0.08 },
      { kind: "tree", x: 0.06, y: 0.7 },
      { kind: "shrub", x: 0.3, y: 0.36 },
      { kind: "shrub", x: 0.4, y: 0.36 },
    ],
  },
  {
    name: "Patio & Deck", icon: "table-picnic", canvas_w_ft: 40, canvas_h_ft: 30,
    els: [
      { kind: "deck", x: 0.06, y: 0.1, w: 0.5, h: 0.5 },
      { kind: "paver", x: 0.58, y: 0.3, w: 0.36, h: 0.4 },
      { kind: "diningset", x: 0.14, y: 0.18 },
      { kind: "grill", x: 0.6, y: 0.12 },
      { kind: "umbrella", x: 0.34, y: 0.2 },
      { kind: "planter", x: 0.06, y: 0.02 },
      { kind: "planter", x: 0.5, y: 0.02 },
      { kind: "firepit", x: 0.7, y: 0.42 },
    ],
  },
  {
    name: "Garden Beds", icon: "flower", canvas_w_ft: 40, canvas_h_ft: 30,
    els: [
      { kind: "flowerbed", x: 0.06, y: 0.08, w: 0.4, h: 0.14 },
      { kind: "flowerbed", x: 0.54, y: 0.08, w: 0.4, h: 0.14 },
      { kind: "veg", x: 0.1, y: 0.4, w: 0.35, h: 0.3 },
      { kind: "gravel", x: 0.5, y: 0.4, w: 0.4, h: 0.3 },
      { kind: "tree", x: 0.44, y: 0.02 },
      { kind: "shrub", x: 0.02, y: 0.3 },
      { kind: "shrub", x: 0.92, y: 0.3 },
      { kind: "planter", x: 0.7, y: 0.02 },
    ],
  },
];

const GRID_FT = 5;
const uid = () => `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
const clamp01 = (v: number) => Math.max(0, Math.min(1, v));

function polyAreaFt(pts: Pt[], wFt: number, hFt: number) {
  if (pts.length < 3) return 0;
  let a = 0;
  for (let i = 0; i < pts.length; i++) {
    const p = pts[i];
    const q = pts[(i + 1) % pts.length];
    a += p.x * wFt * (q.y * hFt) - q.x * wFt * (p.y * hFt);
  }
  return Math.abs(a / 2);
}
function polyPerimFt(pts: Pt[], wFt: number, hFt: number) {
  if (pts.length < 2) return 0;
  const n = pts.length >= 3 ? pts.length : pts.length - 1;
  let d = 0;
  for (let i = 0; i < n; i++) {
    const p = pts[i];
    const q = pts[(i + 1) % pts.length];
    const dx = (q.x - p.x) * wFt;
    const dy = (q.y - p.y) * hFt;
    d += Math.sqrt(dx * dx + dy * dy);
  }
  return d;
}

/* -------- Draggable element -------- */
function DraggableEl({
  el, cw, ch, selected, onSelect, onCommit,
}: {
  el: El; cw: number; ch: number; selected: boolean;
  onSelect: (id: string) => void;
  onCommit: (id: string, pos: { x: number; y: number }) => void;
}) {
  const pan = useRef(new Animated.ValueXY({ x: 0, y: 0 })).current;
  const responder = useMemo(
    () =>
      PanResponder.create({
        onStartShouldSetPanResponder: () => true,
        onMoveShouldSetPanResponder: (_e, g) => Math.abs(g.dx) > 2 || Math.abs(g.dy) > 2,
        onPanResponderGrant: () => onSelect(el.id),
        onPanResponderMove: Animated.event([null, { dx: pan.x, dy: pan.y }], { useNativeDriver: false }),
        onPanResponderRelease: (_e, g) => {
          const nx = clamp01(el.x + g.dx / cw);
          const ny = clamp01(el.y + g.dy / ch);
          pan.setValue({ x: 0, y: 0 });
          onCommit(el.id, { x: nx, y: ny });
        },
      }),
    // recreate when the committed position or canvas size changes
    [el.id, el.x, el.y, cw, ch] // eslint-disable-line react-hooks/exhaustive-deps
  );

  const left = el.x * cw;
  const top = el.y * ch;
  const w = el.w * cw;
  const h = el.h * ch;
  const iconSize = Math.max(12, Math.min(w, h) * 0.5);

  return (
    <Animated.View
      {...responder.panHandlers}
      style={[
        {
          position: "absolute",
          left,
          top,
          width: w,
          height: h,
          transform: [{ translateX: pan.x }, { translateY: pan.y }, { rotate: `${el.rotation}deg` }],
        },
      ]}
    >
      <View
        style={[
          styles.el,
          {
            backgroundColor: el.fill ? "transparent" : el.color + "D9",
            borderRadius: el.round ? Math.max(w, h) : radius.sm,
            borderColor: selected ? colors.onSurface : "#00000022",
            borderWidth: selected ? 2 : 1,
            borderStyle: selected ? "dashed" : "solid",
            overflow: "hidden",
          },
        ]}
      >
        {el.fill ? (
          <>
            <TextureFill kind={el.fill} w={w} h={h} color={el.color} />
            {Math.min(w, h) > 34 ? (
              <View style={styles.texBadge}>
                <Glyph name={el.icon} set={el.set} size={13} color={el.color} />
              </View>
            ) : null}
          </>
        ) : (
          <Glyph name={el.icon} set={el.set} size={iconSize} color="#ffffff" />
        )}
      </View>
    </Animated.View>
  );
}

export default function CadEditor() {
  return (
    <AdminOnly>
      <CadEditorScreen />
    </AdminOnly>
  );
}

function CadEditorScreen() {
  const { id } = useLocalSearchParams<{ id?: string }>();
  const router = useRouter();
  const shotRef = useRef<ViewShot>(null);

  const [name, setName] = useState("Untitled design");
  const [wFt, setWFt] = useState(60);
  const [hFt, setHFt] = useState(40);
  const [els, setEls] = useState<El[]>([]);
  const [boundary, setBoundary] = useState<Pt[]>([]);
  const [selId, setSelId] = useState<string | null>(null);
  const [boundaryMode, setBoundaryMode] = useState(false);
  const [snap, setSnap] = useState(true);

  const [customerId, setCustomerId] = useState<string | null>(null);
  const [leadId, setLeadId] = useState<string | null>(null);
  const [attachLabel, setAttachLabel] = useState("");

  const [boxW, setBoxW] = useState(0);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [palSearch, setPalSearch] = useState("");
  const [tplOpen, setTplOpen] = useState(false);
  const [scaleOpen, setScaleOpen] = useState(false);
  const [saveOpen, setSaveOpen] = useState(false);
  const [pickerMode, setPickerMode] = useState<"customer" | "lead" | null>(null);
  const [customers, setCustomers] = useState<any[]>([]);
  const [leads, setLeads] = useState<any[]>([]);
  const [saving, setSaving] = useState(false);

  const cw = boxW;
  const ch = boxW > 0 ? boxW * (hFt / wFt) : 0;

  const loadAll = useCallback(async () => {
    try {
      const [c, l] = await Promise.all([api.get("/customers"), api.get("/leads")]);
      setCustomers(c || []);
      setLeads(l || []);
    } catch {}
    if (id) {
      try {
        const d = await api.get(`/designs/${id}`);
        setName(d.name || "Untitled design");
        setWFt(d.canvas_w_ft || 60);
        setHFt(d.canvas_h_ft || 40);
        setEls(d.elements || []);
        setBoundary(d.boundary || []);
        setCustomerId(d.customer_id || null);
        setLeadId(d.lead_id || null);
      } catch {}
    }
  }, [id]);

  useFocusEffect(useCallback(() => { loadAll(); }, [loadAll]));

  const areaFt = useMemo(() => polyAreaFt(boundary, wFt, hFt), [boundary, wFt, hFt]);
  const perimFt = useMemo(() => polyPerimFt(boundary, wFt, hFt), [boundary, wFt, hFt]);
  const sel = els.find((e) => e.id === selId) || null;

  // Snap a normalized coord to the nearest 5-ft grid line along a given axis.
  const snapAxis = (v: number, totalFt: number) => {
    if (!snap || totalFt <= 0) return clamp01(v);
    const step = GRID_FT / totalFt;
    return clamp01(Math.round(v / step) * step);
  };

  const addElement = (item: Omit<El, "id" | "x" | "y" | "rotation">) => {
    const e: El = {
      ...item,
      id: uid(),
      x: clamp01(0.5 - item.w / 2),
      y: clamp01(0.5 - item.h / 2),
      rotation: 0,
    };
    setEls((prev) => [...prev, e]);
    setSelId(e.id);
    setPaletteOpen(false);
  };

  const commitPos = (eid: string, pos: { x: number; y: number }) =>
    setEls((prev) => prev.map((e) => (e.id === eid ? { ...e, x: snapAxis(pos.x, wFt), y: snapAxis(pos.y, hFt) } : e)));

  const updateSel = (patch: Partial<El>) =>
    setEls((prev) => prev.map((e) => (e.id === selId ? { ...e, ...patch } : e)));

  const scaleSel = (f: number) => {
    if (!sel) return;
    updateSel({ w: clamp01(Math.max(0.03, sel.w * f)), h: clamp01(Math.max(0.03, sel.h * f)) });
  };
  const rotateSel = () => sel && updateSel({ rotation: (sel.rotation + 15) % 360 });
  const duplicateSel = () => {
    if (!sel) return;
    const copy: El = { ...sel, id: uid(), x: snapAxis(sel.x + 0.05, wFt), y: snapAxis(sel.y + 0.05, hFt) };
    setEls((prev) => [...prev, copy]);
    setSelId(copy.id);
  };
  const deleteSel = () => {
    if (!sel) return;
    setEls((prev) => prev.filter((e) => e.id !== selId));
    setSelId(null);
  };
  const cycleColor = () => {
    if (!sel) return;
    const i = COLORS.indexOf(sel.color);
    updateSel({ color: COLORS[(i + 1) % COLORS.length] });
  };

  const addBoundaryPoint = (locX: number, locY: number) => {
    setBoundary((prev) => [...prev, { x: snapAxis(locX / cw, wFt), y: snapAxis(locY / ch, hFt) }]);
  };

  const applyTemplate = (t: (typeof TEMPLATES)[number]) => {
    setWFt(t.canvas_w_ft);
    setHFt(t.canvas_h_ft);
    const built: El[] = t.els
      .filter((te) => PAL_BY_KIND[te.kind])
      .map((te) => {
        const base = PAL_BY_KIND[te.kind];
        return {
          ...base,
          id: uid(),
          x: te.x,
          y: te.y,
          w: te.w ?? base.w,
          h: te.h ?? base.h,
          rotation: 0,
        } as El;
      });
    setEls(built);
    setSelId(null);
    setTplOpen(false);
    if (!name || name === "Untitled design") setName(t.name);
  };

  // filtered palette by search
  const filteredPalette = useMemo(() => {
    const q = palSearch.trim().toLowerCase();
    if (!q) return PALETTE;
    return PALETTE
      .map((g) => ({ group: g.group, items: g.items.filter((it) => it.label.toLowerCase().includes(q) || it.kind.includes(q)) }))
      .filter((g) => g.items.length > 0);
  }, [palSearch]);

  const gridLines = useMemo(() => {
    if (cw <= 0) return { v: [] as number[], h: [] as number[] };
    const v: number[] = [];
    const h: number[] = [];
    for (let f = GRID_FT; f < wFt; f += GRID_FT) v.push((f / wFt) * cw);
    for (let f = GRID_FT; f < hFt; f += GRID_FT) h.push((f / hFt) * ch);
    return { v, h };
  }, [cw, ch, wFt, hFt]);

  const capture = async (): Promise<string | null> => {
    try {
      return await captureRef(shotRef, { format: "png", quality: 0.8, result: "data-uri" });
    } catch {
      return null;
    }
  };

  const doSave = async () => {
    setSaving(true);
    try {
      const thumbnail = await capture();
      const payload = {
        name: name || "Untitled design",
        customer_id: customerId,
        lead_id: leadId,
        canvas_w_ft: wFt,
        canvas_h_ft: hFt,
        boundary,
        elements: els,
        area_sqft: areaFt,
        perimeter_ft: perimFt,
        thumbnail,
      };
      if (id) await api.put(`/designs/${id}`, payload);
      else await api.post("/designs", payload);
      setSaveOpen(false);
      router.back();
    } catch (e: any) {
      Alert.alert("Save failed", e?.message || "Please try again.");
    } finally {
      setSaving(false);
    }
  };

  const shareImage = async () => {
    const uri = await capture();
    if (!uri) {
      Alert.alert("Export failed", "Could not capture the design. Try again.");
      return;
    }
    try {
      if (Platform.OS === "web") {
        if (typeof document !== "undefined") {
          const a = document.createElement("a");
          a.href = uri;
          a.download = `${name.replace(/\s+/g, "_")}.png`;
          a.click();
        }
        return;
      }
      if (!(await Sharing.isAvailableAsync())) return;
      const path = `${FileSystem.cacheDirectory}${name.replace(/\s+/g, "_")}.png`;
      const raw = uri.split(",", 2)[1] || "";
      await FileSystem.writeAsStringAsync(path, raw, { encoding: FileSystem.EncodingType.Base64 });
      await Sharing.shareAsync(path, { mimeType: "image/png", dialogTitle: "Share design" });
    } catch (e: any) {
      Alert.alert("Could not share", e?.message || "Please try again.");
    }
  };

  const chooseAttach = (mode: "customer" | "lead", cid: string, label: string) => {
    if (mode === "customer") { setCustomerId(cid); setLeadId(null); }
    else { setLeadId(cid); setCustomerId(null); }
    setAttachLabel(`${mode === "customer" ? "Customer" : "Lead"}: ${label}`);
    setPickerMode(null);
  };

  const pickerList = pickerMode === "customer" ? customers : leads;

  return (
    <View style={styles.root}>
      <Header
        title={id ? "Edit Design" : "New Design"}
        back
        right={
          <Pressable onPress={shareImage} hitSlop={8} testID="cad-share">
            <Ionicons name="share-outline" size={22} color={colors.brand} />
          </Pressable>
        }
      />

      <ScrollView contentContainerStyle={{ paddingBottom: spacing["3xl"] }} scrollEnabled={!boundaryMode}>
        {/* Scale + area bar */}
        <View style={styles.infoBar}>
          <Pressable style={styles.infoChip} onPress={() => setScaleOpen(true)} testID="cad-scale">
            <Ionicons name="resize-outline" size={15} color={colors.brand} />
            <Text style={styles.infoChipText}>{Math.round(wFt)}×{Math.round(hFt)} ft</Text>
          </Pressable>
          <View style={styles.infoChip}>
            <Ionicons name="scan-outline" size={15} color={colors.brand} />
            <Text style={styles.infoChipText}>{areaFt ? `${Math.round(areaFt).toLocaleString()} sq ft` : "— area"}</Text>
          </View>
          <View style={styles.infoChip}>
            <Ionicons name="git-commit-outline" size={15} color={colors.brand} />
            <Text style={styles.infoChipText}>{perimFt ? `${Math.round(perimFt)} ft` : "— perim"}</Text>
          </View>
          <Pressable style={styles.infoChip} onPress={() => setTplOpen(true)} testID="cad-templates">
            <Ionicons name="albums-outline" size={15} color={colors.brand} />
            <Text style={styles.infoChipText}>Templates</Text>
          </Pressable>
          <Pressable style={[styles.infoChip, snap && styles.infoChipOn]} onPress={() => setSnap((v) => !v)} testID="cad-snap-toggle">
            <Ionicons name="magnet-outline" size={15} color={snap ? "#fff" : colors.brand} />
            <Text style={[styles.infoChipText, snap && { color: "#fff" }]}>Snap</Text>
          </Pressable>
        </View>

        {/* Canvas */}
        <View style={styles.canvasPad} onLayout={(e) => setBoxW(e.nativeEvent.layout.width)}>
          <ViewShot ref={shotRef} style={{ width: "100%" }}>
            <View style={[styles.canvas, { height: ch || 260 }]} testID="cad-canvas">
              {/* grid + boundary layer */}
              <Svg width={cw} height={ch} style={StyleSheet.absoluteFill} pointerEvents="none">
                {gridLines.v.map((x, i) => (
                  <Line key={`v${i}`} x1={x} y1={0} x2={x} y2={ch} stroke="#0EA5E922" strokeWidth={1} />
                ))}
                {gridLines.h.map((y, i) => (
                  <Line key={`h${i}`} x1={0} y1={y} x2={cw} y2={y} stroke="#0EA5E922" strokeWidth={1} />
                ))}
                {boundary.length >= 2 ? (
                  <Polygon
                    points={boundary.map((p) => `${p.x * cw},${p.y * ch}`).join(" ")}
                    fill="#22C55E22"
                    stroke="#15803D"
                    strokeWidth={2}
                  />
                ) : null}
                {boundary.map((p, i) => (
                  <Circle key={`pt${i}`} cx={p.x * cw} cy={p.y * ch} r={5} fill="#15803D" />
                ))}
              </Svg>

              {/* elements */}
              {cw > 0 && els.map((el) => (
                <DraggableEl
                  key={el.id}
                  el={el}
                  cw={cw}
                  ch={ch}
                  selected={el.id === selId}
                  onSelect={setSelId}
                  onCommit={commitPos}
                />
              ))}

              {/* boundary tap catcher */}
              {boundaryMode ? (
                <View
                  style={StyleSheet.absoluteFill}
                  testID="cad-boundary-catcher"
                  onStartShouldSetResponder={() => true}
                  onResponderRelease={(e) => addBoundaryPoint(e.nativeEvent.locationX, e.nativeEvent.locationY)}
                />
              ) : (
                <Pressable style={StyleSheet.absoluteFill} onPress={() => setSelId(null)} pointerEvents="box-none" />
              )}
            </View>
          </ViewShot>
        </View>

        {/* Selected element toolbar */}
        {sel && !boundaryMode ? (
          <View style={styles.selBar} testID="cad-sel-toolbar">
            <Text style={styles.selLabel} numberOfLines={1}>
              {sel.label} · {Math.round(sel.w * wFt)}×{Math.round(sel.h * hFt)} ft
            </Text>
            <View style={styles.selBtns}>
              {[
                { icon: "remove-outline", fn: () => scaleSel(0.85), t: "cad-smaller" },
                { icon: "add-outline", fn: () => scaleSel(1.18), t: "cad-bigger" },
                { icon: "refresh-outline", fn: rotateSel, t: "cad-rotate" },
                { icon: "color-palette-outline", fn: cycleColor, t: "cad-color" },
                { icon: "copy-outline", fn: duplicateSel, t: "cad-dup" },
                { icon: "trash-outline", fn: deleteSel, t: "cad-del", danger: true },
              ].map((b) => (
                <Pressable key={b.t} style={styles.selBtn} onPress={b.fn} testID={b.t}>
                  <Ionicons name={b.icon as any} size={18} color={b.danger ? colors.error : colors.brand} />
                </Pressable>
              ))}
            </View>
          </View>
        ) : null}

        {/* Boundary controls */}
        <View style={styles.boundaryRow}>
          <Pressable
            style={[styles.boundaryBtn, boundaryMode && styles.boundaryBtnOn]}
            onPress={() => { setBoundaryMode((v) => !v); setSelId(null); }}
            testID="cad-boundary-toggle"
          >
            <Ionicons name="analytics-outline" size={16} color={boundaryMode ? "#fff" : colors.brand} />
            <Text style={[styles.boundaryText, boundaryMode && { color: "#fff" }]}>
              {boundaryMode ? "Done drawing" : "Draw boundary"}
            </Text>
          </Pressable>
          {boundary.length > 0 ? (
            <>
              <Pressable style={styles.miniBtn} onPress={() => setBoundary((p) => p.slice(0, -1))} testID="cad-boundary-undo">
                <Ionicons name="arrow-undo-outline" size={16} color={colors.onSurfaceSecondary} />
              </Pressable>
              <Pressable style={styles.miniBtn} onPress={() => setBoundary([])} testID="cad-boundary-clear">
                <Ionicons name="close-outline" size={18} color={colors.error} />
              </Pressable>
            </>
          ) : null}
        </View>
        {boundaryMode ? (
          <Text style={styles.hint}>Tap the canvas to drop boundary points. They auto-connect into a lot outline.</Text>
        ) : null}
      </ScrollView>

      {/* Bottom action bar */}
      <View style={styles.bottomBar}>
        <Pressable style={styles.addBtn} onPress={() => setPaletteOpen(true)} testID="cad-add-element">
          <Ionicons name="add-circle" size={20} color="#fff" />
          <Text style={styles.addBtnText}>Add element</Text>
        </Pressable>
        <Pressable style={styles.saveBtn} onPress={() => setSaveOpen(true)} testID="cad-save-open">
          <Ionicons name="save-outline" size={18} color={colors.brand} />
          <Text style={styles.saveBtnText}>Save</Text>
        </Pressable>
      </View>

      {/* Palette sheet */}
      <Sheet visible={paletteOpen} onClose={() => setPaletteOpen(false)} title="Add element" testID="cad-palette-sheet">
        <View style={styles.palSearchBox}>
          <Ionicons name="search" size={16} color={colors.muted} />
          <AppTextInput
            style={styles.palSearchInput}
            value={palSearch}
            onChangeText={setPalSearch}
            placeholder="Search symbols (tree, pool, deck…)"
            placeholderTextColor={colors.muted}
            testID="cad-pal-search"
          />
          {palSearch ? (
            <Pressable onPress={() => setPalSearch("")} hitSlop={8}><Ionicons name="close-circle" size={16} color={colors.muted} /></Pressable>
          ) : null}
        </View>
        {filteredPalette.length === 0 ? (
          <Text style={styles.hint}>No symbols match “{palSearch}”.</Text>
        ) : (
          filteredPalette.map((grp) => (
            <View key={grp.group} style={{ marginBottom: spacing.md }}>
              <Text style={styles.palGroup}>{grp.group}</Text>
              <View style={styles.palWrap}>
                {grp.items.map((it) => (
                  <Pressable key={it.kind} style={styles.palItem} onPress={() => addElement(it)} testID={`cad-pal-${it.kind}`}>
                    <View style={[styles.palIcon, { backgroundColor: it.color + "26" }]}>
                      <Glyph name={it.icon} set={it.set} size={22} color={it.color} />
                    </View>
                    <Text style={styles.palLabel} numberOfLines={1}>{it.label}</Text>
                  </Pressable>
                ))}
              </View>
            </View>
          ))
        )}
      </Sheet>

      {/* Templates sheet */}
      <Sheet visible={tplOpen} onClose={() => setTplOpen(false)} title="Start from a template" testID="cad-tpl-sheet">
        <Text style={styles.hint}>Loads a ready-made layout you can rearrange. Replaces the current canvas.</Text>
        <View style={{ height: spacing.sm }} />
        {TEMPLATES.map((t) => (
          <Pressable key={t.name} style={styles.tplRow} onPress={() => applyTemplate(t)} testID={`cad-tpl-${t.name.split(" ")[0].toLowerCase()}`}>
            <View style={styles.tplIcon}>
              <MaterialCommunityIcons name={t.icon as any} size={22} color={colors.brand} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.tplName}>{t.name}</Text>
              <Text style={styles.tplMeta}>{t.els.length} elements · {t.canvas_w_ft}×{t.canvas_h_ft} ft</Text>
            </View>
            <Ionicons name="chevron-forward" size={18} color={colors.muted} />
          </Pressable>
        ))}
      </Sheet>

      {/* Scale sheet */}
      <Sheet visible={scaleOpen} onClose={() => setScaleOpen(false)} title="Canvas scale" testID="cad-scale-sheet">
        <Text style={styles.hint}>Set the real-world size the canvas represents. Grid squares = {GRID_FT} ft.</Text>
        <View style={{ flexDirection: "row", gap: spacing.md, marginTop: spacing.md }}>
          <View style={{ flex: 1 }}>
            <Text style={styles.inputLabel}>WIDTH (FT)</Text>
            <AppTextInput style={styles.input} keyboardType="decimal-pad" value={String(wFt)} onChangeText={(v) => setWFt(parseFloat(v) || 0)} testID="cad-width-ft" />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.inputLabel}>HEIGHT (FT)</Text>
            <AppTextInput style={styles.input} keyboardType="decimal-pad" value={String(hFt)} onChangeText={(v) => setHFt(parseFloat(v) || 0)} testID="cad-height-ft" />
          </View>
        </View>
        <View style={{ height: spacing.md }} />
        <PrimaryButton title="Apply" icon="checkmark-outline" onPress={() => setScaleOpen(false)} testID="cad-scale-apply" />
      </Sheet>

      {/* Save sheet */}
      <Sheet visible={saveOpen} onClose={() => setSaveOpen(false)} title="Save design" testID="cad-save-sheet">
        <Text style={styles.inputLabel}>DESIGN NAME</Text>
        <AppTextInput style={styles.input} value={name} onChangeText={setName} placeholder="Backyard redesign" placeholderTextColor={colors.muted} testID="cad-name" />
        <Text style={[styles.inputLabel, { marginTop: spacing.md }]}>ATTACH TO (OPTIONAL)</Text>
        {attachLabel ? (
          <View style={styles.attachRow}>
            <Text style={styles.attachText}>{attachLabel}</Text>
            <Pressable onPress={() => { setCustomerId(null); setLeadId(null); setAttachLabel(""); }} hitSlop={8} testID="cad-attach-clear">
              <Ionicons name="close-circle" size={18} color={colors.muted} />
            </Pressable>
          </View>
        ) : (
          <View style={{ flexDirection: "row", gap: spacing.sm }}>
            <Pressable style={styles.attachBtn} onPress={() => setPickerMode("customer")} testID="cad-attach-customer">
              <Ionicons name="person-outline" size={16} color={colors.brand} />
              <Text style={styles.attachBtnText}>Customer</Text>
            </Pressable>
            <Pressable style={styles.attachBtn} onPress={() => setPickerMode("lead")} testID="cad-attach-lead">
              <Ionicons name="magnet-outline" size={16} color={colors.brand} />
              <Text style={styles.attachBtnText}>Lead</Text>
            </Pressable>
          </View>
        )}
        <View style={{ height: spacing.lg }} />
        <PrimaryButton title={saving ? "Saving…" : "Save design"} icon="save-outline" loading={saving} onPress={doSave} testID="cad-save-confirm" />
        {saving ? <View style={{ height: spacing.sm }} /> : null}
      </Sheet>

      {/* Attach picker */}
      <Sheet visible={!!pickerMode} onClose={() => setPickerMode(null)} title={pickerMode === "customer" ? "Attach to customer" : "Attach to lead"} testID="cad-picker-sheet">
        {pickerList.length === 0 ? (
          <Text style={styles.hint}>Nothing found.</Text>
        ) : (
          pickerList.map((it) => (
            <Pressable key={it.id} style={styles.pickerRow} onPress={() => chooseAttach(pickerMode as any, it.id, it.name)} testID={`cad-pick-${it.id}`}>
              <Text style={styles.pickerName}>{it.name}</Text>
              {it.address ? <Text style={styles.pickerSub}>{it.address}</Text> : null}
            </Pressable>
          ))
        )}
      </Sheet>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  infoBar: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm, paddingHorizontal: spacing.lg, paddingTop: spacing.md },
  infoChip: { flexDirection: "row", alignItems: "center", gap: 5, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radius.pill, paddingHorizontal: spacing.md, height: 34 },
  infoChipOn: { backgroundColor: colors.brand, borderColor: colors.brand },
  infoChipText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface },
  canvasPad: { padding: spacing.lg },
  canvas: { width: "100%", backgroundColor: "#F0F9FF", borderRadius: radius.md, borderWidth: 1.5, borderColor: colors.border, overflow: "hidden" },
  el: { flex: 1, alignItems: "center", justifyContent: "center" },
  texBadge: { position: "absolute", top: 2, left: 2, width: 20, height: 20, borderRadius: 10, backgroundColor: "rgba(255,255,255,0.85)", alignItems: "center", justifyContent: "center" },
  selBar: { marginHorizontal: spacing.lg, backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, padding: spacing.md, gap: spacing.sm },
  selLabel: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  selBtns: { flexDirection: "row", justifyContent: "space-between" },
  selBtn: { width: 44, height: 40, borderRadius: radius.sm, backgroundColor: colors.surfaceSecondary, alignItems: "center", justifyContent: "center", borderWidth: 1, borderColor: colors.border },
  boundaryRow: { flexDirection: "row", gap: spacing.sm, paddingHorizontal: spacing.lg, marginTop: spacing.md, alignItems: "center" },
  boundaryBtn: { flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: colors.surface, borderWidth: 1.5, borderColor: colors.brand, borderRadius: radius.pill, paddingHorizontal: spacing.md, height: 40 },
  boundaryBtnOn: { backgroundColor: colors.brand },
  boundaryText: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.brand },
  miniBtn: { width: 40, height: 40, borderRadius: radius.sm, backgroundColor: colors.surface, alignItems: "center", justifyContent: "center", borderWidth: 1, borderColor: colors.border },
  hint: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, paddingHorizontal: spacing.lg, marginTop: spacing.sm },
  bottomBar: { flexDirection: "row", gap: spacing.md, padding: spacing.lg, backgroundColor: colors.surface, borderTopWidth: 1, borderTopColor: colors.border },
  addBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, backgroundColor: colors.brand, height: 50, borderRadius: radius.md },
  addBtnText: { fontFamily: font.semibold, fontSize: fontSize.lg, color: "#fff" },
  saveBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, height: 50, paddingHorizontal: spacing.lg, borderRadius: radius.md, borderWidth: 1.5, borderColor: colors.brand },
  saveBtnText: { fontFamily: font.semibold, fontSize: fontSize.lg, color: colors.brand },
  palGroup: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurfaceSecondary, marginBottom: spacing.sm },
  palSearchBox: { flexDirection: "row", alignItems: "center", gap: spacing.sm, backgroundColor: colors.surfaceSecondary, borderWidth: 1.5, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: spacing.md, height: 44, marginBottom: spacing.md },
  palSearchInput: { flex: 1, fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}) },
  tplRow: { flexDirection: "row", alignItems: "center", gap: spacing.md, paddingVertical: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.border },
  tplIcon: { width: 44, height: 44, borderRadius: radius.md, backgroundColor: colors.brandTertiary, alignItems: "center", justifyContent: "center" },
  tplName: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  tplMeta: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 1 },
  palWrap: { flexDirection: "row", flexWrap: "wrap", gap: spacing.md },
  palItem: { width: 76, alignItems: "center", gap: 4 },
  palIcon: { width: 56, height: 56, borderRadius: radius.md, alignItems: "center", justifyContent: "center" },
  palLabel: { fontFamily: font.medium, fontSize: 11, color: colors.onSurfaceSecondary, textAlign: "center" },
  inputLabel: { fontFamily: font.semibold, fontSize: 11, letterSpacing: 0.8, color: colors.onSurfaceSecondary, marginBottom: spacing.xs },
  input: { backgroundColor: colors.surfaceSecondary, borderWidth: 1.5, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: spacing.md, height: 48, fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}) },
  attachBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, height: 46, borderRadius: radius.md, backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border },
  attachBtnText: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.brand },
  attachRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, backgroundColor: colors.brandTertiary, borderRadius: radius.md, paddingHorizontal: spacing.md, height: 46 },
  attachText: { flex: 1, fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onBrandTertiary },
  pickerRow: { paddingVertical: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.border },
  pickerName: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  pickerSub: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 1 },
});
