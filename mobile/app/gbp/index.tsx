import React, { useCallback, useState } from "react";
import { View, Text, ScrollView, Pressable, TextInput, RefreshControl, Alert, Switch } from 'react-native';
import { Ionicons } from "@expo/vector-icons";
import * as WebBrowser from "expo-web-browser";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, font, fontSize } from '@/src/theme';
import { Header } from "@/src/components/widgets";
import { Card, PrimaryButton, EmptyState, Loading } from '@/src/components/ui';

type Tab = "posts" | "reviews" | "business" | "connect";
const DAYS = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"];
const DAY_LABEL = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export default function Gbp() {
  const [tab, setTab] = useState<Tab>("posts");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const [settings, setSettings] = useState<any>({ configured: false, connected: false, redirect_uri: "", suggested_redirect_uri: "" });
  const [locations, setLocations] = useState<any[]>([]);
  const [selected, setSelected] = useState<any>(null);

  // connect form
  const [cid, setCid] = useState("");
  const [secret, setSecret] = useState("");
  const [redirect, setRedirect] = useState("");
  const [savingCfg, setSavingCfg] = useState(false);

  // posts
  const [summary, setSummary] = useState("");
  const [ctaUrl, setCtaUrl] = useState("");
  const [posting, setPosting] = useState(false);
  const [artSheet, setArtSheet] = useState(false);
  const [articles, setArticles] = useState<any[]>([]);
  const [drafting, setDrafting] = useState(false);
  const [autopost, setAutopost] = useState(true);
  const [calendar, setCalendar] = useState<any[]>([]);

  // reviews
  const [reviews, setReviews] = useState<any[]>([]);
  const [replyFor, setReplyFor] = useState<string | null>(null);
  const [replyText, setReplyText] = useState("");
  const [busy, setBusy] = useState(false);

  // business
  const [phone, setPhone] = useState("");
  const [website, setWebsite] = useState("");
  const [hours, setHours] = useState<Record<string, { closed: boolean; open: string; close: string }>>({});
  const [editHours, setEditHours] = useState(false);

  const loadSettings = useCallback(async () => {
    try {
      const s = await api.get("/gbp/settings");
      setSettings(s);
      setCid(s.client_id || "");
      setRedirect(s.redirect_uri || s.suggested_redirect_uri || "");
      try {
        const [ap, cal] = await Promise.all([api.get("/gbp/autopost"), api.get("/gbp/calendar")]);
        setAutopost(ap.enabled);
        setCalendar(cal || []);
      } catch {}
      if (s.connected) {
        try {
          const l = await api.get("/gbp/locations");
          setLocations(l.locations || []);
          if (l.locations?.length) selectLocation(l.locations[0]);
        } catch {}
      }
    } catch {}
    setLoading(false);
    setRefreshing(false);
  }, []);

  useFocusEffect(useCallback(() => { loadSettings(); }, [loadSettings]));

  const selectLocation = (loc: any) => {
    setSelected(loc);
    setPhone(loc?.phoneNumbers?.primaryPhone || "");
    setWebsite(loc?.websiteUri || "");
    const h: any = {};
    DAYS.forEach((d) => (h[d] = { closed: true, open: "09:00", close: "17:00" }));
    (loc?.regularHours?.periods || []).forEach((p: any) => {
      const t = (x: any) => `${String(x?.hours || 0).padStart(2, "0")}:${String(x?.minutes || 0).padStart(2, "0")}`;
      h[p.openDay] = { closed: false, open: t(p.openTime), close: t(p.closeTime) };
    });
    setHours(h);
  };

  const saveConfig = async () => {
    if (!cid.trim() || !secret.trim() || !redirect.trim())
      return Alert.alert("All fields required", "Enter Client ID, Client Secret and Redirect URI.");
    setSavingCfg(true);
    try {
      await api.put("/gbp/settings", { client_id: cid.trim(), client_secret: secret.trim(), redirect_uri: redirect.trim() });
      setSecret("");
      await loadSettings();
      Alert.alert("Saved", "Now tap “Connect Google Business”.");
    } catch (e: any) {
      Alert.alert("Save failed", e.message);
    } finally {
      setSavingCfg(false);
    }
  };

  const connect = async () => {
    try {
      const { url } = await api.get("/gbp/auth-url");
      await WebBrowser.openBrowserAsync(url);
      // user completes consent in browser; refresh status on return
      setTimeout(loadSettings, 1500);
    } catch (e: any) {
      Alert.alert("Cannot start connection", e.message);
    }
  };

  const disconnect = async () => {
    await api.post("/gbp/disconnect", {});
    setLocations([]);
    setSelected(null);
    await loadSettings();
  };

  const openArtSheet = async () => {
    try {
      setArticles(await api.get("/seo/articles"));
    } catch {}
    setArtSheet(true);
  };

  const draftFromArticle = async (aid: string) => {
    setDrafting(true);
    try {
      const r = await api.post("/gbp/ai/post-from-article", { article_id: aid });
      setSummary(r.summary || "");
      if (r.cta_url) setCtaUrl(r.cta_url);
      setArtSheet(false);
    } catch (e: any) {
      Alert.alert("Draft failed", e.message);
    } finally {
      setDrafting(false);
    }
  };

  const publishPost = async () => {
    if (!selected) return Alert.alert("No location", "Connect your Google Business Profile first.");
    if (!summary.trim()) return Alert.alert("Empty post", "Write or draft a post first.");
    setPosting(true);
    try {
      await api.post("/gbp/posts", { location: selected.name, summary: summary.trim(), cta_url: ctaUrl.trim() || undefined });
      setSummary("");
      setCtaUrl("");
      Alert.alert("Posted ✅", "Your update is live on Google Business Profile.");
    } catch (e: any) {
      Alert.alert("Publish failed", e.message);
    } finally {
      setPosting(false);
    }
  };

  const toggleAutopost = async (v: boolean) => {
    setAutopost(v);
    try {
      await api.put("/gbp/autopost", { enabled: v });
    } catch (e: any) {
      Alert.alert("Failed", e.message);
    }
  };

  const loadIntoComposer = (item: any) => {
    setSummary(item.summary || "");
    setCtaUrl(item.cta_url || "");
  };

  const publishCalendarItem = async (pid: string) => {
    try {
      await api.post(`/gbp/calendar/${pid}/publish`, {});
      await loadSettings();
      Alert.alert("Published ✅", "Posted to Google Business Profile.");
    } catch (e: any) {
      Alert.alert("Publish failed", e.message);
    }
  };

  const deleteCalendarItem = async (pid: string) => {
    try {
      await api.del(`/gbp/calendar/${pid}`);
      setCalendar((c) => c.filter((x) => x.id !== pid));
    } catch (e: any) {
      Alert.alert("Failed", e.message);
    }
  };

  const loadReviews = async () => {
    if (!selected) return;
    try {
      const r = await api.get(`/gbp/reviews?location=${encodeURIComponent(selected.name)}`);
      setReviews(r.reviews || []);
    } catch (e: any) {
      Alert.alert("Could not load reviews", e.message);
    }
  };

  const aiReply = async (rv: any) => {
    setBusy(true);
    try {
      const r = await api.post("/gbp/ai/reply-draft", {
        review_text: rv.comment || "",
        rating: starToNum(rv.starRating),
        reviewer_name: rv.reviewer?.displayName || "",
      });
      setReplyFor(rv.name);
      setReplyText(r.comment || "");
    } catch (e: any) {
      Alert.alert("Draft failed", e.message);
    } finally {
      setBusy(false);
    }
  };

  const sendReply = async (rv: any) => {
    setBusy(true);
    try {
      await api.put("/gbp/reviews/reply", { review_name: rv.name, comment: replyText.trim() });
      setReplyFor(null);
      setReplyText("");
      await loadReviews();
      Alert.alert("Reply sent ✅");
    } catch (e: any) {
      Alert.alert("Reply failed", e.message);
    } finally {
      setBusy(false);
    }
  };

  const saveBusiness = async () => {
    if (!selected) return;
    setBusy(true);
    try {
      const payload: any = { location: selected.name, phone, website };
      if (editHours) {
        const periods = DAYS.filter((d) => !hours[d]?.closed).map((d) => {
          const [oh, om] = hours[d].open.split(":").map(Number);
          const [ch, cm] = hours[d].close.split(":").map(Number);
          return { openDay: d, openTime: { hours: oh, minutes: om || 0 }, closeDay: d, closeTime: { hours: ch, minutes: cm || 0 } };
        });
        payload.regular_hours = { periods };
      }
      await api.patch("/gbp/business", payload);
      Alert.alert("Saved ✅", "Business info updated on Google.");
    } catch (e: any) {
      Alert.alert("Update failed", e.message);
    } finally {
      setBusy(false);
    }
  };

  const tabs: { key: Tab; label: string; icon: any }[] = [
    { key: "posts", label: "Posts", icon: "megaphone-outline" },
    { key: "reviews", label: "Reviews", icon: "star-outline" },
    { key: "business", label: "Info", icon: "business-outline" },
    { key: "connect", label: "Connect", icon: "link-outline" },
  ];

  const NotConnected = () => (
    <EmptyState
      icon="logo-google"
      title="Not connected"
      subtitle="Connect your Google Business Profile in the Connect tab to use this."
      testID="gbp-not-connected"
    />
  );

  if (loading) return <View style={styles.root}><Header title="Google Business" back /><Loading /></View>;

  return (
    <View style={styles.root}>
      <Header title="Google Business" back subtitle="Posts, reviews & business info" />

      <View style={styles.segment}>
        {tabs.map((t) => {
          const active = tab === t.key;
          return (
            <Pressable key={t.key} onPress={() => setTab(t.key)} style={[styles.segBtn, active && styles.segBtnActive]} testID={`gbp-tab-${t.key}`}>
              <Ionicons name={t.icon} size={16} color={active ? "#fff" : colors.onSurfaceSecondary} />
              <Text style={[styles.segText, { color: active ? "#fff" : colors.onSurfaceSecondary }]}>{t.label}</Text>
            </Pressable>
          );
        })}
      </View>

      {settings.connected && locations.length > 1 ? (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.locBar} contentContainerStyle={{ gap: 8, paddingHorizontal: spacing.lg, paddingVertical: 10 }}>
          {locations.map((l) => {
            const a = selected?.name === l.name;
            return (
              <Pressable key={l.name} onPress={() => selectLocation(l)} style={[styles.locChip, a && styles.locChipActive]}>
                <Text style={[styles.locChipText, { color: a ? "#fff" : colors.onSurfaceSecondary }]}>{l.title}</Text>
              </Pressable>
            );
          })}
        </ScrollView>
      ) : null}

      <ScrollView
        contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); loadSettings(); }} />}
        keyboardShouldPersistTaps="handled"
      >
        {tab === "posts" && (
          <>
            <Card style={styles.autoCard}>
              <View style={{ flex: 1 }}>
                <Text style={styles.autoTitle}>Auto content calendar</Text>
                <Text style={styles.autoSub}>Auto-draft a Google post whenever an SEO article publishes.</Text>
              </View>
              <Switch value={autopost} onValueChange={toggleAutopost} testID="gbp-autopost-toggle" />
            </Card>
            <View style={{ height: spacing.md }} />
            <PrimaryButton title="Draft from SEO Article" icon="sparkles" variant="outline" onPress={openArtSheet} testID="gbp-draft-open" />
            <View style={{ height: spacing.md }} />
            <Card>
              <Text style={styles.label}>Post content</Text>
              <TextInput style={[styles.input, styles.textArea]} value={summary} onChangeText={setSummary} multiline placeholder="What's new? Share an update, offer or event…" placeholderTextColor={colors.muted} testID="gbp-summary" />
              <Text style={styles.label}>Call-to-action link (optional)</Text>
              <TextInput style={styles.input} value={ctaUrl} onChangeText={setCtaUrl} autoCapitalize="none" placeholder="https://…" placeholderTextColor={colors.muted} />
              <View style={{ height: spacing.md }} />
              <PrimaryButton title="Publish to Google" icon="cloud-upload-outline" loading={posting} onPress={publishPost} disabled={!settings.connected} testID="gbp-publish" />
              {!settings.connected ? <Text style={styles.hint}>Connect your profile to publish. You can still draft posts with AI.</Text> : null}
            </Card>

            {calendar.length ? (
              <>
                <Text style={styles.calHeading}>Content Calendar ({calendar.length})</Text>
                {calendar.map((it) => (
                  <Card key={it.id} style={{ marginBottom: spacing.md }}>
                    <View style={styles.calHead}>
                      <Text style={styles.calTitle} numberOfLines={1}>{it.article_title || "Post"}</Text>
                      <View style={[styles.calStatus, { backgroundColor: it.status === "published" ? "#DCFCE7" : "#FEF9C3" }]}>
                        <Text style={[styles.calStatusText, { color: it.status === "published" ? colors.success : "#A16207" }]}>{it.status}</Text>
                      </View>
                    </View>
                    <Text style={styles.calSummary} numberOfLines={3}>{it.summary}</Text>
                    <View style={styles.calActions}>
                      {it.status !== "published" ? (
                        <>
                          <Pressable style={styles.calBtn} onPress={() => loadIntoComposer(it)} testID={`gbp-cal-load-${it.id}`}>
                            <Ionicons name="create-outline" size={16} color={colors.brand} />
                            <Text style={styles.calBtnText}>Edit</Text>
                          </Pressable>
                          <Pressable style={styles.calBtn} onPress={() => publishCalendarItem(it.id)} testID={`gbp-cal-publish-${it.id}`}>
                            <Ionicons name="cloud-upload-outline" size={16} color={colors.brand} />
                            <Text style={styles.calBtnText}>Publish</Text>
                          </Pressable>
                        </>
                      ) : null}
                      <Pressable style={styles.calBtn} onPress={() => deleteCalendarItem(it.id)} testID={`gbp-cal-delete-${it.id}`}>
                        <Ionicons name="trash-outline" size={16} color={colors.error} />
                        <Text style={[styles.calBtnText, { color: colors.error }]}>Delete</Text>
                      </Pressable>
                    </View>
                  </Card>
                ))}
              </>
            ) : null}
          </>
        )}

        {tab === "reviews" && (
          !settings.connected ? <NotConnected /> : (
            <>
              <PrimaryButton title="Load Reviews" icon="refresh" variant="outline" onPress={loadReviews} testID="gbp-load-reviews" />
              <View style={{ height: spacing.md }} />
              {reviews.length === 0 ? (
                <EmptyState icon="star-outline" title="No reviews loaded" subtitle="Tap Load Reviews." />
              ) : (
                reviews.map((rv) => (
                  <Card key={rv.name} style={{ marginBottom: spacing.md }}>
                    <View style={styles.rvHead}>
                      <Text style={styles.rvName}>{rv.reviewer?.displayName || "Anonymous"}</Text>
                      <Text style={styles.rvStars}>{"★".repeat(starToNum(rv.starRating))}</Text>
                    </View>
                    <Text style={styles.rvText}>{rv.comment || "(no comment)"}</Text>
                    {rv.reviewReply ? (
                      <View style={styles.rvReply}><Text style={styles.rvReplyText}>↳ {rv.reviewReply.comment}</Text></View>
                    ) : replyFor === rv.name ? (
                      <>
                        <TextInput style={[styles.input, styles.textArea, { marginTop: spacing.sm }]} value={replyText} onChangeText={setReplyText} multiline testID="gbp-reply-input" />
                        <View style={{ flexDirection: "row", gap: spacing.sm, marginTop: spacing.sm }}>
                          <View style={{ flex: 1 }}><PrimaryButton title="Send" loading={busy} onPress={() => sendReply(rv)} /></View>
                          <View style={{ flex: 1 }}><PrimaryButton title="Cancel" variant="outline" onPress={() => setReplyFor(null)} /></View>
                        </View>
                      </>
                    ) : (
                      <Pressable style={styles.aiReplyBtn} onPress={() => aiReply(rv)} testID="gbp-ai-reply">
                        <Ionicons name="sparkles" size={14} color={colors.brand} />
                        <Text style={styles.aiReplyText}>AI draft reply</Text>
                      </Pressable>
                    )}
                  </Card>
                ))
              )}
            </>
          )
        )}

        {tab === "business" && (
          !settings.connected ? <NotConnected /> : (
            <Card>
              <Text style={styles.bizTitle}>{selected?.title || "Business"}</Text>
              <Text style={styles.label}>Primary phone</Text>
              <TextInput style={styles.input} value={phone} onChangeText={setPhone} keyboardType="phone-pad" placeholderTextColor={colors.muted} testID="gbp-phone" />
              <Text style={styles.label}>Website</Text>
              <TextInput style={styles.input} value={website} onChangeText={setWebsite} autoCapitalize="none" keyboardType="url" placeholderTextColor={colors.muted} testID="gbp-website" />

              <View style={styles.rowBetween}>
                <Text style={styles.label}>Edit business hours</Text>
                <Switch value={editHours} onValueChange={setEditHours} />
              </View>
              {editHours ? DAYS.map((d, i) => {
                const h = hours[d] || { closed: true, open: "09:00", close: "17:00" };
                return (
                  <View key={d} style={styles.hourRow}>
                    <Text style={styles.hourDay}>{DAY_LABEL[i]}</Text>
                    <Switch value={!h.closed} onValueChange={(v) => setHours({ ...hours, [d]: { ...h, closed: !v } })} />
                    {!h.closed ? (
                      <>
                        <TextInput style={styles.timeInput} value={h.open} onChangeText={(v) => setHours({ ...hours, [d]: { ...h, open: v } })} placeholder="09:00" placeholderTextColor={colors.muted} />
                        <Text style={styles.hourDash}>–</Text>
                        <TextInput style={styles.timeInput} value={h.close} onChangeText={(v) => setHours({ ...hours, [d]: { ...h, close: v } })} placeholder="17:00" placeholderTextColor={colors.muted} />
                      </>
                    ) : (
                      <Text style={styles.closedText}>Closed</Text>
                    )}
                  </View>
                );
              }) : null}

              <View style={{ height: spacing.md }} />
              <PrimaryButton title="Save to Google" icon="save-outline" loading={busy} onPress={saveBusiness} testID="gbp-save-business" />
            </Card>
          )
        )}

        {tab === "connect" && (
          <>
            <Card style={{ marginBottom: spacing.md }}>
              <View style={styles.rowBetween}>
                <Text style={styles.statusLabel}>Status</Text>
                <View style={[styles.statusPill, { backgroundColor: settings.connected ? "#DCFCE7" : "#FEF9C3" }]}>
                  <Text style={[styles.statusPillText, { color: settings.connected ? colors.success : "#A16207" }]}>
                    {settings.connected ? "Connected" : settings.configured ? "Configured" : "Not set up"}
                  </Text>
                </View>
              </View>
              <Text style={styles.hint}>
                Requires a Google Cloud OAuth client and approved Google Business Profile API access. Add your Client ID, Secret and the Redirect URI below (register the same Redirect URI in Google Cloud).
              </Text>
            </Card>
            <Card>
              <Text style={styles.label}>OAuth Client ID</Text>
              <TextInput style={styles.input} value={cid} onChangeText={setCid} autoCapitalize="none" placeholder="…apps.googleusercontent.com" placeholderTextColor={colors.muted} testID="gbp-cid" />
              <Text style={styles.label}>OAuth Client Secret</Text>
              <TextInput style={styles.input} value={secret} onChangeText={setSecret} autoCapitalize="none" secureTextEntry placeholder={settings.configured ? "•••• (unchanged)" : "GOCSPX-…"} placeholderTextColor={colors.muted} testID="gbp-secret" />
              <Text style={styles.label}>Redirect URI</Text>
              <TextInput style={styles.input} value={redirect} onChangeText={setRedirect} autoCapitalize="none" placeholderTextColor={colors.muted} testID="gbp-redirect" />
              <Text style={styles.hint}>Register this exact URI in Google Cloud → Credentials → Authorized redirect URIs.</Text>
              <View style={{ height: spacing.sm }} />
              <PrimaryButton title="Save Credentials" icon="save-outline" loading={savingCfg} onPress={saveConfig} testID="gbp-save-cfg" />
              <View style={{ height: spacing.sm }} />
              <PrimaryButton title="Connect Google Business" icon="logo-google" onPress={connect} disabled={!settings.configured} testID="gbp-connect" />
              {settings.connected ? (
                <>
                  <View style={{ height: spacing.sm }} />
                  <PrimaryButton title="Disconnect" variant="outline" onPress={disconnect} testID="gbp-disconnect" />
                </>
              ) : null}
            </Card>
          </>
        )}
      </ScrollView>

      <Sheet visible={artSheet} onClose={() => setArtSheet(false)} title="Draft post from article" testID="gbp-art-sheet">
        {articles.length === 0 ? (
          <Text style={styles.hint}>No SEO articles yet. Generate one in the SEO Studio first.</Text>
        ) : (
          articles.map((a) => (
            <Pressable key={a.id} style={styles.artRow} onPress={() => draftFromArticle(a.id)} disabled={drafting} testID={`gbp-art-${a.id}`}>
              <Ionicons name="document-text-outline" size={18} color={colors.brand} />
              <Text style={styles.artTitle} numberOfLines={1}>{a.title}</Text>
              {drafting ? <Ionicons name="hourglass-outline" size={16} color={colors.muted} /> : <Ionicons name="chevron-forward" size={16} color={colors.muted} />}
            </Pressable>
          ))
        )}
      </Sheet>
    </View>
  );
}

function starToNum(s?: string): number {
  const map: Record<string, number> = { ONE: 1, TWO: 2, THREE: 3, FOUR: 4, FIVE: 5 };
  return map[s || "FIVE"] || 5;
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  segment: { flexDirection: "row", gap: spacing.sm, paddingHorizontal: spacing.lg, paddingVertical: spacing.md, backgroundColor: colors.surface, borderBottomWidth: 1, borderBottomColor: colors.border },
  segBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 4, height: 38, borderRadius: radius.pill, backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border },
  segBtnActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  segText: { fontFamily: font.semibold, fontSize: fontSize.sm },
  locBar: { flexGrow: 0, backgroundColor: colors.surface, borderBottomWidth: 1, borderBottomColor: colors.border },
  locChip: { paddingHorizontal: spacing.md, paddingVertical: 7, borderRadius: radius.pill, backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border },
  locChipActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  locChipText: { fontFamily: font.semibold, fontSize: fontSize.sm },
  label: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, marginTop: spacing.sm, marginBottom: 4 },
  input: { borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: spacing.md, paddingVertical: 12, fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, backgroundColor: colors.surface },
  textArea: { minHeight: 110, textAlignVertical: "top" },
  hint: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 6, lineHeight: 18 },
  rowBetween: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: spacing.sm },
  statusLabel: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  statusPill: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: radius.pill },
  statusPillText: { fontFamily: font.semibold, fontSize: fontSize.sm },
  rvHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  rvName: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  rvStars: { fontFamily: font.bold, fontSize: fontSize.base, color: "#F59E0B" },
  rvText: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurfaceSecondary, marginTop: 4, lineHeight: 20 },
  rvReply: { marginTop: spacing.sm, backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.sm },
  rvReplyText: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  aiReplyBtn: { flexDirection: "row", alignItems: "center", gap: 5, marginTop: spacing.sm, alignSelf: "flex-start", backgroundColor: colors.brandTertiary, paddingHorizontal: spacing.md, paddingVertical: 8, borderRadius: radius.pill },
  aiReplyText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand },
  bizTitle: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface },
  hourRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, marginTop: spacing.sm },
  hourDay: { width: 36, fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface },
  timeInput: { width: 64, borderWidth: 1, borderColor: colors.border, borderRadius: radius.sm, paddingVertical: 6, textAlign: "center", fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurface, backgroundColor: colors.surface },
  hourDash: { fontFamily: font.regular, color: colors.muted },
  closedText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted },
  artRow: { flexDirection: "row", alignItems: "center", gap: spacing.md, paddingVertical: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.divider },
  artTitle: { flex: 1, fontFamily: font.medium, fontSize: fontSize.base, color: colors.onSurface },
  autoCard: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  autoTitle: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  autoSub: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  calHeading: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface, marginTop: spacing.xl, marginBottom: spacing.sm },
  calHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.sm },
  calTitle: { flex: 1, fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  calStatus: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: radius.pill },
  calStatusText: { fontFamily: font.semibold, fontSize: fontSize.sm, textTransform: "capitalize" },
  calSummary: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, marginTop: spacing.sm, lineHeight: 19 },
  calActions: { flexDirection: "row", gap: spacing.lg, marginTop: spacing.md },
  calBtn: { flexDirection: "row", alignItems: "center", gap: 4 },
  calBtnText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand },
});
