/**
 * Feb-2026 · ScheduleMap — Google Maps stops for the current day.
 *
 * Compact map that sits above ``<ScheduleDayDnDPanel>`` on the
 * admin Schedule page. One pin per job with resolvable coords
 * (``job.location_lat`` + ``job.location_lng`` — projected server-
 * side from ``customers.service_lat`` / ``service_lng``, see
 * ``routers/jobs.py::list_jobs``). Pin colour follows the same
 * ``techColorMap`` the schedule calendar uses so a stop's colour on
 * the map matches its card / event tile below.
 *
 * Reuses the app-wide ``<APIProvider>`` that ``AppLayout`` already
 * mounts (see ``layouts/AppLayout.jsx:264-274``) — no new library,
 * no new provider wrapping needed.
 *
 * Empty-state contract: when zero jobs in ``jobs`` resolve to
 * coords, the component returns ``null`` — the schedule page shows
 * no gray placeholder box.
 *
 * When ``REACT_APP_GOOGLE_MAPS_API_KEY`` is unset the underlying
 * ``<Map>`` renders a light-gray "Map unavailable" tile — no extra
 * work required from this component; the ``<APIProvider>`` mount
 * point handles the fallback itself.
 *
 * ─────────────────────────────────────────────────────────────
 * Feb-2026 · Batch #4 · Item 4 — map pin count bug
 *
 *   Root cause of user-reported "17 jobs but only 8 pins":
 *   multiple jobs at the same customer address were pinning to the
 *   exact same ``(lat, lng)`` and rendering as pin-on-pin (visually
 *   collapsed to one). The dedupe pass below assigns a small
 *   circular spider-offset (< 15m) to duplicate coord groups so
 *   every job is discernible even at moderate zoom.
 *
 *   Additional guardrails:
 *     • Jobs without valid coords are counted + surfaced via the
 *       ``schedule-map-missing-count`` badge in the map corner
 *       (plus a ``console.warn`` with the offending customer IDs).
 *     • ``map.fitBounds`` includes ALL renderable pins on load so
 *       nothing is clipped by the initial viewport.
 *     • Marker clustering (``@googlemaps/markerclusterer``) kicks
 *       in above the dedupe pass; cluster bubbles carry a count
 *       badge so the operator sees "these 8 pins are stacked at
 *       this address" rather than perceiving 8 as the total.
 * ─────────────────────────────────────────────────────────────
 */
import React, { useMemo, useState, useCallback, useEffect, useRef } from "react";
import { Map, AdvancedMarker, InfoWindow, useMap } from "../../lib/maps";
import { MarkerClusterer } from "@googlemaps/markerclusterer";
import { colors } from "@/theme";
import TeardropPin, { deriveDarker } from "@/components/maps/TeardropPin";
import { CustomerLink, AddressLink } from "@/components/customer";
import { PIN_COLOR_BY_DAY } from "@/pages/dispatch/dispatchColors";
// P1 Phase 3 · Feb-2026 — Live technician GPS pin overlay.
// Polls GET /api/workforce/live-locations every 30s, pauses on
// tab-hide, admin-defaulted ON (persisted in localStorage).
import {
  useLiveTechLocations,
  colorForStaleness,
  formatAge,
} from "@/hooks/useLiveTechLocations";

// Deterministic fallback color for jobs whose technician has no
// ``display_color_hex`` picked (or is unassigned) AND for stops
// with no resolvable service-day (missing / malformed
// ``scheduled_date``).
const _UNASSIGNED_COLOR = "#94A3B8"; // slate-400
const _AZ_CENTER = { lat: 33.6975, lng: -112.3708 };
// Spider-offset radius in degrees (~0.00012 lat ≈ 13m).
// Small enough that pins at the same address still cluster in the
// operator's mind, large enough that they're individually clickable
// at typical urban zoom levels.
const _SPIDER_RADIUS_DEG = 0.00012;

// Feb-2026 · ScheduleMap Tech/Day color toggle — localStorage key
// mirrors the Dispatch Board's ``dispatch.pin_color_mode`` naming
// so both surfaces share the same prefs pattern (see
// ``pages/dispatch/dispatchColors.js``).
const _PIN_COLOR_MODE_KEY = "schedule_map.pin_color_mode";
const _PIN_COLOR_MODES = /** @type {const} */ (["tech", "day"]);

// Visual-emphasis presets per active mode.  Both modes always pass
// the SAME channels to the pin (fill = tech color, stroke = day
// color); the toggle changes how heavily each channel is drawn.
//   • ``tech``: thin stroke, fully opaque fill  → tech color leads.
//   • ``day`` : thick stroke, dimmed fill        → day color leads.
const _MODE_EMPHASIS = {
  tech: { strokeWidth: 1,   fillOpacity: 1 },
  day:  { strokeWidth: 3,   fillOpacity: 0.55 },
};

function _loadPinColorMode() {
  try {
    const v = (typeof window !== "undefined")
      ? window.localStorage.getItem(_PIN_COLOR_MODE_KEY) : null;
    if (v && _PIN_COLOR_MODES.includes(v)) return v;
  } catch { /* jsdom / private-mode */ }
  return "tech";
}

function _savePinColorMode(mode) {
  try {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(_PIN_COLOR_MODE_KEY, mode);
    }
  } catch { /* jsdom / private-mode */ }
}

// Feb-2026 · ScheduleMap Tech/Day color toggle — resolve a
// stop's day-color from its ``scheduled_date``. Accepts ISO
// ``YYYY-MM-DD``, full ISO datetime, or any string ``Date`` can
// parse; returns ``null`` when the date can't be resolved so the
// caller can drop to the neutral fallback.
function _dayColorForJob(job) {
  const raw = job?.scheduled_date;
  if (!raw) return null;
  const d = new Date(raw);
  if (Number.isNaN(d.getTime())) return null;
  // ``Date.getUTCDay`` avoids browser-locale drift when the date
  // is a bare ``YYYY-MM-DD`` (parsed as UTC midnight); the pin
  // color palette is keyed by three-letter lowercase day tokens
  // shared with ``pages/dispatch/dispatchColors.js``.
  const idx = d.getUTCDay(); // 0=Sun … 6=Sat
  const tok = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"][idx];
  return PIN_COLOR_BY_DAY[tok] || null;
}

function _fmtTime(job) {
  const raw = job?.scheduled_time || "";
  if (!raw) return null;
  if (/^\d{1,2}:\d{2}/.test(raw)) return raw.slice(0, 5);
  const d = new Date(raw);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

// ─────────────────────────────────────────────────────────────
// Feb-2026 · Schedule map tech-label resolvers.
//
// Operator-reported bug: legend rows + route pins were rendering
// truncated UUIDs (``Tech b72852…``). These resolvers map a
// technician id → human-friendly first-name / initials label and
// are shared by the legend, the numbered route-stop pin label,
// and the live-tech GPS pin tooltip so all three surfaces agree.
//
// Fallback chain (honest degradation — do NOT fabricate names):
//   1. tech record has ``first_name``  → use it verbatim.
//   2. else ``name`` / ``display_name`` → split on whitespace,
//      take the first token.
//   3. else ``email``                   → take the local-part
//      before ``@`` and title-case it.
//   4. else                             → ``Tech <last-4-of-id>``
//      (last 4 chars of the id — more useful than a truncated
//      prefix like ``Tech b72852…``).
//
// Exported for direct unit testing in
// ``test/schedule-map-tech-labels.test.jsx``.
// ─────────────────────────────────────────────────────────────
function _titleCaseWord(w) {
  if (!w) return "";
  return w.charAt(0).toUpperCase() + w.slice(1).toLowerCase();
}

/** Resolve the technician record for an id against the
 *  ``techs`` list, matching on either ``id`` or ``user_id`` so
 *  both tech-rows and user-based synth rows resolve. */
export function _findTechById(techId, techs) {
  if (!techId || !Array.isArray(techs)) return null;
  return techs.find(
    (x) => x && ((x.id || x.user_id) === techId || x.user_id === techId),
  ) || null;
}

export function resolveTechFirstName(techId, techs) {
  if (!techId) return "Unassigned";
  const t = _findTechById(techId, techs);
  // (1) explicit first_name on the record wins.
  const fn = t?.first_name && String(t.first_name).trim();
  if (fn) return fn;
  // (2) split ``name`` / ``display_name`` on whitespace.
  for (const candidate of [t?.name, t?.display_name]) {
    const s = (candidate && String(candidate).trim()) || "";
    if (s) {
      const tok = s.split(/\s+/)[0];
      if (tok) return tok;
    }
  }
  // (3) email local-part, title-cased on the first ``.`` token so
  //     ``ethan.smith@…`` → ``Ethan``.
  const email = (t?.email && String(t.email).trim()) || "";
  if (email && email.includes("@")) {
    const local = email.split("@")[0] || "";
    const firstTok = local.split(/[._-]+/)[0] || "";
    if (firstTok) return _titleCaseWord(firstTok);
  }
  // (4) honest fallback — last 4 chars of the id (NOT a truncated
  //     prefix). Pad short ids so the output is always well-formed.
  const idStr = String(techId);
  const tail = idStr.length >= 4 ? idStr.slice(-4) : idStr;
  return `Tech ${tail}`;
}

export function resolveTechInitials(techId, techs) {
  if (!techId) return "";
  const t = _findTechById(techId, techs);
  // Prefer explicit first_name + last_name initials.
  const fn = t?.first_name && String(t.first_name).trim();
  const ln = t?.last_name && String(t.last_name).trim();
  if (fn && ln) return (fn[0] + ln[0]).toUpperCase();
  if (fn) return fn[0].toUpperCase();
  // Fall back to the first two tokens of ``name`` / ``display_name``.
  for (const candidate of [t?.name, t?.display_name]) {
    const s = (candidate && String(candidate).trim()) || "";
    if (s) {
      const toks = s.split(/\s+/).filter(Boolean);
      if (toks.length >= 2) return (toks[0][0] + toks[1][0]).toUpperCase();
      if (toks.length === 1 && toks[0]) return toks[0][0].toUpperCase();
    }
  }
  // Email local-part first letter.
  const email = (t?.email && String(t.email).trim()) || "";
  if (email && email.includes("@")) {
    const local = email.split("@")[0] || "";
    if (local) return local[0].toUpperCase();
  }
  // Honest fallback — empty string signals "no readable initials";
  // the caller renders the stop number alone in that case.
  return "";
}


function _resolveTechName(job, techs) {
  // InfoWindow caption — single-line full-name slot. Prefers the
  // tech's rendered display name when available, falls back to
  // the first-name resolver (which carries the full fallback
  // chain including the last-4-of-id tail).
  if (!job.technician_id) return "Unassigned";
  const t = _findTechById(job.technician_id, techs);
  const n = (t?.name && String(t.name).trim())
    || (t?.display_name && String(t.display_name).trim())
    || "";
  if (n) return n;
  return resolveTechFirstName(job.technician_id, techs);
}


/**
 * Build a stable per-coord bucket + spread duplicates in a circle.
 *
 * Returns ``{ pins, missing }`` where:
 *   • ``pins`` is the flat list of ``{job, lat, lng, hasCoords}``
 *     with adjusted lat/lng (spider-offset applied to duplicates).
 *   • ``missing`` is the flat list of jobs whose coords could not
 *     be resolved. These are counted + logged but not rendered on
 *     the map.
 *
 * Exported for direct unit testing.
 */
export function _buildDedupedPins(jobs) {
  const missing = [];
  // Bucket by rounded coord (5 decimal places ≈ 1m); jobs sharing a
  // bucket get spider-offset. Using round-to-5 rather than exact
  // equality catches near-duplicate coords too (common when
  // geocoding maps a lot number to the same street segment).
  //
  // NB — we use a plain object dict rather than the built-in ``Map``
  // constructor because this module imports ``Map`` from
  // ``../../lib/maps`` (Google-Maps React wrapper) at the top of the
  // file, which shadows the global constructor.
  const buckets = Object.create(null);
  const clean = [];
  for (const j of jobs || []) {
    const lat = Number(j?.location_lat);
    const lng = Number(j?.location_lng);
    const hasCoords = Number.isFinite(lat) && Number.isFinite(lng)
      && !(lat === 0 && lng === 0);
    if (!hasCoords) {
      missing.push(j);
      continue;
    }
    const key = `${lat.toFixed(5)}:${lng.toFixed(5)}`;
    const bucket = buckets[key] || { key, lat, lng, members: [] };
    bucket.members.push(j);
    buckets[key] = bucket;
    clean.push({ job: j, bucketKey: key });
  }
  const pins = [];
  for (const { job, bucketKey } of clean) {
    const bucket = buckets[bucketKey];
    const size = bucket.members.length;
    if (size === 1) {
      pins.push({ job, lat: bucket.lat, lng: bucket.lng, hasCoords: true });
      continue;
    }
    // Spider-offset: N members arranged on a circle of radius
    // ``_SPIDER_RADIUS_DEG`` around the shared centroid.
    const idx = bucket.members.findIndex((m) => m.id === job.id);
    const angle = (idx / size) * 2 * Math.PI;
    const dLat = Math.sin(angle) * _SPIDER_RADIUS_DEG;
    // Slight latitude-adjusted lng scale so the spread looks circular
    // at any latitude on the map.
    const dLng = Math.cos(angle) * _SPIDER_RADIUS_DEG
      / Math.max(Math.cos(bucket.lat * Math.PI / 180), 0.2);
    pins.push({
      job,
      lat: bucket.lat + dLat,
      lng: bucket.lng + dLng,
      hasCoords: true,
      spidered: true,
    });
  }
  return { pins, missing };
}


/**
 * Phase B.5 · Feb-2026 — Per-technician stop sequence numbering.
 *
 * Returns a ``Map<jobId, number>`` where the number is the 1-based
 * stop sequence for that job within its ``technician_id`` group for
 * the day. Numbering restarts at 1 for each tech so a 3-tech day
 * with 5 stops each shows 1-5 three times (color-differentiated by
 * the existing ``techColorMap``).
 *
 * Ordering rule — hybrid (D.1-c per Phase B.5 dispatch):
 *   1. ``route_index`` (ASC) when present — operators-committed order.
 *   2. Fallback: ``scheduled_at`` / ``scheduled_start`` /
 *      ``scheduled_time`` (ASC) when no route_index.
 *   3. Final tie-break: ``id`` (stable deterministic).
 *
 * Scope rule — count but hide (D.3):
 *   Every job with a ``technician_id`` is counted — including jobs
 *   whose coord resolver returned ``none`` (dropped by
 *   ``_buildDedupedPins``). This keeps the per-tech sequence
 *   consistent with the operator's mental model: a job sequenced
 *   #3 shows "3" on its pin even if the preceding stop (sequenced
 *   #2) was invisible because the property had no geocoded coords.
 *
 * Jobs with no ``technician_id`` land in a shared ``null`` bucket
 * and are numbered among themselves (same rule) so unassigned
 * stops still get a visible sequence.
 *
 * Exported for direct unit testing.
 */
export function _buildPerTechSequence(jobs) {
  const groups = Object.create(null);
  for (const j of jobs || []) {
    if (!j || !j.id) continue;
    const key = j.technician_id || "__unassigned__";
    (groups[key] = groups[key] || []).push(j);
  }
  const _scheduledKey = (j) => (
    j?.scheduled_at
    || j?.scheduled_start
    || j?.scheduled_time
    || j?.scheduled_date
    || ""
  );
  const seq = new window.Map();
  for (const key of Object.keys(groups)) {
    const sorted = groups[key].slice().sort((a, b) => {
      const ai = Number.isFinite(a?.route_index) ? a.route_index : null;
      const bi = Number.isFinite(b?.route_index) ? b.route_index : null;
      if (ai != null && bi != null) return ai - bi;
      if (ai != null) return -1;
      if (bi != null) return 1;
      // Both missing — fall back to scheduled time.
      const as = _scheduledKey(a);
      const bs = _scheduledKey(b);
      if (as && bs && as !== bs) return as < bs ? -1 : 1;
      // Stable tie-break on id so renders are deterministic across
      // test runs.
      return String(a.id).localeCompare(String(b.id));
    });
    sorted.forEach((j, i) => seq.set(j.id, i + 1));
  }
  return seq;
}


/**
 * Inner component: uses ``useMap`` (only valid inside ``<Map>``)
 * to attach a ``MarkerClusterer`` + drive ``fitBounds`` on payload
 * change. Rendering the AdvancedMarkers themselves happens here so
 * we can hand raw marker refs to the clusterer without React
 * fighting Google Maps for DOM ownership.
 */
function _ClusteredMarkers({ pins, techColorMap, colorMode, onSelect,
                              perTechSequence, techs }) {
  const map = useMap();
  const markersRef = useRef({});
  const clustererRef = useRef(null);

  // Attach the clusterer once when the map is ready.
  useEffect(() => {
    if (!map) return undefined;
    if (!clustererRef.current) {
      clustererRef.current = new MarkerClusterer({
        map,
        markers: [],
        // Numbered cluster bubbles — Google's default renderer
        // shows the count inside the bubble, which addresses the
        // Item 4 concern ("only 8 pins" perception when the true
        // count was 17 stacked at fewer addresses).
      });
    }
    return () => {
      if (clustererRef.current) {
        clustererRef.current.clearMarkers();
        clustererRef.current.setMap(null);
        clustererRef.current = null;
      }
    };
  }, [map]);

  // Re-fit the map bounds every time the pin set changes so all
  // pins are visible on initial load (and on filter / date change).
  useEffect(() => {
    if (!map || !pins.length) return;
    // Guard: some test mocks return a bare object without the
    // ``fitBounds`` / ``LatLngBounds`` globals — bail cleanly.
    const g = typeof window !== "undefined" ? window.google : null;
    if (!g?.maps?.LatLngBounds || typeof map.fitBounds !== "function") return;
    const bounds = new g.maps.LatLngBounds();
    for (const p of pins) bounds.extend({ lat: p.lat, lng: p.lng });
    map.fitBounds(bounds, 48);  // 48px padding
  }, [map, pins]);

  const emphasis = _MODE_EMPHASIS[colorMode] || _MODE_EMPHASIS.tech;

  return (
    <>
      {pins.map(({ job, lat, lng }) => {
        // Fill = assigned tech's brand color → gray fallback when
        // the stop is unassigned (or the tech has no picked color).
        const fillHex = (techColorMap && job.technician_id
          ? techColorMap.get(job.technician_id)
          : null) || _UNASSIGNED_COLOR;
        // Stroke = service-day color → gray fallback when the
        // scheduled_date is missing / unparseable.
        const strokeHex = _dayColorForJob(job) || _UNASSIGNED_COLOR;
        // Phase B.5 · Feb-2026 — per-tech stop sequence label.
        //
        // Pre-B.5 the pin label was ``job.route_index + 1``, so any
        // stop that hadn't been through the ``POST /api/jobs/reorder``
        // flow (``route_index == null``) rendered without a number.
        // Phase B.5 switches to a hybrid resolver: ``route_index``
        // when present, else the natural scheduled-time order within
        // the tech group. See ``_buildPerTechSequence`` above for
        // the full ordering rule + count-but-hide invariant. Jobs
        // dropped by ``_buildDedupedPins`` (no coords) are still
        // counted so the visible-pin numbers match the operator's
        // mental ordering (sequenced #3 shows "3" even if #2 was
        // invisible). ``perTechSequence`` is a ``Map<jobId, number>``
        // keyed on the job's id; a miss (job not in map) falls back
        // to the pre-B.5 route_index path for test safety.
        const perTechSeq = perTechSequence && perTechSequence.get(job.id);
        const routeIdx = job?.route_index;
        const stopNum = perTechSeq
          || (Number.isFinite(routeIdx) ? routeIdx + 1 : undefined);
        // Feb-2026 · Pin-label resolver (operator bug fix).
        //
        // The stop-number pin disc is tight on space, so when the
        // technician has resolvable initials we render a compact
        // ``NN·II`` label (e.g. ``01·EM`` for stop 1 of Ethan M.);
        // when no name data is available we fall back to just the
        // zero-padded stop number so the pin stays legible. The
        // ``title`` on the surrounding button carries the full
        // "Stop NN — Ethan" hover tooltip in every branch (see
        // the ``aria-label`` / ``title`` block below).
        const techInitials = job.technician_id
          ? resolveTechInitials(job.technician_id, techs)
          : "";
        let pinLabel;
        if (stopNum == null) {
          pinLabel = undefined;
        } else {
          const padded = Number.isFinite(stopNum)
            ? (stopNum < 10 ? `0${stopNum}` : String(stopNum))
            : String(stopNum);
          pinLabel = techInitials
            ? `${padded}·${techInitials}`
            : padded;
        }
        const techFirstName = job.technician_id
          ? resolveTechFirstName(job.technician_id, techs)
          : null;
        const stopTooltip = stopNum != null
          ? (techFirstName
              ? `Stop ${Number.isFinite(stopNum)
                  && stopNum < 10 ? "0" : ""}${stopNum} — ${techFirstName}`
              : `Stop ${Number.isFinite(stopNum)
                  && stopNum < 10 ? "0" : ""}${stopNum}`)
          : (techFirstName || null);
        // Phase 4 · Feb-2026 — approximate-location signal.
        // ``property_id`` is set on the job but the K58 coord
        // resolver ladder in ``backend/routers/jobs.py`` couldn't
        // find usable coords on the property doc (missing / NaN /
        // zero-pair) and fell through to the customer's
        // ``service_lat`` / ``service_lng``. ``coord_source ===
        // "customer"`` alone is NOT approximate — it's the
        // legitimate render for single-property customers whose
        // ``property_id`` is null. The signal fires ONLY when a
        // property WAS attached but failed to resolve. See
        // ``backend/tests/test_jobs_map_coord_ladder.py``
        // ``test_phase4_customer_fallback_preserves_property_id_approximate_signal``.
        const isApproximate = Boolean(
          job?.coord_source === "customer" && job?.property_id,
        );
        return (
          <AdvancedMarker
            key={job.id}
            position={{ lat, lng }}
            onClick={() => onSelect(job.id)}
            ref={(el) => {
              // ``@vis.gl/react-google-maps`` forwards refs to the
              // underlying ``AdvancedMarkerElement`` — feed it into
              // the clusterer so cluster bubbles auto-appear when
              // pins overlap at low zoom.
              const clusterer = clustererRef.current;
              const prev = markersRef.current[job.id];
              if (!clusterer) return;
              if (prev && prev !== el) {
                clusterer.removeMarker(prev);
                delete markersRef.current[job.id];
              }
              if (el) {
                markersRef.current[job.id] = el;
                clusterer.addMarker(el);
              }
            }}
          >
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); onSelect(job.id); }}
              aria-label={(() => {
                const base = isApproximate
                  ? `Job pin for ${job.customer_name || "job"} `
                    + "(approximate location — property coords missing)"
                  : `Job pin for ${job.customer_name || "job"}`;
                return stopTooltip ? `${base} — ${stopTooltip}` : base;
              })()}
              title={(() => {
                // Feb-2026 · tech-label bug fix — the hover
                // tooltip now carries "Stop NN — <FirstName>" on
                // every pin that has a resolvable sequence +
                // tech so the operator can see tech context
                // without opening the InfoWindow. Approximate-
                // location pins keep their explanatory tooltip
                // (approximate location trumps stop label).
                if (isApproximate) {
                  return "Approximate location — property has no "
                    + "geocoded coords; falling back to the "
                    + "customer's service address. Fix on the "
                    + "property's edit page.";
                }
                return stopTooltip || undefined;
              })()}
              data-testid={`schedule-map-pin-${job.id}`}
              data-color-mode={colorMode}
              data-approximate={isApproximate ? "true" : "false"}
              data-coord-source={job?.coord_source || "none"}
              data-pin-sequence={pinLabel != null ? String(pinLabel) : ""}
              data-tech-first-name={techFirstName || ""}
              data-tech-initials={techInitials || ""}
              style={{
                background: "transparent",
                // Phase 4 · Feb-2026 — approximate pins get a
                // dashed outline so operators can spot which
                // pins fell back to the customer address. 1px
                // transparent border on non-approximate pins so
                // the layout box height is identical in both
                // states (no jump when a pin's status flips).
                border: isApproximate
                  ? `2px dashed ${deriveDarker(fillHex)}`
                  : "2px solid transparent",
                borderRadius: "50%",
                padding: isApproximate ? 1 : 1,
                cursor: "pointer",
                filter: "drop-shadow(0 1px 2px rgba(0,0,0,0.35))",
                transform: "translateY(-24px)",
                // Lighten the whole pin by 30% so the approximate
                // state reads as "lower confidence" at a glance.
                opacity: isApproximate ? 0.7 : 1,
              }}
            >
              {/* Phase M1 · Feb-2026 · Sitewide custom teardrop pin.
                   Per-marker color semantics (assigned-tech color
                   via ``techColorMap`` → unassigned slate fallback)
                   are preserved verbatim; only the SHAPE changes.

                   Feb-2026 · Tech/Day color toggle — fill always
                   comes from the tech color, stroke always from
                   the service-day color. The active mode dials the
                   stroke width + fill opacity to emphasize one
                   channel visually. */}
              <TeardropPin color={fillHex}
                             stroke={strokeHex}
                             strokeWidth={emphasis.strokeWidth}
                             fillOpacity={emphasis.fillOpacity}
                             label={pinLabel}
                             testid={`schedule-map-pin-${job.id}-svg`} />
            </button>
          </AdvancedMarker>
        );
      })}
    </>
  );
}


/**
 * ``jobs`` — day's jobs list (already filtered to the focused date).
 * ``techs`` — techs list for tech-name popover lookup.
 * ``techColorMap`` — Map<techId, colorHex> shared with the schedule
 *                    calendar / grid so pin colour matches cards.
 */
export default function ScheduleMap({ jobs = [], techs = [], techColorMap }) {
  const [activeId, setActiveId] = useState(null);
  const [activeLiveTechId, setActiveLiveTechId] = useState(null);
  // Feb-2026 · Tech/Day color toggle. Lazy-init from localStorage
  // so the first paint already reflects the operator's saved
  // preference — no post-mount flash from ``tech`` to ``day``.
  const [colorMode, setColorMode] = useState(() => _loadPinColorMode());

  // P1 Phase 3 · live-tech overlay source — polls every 30s,
  // pauses on tab-hide, admin-defaulted ON.
  const {
    pings: livePings,
    enabled: liveEnabled,
    setEnabled: setLiveEnabled,
  } = useLiveTechLocations();

  const { pins, missing } = useMemo(() => _buildDedupedPins(jobs), [jobs]);
  // Phase B.5 · Feb-2026 — hybrid per-tech sequence numbering.
  // Computed on the FULL ``jobs`` input (not ``pins``) so that
  // stops dropped by ``_buildDedupedPins`` still occupy their
  // sequence slot — a job sequenced #3 shows "3" on its pin even
  // if #2 was invisible for lack of coords. See
  // ``_buildPerTechSequence`` for the full ordering + grouping rule.
  const perTechSequence = useMemo(
    () => _buildPerTechSequence(jobs),
    [jobs],
  );
  // Phase B.5 · Feb-2026 — per-tech stop counts for the legend.
  // Counts EVERY job assigned to the tech (including coord drops)
  // so the legend badge matches the per-tech sequence numbering,
  // not just what's visible on the map.
  const perTechStopCounts = useMemo(() => {
    const counts = new window.Map();
    for (const j of jobs || []) {
      if (!j?.technician_id) continue;
      counts.set(j.technician_id, (counts.get(j.technician_id) || 0) + 1);
    }
    return counts;
  }, [jobs]);

  // Log the customer IDs of jobs without map coords so admins can
  // fix the underlying customer record. Once per pin-set change.
  useEffect(() => {
    if (!missing.length) return;
    // eslint-disable-next-line no-console
    console.warn(
      `[schedule-map] ${missing.length} job(s) missing map coords:`,
      missing.map((j) => ({
        job_id: j.id,
        customer_id: j.customer_id,
        customer_name: j.customer_name,
        address: j.address,
      })),
    );
  }, [missing]);

  const active = useMemo(
    () => pins.find((p) => p.job.id === activeId) || null,
    [pins, activeId],
  );

  const initialCenter = useMemo(() => {
    if (pins.length > 0) return { lat: pins[0].lat, lng: pins[0].lng };
    return _AZ_CENTER;
  }, [pins.length > 0]); // eslint-disable-line react-hooks/exhaustive-deps

  const onSelect = useCallback((id) => {
    setActiveId((cur) => (cur === id ? null : id));
  }, []);

  // Feb-2026 · Tech/Day color toggle — click / keyboard handler.
  const _onSelectColorMode = useCallback((mode) => {
    if (!_PIN_COLOR_MODES.includes(mode)) return;
    setColorMode(mode);
    _savePinColorMode(mode);
  }, []);

  // Empty-state contract — return null so the schedule page doesn't
  // render an empty gray box. Note: even if all coords are missing,
  // we still return null (the missing-count badge only surfaces
  // when at least one pin renders).
  if (pins.length === 0) return null;

  return (
    <div
      className="rounded-xl overflow-hidden mb-3"
      style={{
        border: `1px solid ${colors.border}`,
        height: 'clamp(240px, 45vh, 480px)',
        position: "relative",
      }}
      data-testid="schedule-map-container"
    >
      {/* Feb-2026 · Tech/Day color toggle — header pill sitting on
          the top-left of the map tile. Keyboard-accessible via the
          native ``role=radiogroup`` / ``role=radio`` semantics. */}
      <div
        role="radiogroup"
        aria-label="Color pins by"
        data-testid="schedule-map-color-toggle"
        style={{
          position: "absolute", top: 8, left: 8, zIndex: 5,
          display: "inline-flex",
          background: "rgba(255,255,255,0.94)",
          borderRadius: 999,
          padding: 3,
          boxShadow: "0 1px 3px rgba(0,0,0,0.18)",
          fontSize: 11,
          fontWeight: 600,
          gap: 2,
        }}
      >
        {_PIN_COLOR_MODES.map((mode) => {
          const isActive = mode === colorMode;
          return (
            <button
              key={mode}
              type="button"
              role="radio"
              aria-checked={isActive}
              tabIndex={isActive ? 0 : -1}
              data-testid={`schedule-map-color-mode-${mode}`}
              data-active={isActive ? "true" : "false"}
              onClick={() => _onSelectColorMode(mode)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  _onSelectColorMode(mode);
                } else if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
                  e.preventDefault();
                  const next = mode === "tech" ? "day" : "tech";
                  _onSelectColorMode(next);
                }
              }}
              style={{
                border: 0,
                cursor: "pointer",
                padding: "4px 10px",
                borderRadius: 999,
                background: isActive ? colors.onSurface : "transparent",
                color: isActive ? "#FFFFFF" : colors.onSurface,
                textTransform: "capitalize",
              }}
            >
              {mode}
            </button>
          );
        })}
      </div>
      {/* Phase B.5 · Feb-2026 — per-tech color legend.
          Shows the mapping between the pin fill color
          (``techColorMap``) and the technician name, plus the stop
          count for the current day. One entry per technician with
          at least one job on the day. Positioned bottom-left so it
          doesn't collide with the top-left color toggle or the
          live-tech toggle. In ``colorMode === "day"`` the legend
          still renders — the fill color on each pin reflects the
          tech color regardless of the active mode (the mode only
          dials stroke-vs-fill emphasis per ``_MODE_EMPHASIS``). */}
      {techColorMap && Array.from(perTechStopCounts.keys()).length > 0 ? (
        <div
          data-testid="schedule-map-tech-legend"
          style={{
            position: "absolute", bottom: 8, left: 8, zIndex: 5,
            display: "inline-flex", flexDirection: "column", gap: 2,
            background: "rgba(255,255,255,0.94)",
            borderRadius: 10,
            padding: "6px 10px",
            boxShadow: "0 1px 3px rgba(0,0,0,0.18)",
            fontSize: 11,
            fontWeight: 600,
            maxWidth: 220,
            maxHeight: 180,
            overflowY: "auto",
          }}
        >
          {Array.from(perTechStopCounts.entries())
            .sort((a, b) => b[1] - a[1])
            .map(([tid, count]) => {
              const color = (techColorMap.get(tid)) || _UNASSIGNED_COLOR;
              // Feb-2026 · tech-label bug fix — legend row now
              // renders the technician's first name (via the
              // shared resolver), NOT the pre-fix truncated
              // ``Tech b72852…`` UUID prefix. See the resolver's
              // doc-comment for the full honest-fallback chain.
              const name = resolveTechFirstName(tid, techs);
              return (
                <div
                  key={tid}
                  data-testid={`schedule-map-tech-legend-${tid}`}
                  style={{
                    display: "inline-flex", alignItems: "center",
                    gap: 6, color: colors.onSurface,
                  }}
                >
                  <span
                    aria-hidden="true"
                    style={{
                      display: "inline-block", width: 10, height: 10,
                      borderRadius: "50%", background: color,
                      border: "1px solid rgba(0,0,0,0.15)",
                      flex: "0 0 10px",
                    }}
                  />
                  <span style={{
                    overflow: "hidden", textOverflow: "ellipsis",
                    whiteSpace: "nowrap", flex: 1,
                  }}>{name}</span>
                  <span
                    data-testid={`schedule-map-tech-legend-count-${tid}`}
                    style={{
                      color: colors.muted, fontWeight: 500,
                      fontVariantNumeric: "tabular-nums",
                    }}
                  >
                    {count} stop{count === 1 ? "" : "s"}
                  </span>
                </div>
              );
            })}
        </div>
      ) : null}
      {/* P1 Phase 3 · Live-tech overlay toggle. */}
      <button
        type="button"
        role="switch"
        aria-checked={liveEnabled}
        aria-label="Show live technician locations"
        data-testid="schedule-map-live-tech-toggle"
        data-enabled={liveEnabled ? "true" : "false"}
        onClick={() => setLiveEnabled(!liveEnabled)}
        style={{
          position: "absolute", top: 8, left: 120, zIndex: 5,
          background: liveEnabled ? "#22c55e" : "rgba(255,255,255,0.94)",
          color: liveEnabled ? "#FFFFFF" : colors.onSurface,
          border: 0, cursor: "pointer",
          borderRadius: 999, padding: "4px 10px",
          boxShadow: "0 1px 3px rgba(0,0,0,0.18)",
          fontSize: 11, fontWeight: 600,
          display: "inline-flex", alignItems: "center", gap: 6,
        }}
      >
        <span
          style={{
            display: "inline-block", width: 8, height: 8,
            borderRadius: "50%",
            background: liveEnabled ? "#FFFFFF" : "#94a3b8",
          }}
          aria-hidden="true"
        />
        {liveEnabled ? "Live techs on" : "Show live techs"}
      </button>
      <Map
        mapId="SCHEDULE_MAP"
        defaultCenter={initialCenter}
        defaultZoom={11}
        gestureHandling="cooperative"
        disableDefaultUI={false}
        clickableIcons={false}
        style={{ width: "100%", height: "100%" }}
      >
        <_ClusteredMarkers
          pins={pins}
          techColorMap={techColorMap}
          colorMode={colorMode}
          onSelect={onSelect}
          perTechSequence={perTechSequence}
          techs={techs}
        />
        {/* Live-tech markers — outside the clusterer so a tech
            standing on top of a job pin is still individually
            visible. */}
        {liveEnabled ? livePings.map((p) => {
          // Feb-2026 · tech-label bug fix — live-tech pin hover
          // tooltip now carries the first-name (via the shared
          // resolver, which prefers ``techs[].first_name``) with
          // the ping's own ``user_name`` string as a secondary
          // fallback for techs that aren't in the ``techs`` list
          // (e.g. a tech who just started a shift in a different
          // tenant surface). Format: ``<FirstName> · <Age>``.
          const liveFirst = resolveTechFirstName(p.user_id, techs);
          // Resolver's honest fallback is ``Tech <tail>`` — if we
          // land there, prefer the ping's own ``user_name`` since
          // the live-locations endpoint carries a resolved display
          // name directly.
          const liveLabel = liveFirst.startsWith("Tech ")
            && p.user_name
            ? String(p.user_name).trim().split(/\s+/)[0] || p.user_name
            : liveFirst;
          return (
          <AdvancedMarker
            key={`live-${p.user_id}`}
            position={{ lat: p.lat, lng: p.lon }}
            onClick={() => setActiveLiveTechId(
              activeLiveTechId === p.user_id ? null : p.user_id,
            )}
            title={`${liveLabel} · ${formatAge(p.age_seconds)}`}
          >
            <div
              data-testid={`schedule-map-live-tech-pin-${p.user_id}`}
              data-staleness={p.staleness}
              data-tech-first-name={liveLabel}
              style={{
                width: 14, height: 14, borderRadius: "50%",
                background: colorForStaleness(p.staleness),
                border: "2px solid #FFFFFF",
                boxShadow: "0 0 0 1px rgba(0,0,0,0.25), "
                  + "0 2px 4px rgba(0,0,0,0.3)",
              }}
            />
          </AdvancedMarker>
          );
        }) : null}
        {liveEnabled && activeLiveTechId ? (() => {
          const lp = livePings.find(
            (x) => x.user_id === activeLiveTechId);
          if (!lp) return null;
          return (
            <InfoWindow
              position={{ lat: lp.lat, lng: lp.lon }}
              onCloseClick={() => setActiveLiveTechId(null)}
            >
              <div
                style={{ minWidth: 180, maxWidth: 240 }}
                data-testid={`schedule-map-live-tech-info-${lp.user_id}`}
              >
                <div style={{ fontWeight: 600, fontSize: 13,
                                color: colors.onSurface }}>
                  {lp.user_name}
                </div>
                <div style={{ fontSize: 12,
                                color: colors.onSurfaceSecondary,
                                marginTop: 2 }}>
                  updated {formatAge(lp.age_seconds)}
                </div>
                <div
                  style={{ fontSize: 11, marginTop: 4,
                             display: "inline-flex",
                             alignItems: "center", gap: 4,
                             color: colorForStaleness(lp.staleness),
                             textTransform: "capitalize" }}
                  data-testid={`schedule-map-live-tech-staleness-${lp.user_id}`}
                >
                  <span style={{
                    display: "inline-block", width: 6, height: 6,
                    borderRadius: "50%",
                    background: colorForStaleness(lp.staleness),
                  }} />
                  {lp.staleness}
                </div>
              </div>
            </InfoWindow>
          );
        })() : null}
        {active ? (
          <InfoWindow
            position={{ lat: active.lat, lng: active.lng }}
            onCloseClick={() => setActiveId(null)}
          >
            <div
              style={{ minWidth: 200, maxWidth: 260 }}
              data-testid="schedule-map-infowindow"
            >
              <div
                style={{ fontWeight: 600, fontSize: 13, color: colors.onSurface }}
                data-testid={`schedule-map-info-customer-${active.job.id}`}
              >
                <CustomerLink
                  customerId={active.job.customer_id}
                  name={active.job.customer_name || active.job.title || "Job"}
                />
              </div>
              {active.job.address ? (
                <div
                  style={{ fontSize: 12, color: colors.muted, marginTop: 2 }}
                  data-testid={`schedule-map-info-address-${active.job.id}`}
                >
                  <AddressLink address={active.job.address} />
                </div>
              ) : null}
              {/* Phase 4 · Feb-2026 — property-origin chip. Shows the
                   property label as a secondary line when the K58 /
                   P31 coord resolver landed on the property rung so
                   operators know the pin reflects the property's
                   address, not the customer's billing address. Only
                   rendered when ``coord_source === "property"`` AND
                   a label was stamped server-side. See
                   backend/routers/jobs.py:1327-1336 for the stamp +
                   backend/tests/test_jobs_map_coord_ladder.py
                   ``test_phase4_property_rung_stamps_coord_source_and_label``
                   for the contract lock. */}
              {active.job.coord_source === "property"
                && active.job.property_label ? (
                <div
                  style={{
                    fontSize: 11,
                    color: colors.onSurfaceSecondary,
                    marginTop: 4,
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 4,
                    padding: "2px 6px",
                    borderRadius: 999,
                    background: "rgba(14,165,233,0.08)",
                    border: "1px solid rgba(14,165,233,0.25)",
                  }}
                  data-testid={`schedule-map-info-property-${active.job.id}`}
                >
                  <span
                    aria-hidden="true"
                    style={{
                      display: "inline-block",
                      width: 6, height: 6,
                      borderRadius: "50%",
                      background: "#0EA5E9",
                    }}
                  />
                  Property: <strong>{active.job.property_label}</strong>
                </div>
              ) : null}
              {_fmtTime(active.job) ? (
                <div
                  style={{ fontSize: 12, color: colors.onSurfaceSecondary, marginTop: 4 }}
                  data-testid={`schedule-map-info-time-${active.job.id}`}
                >
                  {_fmtTime(active.job)}
                </div>
              ) : null}
              <div
                style={{ fontSize: 11, color: colors.onSurfaceSecondary, marginTop: 4 }}
                data-testid={`schedule-map-info-tech-${active.job.id}`}
              >
                Tech: <strong>{_resolveTechName(active.job, techs)}</strong>
              </div>
            </div>
          </InfoWindow>
        ) : null}
      </Map>
      {/* Feb-2026 · Item 4 — badge surfaces when at least one job on
          this schedule cannot be plotted. Absolute-positioned so it
          overlays the map without shrinking the tile height. */}
      {missing.length > 0 ? (
        <div
          style={{
            position: "absolute", top: 8, right: 8, zIndex: 5,
            padding: "4px 8px", borderRadius: 6,
            background: "rgba(0,0,0,0.72)", color: "#fff",
            fontSize: 11, fontWeight: 600,
            pointerEvents: "none",
          }}
          data-testid="schedule-map-missing-count"
          title={
            "Some jobs on today's schedule couldn't be plotted — "
            + "check the console for their customer IDs."
          }
        >
          {missing.length} job{missing.length === 1 ? "" : "s"} missing location
        </div>
      ) : null}
    </div>
  );
}
