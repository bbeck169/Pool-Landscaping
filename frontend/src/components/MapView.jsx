import React, { useEffect, useState } from "react";
import { MapContainer, TileLayer, Marker, Popup, Polyline, useMap, CircleMarker } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { GoogleMap, Marker as GMarker, InfoWindow, Polyline as GPolyline, useJsApiLoader } from "@react-google-maps/api";
import { api } from "@/api";

// Fix default marker icon paths (CRA doesn't resolve them from the package).
delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png",
  iconUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
  shadowUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",
});

const DOT_COLORS = {
  green: "#16A34A", blue: "#0284C7", yellow: "#CA8A04", red: "#DC2626",
  purple: "#7C3AED", gray: "#71717A", orange: "#EA580C",
};

function coloredIcon(hex) {
  return L.divIcon({
    className: "custom-pin",
    html: `<div style="background:${hex};width:14px;height:14px;border-radius:50%;border:2px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,.4)"></div>`,
    iconSize: [14, 14], iconAnchor: [7, 7], popupAnchor: [0, -7],
  });
}

function Recenter({ center }) {
  const map = useMap();
  useEffect(() => { if (center) map.setView(center, map.getZoom(), { animate: true }); }, [center, map]);
  return null;
}

export default function MapView({
  center = [33.7897, -112.3226], // Vistancia, Peoria AZ
  zoom = 13,
  height = 560,
  layers = [], // [{ key, points: [{id, lat, lng, color, label, subtitle, onClick}], polyline?: [[lat,lng]...] }]
  onMapClick,
  testid = "map-view",
}) {
  const [provider, setProvider] = useState("openstreetmap");
  useEffect(() => {
    api.get("/public/map-settings")
      .then((r) => setProvider(r?.map_provider || "openstreetmap"))
      .catch(() => {});
  }, []);
  if (provider === "google" && process.env.REACT_APP_GOOGLE_API_KEY) {
    return <GoogleMapView center={center} zoom={zoom} height={height} layers={layers} testid={testid} />;
  }
  return <LeafletMapView center={center} zoom={zoom} height={height} layers={layers} testid={testid} />;
}

function LeafletMapView({
  center, zoom, height, layers, testid,
}) {
  return (
    <div
      className="rounded-2xl overflow-hidden"
      style={{ height, border: "1px solid #E4E4E7" }}
      data-testid={testid}
    >
      <MapContainer center={center} zoom={zoom} style={{ height: "100%", width: "100%" }} scrollWheelZoom>
        <TileLayer
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          attribution='&copy; <a href="https://openstreetmap.org">OpenStreetMap</a>'
        />
        <Recenter center={center} />
        {layers.map((L2) => (
          <React.Fragment key={L2.key}>
            {(L2.points || [])
              .filter((p) => Number.isFinite(p.lat) && Number.isFinite(p.lng))
              .map((p) => (
                <Marker
                  key={`${L2.key}-${p.id}`}
                  position={[p.lat, p.lng]}
                  icon={coloredIcon(DOT_COLORS[p.color] || p.color || DOT_COLORS.blue)}
                  eventHandlers={p.onClick ? { click: () => p.onClick(p) } : undefined}
                >
                  {(p.label || p.subtitle) && (
                    <Popup>
                      <div style={{ fontSize: 12 }}>
                        {p.label && <div style={{ fontWeight: 700 }}>{p.label}</div>}
                        {p.subtitle && <div style={{ color: "#52525B" }}>{p.subtitle}</div>}
                        {p.actions}
                      </div>
                    </Popup>
                  )}
                </Marker>
              ))}
            {L2.polyline && L2.polyline.length > 1 && (
              <Polyline
                positions={L2.polyline}
                pathOptions={{ color: L2.polylineColor || "#0284C7", weight: 3, dashArray: L2.dashed ? "6,6" : undefined }}
              />
            )}
            {(L2.circles || []).map((c) => (
              <CircleMarker
                key={`${L2.key}-c-${c.id}`}
                center={[c.lat, c.lng]}
                pathOptions={{ color: c.color || "#0284C7", fillColor: c.color || "#0284C7", fillOpacity: 0.15 }}
                radius={c.radius || 12}
              />
            ))}
          </React.Fragment>
        ))}
      </MapContainer>
    </div>
  );
}

export { DOT_COLORS };

const GOOGLE_LIBS = ["places"];

function GoogleMapView({ center, zoom, height, layers, testid }) {
  const { isLoaded } = useJsApiLoader({
    id: "gm-script",
    googleMapsApiKey: process.env.REACT_APP_GOOGLE_API_KEY,
    libraries: GOOGLE_LIBS,
  });
  const [selected, setSelected] = React.useState(null);
  if (!isLoaded) {
    return (
      <div className="rounded-2xl flex items-center justify-center text-sm"
           style={{ height, border: "1px solid #E4E4E7", color: "#71717A" }} data-testid={testid}>
        Loading Google Maps…
      </div>
    );
  }
  return (
    <div className="rounded-2xl overflow-hidden" style={{ height, border: "1px solid #E4E4E7" }} data-testid={testid}>
      <GoogleMap
        mapContainerStyle={{ width: "100%", height: "100%" }}
        center={{ lat: center[0], lng: center[1] }}
        zoom={zoom}
        options={{ streetViewControl: false, mapTypeControl: true, fullscreenControl: false }}
      >
        {layers.map((L2) => (
          <React.Fragment key={L2.key}>
            {(L2.points || [])
              .filter((p) => Number.isFinite(p.lat) && Number.isFinite(p.lng))
              .map((p) => (
                <GMarker
                  key={`g-${L2.key}-${p.id}`}
                  position={{ lat: p.lat, lng: p.lng }}
                  onClick={() => { setSelected({ key: `${L2.key}-${p.id}`, p }); p.onClick?.(p); }}
                  icon={{
                    path: window.google.maps.SymbolPath.CIRCLE,
                    scale: 7,
                    fillColor: DOT_COLORS[p.color] || p.color || DOT_COLORS.blue,
                    fillOpacity: 1,
                    strokeColor: "#ffffff",
                    strokeWeight: 2,
                  }}
                />
              ))}
            {L2.polyline && L2.polyline.length > 1 && (
              <GPolyline
                path={L2.polyline.map(([lat, lng]) => ({ lat, lng }))}
                options={{
                  strokeColor: L2.polylineColor || "#0284C7",
                  strokeOpacity: L2.dashed ? 0 : 0.8,
                  strokeWeight: 3,
                  icons: L2.dashed ? [{
                    icon: { path: "M 0,-1 0,1", strokeOpacity: 1, scale: 3 },
                    offset: "0", repeat: "10px",
                  }] : undefined,
                }}
              />
            )}
          </React.Fragment>
        ))}
        {selected?.p && (
          <InfoWindow position={{ lat: selected.p.lat, lng: selected.p.lng }} onCloseClick={() => setSelected(null)}>
            <div style={{ fontSize: 12, maxWidth: 240 }}>
              {selected.p.label && <div style={{ fontWeight: 700 }}>{selected.p.label}</div>}
              {selected.p.subtitle && <div style={{ color: "#52525B" }}>{selected.p.subtitle}</div>}
            </div>
          </InfoWindow>
        )}
      </GoogleMap>
    </div>
  );
}
