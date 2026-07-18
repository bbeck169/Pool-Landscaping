import React, { useCallback, useEffect, useMemo, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, TextInput, Platform, Alert, Linking, ActivityIndicator, Image } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import * as Location from "expo-location";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { storage } from "@/src/utils/storage";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import { Loading, Sheet, PrimaryButton, EmptyState } from "@/src/components/ui";
import MapCanvas from "@/src/components/d2d/MapCanvas";
import { DISPO, ORDER, leadStatusMeta } from "@/src/components/d2d/dispo";
import { ZillowUsageChip, ZillowRateLimitedBanner } from "@/src/components/ZillowUsageChip";

const empty = { id: "", address: "", name: "", phone: "", disposition: "not_home", notes: "", lat: null as number | null, lng: null as number | null, zpid: null as string | null, sold_price: null as number | null };

const toRad = (d: number) => (d * Math.PI) / 180;
function haversineMi(a: { lat: number; lng: number }, b: { lat: number; lng: number }) {
  const R = 3958.8;
  const dLat = toRad(b.lat - a.lat), dLng = toRad(b.lng - a.lng);
  const x = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(x));
}
function optimizeRoute(points: any[], start: { lat: number; lng: number }) {
  const remaining = [...points];
  const order: any[] = [];
  let cur = start;
  while (remaining.length) {
    let bi = 0, bd = Infinity;
    remaining.forEach((p, i) => { const d = haversineMi(cur, p); if (d < bd) { bd = d; bi = i; } });
    const nx = remaining.splice(bi, 1)[0];
    order.push(nx);
    cur = nx;
  }
  return order;
}

export default function D2DCanvass() {
  const [knocks, setKnocks] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [region, setRegion] = useState<any>({ latitude: 33.7, longitude: -112.3, latitudeDelta: 0.05, longitudeDelta: 0.05 });
  const [sheet, setSheet] = useState(false);
  const [form, setForm] = useState<any>(empty);
  const [saving, setSaving] = useState(false);
  const [locating, setLocating] = useState(false);
  const [zip, setZip] = useState("85383");
  const [soldLeads, setSoldLeads] = useState<any[]>([]);
  const [loadingSold, setLoadingSold] = useState(false);
  const [tab, setTab] = useState<"doors" | "sold" | "leads">("sold");
  const [showFilters, setShowFilters] = useState(false);
  const [minBeds, setMinBeds] = useState<number | null>(null);
  const [minPrice, setMinPrice] = useState("");
  const [maxPrice, setMaxPrice] = useState("");
  const [soldSheet, setSoldSheet] = useState(false);
  const [route, setRoute] = useState<any[] | null>(null);
  const [routeMiles, setRouteMiles] = useState(0);
  const [soldError, setSoldError] = useState<string | null>(null);
  const [soldProp, setSoldProp] = useState<any>(null);
  const [hideWalked, setHideWalked] = useState(false);
  const [geo, setGeo] = useState<{ lat: number; lng: number } | null>(null);
  const [openLeads, setOpenLeads] = useState<any[]>([]);
  const [loadingLeads, setLoadingLeads] = useState(false);
  const [leadSheet, setLeadSheet] = useState(false);
  const [leadProp, setLeadProp] = useState<any>(null);
  const [convertingLead, setConvertingLead] = useState(false);
  const storeKey = "d2d_sold_working_set";
  const [hydrated, setHydrated] = useState(false);

  const load = useCallback(async () => {
    try {
      const k = await api.get("/d2d/knocks");
      setKnocks(k);
      const withGeo = k.find((x: any) => x.lat && x.lng);
      if (withGeo) setRegion((r: any) => ({ ...r, latitude: withGeo.lat, longitude: withGeo.lng }));
    } catch {
      setKnocks([]);
    } finally {
      setLoading(false);
    }
  }, []);

  // Load knocks + restore previously-loaded sold leads (persisted per tech). No auto-fetch from Zillow.
  useFocusEffect(useCallback(() => {
    load();
    loadOpenLeads();
    (async () => {
      const raw = await storage.getItem<string>(storeKey, "");
      if (raw) { try { const arr = JSON.parse(raw); if (Array.isArray(arr)) setSoldLeads(arr); } catch {} }
      setHydrated(true);
    })();
  }, [load]));

  // Open CRM leads (not won/lost) shown as map pins; geocode any missing coordinates (native).
  const loadOpenLeads = async () => {
    setLoadingLeads(true);
    try {
      const res = await api.get("/d2d/open-leads");
      const leads = res.leads || [];
      setOpenLeads(leads);
      if (Platform.OS !== "web") {
        for (const l of leads) {
          if ((l.lat == null || l.lng == null) && l.address) {
            try {
              const g = await Location.geocodeAsync(l.address);
              if (g?.[0]) {
                l.lat = g[0].latitude; l.lng = g[0].longitude;
                setOpenLeads((prev) => prev.map((x) => (x.id === l.id ? { ...x, lat: l.lat, lng: l.lng } : x)));
              }
            } catch {}
          }
        }
      }
    } catch {
      setOpenLeads([]);
    } finally {
      setLoadingLeads(false);
    }
  };

  const openLeadDetail = (l: any) => { setLeadProp(l); setLeadSheet(true); };
  const callLead = (l: any) => { if (l?.phone) Linking.openURL(`tel:${l.phone}`); };
  const navigateToLead = (l: any) => {
    if (l?.lat && l?.lng) return navigateTo({ lat: l.lat, lng: l.lng, address: l.address });
    if (l?.address) Linking.openURL(`https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(l.address)}`);
    else Alert.alert("No location", "This lead has no address or coordinates.");
  };
  const convertLead = async (l: any) => {
    if (!l?.id) return;
    setConvertingLead(true);
    try {
      const cust = await api.post(`/leads/${l.id}/convert`, {});
      setLeadSheet(false);
      setOpenLeads((prev) => prev.filter((x) => x.id !== l.id));
      Alert.alert("Converted 🎉", `${cust.name} is now a customer.`);
    } catch (e: any) {
      Alert.alert("Error", e.message || "Could not convert this lead.");
    } finally {
      setConvertingLead(false);
    }
  };

  // Persist the working set so the tech doesn't have to refresh until they've worked through it.
  useEffect(() => {
    if (hydrated) storage.setItem(storeKey, JSON.stringify(soldLeads));
  }, [soldLeads, hydrated, storeKey]);

  const getLocation = async (): Promise<{ lat: number; lng: number } | null> => {
    const perm = await Location.getForegroundPermissionsAsync();
    let status = perm.status;
    if (status !== "granted") {
      if (!perm.canAskAgain) {
        Alert.alert("Location is off", "Enable location to drop pins at your position. You can still log doors by address.", [
          { text: "Not now", style: "cancel" },
          { text: "Open Settings", onPress: () => Linking.openSettings() },
        ]);
        return null;
      }
      const req = await Location.requestForegroundPermissionsAsync();
      status = req.status;
      if (status !== "granted") return null;
    }
    const pos = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
    const coords = { lat: pos.coords.latitude, lng: pos.coords.longitude };
    setGeo(coords);
    return coords;
  };

  const openAdd = (coords?: { lat: number; lng: number } | null) => {
    setForm({ ...empty, lat: coords?.lat ?? null, lng: coords?.lng ?? null });
    setSheet(true);
  };

  const logAtMyLocation = async () => {
    setLocating(true);
    try {
      const c = await getLocation();
      if (c) setRegion((r: any) => ({ ...r, latitude: c.lat, longitude: c.lng }));
      openAdd(c);
    } finally {
      setLocating(false);
    }
  };

  const openEdit = (k: any) => {
    setForm({ id: k.id, address: k.address || "", name: k.name || "", phone: k.phone || "", disposition: k.disposition, notes: k.notes || "", lat: k.lat, lng: k.lng });
    setSheet(true);
  };

  const loadSold = async (zipArg?: string, silent = false) => {
    const z = (zipArg ?? zip).trim();
    if (!/^\d{5}$/.test(z)) {
      if (!silent) Alert.alert("ZIP required", "Enter a valid 5-digit ZIP code.");
      return;
    }
    setLoadingSold(true);
    setSoldError(null);
    try {
      const qs = [`zip=${z}`, `days=30`];
      if (minBeds) qs.push(`min_beds=${minBeds}`);
      if (minPrice.trim()) qs.push(`min_price=${parseInt(minPrice, 10)}`);
      if (maxPrice.trim()) qs.push(`max_price=${parseInt(maxPrice, 10)}`);
      const res = await api.get(`/d2d/sold-leads?${qs.join("&")}`);
      const props = res.properties || [];
      // Merge with the tech's existing working set: dedupe by zpid, keep previously-loaded
      // leads (so no forced refresh) and preserve their local skipped state.
      const byId = new Map<string, any>();
      soldLeads.forEach((p) => byId.set(p.zpid, p));
      let added = 0;
      props.forEach((np: any) => {
        const ex = byId.get(np.zpid);
        if (ex) byId.set(np.zpid, { ...ex, ...np, skipped: ex.skipped || np.skipped });
        else { byId.set(np.zpid, np); added += 1; }
      });
      setSoldLeads(Array.from(byId.values()));
      setRoute(null);
      setTab("sold");
      const first = props.find((p: any) => p.lat && p.lng);
      if (first) setRegion((r: any) => ({ ...r, latitude: first.lat, longitude: first.lng }));
      if (!silent) {
        Alert.alert("Leads refreshed", added > 0 ? `Added ${added} new lead${added === 1 ? "" : "s"}.` : "No new leads — your list is up to date.");
      }
    } catch (e: any) {
      setSoldError(e.message || "Zillow data is unavailable right now.");
      setTab("sold");
      if (!silent) Alert.alert("Couldn't load", e.message || "Zillow data is unavailable right now.");
    } finally {
      setLoadingSold(false);
    }
  };

  const navigateTo = (p: any) => {
    if (!p?.lat || !p?.lng) { Alert.alert("No location", "This home has no map coordinates."); return; }
    const dest = `${p.lat},${p.lng}`;
    const label = encodeURIComponent(p.address || "Destination");
    const url = Platform.select({
      ios: `http://maps.apple.com/?daddr=${dest}&q=${label}`,
      android: `google.navigation:q=${dest}`,
      default: `https://www.google.com/maps/dir/?api=1&destination=${dest}`,
    }) as string;
    Linking.openURL(url).catch(() => Linking.openURL(`https://www.google.com/maps/dir/?api=1&destination=${dest}`));
  };

  const openSold = (p: any) => { setSoldProp(p); setSoldSheet(true); };

  const planRoute = () => {
    const pts = soldLeads.filter((p) => p.lat && p.lng && !p.skipped);
    if (pts.length < 2) {
      Alert.alert("Not enough stops", "Load recently-sold homes first (need at least 2 un-walked homes).");
      return;
    }
    const start = geo || { lat: region.latitude, lng: region.longitude };
    const ordered = optimizeRoute(pts, start);
    let miles = haversineMi(start, ordered[0]);
    for (let i = 1; i < ordered.length; i++) miles += haversineMi(ordered[i - 1], ordered[i]);
    setRoute(ordered);
    setRouteMiles(miles);
    setTab("sold");
    if (ordered[0]) setRegion((r: any) => ({ ...r, latitude: ordered[0].lat, longitude: ordered[0].lng }));
  };

  const clearRoute = () => { setRoute(null); setRouteMiles(0); };

  const openRouteInMaps = () => {
    if (!route || !route.length) return;
    const MAX = 10; // Google Maps URL supports ~10 stops
    const stops = route.slice(0, MAX);
    const dest = `${stops[stops.length - 1].lat},${stops[stops.length - 1].lng}`;
    const way = stops.slice(0, -1).map((p) => `${p.lat},${p.lng}`).join("|");
    let url = `https://www.google.com/maps/dir/?api=1&destination=${dest}&travelmode=driving`;
    if (geo) url += `&origin=${geo.lat},${geo.lng}`;
    if (way) url += `&waypoints=${encodeURIComponent(way)}`;
    const go = () => Linking.openURL(url);
    if (route.length > MAX) {
      Alert.alert("Long route", `Opening the first ${MAX} stops in Maps. Mark them walked and re-plan for the rest.`, [
        { text: "Cancel", style: "cancel" }, { text: "Open", onPress: go },
      ]);
    } else { go(); }
  };

  const toggleSkip = async (p: any) => {
    const next = !p.skipped;
    // optimistic update in list + open sheet
    setSoldLeads((prev) => prev.map((x) => (x.zpid === p.zpid ? { ...x, skipped: next } : x)));
    setSoldProp((cur: any) => (cur && cur.zpid === p.zpid ? { ...cur, skipped: next } : cur));
    try {
      if (next) await api.post(`/d2d/skip/${p.zpid}`, {});
      else await api.del(`/d2d/skip/${p.zpid}`);
    } catch {
      // revert on failure
      setSoldLeads((prev) => prev.map((x) => (x.zpid === p.zpid ? { ...x, skipped: !next } : x)));
      setSoldProp((cur: any) => (cur && cur.zpid === p.zpid ? { ...cur, skipped: !next } : cur));
    }
  };

  const fmtSold = (p: any) => {
    const price = p.price ? `$${Number(p.price).toLocaleString()}` : "";
    const d = p.date_sold ? new Date(p.date_sold).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "";
    const bb = [p.beds ? `${p.beds}bd` : "", p.baths ? `${p.baths}ba` : "", p.sqft ? `${Number(p.sqft).toLocaleString()} sqft` : ""].filter(Boolean).join(" · ");
    return { price, d, bb };
  };

  const openAddFromSold = (p: any) => {
    const { price, d } = fmtSold(p);
    setForm({
      ...empty,
      address: p.address || "",
      lat: p.lat ?? null,
      lng: p.lng ?? null,
      zpid: p.zpid || null,
      sold_price: p.price ?? null,
      notes: `Recently sold${price ? ` for ${price}` : ""}${d ? ` on ${d}` : ""}. New owner — pool service lead.`,
      disposition: "not_home",
    });
    setSheet(true);
  };

  const save = async () => {
    setSaving(true);
    try {
      const body: any = { address: form.address, name: form.name, phone: form.phone, disposition: form.disposition, notes: form.notes, lat: form.lat, lng: form.lng };
      if (form.zpid) body.zpid = form.zpid;
      if (form.sold_price != null) body.sold_price = form.sold_price;
      if (form.id) await api.put(`/d2d/knocks/${form.id}`, body);
      else await api.post("/d2d/knocks", body);
      setSheet(false);
      await load();
      if (form.zpid) setSoldLeads((prev) => prev.map((p) => (p.zpid === form.zpid ? { ...p, logged: true } : p)));
    } catch (e: any) {
      Alert.alert("Error", e.message || "Could not save.");
    } finally {
      setSaving(false);
    }
  };

  const del = async () => {
    if (!form.id) return;
    try { await api.del(`/d2d/knocks/${form.id}`); setSheet(false); await load(); } catch {}
  };

  const convert = async () => {
    setSaving(true);
    try {
      const cust = await api.post(`/d2d/knocks/${form.id}/convert`, {});
      setSheet(false);
      await load();
      Alert.alert("Converted 🎉", `${cust.name} is now a customer.`);
    } catch (e: any) {
      Alert.alert("Error", e.message || "Could not convert.");
    } finally {
      setSaving(false);
    }
  };

  const stats = useMemo(() => {
    const s = { knocks: knocks.length, leads: 0, sold: 0 };
    knocks.forEach((k) => {
      if (k.disposition === "interested" || k.disposition === "sold") s.leads++;
      if (k.disposition === "sold") s.sold++;
    });
    return s;
  }, [knocks]);

  if (loading) return <Loading testID="d2d-loading" />;
  const canConvert = form.disposition === "interested" || form.disposition === "sold";
  const walkedCount = soldLeads.filter((p) => p.skipped).length;
  const routeIndex: Record<string, number> = {};
  if (route) route.forEach((p, i) => { routeIndex[p.zpid] = i + 1; });
  const visibleSold = (hideWalked ? soldLeads.filter((p) => !p.skipped) : soldLeads)
    .slice()
    .sort((a, b) => {
      if (a.skipped !== b.skipped) return a.skipped ? 1 : -1;
      if (route) return (routeIndex[a.zpid] || 999) - (routeIndex[b.zpid] || 999);
      return 0;
    });

  return (
    <View style={styles.root}>
      <Header title="Door-to-Door" back subtitle="Log knocks & capture leads"
              right={<ZillowUsageChip testID="d2d-zillow-chip" />} />
      <ZillowRateLimitedBanner testID="d2d-zillow-banner" />

      <ScrollView style={styles.scroll} contentContainerStyle={{ paddingBottom: spacing["3xl"] }} keyboardShouldPersistTaps="handled">
        <View style={styles.mapBox}>
          <MapCanvas
            knocks={knocks}
            soldLeads={tab === "leads" ? [] : soldLeads}
            openLeads={tab === "leads" ? openLeads : []}
            route={tab === "leads" ? null : route}
            region={region}
            onRegionChange={setRegion}
            onLongPress={(coords: any) => openAdd(coords)}
            onMarkerPress={(k: any) => openEdit(k)}
            onSoldPress={(p: any) => openSold(p)}
            onLeadPress={(l: any) => openLeadDetail(l)}
          />
        </View>

        {tab !== "leads" ? (
          <View style={styles.zipRow}>
            <View style={styles.zipInputWrap}>
              <Ionicons name="location-outline" size={16} color={colors.muted} />
              <TextInput
                style={styles.zipInput}
                value={zip}
                onChangeText={(v) => setZip(v.replace(/[^0-9]/g, "").slice(0, 5))}
                placeholder="Recently-sold by ZIP"
                placeholderTextColor={colors.muted}
                keyboardType="number-pad"
                maxLength={5}
                testID="d2d-zip"
              />
            </View>
            <Pressable style={[styles.zipBtn, loadingSold && { opacity: 0.7 }]} onPress={() => loadSold()} disabled={loadingSold} testID="d2d-load-sold">
              {loadingSold ? <ActivityIndicator color="#fff" size="small" /> : <Ionicons name="refresh" size={16} color="#fff" />}
              <Text style={styles.zipBtnText}>{loadingSold ? "Loading…" : "Refresh Leads"}</Text>
            </Pressable>
          </View>
        ) : (
          <Pressable style={styles.leadRefresh} onPress={loadOpenLeads} disabled={loadingLeads} testID="d2d-refresh-open-leads">
            {loadingLeads ? <ActivityIndicator color={colors.brand} size="small" /> : <Ionicons name="refresh" size={16} color={colors.brand} />}
            <Text style={styles.leadRefreshText}>{loadingLeads ? "Refreshing…" : "Refresh open leads"}</Text>
          </Pressable>
        )}

        {tab === "sold" ? (
          <Pressable style={styles.filterToggle} onPress={() => setShowFilters((s) => !s)} testID="d2d-filter-toggle">
            <Ionicons name="options-outline" size={15} color={colors.brand} />
            <Text style={styles.filterToggleText}>
              Target filters{minBeds || minPrice.trim() || maxPrice.trim() ? ` · ${[minBeds ? `${minBeds}+ bd` : "", minPrice.trim() ? `≥$${minPrice}` : "", maxPrice.trim() ? `≤$${maxPrice}` : ""].filter(Boolean).join(", ")}` : ""}
            </Text>
            <Ionicons name={showFilters ? "chevron-up" : "chevron-down"} size={15} color={colors.muted} />
          </Pressable>
        ) : null}

        {showFilters && tab === "sold" ? (
          <View style={styles.filterBox}>
            <Text style={styles.label}>Min bedrooms</Text>
            <View style={styles.chipRow}>
              {[null, 2, 3, 4, 5].map((b) => (
                <Pressable key={String(b)} style={[styles.bedChip, minBeds === b && styles.bedChipActive]} onPress={() => setMinBeds(b)} testID={`d2d-minbeds-${b ?? "any"}`}>
                  <Text style={[styles.bedChipText, minBeds === b && { color: "#fff" }]}>{b ? `${b}+` : "Any"}</Text>
                </Pressable>
              ))}
            </View>
            <View style={styles.priceRow}>
              <View style={{ flex: 1 }}>
                <Text style={styles.label}>Min price ($)</Text>
                <TextInput style={styles.priceInput} value={minPrice} onChangeText={(v) => setMinPrice(v.replace(/[^0-9]/g, ""))} placeholder="e.g. 400000" placeholderTextColor={colors.muted} keyboardType="number-pad" testID="d2d-minprice" />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.label}>Max price ($)</Text>
                <TextInput style={styles.priceInput} value={maxPrice} onChangeText={(v) => setMaxPrice(v.replace(/[^0-9]/g, ""))} placeholder="e.g. 900000" placeholderTextColor={colors.muted} keyboardType="number-pad" testID="d2d-maxprice" />
              </View>
            </View>
            {minBeds || minPrice.trim() || maxPrice.trim() ? (
              <Pressable onPress={() => { setMinBeds(null); setMinPrice(""); setMaxPrice(""); }} testID="d2d-clear-filters">
                <Text style={styles.clearFilters}>Clear filters</Text>
              </Pressable>
            ) : null}
          </View>
        ) : null}

        <View style={styles.statsRow}>
          <Stat label="Knocks" value={stats.knocks} color={colors.brand} />
          <Stat label="Leads" value={stats.leads} color="#0284C7" />
          <Stat label="Sold" value={stats.sold} color="#16A34A" />
        </View>

        <Pressable style={styles.logBtn} onPress={logAtMyLocation} disabled={locating} testID="d2d-log-door">
          {locating ? <ActivityIndicator color="#fff" /> : <Ionicons name="add-circle" size={18} color="#fff" />}
          <Text style={styles.logBtnText}>{locating ? "Locating…" : "Log a door"}</Text>
        </Pressable>

        <View style={styles.tabRow}>
          <Pressable style={[styles.tab, tab === "doors" && styles.tabActive]} onPress={() => setTab("doors")} testID="d2d-tab-doors">
            <Text style={[styles.tabText, tab === "doors" && styles.tabTextActive]} numberOfLines={1}>Doors ({knocks.length})</Text>
          </Pressable>
          <Pressable style={[styles.tab, tab === "leads" && styles.tabActive]} onPress={() => setTab("leads")} testID="d2d-tab-leads">
            <Text style={[styles.tabText, tab === "leads" && styles.tabTextActive]} numberOfLines={1}>Open Leads ({openLeads.length})</Text>
          </Pressable>
          <Pressable style={[styles.tab, tab === "sold" && styles.tabActive]} onPress={() => setTab("sold")} testID="d2d-tab-sold">
            <Text style={[styles.tabText, tab === "sold" && styles.tabTextActive]} numberOfLines={1}>Sold ({soldLeads.length})</Text>
          </Pressable>
        </View>

        <View style={{ paddingHorizontal: spacing.lg, paddingTop: spacing.sm }}>
          {tab === "doors" ? (
            knocks.length === 0 ? (
              <EmptyState icon="footsteps-outline" title="No doors yet" subtitle="Tap 'Log a door' to record your first knock." testID="d2d-empty" />
            ) : (
              knocks.map((k) => {
                const d = DISPO[k.disposition] || DISPO.not_home;
                return (
                  <Pressable key={k.id} style={styles.card} onPress={() => openEdit(k)} testID={`d2d-knock-${k.id}`}>
                    <View style={[styles.dot, { backgroundColor: d.color }]}>
                      <Ionicons name={d.icon as any} size={15} color="#fff" />
                    </View>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.cardTitle} numberOfLines={1}>{k.address || k.name || "Door"}</Text>
                      <Text style={styles.cardMeta} numberOfLines={1}>{d.label}{k.name && k.address ? ` · ${k.name}` : ""}{k.converted ? " · ✓ customer" : ""}</Text>
                    </View>
                    <Ionicons name="chevron-forward" size={18} color={colors.muted} />
                  </Pressable>
                );
              })
            )
          ) : tab === "leads" ? (
            loadingLeads && openLeads.length === 0 ? (
              <View style={styles.soldLoading} testID="d2d-leads-loading">
                <ActivityIndicator color="#0284C7" />
                <Text style={styles.soldLoadingText}>Loading open leads…</Text>
              </View>
            ) : openLeads.length === 0 ? (
              <EmptyState icon="people-outline" title="No open leads" subtitle="Leads that aren't won or lost will appear here as map pins and cards." testID="d2d-leads-empty" />
            ) : (
              openLeads.map((l) => {
                const sm = leadStatusMeta(l.status);
                return (
                <Pressable key={l.id} style={styles.card} onPress={() => openLeadDetail(l)} testID={`d2d-lead-${l.id}`}>
                  <View style={[styles.dot, { backgroundColor: sm.color }]}>
                    <Ionicons name="person" size={15} color="#fff" />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.cardTitle} numberOfLines={1}>{l.name || l.address || "Lead"}</Text>
                    <Text style={styles.cardMeta} numberOfLines={1}>{[l.address, l.phone, l.source].filter(Boolean).join(" · ") || "Open lead"}</Text>
                  </View>
                  <View style={[styles.statusBadge, { backgroundColor: sm.color + "1A", borderColor: sm.color }]}>
                    <Text style={[styles.statusBadgeText, { color: sm.color }]}>{sm.label}</Text>
                  </View>
                </Pressable>
                );
              })
            )
          ) : loadingSold && soldLeads.length === 0 ? (
            <View style={styles.soldLoading} testID="d2d-sold-loading">
              <ActivityIndicator color="#7C3AED" />
              <Text style={styles.soldLoadingText}>Pulling recently-sold homes…</Text>
            </View>
          ) : soldError && soldLeads.length === 0 ? (
            <View style={styles.errorBox} testID="d2d-sold-error">
              <Ionicons name="cloud-offline-outline" size={26} color={colors.error} />
              <Text style={styles.errorText}>{soldError}</Text>
              <Pressable style={styles.retryBtn} onPress={() => loadSold()} testID="d2d-sold-retry">
                <Ionicons name="refresh" size={15} color="#fff" />
                <Text style={styles.retryText}>Try again</Text>
              </Pressable>
            </View>
          ) : soldLeads.length === 0 ? (
            <EmptyState icon="home-outline" title="No leads loaded" subtitle="Enter a ZIP above and tap 'Refresh Leads' to pull homes sold in the last 30 days." testID="d2d-sold-empty" />
          ) : (
            <>
              {route ? (
                <View style={styles.routeBanner} testID="d2d-route-banner">
                  <Ionicons name="navigate-circle" size={20} color="#fff" />
                  <View style={{ flex: 1 }}>
                    <Text style={styles.routeTitle}>Optimized route · {route.length} stops</Text>
                    <Text style={styles.routeSub}>~{routeMiles.toFixed(1)} mi driving · nearest-first</Text>
                  </View>
                  <Pressable onPress={openRouteInMaps} style={styles.routeGoBtn} testID="d2d-route-open">
                    <Ionicons name="map" size={14} color="#7C3AED" />
                    <Text style={styles.routeGoText}>Open</Text>
                  </Pressable>
                  <Pressable onPress={clearRoute} hitSlop={8} testID="d2d-route-clear">
                    <Ionicons name="close-circle" size={22} color="rgba(255,255,255,0.85)" />
                  </Pressable>
                </View>
              ) : (
                <Pressable style={styles.planBtn} onPress={planRoute} testID="d2d-plan-route">
                  <Ionicons name="navigate" size={16} color="#fff" />
                  <Text style={styles.planBtnText}>Plan efficient route</Text>
                </Pressable>
              )}
              {walkedCount > 0 ? (
                <Pressable style={styles.hideWalkedRow} onPress={() => setHideWalked((s) => !s)} testID="d2d-hide-walked">
                  <Ionicons name={hideWalked ? "eye-off-outline" : "eye-outline"} size={15} color={colors.muted} />
                  <Text style={styles.hideWalkedText}>{hideWalked ? `Showing remaining · ${walkedCount} walked hidden` : `Hide ${walkedCount} walked`}</Text>
                </Pressable>
              ) : null}
              {visibleSold.map((p) => {
                const { price, d, bb } = fmtSold(p);
                const dotColor = p.skipped ? "#9CA3AF" : p.logged ? "#16A34A" : "#7C3AED";
                const stopNo = route && !p.skipped ? routeIndex[p.zpid] : undefined;
                return (
                  <Pressable key={p.zpid} style={[styles.card, p.skipped && styles.cardSkipped]} onPress={() => openSold(p)} testID={`d2d-sold-${p.zpid}`}>
                    <View style={[styles.dot, { backgroundColor: stopNo ? "#7C3AED" : dotColor }]}>
                      {stopNo ? <Text style={styles.stopNum}>{stopNo}</Text> : <Ionicons name={p.skipped ? "walk" : p.logged ? "checkmark" : "home"} size={15} color="#fff" />}
                    </View>
                    <View style={{ flex: 1 }}>
                      <Text style={[styles.cardTitle, p.skipped && styles.textMuted]} numberOfLines={1}>{p.address}</Text>
                      <Text style={styles.cardMeta} numberOfLines={1}>{p.skipped ? "Walked · " : ""}{[price && `Sold ${price}`, d, bb].filter(Boolean).join(" · ")}</Text>
                    </View>
                    <Pressable hitSlop={10} onPress={() => toggleSkip(p)} style={styles.walkBtn} testID={`d2d-walk-${p.zpid}`}>
                      <Ionicons name={p.skipped ? "refresh" : "walk"} size={19} color={p.skipped ? colors.brand : colors.muted} />
                    </Pressable>
                  </Pressable>
                );
              })}
            </>
          )}
        </View>
      </ScrollView>

      <Sheet visible={sheet} onClose={() => setSheet(false)} title={form.id ? "Update Door" : "Log Door"} testID="d2d-sheet">
        <ScrollView keyboardShouldPersistTaps="handled" style={{ maxHeight: 460 }}>
          <Text style={styles.label}>Disposition</Text>
          <View style={styles.chipRow}>
            {ORDER.map((key) => (
              <Pressable key={key} style={[styles.chip, form.disposition === key && { backgroundColor: DISPO[key].color, borderColor: DISPO[key].color }]} onPress={() => setForm((f: any) => ({ ...f, disposition: key }))} testID={`d2d-dispo-${key}`}>
                <Text style={[styles.chipText, form.disposition === key && { color: "#fff" }]}>{DISPO[key].label}</Text>
              </Pressable>
            ))}
          </View>
          <Field label="Address" value={form.address} onChangeText={(v: string) => setForm((f: any) => ({ ...f, address: v }))} placeholder="123 Palm St" testID="d2d-address" />
          <Field label="Name" value={form.name} onChangeText={(v: string) => setForm((f: any) => ({ ...f, name: v }))} placeholder="Homeowner name" testID="d2d-name" />
          <Field label="Phone" value={form.phone} onChangeText={(v: string) => setForm((f: any) => ({ ...f, phone: v }))} placeholder="480-555-0100" keyboardType="phone-pad" testID="d2d-phone" />
          <Field label="Notes" value={form.notes} onChangeText={(v: string) => setForm((f: any) => ({ ...f, notes: v }))} placeholder="Interested in weekly cleaning…" multiline testID="d2d-notes" />
          {form.zpid ? <Text style={styles.soldTag}>🏠 Recently sold home from Zillow</Text> : null}
          {form.lat ? <Text style={styles.geoTag}>📍 Pinned at your location</Text> : null}
          <View style={{ height: spacing.md }} />
          <PrimaryButton title={form.id ? "Save" : "Log Door"} icon="checkmark" loading={saving} onPress={save} testID="d2d-save" />
          {form.id && canConvert && !knocks.find((k) => k.id === form.id)?.converted ? (
            <Pressable style={styles.convertBtn} onPress={convert} disabled={saving} testID="d2d-convert">
              <Ionicons name="person-add" size={16} color="#fff" />
              <Text style={styles.convertText}>Convert to Customer</Text>
            </Pressable>
          ) : null}
          {form.id ? (
            <Pressable style={styles.delBtn} onPress={del} testID="d2d-delete">
              <Text style={styles.delText}>Delete door</Text>
            </Pressable>
          ) : null}
        </ScrollView>
      </Sheet>

      <Sheet visible={soldSheet} onClose={() => setSoldSheet(false)} title="Recently Sold Home" testID="d2d-sold-sheet">
        {soldProp ? (
          <View>
            {soldProp.image ? (
              <Image source={{ uri: soldProp.image }} style={styles.soldImg} resizeMode="cover" />
            ) : null}
            <Text style={styles.soldAddr}>{soldProp.address}</Text>
            <View style={styles.soldMetaRow}>
              {soldProp.price ? <Text style={styles.soldPrice}>${Number(soldProp.price).toLocaleString()}</Text> : null}
              <Text style={styles.soldSub}>{[soldProp.beds ? `${soldProp.beds} bd` : "", soldProp.baths ? `${soldProp.baths} ba` : "", soldProp.sqft ? `${Number(soldProp.sqft).toLocaleString()} sqft` : ""].filter(Boolean).join(" · ")}</Text>
            </View>
            {soldProp.date_sold ? <Text style={styles.soldSub}>Sold {new Date(soldProp.date_sold).toLocaleDateString(undefined, { month: "long", day: "numeric", year: "numeric" })}</Text> : null}
            {soldProp.logged ? <Text style={[styles.soldTag, { color: "#16A34A" }]}>✓ Already logged as a door</Text> : null}
            <View style={{ height: spacing.md }} />
            <PrimaryButton title="Navigate here" icon="navigate" onPress={() => navigateTo(soldProp)} testID="d2d-sold-navigate" />
            {!soldProp.logged ? (
              <Pressable style={styles.logSoldBtn} onPress={() => { setSoldSheet(false); openAddFromSold(soldProp); }} testID="d2d-sold-log">
                <Ionicons name="add-circle" size={16} color="#fff" />
                <Text style={styles.convertText}>Log as door</Text>
              </Pressable>
            ) : null}
            {soldProp.detail_url ? (
              <Pressable style={styles.zillowLink} onPress={() => Linking.openURL(soldProp.detail_url)} testID="d2d-sold-zillow">
                <Text style={styles.zillowLinkText}>View on Zillow ↗</Text>
              </Pressable>
            ) : null}
            <Pressable style={styles.skipRow} onPress={() => toggleSkip(soldProp)} testID="d2d-sold-skip">
              <Ionicons name={soldProp.skipped ? "refresh" : "walk"} size={16} color={colors.muted} />
              <Text style={styles.skipRowText}>{soldProp.skipped ? "Un-mark (still a target)" : "Mark as walked / skip"}</Text>
            </Pressable>
          </View>
        ) : null}
      </Sheet>

      <Sheet visible={leadSheet} onClose={() => setLeadSheet(false)} title="Open Lead" testID="d2d-lead-sheet">
        {leadProp ? (
          <View>
            <Text style={styles.soldAddr}>{leadProp.name || leadProp.address || "Lead"}</Text>
            <View style={[styles.statusBadge, { alignSelf: "flex-start", marginTop: spacing.xs, backgroundColor: leadStatusMeta(leadProp.status).color + "1A", borderColor: leadStatusMeta(leadProp.status).color }]}>
              <Text style={[styles.statusBadgeText, { color: leadStatusMeta(leadProp.status).color }]}>{leadStatusMeta(leadProp.status).label}</Text>
            </View>
            {leadProp.name && leadProp.address ? <Text style={styles.soldSub}>{leadProp.address}</Text> : null}
            {leadProp.phone ? <Text style={styles.soldSub}>📞 {leadProp.phone}</Text> : null}
            {leadProp.source ? <Text style={styles.soldSub}>Source: {leadProp.source}</Text> : null}
            {leadProp.notes ? <Text style={[styles.soldSub, { marginTop: spacing.sm }]}>{leadProp.notes}</Text> : null}
            <View style={{ height: spacing.md }} />
            <PrimaryButton title="Navigate here" icon="navigate" onPress={() => navigateToLead(leadProp)} testID="d2d-lead-navigate" />
            {leadProp.phone ? (
              <Pressable style={styles.logSoldBtn} onPress={() => callLead(leadProp)} testID="d2d-lead-call">
                <Ionicons name="call" size={16} color="#fff" />
                <Text style={styles.convertText}>Call lead</Text>
              </Pressable>
            ) : null}
            <Pressable style={[styles.convertBtn, convertingLead && { opacity: 0.7 }]} onPress={() => convertLead(leadProp)} disabled={convertingLead} testID="d2d-lead-convert">
              {convertingLead ? <ActivityIndicator color="#fff" size="small" /> : <Ionicons name="person-add" size={16} color="#fff" />}
              <Text style={styles.convertText}>{convertingLead ? "Converting…" : "Convert to Customer"}</Text>
            </Pressable>
          </View>
        ) : null}
      </Sheet>
    </View>
  );
}

function Stat({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <View style={styles.stat}>
      <Text style={[styles.statVal, { color }]}>{value}</Text>
      <Text style={styles.statLabel}>{label}</Text>
    </View>
  );
}

function Field({ label, ...props }: any) {
  return (
    <View style={{ marginTop: spacing.sm }}>
      <Text style={styles.label}>{label}</Text>
      <TextInput style={[styles.input, props.multiline && { height: 72, textAlignVertical: "top" }]} placeholderTextColor={colors.muted} {...props} />
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  scroll: { flex: 1 },
  mapBox: { height: 220, backgroundColor: colors.surfaceTertiary },
  mapPlaceholder: { flex: 1, alignItems: "center", justifyContent: "center", padding: spacing.lg, gap: spacing.sm },
  mapPlaceholderText: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, textAlign: "center", lineHeight: 20 },
  statsRow: { flexDirection: "row", gap: spacing.sm, padding: spacing.lg, paddingBottom: spacing.sm },
  stat: { flex: 1, backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border, alignItems: "center" },
  statVal: { fontFamily: font.bold, fontSize: fontSize["2xl"] },
  statLabel: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  logBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, marginHorizontal: spacing.lg, height: 48, borderRadius: radius.md, backgroundColor: colors.brand },
  logBtnText: { fontFamily: font.semibold, fontSize: fontSize.base, color: "#fff" },
  zipRow: { flexDirection: "row", gap: spacing.sm, paddingHorizontal: spacing.lg, paddingTop: spacing.md },
  zipInputWrap: { flex: 1, flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: colors.surface, borderWidth: 1.5, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: spacing.md, height: 46 },
  zipInput: { flex: 1, fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}) },
  zipBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, paddingHorizontal: spacing.md, height: 46, borderRadius: radius.md, backgroundColor: "#7C3AED" },
  zipBtnText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: "#fff" },
  filterToggle: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: spacing.lg, paddingTop: spacing.sm },
  filterToggleText: { flex: 1, fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand },
  filterBox: { marginHorizontal: spacing.lg, marginTop: spacing.xs, padding: spacing.md, backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border },
  bedChip: { paddingHorizontal: spacing.md, height: 34, borderRadius: radius.pill, alignItems: "center", justifyContent: "center", backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border },
  bedChipActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  bedChipText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  priceRow: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.xs },
  priceInput: { backgroundColor: colors.surfaceSecondary, borderWidth: 1.5, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: spacing.md, height: 44, fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}) },
  clearFilters: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.error, marginTop: spacing.sm },
  tabRow: { flexDirection: "row", gap: spacing.sm, paddingHorizontal: spacing.lg, paddingTop: spacing.md },
  tab: { flex: 1, height: 40, borderRadius: radius.md, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  tabActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  tabText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  tabTextActive: { color: "#fff" },
  card: { flexDirection: "row", alignItems: "center", gap: spacing.md, backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.sm },
  cardSkipped: { opacity: 0.55 },
  statusBadge: { paddingHorizontal: spacing.sm, height: 24, borderRadius: radius.pill, borderWidth: 1, alignItems: "center", justifyContent: "center" },
  statusBadgeText: { fontFamily: font.bold, fontSize: fontSize.sm, textTransform: "uppercase", letterSpacing: 0.3 },
  textMuted: { color: colors.muted, textDecorationLine: "line-through" },
  walkBtn: { width: 36, height: 36, alignItems: "center", justifyContent: "center" },
  hideWalkedRow: { flexDirection: "row", alignItems: "center", gap: 6, paddingVertical: spacing.xs, marginBottom: spacing.xs },
  hideWalkedText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted },
  planBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, height: 46, borderRadius: radius.md, backgroundColor: "#7C3AED", marginBottom: spacing.sm },
  planBtnText: { fontFamily: font.semibold, fontSize: fontSize.base, color: "#fff" },
  routeBanner: { flexDirection: "row", alignItems: "center", gap: spacing.sm, backgroundColor: "#7C3AED", borderRadius: radius.md, padding: spacing.md, marginBottom: spacing.sm },
  routeTitle: { fontFamily: font.bold, fontSize: fontSize.base, color: "#fff" },
  routeSub: { fontFamily: font.regular, fontSize: fontSize.sm, color: "rgba(255,255,255,0.85)", marginTop: 1 },
  routeGoBtn: { flexDirection: "row", alignItems: "center", gap: 4, backgroundColor: "#fff", paddingHorizontal: spacing.sm, height: 32, borderRadius: radius.pill },
  routeGoText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: "#7C3AED" },
  stopNum: { fontFamily: font.bold, fontSize: fontSize.sm, color: "#fff" },
  soldLoading: { alignItems: "center", justifyContent: "center", paddingVertical: spacing["3xl"], gap: spacing.md },
  soldLoadingText: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.muted },
  errorBox: { alignItems: "center", justifyContent: "center", paddingVertical: spacing["2xl"], gap: spacing.md, backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, padding: spacing.lg },
  errorText: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurfaceSecondary, textAlign: "center", lineHeight: 20 },
  retryBtn: { flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: "#7C3AED", paddingHorizontal: spacing.lg, height: 42, borderRadius: radius.md },
  retryText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: "#fff" },
  skipRow: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, height: 42, marginTop: spacing.xs },
  skipRowText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.muted },
  dot: { width: 34, height: 34, borderRadius: 17, alignItems: "center", justifyContent: "center" },
  cardTitle: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  cardMeta: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 1 },
  label: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, marginBottom: spacing.xs, marginTop: spacing.sm },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  chip: { paddingHorizontal: spacing.md, height: 36, borderRadius: radius.pill, alignItems: "center", justifyContent: "center", backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border },
  chipText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  input: { backgroundColor: colors.surfaceSecondary, borderWidth: 1.5, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: spacing.md, height: 48, fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}) },
  geoTag: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.success, marginTop: spacing.sm },
  soldTag: { fontFamily: font.medium, fontSize: fontSize.sm, color: "#7C3AED", marginTop: spacing.sm },
  soldImg: { width: "100%", height: 150, borderRadius: radius.md, marginBottom: spacing.md, backgroundColor: colors.surfaceTertiary },
  soldAddr: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  soldMetaRow: { flexDirection: "row", alignItems: "baseline", gap: spacing.sm, marginTop: spacing.xs, flexWrap: "wrap" },
  soldPrice: { fontFamily: font.bold, fontSize: fontSize.xl, color: "#16A34A" },
  soldSub: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, marginTop: 2 },
  logSoldBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, marginTop: spacing.sm, height: 46, borderRadius: radius.md, backgroundColor: "#7C3AED" },
  zillowLink: { alignItems: "center", justifyContent: "center", height: 40, marginTop: spacing.xs },
  zillowLinkText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand },
  convertBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, marginTop: spacing.sm, height: 46, borderRadius: radius.md, backgroundColor: "#16A34A" },
  convertText: { fontFamily: font.semibold, fontSize: fontSize.base, color: "#fff" },
  delBtn: { alignItems: "center", justifyContent: "center", height: 44, marginTop: spacing.xs },
  delText: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.error },
});
