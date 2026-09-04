/**
 * Phase K39a · Feb-2026 — HERE Maps adapter.
 *
 * Mirrors the ``@vis.gl/react-google-maps`` surface using HERE's
 * ``@here/maps-api-for-javascript`` (v3.2, HARP engine).  Under
 * ``REACT_APP_MAPS_PROVIDER=here`` + a set ``REACT_APP_HERE_API_KEY``
 * this replaces the Google adapter one-for-one.
 *
 * Boundary contract (K39a §4): NEVER throw at render time — a
 * missing key, dynamic-import failure, or SDK init crash must log
 * and render a "Map unavailable" fallback tile.
 */
import React, {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

/**
 * Context stores the live ``H.Map`` instance so children (Marker,
 * Polyline, InfoWindow) can attach to it. ``null`` before init or
 * after a failed init.
 */
const HereContext = createContext({ map: null, H: null, ready: false });

let _sdkPromise = null;
function _loadHereSDK() {
  // Lazy import so the ~800KB HERE bundle only lands on the map
  // route. Also isolates the ``window``-touching side effects.
  //
  // K39a caveat: ``@here/maps-api-for-javascript`` ships on HERE's
  // private npm registry (``@here:registry=https://repo.platform.here.com/...``).
  // Webpack/Vite would fail the build if it statically resolved the
  // module and the ``.npmrc`` scope isn't configured. We bypass
  // static analysis with a runtime-composed specifier so the
  // resolution only happens if HERE mode is genuinely activated.
  // ``.catch`` renders the K39a fallback tile ("Map unavailable")
  // when the package isn't installed. Install instructions live in
  // ``/app/frontend/src/lib/maps/README.md``.
  if (_sdkPromise) return _sdkPromise;
  const _mod = ["@here", "maps-api-for-javascript"].join("/");
  // eslint-disable-next-line no-new-func
  const _dynImport = new Function("m", "return import(m);");
  try {
    _sdkPromise = _dynImport(_mod)
      .then((mod) => mod?.default || mod)
      .catch((err) => {
        // eslint-disable-next-line no-console
        console.warn("[maps/here] SDK dynamic import failed:", err);
        _sdkPromise = null;
        return null;
      });
  } catch (err) {
    // eslint-disable-next-line no-console
    console.warn("[maps/here] SDK dynamic loader unavailable:", err);
    _sdkPromise = Promise.resolve(null);
  }
  return _sdkPromise;
}

function _fallbackTile(label = "Map unavailable") {
  return (
    <div
      data-testid="maps-here-fallback"
      style={{
        width: "100%",
        height: "100%",
        minHeight: 320,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "#f1f5f9",
        color: "#475569",
        border: "1px dashed #cbd5e1",
        borderRadius: 8,
        fontSize: 13,
      }}
    >
      {label}
    </div>
  );
}

function _toLngLat(p) {
  if (!p) return null;
  const lat = typeof p.lat === "function" ? p.lat() : p.lat;
  const lng = typeof p.lng === "function" ? p.lng() : p.lng ?? p.lon;
  if (typeof lat !== "number" || typeof lng !== "number") return null;
  return { lat, lng };
}

/**
 * ``MapsProviderGate`` in HERE mode is a lightweight identity
 * wrapper — actual HERE SDK init happens per-Map so multiple maps
 * on one page share the same Platform via SDK-internal caching.
 */
export function MapsProviderGate({ children }) {
  return <>{children}</>;
}

export function Map({
  center = { lat: 33.68, lng: -112.38 },
  zoom = 11,
  style,
  children,
  onCameraChanged,
  ...rest
}) {
  const el = useRef(null);
  const mapRef = useRef(null);
  const [ctxValue, setCtxValue] = useState({ map: null, H: null, ready: false });
  const [initError, setInitError] = useState(null);

  useEffect(() => {
    let disposed = false;
    let mapInstance = null;
    let behavior = null;
    let mapEvents = null;
    let ui = null;
    const key = process.env.REACT_APP_HERE_API_KEY || "";
    if (!key) {
      setInitError("no-key");
      return () => {};
    }
    _loadHereSDK()
      .then((H) => {
        if (disposed || !el.current || !H) {
          if (!H) setInitError("sdk-load-failed");
          return;
        }
        try {
          const platform = new H.service.Platform({ apikey: key });
          const layers = platform.createDefaultLayers();
          mapInstance = new H.Map(
            el.current,
            layers.vector.normal.map,
            {
              center: _toLngLat(center) || { lat: 0, lng: 0 },
              zoom,
              pixelRatio:
                typeof window !== "undefined"
                  ? window.devicePixelRatio || 1
                  : 1,
            },
          );
          mapEvents = new H.mapevents.MapEvents(mapInstance);
          behavior = new H.mapevents.Behavior(mapEvents);
          ui = H.ui.UI.createDefault(mapInstance, layers);
          mapRef.current = mapInstance;
          if (typeof onCameraChanged === "function") {
            mapInstance.addEventListener("mapviewchangeend", () => {
              const c = mapInstance.getCenter();
              onCameraChanged({
                detail: {
                  center: { lat: c.lat, lng: c.lng },
                  zoom: mapInstance.getZoom(),
                },
              });
            });
          }
          setCtxValue({ map: mapInstance, H, ready: true });
        } catch (err) {
          // eslint-disable-next-line no-console
          console.warn("[maps/here] map init crashed:", err);
          setInitError(err?.message || "init-failed");
        }
      })
      .catch((err) => {
        // eslint-disable-next-line no-console
        console.warn("[maps/here] SDK promise rejected:", err);
        setInitError("sdk-load-failed");
      });
    const resize = () => mapInstance?.getViewPort?.().resize();
    if (typeof window !== "undefined") window.addEventListener("resize", resize);
    return () => {
      disposed = true;
      if (typeof window !== "undefined") window.removeEventListener("resize", resize);
      try {
        ui?.dispose?.();
        behavior?.dispose?.();
        mapEvents?.dispose?.();
        mapInstance?.dispose?.();
      } catch (err) {
        // eslint-disable-next-line no-console
        console.warn("[maps/here] dispose warn:", err);
      }
      mapRef.current = null;
      setCtxValue({ map: null, H: null, ready: false });
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const c = _toLngLat(center);
    if (c) map.setCenter(c);
    if (typeof zoom === "number") map.setZoom(zoom);
  }, [center, zoom]);

  const value = useMemo(() => ctxValue, [ctxValue]);

  if (initError) return _fallbackTile();

  return (
    <HereContext.Provider value={value}>
      <div
        ref={el}
        data-testid="maps-here-container"
        style={{ width: "100%", height: "100%", minHeight: 320, ...(style || {}) }}
        {...rest}
      />
      {value.ready ? children : null}
    </HereContext.Provider>
  );
}

export const MapView = Map;

export function AdvancedMarker({ position, onClick, children }) {
  const { map, H } = useContext(HereContext);
  useEffect(() => {
    if (!map || !H) return;
    const p = _toLngLat(position);
    if (!p) return;
    let marker;
    try {
      // Use DomMarker for arbitrary HTML content (children); fall
      // back to plain Marker if children is empty.
      if (children) {
        const html =
          typeof children === "string"
            ? children
            : '<div style="width:16px;height:16px;border-radius:50%;background:#2563eb;border:2px solid #fff"></div>';
        const domIcon = new H.map.DomIcon(html);
        marker = new H.map.DomMarker(p, { icon: domIcon });
      } else {
        marker = new H.map.Marker(p);
      }
      if (onClick) marker.addEventListener("tap", onClick);
      map.addObject(marker);
    } catch (err) {
      // eslint-disable-next-line no-console
      console.warn("[maps/here] AdvancedMarker error:", err);
      return;
    }
    return () => {
      try {
        if (onClick) marker.removeEventListener?.("tap", onClick);
        map.removeObject(marker);
      } catch (err) {
        // eslint-disable-next-line no-console
        console.warn("[maps/here] AdvancedMarker cleanup warn:", err);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, H, position?.lat, position?.lng]);
  return null;
}

// Google-parity aliases.
export const Marker = AdvancedMarker;

export function InfoWindow({ position, children, onCloseClick }) {
  const { map, H } = useContext(HereContext);
  useEffect(() => {
    if (!map || !H) return;
    const p = _toLngLat(position);
    if (!p) return;
    let bubble;
    try {
      const html =
        typeof children === "string"
          ? children
          : (children?.props?.children ?? "");
      bubble = new H.ui.InfoBubble(p, { content: String(html) });
      const ui = map.getUI?.();
      if (ui) ui.addBubble(bubble);
      if (onCloseClick) bubble.addEventListener?.("statechange", () => {
        if (bubble.getState() === H.ui.InfoBubble.State.CLOSED) onCloseClick();
      });
    } catch (err) {
      // eslint-disable-next-line no-console
      console.warn("[maps/here] InfoWindow error:", err);
    }
    return () => {
      try {
        const ui = map.getUI?.();
        ui?.removeBubble?.(bubble);
      } catch (err) {
        // eslint-disable-next-line no-console
        console.warn("[maps/here] InfoWindow cleanup warn:", err);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, H, position?.lat, position?.lng]);
  return null;
}

export function Polyline({ path = [], strokeColor = "#1d4ed8", lineWidth = 4 }) {
  const { map, H } = useContext(HereContext);
  useEffect(() => {
    if (!map || !H || !path.length) return;
    let polyline;
    try {
      const line = new H.geo.LineString();
      path.forEach((pt) => {
        const p = _toLngLat(pt);
        if (p) line.pushPoint(p);
      });
      polyline = new H.map.Polyline(line, { style: { strokeColor, lineWidth } });
      map.addObject(polyline);
    } catch (err) {
      // eslint-disable-next-line no-console
      console.warn("[maps/here] Polyline error:", err);
      return;
    }
    return () => {
      try { map.removeObject(polyline); } catch (err) {
        // eslint-disable-next-line no-console
        console.warn("[maps/here] Polyline cleanup warn:", err);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, H, JSON.stringify(path), strokeColor, lineWidth]);
  return null;
}

/** No-op ``<Pin>`` — Google-only concept. */
export function Pin() {
  return null;
}

/** ``useMap`` returns the ``H.Map`` instance for consumer effects. */
export function useMap() {
  return useContext(HereContext).map;
}

/**
 * ``useMapsLibrary`` is a Google concept.  In HERE mode we return
 * an empty proxy so consumers that ``if (lib) { … }`` gracefully
 * skip the library-specific branch.
 */
export function useMapsLibrary() {
  return null;
}
