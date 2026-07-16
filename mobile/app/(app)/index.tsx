import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, RefreshControl, Pressable, TextInput, Platform, Alert } from "react-native";
import { Image } from "expo-image";
import { LinearGradient } from "expo-linear-gradient";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter, Redirect } from "expo-router";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize, money, IMAGES } from "@/src/theme";
import { Loading, StatusChip, Sheet, PrimaryButton } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";
import BudgetHealthCard from "@/src/components/BudgetHealthCard";

export default function Dashboard() {
  const { user } = useAuth();
  const router = useRouter();
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const d = await api.get("/dashboard");
      setData(d);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load])
  );

  // Technicians don't have a Dashboard tab — send them to their Today's Schedule.
  if (user?.role === "technician") return <Redirect href="/(app)/today" />;
  if (user?.role === "customer") return <Redirect href="/(app)/schedule" />;

  if (loading) {
    return (
      <View style={styles.root}>
        <Header title="Dashboard" subtitle={`Hi, ${user?.name?.split(" ")[0] || ""}`} />
        <Loading testID="dashboard-loading" />
      </View>
    );
  }

  return (
    <View style={styles.root}>
      <Header title="Dashboard" subtitle={`Hi, ${user?.name?.split(" ")[0] || ""}`} />
      <ScrollView
        testID="dashboard-scroll"
        contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
      >
        <BudgetHealthCard />
        <View style={styles.hero}>
          <Image source={{ uri: IMAGES.dashboardHero }} style={StyleSheet.absoluteFill} contentFit="cover" />
          <LinearGradient colors={["rgba(0,60,95,0.55)", "rgba(26,43,60,0.92)"]} style={StyleSheet.absoluteFill} />
          <View style={styles.heroInner}>
            <Text style={styles.heroLabel}>Total Revenue</Text>
            <Text style={styles.heroValue} testID="dashboard-revenue">
              {money(data.revenue)}
            </Text>
            <View style={styles.heroRow}>
              <View style={styles.heroPill}>
                <Ionicons name="flash" size={14} color="#fff" />
                <Text style={styles.heroPillText}>{data.active_jobs} active jobs</Text>
              </View>
              <View style={styles.heroPill}>
                <Ionicons name="time-outline" size={14} color="#fff" />
                <Text style={styles.heroPillText}>{money(data.outstanding)} due</Text>
              </View>
            </View>
          </View>
        </View>

        {data.requested_jobs > 0 ? (
          <Pressable style={styles.requestBanner} onPress={() => router.push("/(app)/jobs")} testID="new-requests-banner">
            <View style={styles.requestIcon}>
              <Ionicons name="notifications" size={18} color="#C2410C" />
            </View>
            <Text style={styles.requestText}>
              {data.requested_jobs} new service request{data.requested_jobs > 1 ? "s" : ""} awaiting review
            </Text>
            <Ionicons name="chevron-forward" size={18} color="#C2410C" />
          </Pressable>
        ) : null}

        <View style={styles.grid}>
          <Kpi icon="briefcase" label="Active Jobs" value={data.active_jobs} onPress={() => router.push("/(app)/jobs")} />
          <Kpi icon="hourglass-outline" label="Pending" value={data.pending_jobs} onPress={() => router.push("/(app)/jobs")} />
          <Kpi icon="people" label="Customers" value={data.total_customers} onPress={() => router.push("/(app)/customers")} />
          <Kpi icon="construct" label="Technicians" value={data.total_technicians} onPress={() => router.push("/technicians")} />
        </View>

        <ReferralRevenueTile />

        <RevenueChart series={data.revenue_series || []} outstanding={data.outstanding} />

        <PaymentsWidget onOpen={() => router.push("/payments")} onOpenInvoice={(id: string) => router.push(`/quote/${id}`)} />

        <MaintenanceDigest onOpen={() => router.push("/maintenance")} />

        <ReadyToSchedule onOpenQuote={(id: string) => router.push(`/quote/${id}`)} />

        {data.revenue_by_service?.length ? (
          <View style={styles.chartCard} testID="revenue-by-service">
            <Text style={styles.chartTitle}>Revenue by Service</Text>
            {data.revenue_by_service.map((s: any) => {
              const max = Math.max(...data.revenue_by_service.map((x: any) => x.value), 1);
              return (
                <View key={s.label} style={styles.svcRow}>
                  <Text style={styles.svcLabel} numberOfLines={1}>{s.label}</Text>
                  <View style={styles.svcBarTrack}>
                    <View style={[styles.svcBar, { width: `${Math.max(4, (s.value / max) * 100)}%` }]} />
                  </View>
                  <Text style={styles.svcValue}>{money(s.value)}</Text>
                </View>
              );
            })}
            {data.recurring_vs_project ? (
              <View style={styles.splitRow}>
                <View style={styles.splitItem}>
                  <View style={[styles.dot, { backgroundColor: colors.brand }]} />
                  <Text style={styles.splitText}>Recurring {money(data.recurring_vs_project.recurring)}</Text>
                </View>
                <View style={styles.splitItem}>
                  <View style={[styles.dot, { backgroundColor: colors.brandSecondary }]} />
                  <Text style={styles.splitText}>Project {money(data.recurring_vs_project.project)}</Text>
                </View>
              </View>
            ) : null}
          </View>
        ) : null}

        <View style={styles.sectionRow}>
          <Text style={styles.sectionTitle}>Recent Jobs</Text>
          <Pressable onPress={() => router.push("/(app)/jobs")} testID="see-all-jobs">
            <Text style={styles.link}>See all</Text>
          </Pressable>
        </View>

        {data.recent_jobs?.map((j: any) => (
          <Pressable
            key={j.id}
            style={styles.activityRow}
            onPress={() => router.push(`/job/${j.id}`)}
            testID={`recent-job-${j.id}`}
          >
            <View style={styles.activityIcon}>
              <Ionicons name="water-outline" size={18} color={colors.brand} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.activityTitle} numberOfLines={1}>
                {j.title}
              </Text>
              <Text style={styles.activitySub}>{j.customer_name}</Text>
            </View>
            <StatusChip status={j.status} />
          </Pressable>
        ))}
      </ScrollView>
    </View>
  );
}

function MaintenanceDigest({ onOpen }: { onOpen: () => void }) {
  const [d, setD] = useState<any>(null);
  const [sheet, setSheet] = useState(false);
  const [techs, setTechs] = useState<any[]>([]);
  const [date, setDate] = useState("");
  const [tech, setTech] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const preset = (days: number) => {
    const x = new Date();
    x.setDate(x.getDate() + days);
    return x.toISOString().slice(0, 10);
  };

  const load = useCallback(async () => {
    try {
      setD(await api.get("/maintenance/digest"));
    } catch {
      setD(null);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const openSheet = async () => {
    setDate(preset(1));
    setTech(null);
    setSheet(true);
    if (!techs.length) {
      try { setTechs(await api.get("/technicians")); } catch {}
    }
  };

  const bulkSchedule = async () => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) {
      Alert.alert("Pick a date", "Enter the service date as YYYY-MM-DD.");
      return;
    }
    setBusy(true);
    try {
      const res = await api.post("/maintenance/bulk-schedule", { scheduled_date: date, technician_id: tech });
      setSheet(false);
      await load();
      Alert.alert("Scheduled ✅", `${res.created} pool${res.created === 1 ? "" : "s"} booked for ${date}.`);
    } catch (e: any) {
      Alert.alert("Failed", e.message || "Please try again.");
    } finally {
      setBusy(false);
    }
  };

  if (!d) return null;
  const dueLabel = (it: any) =>
    it.overdue ? `${Math.abs(it.days)}d overdue` : it.days === 0 ? "due today" : `due in ${it.days}d`;
  const total = d.overdue + d.due_this_week;

  return (
    <View style={styles.chartCard} testID="maintenance-digest">
      <View style={styles.chartHeader}>
        <View>
          <Text style={styles.chartTitle}>Maintenance This Week</Text>
          <Text style={styles.chartSub}>Filter & salt cell cleanings</Text>
        </View>
        <Pressable onPress={onOpen} testID="maintenance-digest-viewall">
          <Text style={styles.link}>View all</Text>
        </Pressable>
      </View>

      <View style={styles.payStatsRow}>
        <View style={[styles.payStat, { backgroundColor: "#FEE2E2" }]}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 5 }}>
            <Ionicons name="alert-circle" size={14} color="#DC2626" />
            <Text style={[styles.payStatLabel, { color: "#DC2626" }]}>Overdue</Text>
          </View>
          <Text style={styles.payStatValue} testID="digest-overdue">{d.overdue}</Text>
        </View>
        <View style={[styles.payStat, { backgroundColor: "#FEF9C3" }]}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 5 }}>
            <Ionicons name="time-outline" size={14} color="#A16207" />
            <Text style={[styles.payStatLabel, { color: "#A16207" }]}>Due this week</Text>
          </View>
          <Text style={styles.payStatValue} testID="digest-due">{d.due_this_week}</Text>
        </View>
      </View>

      {d.items.length ? (
        <>
          <Text style={styles.overdueHeading}>Needs scheduling</Text>
          {d.items.map((it: any) => (
            <Pressable key={`${it.customer_id}_${it.type}`} style={styles.overdueRow} onPress={onOpen} testID={`digest-item-${it.customer_id}-${it.type}`}>
              <View style={styles.activityIcon}>
                <Ionicons name={it.type === "filter" ? "filter" : "flash"} size={16} color={colors.brand} />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.overdueName} numberOfLines={1}>{it.customer_name}</Text>
                <Text style={styles.overdueMeta} numberOfLines={1}>{it.label}</Text>
              </View>
              <View style={[styles.digestBadge, { backgroundColor: it.overdue ? "#FEE2E2" : "#FEF9C3" }]}>
                <Text style={[styles.digestBadgeText, { color: it.overdue ? "#DC2626" : "#A16207" }]}>{dueLabel(it)}</Text>
              </View>
            </Pressable>
          ))}
          <Pressable style={styles.bulkBtn} onPress={openSheet} testID="digest-bulk-schedule">
            <Ionicons name="calendar" size={16} color="#fff" />
            <Text style={styles.bulkBtnText}>Schedule all {total} in one tap</Text>
          </Pressable>
        </>
      ) : (
        <View style={styles.allClear}>
          <Ionicons name="checkmark-circle" size={16} color={colors.success} />
          <Text style={styles.allClearText}>All pools on schedule 🎉</Text>
        </View>
      )}

      <Sheet visible={sheet} onClose={() => setSheet(false)} title={`Schedule ${total} pool${total === 1 ? "" : "s"}`} testID="digest-bulk-sheet">
        <Text style={styles.bulkHint}>Books every overdue & due-this-week cleaning onto one day and technician.</Text>
        <Text style={styles.bulkLabel}>Service date</Text>
        <View style={styles.bulkPresetRow}>
          {[["Tomorrow", 1], ["+3 days", 3], ["+1 week", 7]].map(([lbl, dd]) => (
            <Pressable key={lbl as string} style={[styles.bulkPreset, date === preset(dd as number) && styles.bulkPresetOn]} onPress={() => setDate(preset(dd as number))} testID={`digest-preset-${dd}`}>
              <Text style={[styles.bulkPresetText, date === preset(dd as number) && styles.bulkPresetTextOn]}>{lbl}</Text>
            </Pressable>
          ))}
        </View>
        <TextInput style={styles.bulkInput} value={date} onChangeText={setDate} placeholder="YYYY-MM-DD" placeholderTextColor={colors.muted} testID="digest-date-input" />
        <Text style={styles.bulkLabel}>Assign technician</Text>
        <View style={styles.bulkPresetRow}>
          <Pressable style={[styles.bulkPreset, !tech && styles.bulkPresetOn]} onPress={() => setTech(null)} testID="digest-tech-none">
            <Text style={[styles.bulkPresetText, !tech && styles.bulkPresetTextOn]}>Unassigned</Text>
          </Pressable>
          {techs.map((t) => (
            <Pressable key={t.id} style={[styles.bulkPreset, tech === t.id && styles.bulkPresetOn]} onPress={() => setTech(t.id)} testID={`digest-tech-${t.id}`}>
              <Text style={[styles.bulkPresetText, tech === t.id && styles.bulkPresetTextOn]}>{t.name}</Text>
            </Pressable>
          ))}
        </View>
        <View style={{ height: spacing.md }} />
        <PrimaryButton title={`Schedule ${total} Pool${total === 1 ? "" : "s"}`} icon="calendar" loading={busy} onPress={bulkSchedule} testID="digest-bulk-confirm" />
      </Sheet>
    </View>
  );
}

function ReadyToSchedule({ onOpenQuote }: { onOpenQuote: (id: string) => void }) {
  const [items, setItems] = useState<any[] | null>(null);
  const [techs, setTechs] = useState<any[]>([]);
  const [active, setActive] = useState<any>(null); // estimate being scheduled
  const [date, setDate] = useState("");
  const [tech, setTech] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const preset = (days: number) => {
    const x = new Date();
    x.setDate(x.getDate() + days);
    return x.toISOString().slice(0, 10);
  };

  const load = useCallback(async () => {
    try {
      setItems(await api.get("/quotes/ready-to-schedule"));
    } catch {
      setItems([]);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const openSheet = async (est: any) => {
    setActive(est);
    setDate(preset(1));
    setTech(null);
    if (!techs.length) {
      try { setTechs(await api.get("/technicians")); } catch {}
    }
  };

  const schedule = async () => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) {
      Alert.alert("Pick a date", "Enter the service date as YYYY-MM-DD.");
      return;
    }
    setBusy(true);
    try {
      await api.post(`/quotes/${active.id}/schedule`, { scheduled_date: date, technician_id: tech });
      setActive(null);
      await load();
      Alert.alert("Scheduled ✅", `Job created for ${date}.`);
    } catch (e: any) {
      Alert.alert("Failed", e.message || "Please try again.");
    } finally {
      setBusy(false);
    }
  };

  if (!items || items.length === 0) return null;

  return (
    <View style={styles.chartCard} testID="ready-to-schedule">
      <View style={styles.chartHeader}>
        <View>
          <Text style={styles.chartTitle}>Approved Estimates</Text>
          <Text style={styles.chartSub}>Ready to schedule</Text>
        </View>
        <View style={styles.digestBadge}>
          <Text style={[styles.digestBadgeText, { color: colors.brand }]}>{items.length}</Text>
        </View>
      </View>

      {items.map((it) => (
        <View key={it.id} style={styles.overdueRow} testID={`rts-${it.id}`}>
          <Pressable style={{ flex: 1 }} onPress={() => onOpenQuote(it.id)}>
            <Text style={styles.overdueName} numberOfLines={1}>{it.customer_name}</Text>
            <Text style={styles.overdueMeta} numberOfLines={1}>{it.title} · {money(it.total)}</Text>
          </Pressable>
          <Pressable style={styles.rtsBtn} onPress={() => openSheet(it)} testID={`rts-schedule-${it.id}`}>
            <Ionicons name="calendar" size={13} color="#fff" />
            <Text style={styles.rtsBtnText}>Schedule</Text>
          </Pressable>
        </View>
      ))}

      <Sheet visible={!!active} onClose={() => setActive(null)} title="Schedule Service" testID="rts-sheet">
        {active ? (
          <>
            <Text style={styles.bulkHint}>{active.customer_name} · {active.title} · {money(active.total)}</Text>
            <Text style={styles.bulkLabel}>Service date</Text>
            <View style={styles.bulkPresetRow}>
              {[["Tomorrow", 1], ["+3 days", 3], ["+1 week", 7]].map(([lbl, dd]) => (
                <Pressable key={lbl as string} style={[styles.bulkPreset, date === preset(dd as number) && styles.bulkPresetOn]} onPress={() => setDate(preset(dd as number))} testID={`rts-preset-${dd}`}>
                  <Text style={[styles.bulkPresetText, date === preset(dd as number) && styles.bulkPresetTextOn]}>{lbl}</Text>
                </Pressable>
              ))}
            </View>
            <TextInput style={styles.bulkInput} value={date} onChangeText={setDate} placeholder="YYYY-MM-DD" placeholderTextColor={colors.muted} testID="rts-date-input" />
            <Text style={styles.bulkLabel}>Assign technician</Text>
            <View style={styles.bulkPresetRow}>
              <Pressable style={[styles.bulkPreset, !tech && styles.bulkPresetOn]} onPress={() => setTech(null)} testID="rts-tech-none">
                <Text style={[styles.bulkPresetText, !tech && styles.bulkPresetTextOn]}>Unassigned</Text>
              </Pressable>
              {techs.map((t) => (
                <Pressable key={t.id} style={[styles.bulkPreset, tech === t.id && styles.bulkPresetOn]} onPress={() => setTech(t.id)} testID={`rts-tech-${t.id}`}>
                  <Text style={[styles.bulkPresetText, tech === t.id && styles.bulkPresetTextOn]}>{t.name}</Text>
                </Pressable>
              ))}
            </View>
            <View style={{ height: spacing.md }} />
            <PrimaryButton title="Create Job" icon="calendar" loading={busy} onPress={schedule} testID="rts-confirm" />
          </>
        ) : null}
      </Sheet>
    </View>
  );
}

function PaymentsWidget({ onOpen, onOpenInvoice }: { onOpen: () => void; onOpenInvoice: (id: string) => void }) {
  const [summary, setSummary] = useState<any>(null);
  const [reminding, setReminding] = useState<string | null>(null);
  const [reminded, setReminded] = useState<Record<string, boolean>>({});

  const load = useCallback(async () => {
    try {
      setSummary(await api.get("/payments/summary"));
    } catch {
      setSummary(null);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const remind = async (id: string) => {
    setReminding(id);
    try {
      await api.post(`/quotes/${id}/remind`);
      setReminded((r) => ({ ...r, [id]: true }));
    } catch {}
    finally { setReminding(null); }
  };

  if (!summary) return null;
  const overdue = (summary.overdue || []).slice(0, 4);

  return (
    <View style={styles.chartCard} testID="payments-widget">
      <View style={styles.chartHeader}>
        <View>
          <Text style={styles.chartTitle}>Payments</Text>
          <Text style={styles.chartSub}>{summary.month_label}</Text>
        </View>
        <Pressable onPress={onOpen} testID="payments-widget-viewall">
          <Text style={styles.link}>View all</Text>
        </Pressable>
      </View>

      <View style={styles.payStatsRow}>
        <View style={[styles.payStat, { backgroundColor: colors.success + "12" }]}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 5 }}>
            <Ionicons name="trending-up" size={14} color={colors.success} />
            <Text style={[styles.payStatLabel, { color: colors.success }]}>Collected</Text>
          </View>
          <Text style={styles.payStatValue} numberOfLines={1} adjustsFontSizeToFit testID="widget-collected">{money(summary.collected_this_month)}</Text>
        </View>
        <View style={[styles.payStat, { backgroundColor: "#FEF9C3" }]}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 5 }}>
            <Ionicons name="time-outline" size={14} color="#A16207" />
            <Text style={[styles.payStatLabel, { color: "#A16207" }]}>Outstanding</Text>
          </View>
          <Text style={styles.payStatValue} numberOfLines={1} adjustsFontSizeToFit testID="widget-outstanding">{money(summary.outstanding_total)}</Text>
          <Text style={styles.payStatMeta}>{summary.outstanding_count} invoice{summary.outstanding_count === 1 ? "" : "s"}</Text>
        </View>
      </View>

      {overdue.length ? (
        <>
          <Text style={styles.overdueHeading}>Awaiting payment</Text>
          {overdue.map((o: any) => {
            const done = reminded[o.id] || o.reminded_at;
            return (
              <View key={o.id} style={styles.overdueRow} testID={`overdue-${o.id}`}>
                <Pressable style={{ flex: 1 }} onPress={() => onOpenInvoice(o.id)}>
                  <Text style={styles.overdueName} numberOfLines={1}>{o.customer_name}</Text>
                  <Text style={styles.overdueMeta} numberOfLines={1}>
                    {money(o.total)} · {o.days === 0 ? "today" : `${o.days}d`}
                  </Text>
                </Pressable>
                <Pressable
                  style={[styles.remindBtn, done && styles.remindBtnDone]}
                  onPress={() => !done && remind(o.id)}
                  disabled={!!done || reminding === o.id}
                  testID={`remind-${o.id}`}
                >
                  <Ionicons name={done ? "checkmark" : "notifications-outline"} size={13} color={done ? colors.success : "#fff"} />
                  <Text style={[styles.remindText, done && { color: colors.success }]}>
                    {done ? "Sent" : reminding === o.id ? "…" : "Remind"}
                  </Text>
                </Pressable>
              </View>
            );
          })}
        </>
      ) : (
        <View style={styles.allClear}>
          <Ionicons name="checkmark-circle" size={16} color={colors.success} />
          <Text style={styles.allClearText}>No outstanding invoices 🎉</Text>
        </View>
      )}
    </View>
  );
}

function RevenueChart({ series, outstanding }: { series: { label: string; value: number }[]; outstanding: number }) {
  const max = Math.max(...series.map((s) => s.value), 1);
  return (
    <View style={styles.chartCard} testID="revenue-chart">
      <View style={styles.chartHeader}>
        <View>
          <Text style={styles.chartTitle}>Revenue Trend</Text>
          <Text style={styles.chartSub}>Last 6 months</Text>
        </View>
        <View style={styles.outstandingPill}>
          <Ionicons name="alert-circle-outline" size={14} color={colors.warning} />
          <Text style={styles.outstandingText}>{money(outstanding)} due</Text>
        </View>
      </View>
      <View style={styles.barsRow}>
        {series.map((s, i) => {
          const isLast = i === series.length - 1;
          const h = Math.max(6, (s.value / max) * 120);
          return (
            <View key={s.label} style={styles.barCol} testID={`revenue-bar-${s.label}`}>
              <Text style={styles.barValue}>{s.value >= 1000 ? `${(s.value / 1000).toFixed(1)}k` : Math.round(s.value)}</Text>
              <View style={styles.barTrack}>
                <View style={[styles.bar, { height: h, backgroundColor: isLast ? colors.brand : colors.brandTertiary }]} />
              </View>
              <Text style={[styles.barLabel, isLast && { color: colors.brand, fontFamily: font.bold }]}>{s.label}</Text>
            </View>
          );
        })}
      </View>
    </View>
  );
}

function Kpi({ icon, label, value, onPress }: { icon: any; label: string; value: number; onPress: () => void }) {  return (
    <Pressable style={styles.kpi} onPress={onPress} testID={`kpi-${label.toLowerCase().replace(/\s/g, "-")}`}>
      <View style={styles.kpiIcon}>
        <Ionicons name={icon} size={20} color={colors.brand} />
      </View>
      <Text style={styles.kpiValue}>{value}</Text>
      <Text style={styles.kpiLabel}>{label}</Text>
    </Pressable>
  );
}

/** Phase 20B module B — Referral Revenue tile (mobile). */
function ReferralRevenueTile() {
  const router = useRouter();
  const [data, setData] = React.useState<any>(null);
  React.useEffect(() => {
    api.get("/referrals/admin/analytics/v2").then(setData).catch(() => setData(null));
  }, []);
  if (!data) return null;
  const rev = data?.revenue_attribution?.total_usd || 0;
  const converted = data?.funnel?.converted || 0;
  return (
    <Pressable onPress={() => router.push("/admin/referrals" as any)}
               style={styles.refTile} testID="tile-referral-revenue">
      <View style={styles.refIcon}>
        <Ionicons name="trending-up" size={22} color="#fff" />
      </View>
      <View style={{ flex: 1 }}>
        <Text style={styles.refLabel}>Referral Revenue</Text>
        <Text style={styles.refValue}>${rev.toLocaleString()}</Text>
        <Text style={styles.refSub}>
          {converted} converted · tap to open analytics
        </Text>
      </View>
      <Ionicons name="chevron-forward" size={20} color="#fff" />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  refTile: { flexDirection: "row", alignItems: "center", gap: spacing.md,
             backgroundColor: colors.brand, padding: spacing.lg,
             borderRadius: radius.lg, marginBottom: spacing.lg },
  refIcon: { width: 44, height: 44, borderRadius: 22,
             backgroundColor: "rgba(255,255,255,0.22)",
             alignItems: "center", justifyContent: "center" },
  refLabel: { fontFamily: font.bold, fontSize: 10,
              color: "rgba(255,255,255,0.85)",
              letterSpacing: 0.8, textTransform: "uppercase" },
  refValue: { fontFamily: font.bold, fontSize: 26, color: "#fff",
              marginTop: 2 },
  refSub: { fontFamily: font.regular, fontSize: 12,
            color: "rgba(255,255,255,0.85)", marginTop: 2 },
  hero: { height: 160, borderRadius: radius.lg, overflow: "hidden", marginBottom: spacing.lg },
  heroInner: { flex: 1, padding: spacing.lg, justifyContent: "flex-end" },
  heroLabel: { fontFamily: font.medium, fontSize: fontSize.base, color: "rgba(255,255,255,0.85)" },
  heroValue: { fontFamily: font.bold, fontSize: 34, color: "#fff", marginTop: 2 },
  heroRow: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.md },
  heroPill: {
    flexDirection: "row",
    alignItems: "center",
    gap: 5,
    backgroundColor: "rgba(255,255,255,0.18)",
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: radius.pill,
  },
  heroPillText: { fontFamily: font.medium, fontSize: fontSize.sm, color: "#fff" },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.md },
  kpi: {
    width: "47.5%",
    flexGrow: 1,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.lg,
    borderWidth: 1,
    borderColor: colors.border,
  },
  kpiIcon: {
    width: 40,
    height: 40,
    borderRadius: radius.md,
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: spacing.sm,
  },
  kpiValue: { fontFamily: font.bold, fontSize: fontSize["2xl"], color: colors.onSurface },
  kpiLabel: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  chartCard: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.lg,
    borderWidth: 1,
    borderColor: colors.border,
    marginTop: spacing.lg,
  },
  chartHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start", marginBottom: spacing.lg },
  chartTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  chartSub: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 1 },
  svcRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, marginTop: spacing.sm },
  svcLabel: { width: 96, fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  svcBarTrack: { flex: 1, height: 10, borderRadius: 5, backgroundColor: colors.surfaceTertiary, overflow: "hidden" },
  svcBar: { height: 10, borderRadius: 5, backgroundColor: colors.brand },
  svcValue: { width: 74, textAlign: "right", fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface },
  splitRow: { flexDirection: "row", gap: spacing.lg, marginTop: spacing.lg, borderTopWidth: 1, borderTopColor: colors.divider, paddingTop: spacing.md },
  splitItem: { flexDirection: "row", alignItems: "center", gap: 6 },
  dot: { width: 10, height: 10, borderRadius: 5 },
  splitText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  outstandingPill: { flexDirection: "row", alignItems: "center", gap: 4, backgroundColor: "#FEF9C3", paddingHorizontal: 10, paddingVertical: 5, borderRadius: radius.pill },
  outstandingText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: "#A16207" },
  payStatsRow: { flexDirection: "row", gap: spacing.md },
  payStat: { flex: 1, borderRadius: radius.md, padding: spacing.md },
  payStatLabel: { fontFamily: font.semibold, fontSize: fontSize.sm },
  payStatValue: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface, marginTop: 4 },
  payStatMeta: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 1 },
  overdueHeading: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.muted, textTransform: "uppercase", letterSpacing: 0.5, marginTop: spacing.lg, marginBottom: spacing.xs },
  overdueRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingVertical: spacing.sm, borderTopWidth: 1, borderTopColor: colors.divider },
  overdueName: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  overdueMeta: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 1 },
  remindBtn: { flexDirection: "row", alignItems: "center", gap: 4, backgroundColor: colors.brand, paddingHorizontal: 12, height: 32, borderRadius: radius.pill },
  remindBtnDone: { backgroundColor: colors.success + "1A" },
  remindText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: "#fff" },
  allClear: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: spacing.md },
  allClearText: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.onSurfaceSecondary },
  digestBadge: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: radius.pill },
  digestBadgeText: { fontFamily: font.bold, fontSize: fontSize.sm },
  bulkBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, marginTop: spacing.md, height: 46, borderRadius: radius.md, backgroundColor: colors.brand },
  bulkBtnText: { fontFamily: font.semibold, fontSize: fontSize.base, color: "#fff" },
  bulkHint: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginBottom: spacing.sm, lineHeight: 18 },
  bulkLabel: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, marginTop: spacing.md, marginBottom: spacing.xs },
  bulkPresetRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  bulkPreset: { paddingHorizontal: spacing.md, height: 36, borderRadius: radius.pill, alignItems: "center", justifyContent: "center", backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border },
  bulkPresetOn: { backgroundColor: colors.brand, borderColor: colors.brand },
  bulkPresetText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  bulkPresetTextOn: { color: "#fff" },
  rtsBtn: { flexDirection: "row", alignItems: "center", gap: 4, backgroundColor: colors.brand, paddingHorizontal: 12, height: 32, borderRadius: radius.pill },
  rtsBtnText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: "#fff" },
  bulkInput: { backgroundColor: colors.surfaceSecondary, borderWidth: 1.5, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: spacing.md, height: 48, marginTop: spacing.sm, fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}) },
  barsRow: { flexDirection: "row", alignItems: "flex-end", justifyContent: "space-between", height: 170 },
  barCol: { flex: 1, alignItems: "center", gap: 6 },
  barValue: { fontFamily: font.medium, fontSize: 10, color: colors.muted },
  barTrack: { height: 120, justifyContent: "flex-end" },
  bar: { width: 22, borderRadius: radius.sm },
  barLabel: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted },
  sectionRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginTop: spacing.xl, marginBottom: spacing.md },  sectionTitle: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface },
  link: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.brand },
  activityRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
    marginBottom: spacing.sm,
  },
  activityIcon: {
    width: 40,
    height: 40,
    borderRadius: radius.md,
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  activityTitle: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  activitySub: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
});
