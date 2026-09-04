import React from "react";
import { StyleSheet, View, Text } from "react-native";
import { MapView, Marker, Polyline, Polygon } from "@/src/lib/maps";
import { hasGoogleMapsKey, MapUnavailablePlaceholder } from "@/src/utils/mapsKey";

type Coord = { latitude: number; longitude: number };

export default function MeasureMap({
  mode,
  points,
  region,
  onRegionChange,
  onPress,
  mapRef,
}: {
  mode: "distance" | "area";
  points: Coord[];
  region: any;
  onRegionChange: (r: any) => void;
  onPress: (c: Coord) => void;
  mapRef?: any;
}) {
  // Phase K20 — safety guard: prevent native crash when Google Maps
  // API key is missing on Android.
  if (!hasGoogleMapsKey()) {
    return (
      <MapUnavailablePlaceholder
        provider="Google Maps"
        testID="measure-map-unavailable"
        message="Google Maps API key not configured. Measurement map requires a valid key."
      />
    );
  }

  return (
    <MapView
      ref={mapRef}
      style={StyleSheet.absoluteFill}
      mapType="hybrid"
      initialRegion={region}
      onRegionChangeComplete={onRegionChange}
      onPress={(e: any) => onPress(e.nativeEvent.coordinate)}
      showsUserLocation
      showsMyLocationButton={false}
      testID="measure-map"
    >
      {mode === "distance" && points.length > 1 ? (
        <Polyline coordinates={points} strokeColor="#F59E0B" strokeWidth={3} />
      ) : null}
      {mode === "area" && points.length > 2 ? (
        <Polygon coordinates={points} strokeColor="#F59E0B" strokeWidth={3} fillColor="rgba(245,158,11,0.25)" />
      ) : null}
      {points.map((p, i) => (
        <Marker key={i} coordinate={p} anchor={{ x: 0.5, y: 0.5 }} tracksViewChanges={false}>
          <MarkerDot index={i} />
        </Marker>
      ))}
    </MapView>
  );
}
function MarkerDot({ index }: { index: number }) {
  return (
    <View style={dotStyles.dot}>
      <Text style={dotStyles.txt}>{index + 1}</Text>
    </View>
  );
}
const dotStyles = StyleSheet.create({
  dot: { width: 22, height: 22, borderRadius: 11, backgroundColor: "#F59E0B", borderWidth: 2, borderColor: "#fff", alignItems: "center", justifyContent: "center" },
  txt: { color: "#fff", fontSize: 11, fontWeight: "700" },
});
