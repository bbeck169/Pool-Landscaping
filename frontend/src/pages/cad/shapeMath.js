/**
 * Shape math + snap helpers for the CAD Studio editor.
 *
 * Phase CAD-2 · Feb-2026 — pulled out of ``Editor.jsx`` so unit
 * tests can drive the math without mounting Konva. Pure functions,
 * no React.
 */


export function shoelaceSqft(coords, canvasWft, canvasHft) {
  const n = coords?.length || 0;
  if (n < 3) return 0;
  let s = 0;
  for (let i = 0; i < n; i++) {
    const p1 = coords[i];
    const p2 = coords[(i + 1) % n];
    const x1 = p1.x * canvasWft;
    const y1 = p1.y * canvasHft;
    const x2 = p2.x * canvasWft;
    const y2 = p2.y * canvasHft;
    s += (x1 * y2) - (x2 * y1);
  }
  return Math.abs(s) / 2;
}


export function polylineLengthFt(coords, canvasWft, canvasHft) {
  if (!coords || coords.length < 2) return 0;
  let total = 0;
  for (let i = 0; i < coords.length - 1; i++) {
    const dx = (coords[i + 1].x - coords[i].x) * canvasWft;
    const dy = (coords[i + 1].y - coords[i].y) * canvasHft;
    total += Math.hypot(dx, dy);
  }
  return total;
}


export function feetToImperial(feetVal) {
  const total = Math.max(0, feetVal);
  const ft = Math.floor(total);
  const inches = Math.round((total - ft) * 12);
  if (inches >= 12) return `${ft + 1}' 0"`;
  return `${ft}' ${inches}"`;
}


function _pointToSegment(px, py, ax, ay, bx, by) {
  const dx = bx - ax;
  const dy = by - ay;
  const lenSq = dx * dx + dy * dy;
  if (lenSq === 0) {
    return { x: ax, y: ay, d: Math.hypot(px - ax, py - ay) };
  }
  let t = ((px - ax) * dx + (py - ay) * dy) / lenSq;
  t = Math.max(0, Math.min(1, t));
  const projX = ax + t * dx;
  const projY = ay + t * dy;
  return { x: projX, y: projY, d: Math.hypot(px - projX, py - projY) };
}


/** Snap the given normalized point to the closest edge within
 * ``thresholdPx``. ``edges`` is an array of ``[a, b]`` normalized
 * point pairs. Returns ``{x, y, snapped: boolean}``.
 */
export function snapPoint(normPt, edges, thresholdPx, canvasSizePx) {
  const px = normPt.x * canvasSizePx.w;
  const py = normPt.y * canvasSizePx.h;
  let best = { d: Infinity, x: px, y: py };
  for (const [aN, bN] of edges) {
    if (!aN || !bN) continue;
    const ax = aN.x * canvasSizePx.w;
    const ay = aN.y * canvasSizePx.h;
    const bx = bN.x * canvasSizePx.w;
    const by = bN.y * canvasSizePx.h;
    const r = _pointToSegment(px, py, ax, ay, bx, by);
    if (r.d < best.d) best = r;
  }
  if (best.d <= thresholdPx) {
    return {
      x: best.x / canvasSizePx.w,
      y: best.y / canvasSizePx.h,
      snapped: true,
    };
  }
  return { x: normPt.x, y: normPt.y, snapped: false };
}


/** Enumerate all snap-target edges from the design: boundary
 * polygon + any element whose ``coords`` array has 2+ vertices.
 * Legacy elements with only ``x/y/w/h`` (no ``coords``) also
 * contribute their 4 corner edges. */
export function collectSnapEdges(design) {
  const out = [];
  const b = design?.boundary || [];
  if (Array.isArray(b) && b.length >= 2) {
    for (let i = 0; i < b.length; i++) {
      const a = b[i];
      const c = b[(i + 1) % b.length];
      if (a && c && typeof a.x === "number" && typeof c.x === "number") {
        out.push([a, c]);
      }
    }
  }
  for (const el of (design?.elements || [])) {
    if (Array.isArray(el.coords) && el.coords.length >= 2) {
      const close = el.type === "paver" || el.type === "pool"
        || el.type === "spa";
      const n = el.coords.length;
      for (let i = 0; i < (close ? n : n - 1); i++) {
        out.push([el.coords[i], el.coords[(i + 1) % n]]);
      }
    } else if (
      typeof el.x === "number" && typeof el.y === "number"
      && typeof el.w === "number" && typeof el.h === "number"
    ) {
      // Legacy rectangle element (rect / spa / firepit / text).
      const a = { x: el.x, y: el.y };
      const c = { x: el.x + el.w, y: el.y };
      const d = { x: el.x + el.w, y: el.y + el.h };
      const e = { x: el.x, y: el.y + el.h };
      out.push([a, c], [c, d], [d, e], [e, a]);
    }
  }
  return out;
}


export function polygonCentroid(coords) {
  if (!coords || coords.length === 0) return { x: 0.5, y: 0.5 };
  let sx = 0;
  let sy = 0;
  for (const p of coords) {
    sx += p.x;
    sy += p.y;
  }
  return { x: sx / coords.length, y: sy / coords.length };
}
