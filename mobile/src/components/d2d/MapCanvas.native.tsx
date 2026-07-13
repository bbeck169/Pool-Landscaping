import React from "react";
import { StyleSheet } from "react-native";
import MapView, { Marker, Polyline } from "react-native-maps";
import { DISPO, leadStatusMeta } from "./dispo";

export default function MapCanvas({ knocks, soldLeads = [], openLeads = [], route, region, onRegionChange, onLongPress, onMarkerPress, onSoldPress, onLeadPress }: any) {
  return (
    <MapView
      style={StyleSheet.absoluteFill}
      region={region}
      onRegionChangeComplete={onRegionChange}
      onLongPress={(e: any) => onLongPress({ lat: e.nativeEvent.coordinate.latitude, lng: e.nativeEvent.coordinate.longitude })}
      showsUserLocation
      testID="d2d-map"
    >
      {route && route.length > 1 ? (
        <Polyline
          coordinates={route.map((p: any) => ({ latitude: p.lat, longitude: p.lng }))}
          strokeColor="#7C3AED"
          strokeWidth={4}
        />
      ) : null}
      {soldLeads.filter((p: any) => p.lat && p.lng && !p.logged).map((p: any) => (
        <Marker
          key={`sold-${p.zpid}`}
          coordinate={{ latitude: p.lat, longitude: p.lng }}
          pinColor={p.skipped ? "#9CA3AF" : "#7C3AED"}
          opacity={p.skipped ? 0.6 : 1}
          title={p.address}
          description={p.price ? `Recently sold · $${Number(p.price).toLocaleString()}${p.skipped ? " · walked" : ""}` : "Recently sold"}
          onPress={() => onSoldPress && onSoldPress(p)}
        />
      ))}
      {openLeads.filter((l: any) => l.lat && l.lng).map((l: any) => (
        <Marker
          key={`lead-${l.id}`}
          coordinate={{ latitude: l.lat, longitude: l.lng }}
          pinColor={leadStatusMeta(l.status).color}
          title={l.name || l.address}
          description={`${leadStatusMeta(l.status).label}${l.address ? ` · ${l.address}` : ""}`}
          onPress={() => onLeadPress && onLeadPress(l)}
        />
      ))}
      {knocks.filter((k: any) => k.lat && k.lng).map((k: any) => (
        <Marker
          key={k.id}
          coordinate={{ latitude: k.lat, longitude: k.lng }}
          pinColor={DISPO[k.disposition]?.color}
          onPress={() => onMarkerPress(k)}
        />
      ))}
    </MapView>
  );
}
