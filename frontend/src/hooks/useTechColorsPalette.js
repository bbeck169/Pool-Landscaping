/**
 * Feb-2026 · Live-Tech-Map · Phase 2 — palette fetcher hook.
 *
 * Fetches the approved 12-color palette from
 * ``GET /api/tech-colors/palette`` (Phase 1 endpoint) exactly once
 * per page load and caches it in a module-scoped Promise so the
 * multiple color-pickers on ``/team`` and ``/crews`` don't race
 * three parallel HTTP fetches when a card mounts.
 *
 * On network failure the hook falls back to the local mirror at
 * ``lib/techColorsPalette`` — the mirror IS the source-of-truth for
 * the client contract, so the UI still renders 12 correct swatches
 * even if the palette endpoint hiccups.
 */
import { useEffect, useState } from "react";
import { api } from "@/api";
import { TECH_COLOR_PALETTE as _FALLBACK_PALETTE } from "@/lib/techColorsPalette";

let _paletteCache = null; // Promise<PaletteEntry[]>

function _fetchPaletteOnce() {
  if (_paletteCache) return _paletteCache;
  _paletteCache = api
    .get("/tech-colors/palette")
    .then((r) => {
      // Response shape: { palette: [{ name, hex }, ...] }
      const p = Array.isArray(r?.palette) ? r.palette : [];
      if (p.length === 12) return p;
      // Server returned something unexpected — fall back to the
      // local mirror so the UI never renders an empty picker.
      return _FALLBACK_PALETTE;
    })
    .catch(() => _FALLBACK_PALETTE);
  return _paletteCache;
}

export function useTechColorsPalette() {
  const [palette, setPalette] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    let alive = true;
    _fetchPaletteOnce()
      .then((p) => { if (alive) setPalette(p); })
      .catch((e) => { if (alive) setError(e); });
    return () => { alive = false; };
  }, []);
  return { palette, loading: palette === null, error };
}
