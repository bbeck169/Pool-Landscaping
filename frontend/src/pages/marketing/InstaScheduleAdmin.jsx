import React, { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, Copy, Plus, Trash2, ExternalLink, Check, X, Calendar as CalIcon, Clock } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { toast } from "sonner";

const DOW = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];

function ServiceRow({ svc, onChange, onRemove }) {
  const set = (patch) => onChange({ ...svc, ...patch });
  return (
    <div className="rounded-lg p-2 grid grid-cols-12 gap-1 items-center"
          style={{ backgroundColor: colors.surfaceSecondary,
                    border: `1px solid ${colors.border}` }}>
      <Input className="col-span-4" value={svc.name}
              onChange={(e) => set({ name: e.target.value })}
              placeholder="Service name" />
      <Input className="col-span-2" type="number" value={svc.duration_minutes}
              min={15} step={15}
              onChange={(e) => set({ duration_minutes: Number(e.target.value) })}
              placeholder="min" />
      <label className="col-span-2 flex items-center gap-1 text-xs">
        <Switch checked={svc.allow_public_book !== false}
                 onCheckedChange={(v) => set({ allow_public_book: v })} />
        Public
      </label>
      <label className="col-span-3 flex items-center gap-1 text-xs">
        <Switch checked={!!svc.requires_address}
                 onCheckedChange={(v) => set({ requires_address: v })} />
        Needs address
      </label>
      <button
        // Phase K54.1 · Feb-2026 — promoted icon-only remove from
        // ``text-red-500`` foreground to the solid destructive
        // spec.  Row-level trash button; small but destructive.
        className="col-span-1 inline-flex items-center justify-center h-8 w-8 rounded-lg text-white bg-[#DC2626] hover:bg-[#B91C1C] active:brightness-95 focus:outline-none focus-visible:ring-2 focus-visible:ring-[#EF4444] focus-visible:ring-offset-1 disabled:opacity-55 shadow-sm"
        onClick={onRemove}
        aria-label="Remove service"
        data-testid="insta-service-row-remove-btn"
      >
        <Trash2 className="w-4 h-4" />
      </button>
    </div>
  );
}

function WeekdayWindows({ rules, onChange }) {
  const set = (dow, wins) => onChange({
    ...rules,
    weekday_windows: { ...(rules.weekday_windows || {}), [dow]: wins },
  });
  return (
    <div className="space-y-1">
      {DOW.map((d) => {
        const wins = (rules.weekday_windows || {})[d] || [];
        return (
          <div key={d} className="flex items-center gap-2 text-sm">
            <span className="w-8 uppercase text-xs font-semibold">{d}</span>
            {wins.map((w, i) => (
              <span key={i} className="flex items-center gap-1">
                <Input value={w.start} className="w-16 text-xs"
                        onChange={(e) => {
                          const c = [...wins];
                          c[i] = { ...c[i], start: e.target.value };
                          set(d, c);
                        }} />
                <span>→</span>
                <Input value={w.end} className="w-16 text-xs"
                        onChange={(e) => {
                          const c = [...wins];
                          c[i] = { ...c[i], end: e.target.value };
                          set(d, c);
                        }} />
                <button onClick={() => set(d, wins.filter((_, ix) => ix !== i))}
                        className="text-red-500 text-xs">×</button>
              </span>
            ))}
            <button onClick={() => set(d, [...wins,
                                            { start: "09:00", end: "17:00" }])}
                    className="text-xs px-2 py-1 rounded border">
              + window
            </button>
          </div>
        );
      })}
    </div>
  );
}

function BookingsPanel({ refresh }) {
  const [rows, setRows] = useState([]);
  const [sel, setSel] = useState(null);
  const load = useCallback(async () => {
    const r = await api.get("/instaschedule/bookings?limit=100")
      .catch(() => ({ bookings: [] }));
    setRows(r.bookings || []);
  }, []);
  useEffect(() => { load(); }, [load, refresh]);

  const confirm = async (id) => {
    try {
      const r = await api.post(`/instaschedule/bookings/${id}/confirm`);
      toast.success(`Confirmed → job ${r.job_id?.slice(0, 6)}…`);
      setSel(null); load();
    } catch (e) { toast.error(e?.message || "Confirm failed"); }
  };
  const decline = async (id) => {
    try {
      await api.post(`/instaschedule/bookings/${id}/decline`, { reason: "" });
      toast.success("Declined"); setSel(null); load();
    } catch (e) { toast.error(e?.message || "Decline failed"); }
  };
  const cancel = async (id) => {
    if (!window.confirm("Cancel this booking (and its linked job)?")) return;
    try {
      await api.post(`/instaschedule/bookings/${id}/cancel`);
      toast.success("Cancelled"); setSel(null); load();
    } catch (e) { toast.error(e?.message || "Cancel failed"); }
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4"
          data-testid="is-bookings-panel">
      <div className="rounded-2xl p-4"
            style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}>
        <h3 className="font-semibold mb-2">Recent bookings</h3>
        {rows.length === 0 && (
          <div className="text-sm text-center py-6"
                style={{ color: colors.muted }}>
            No bookings yet.
          </div>
        )}
        <div className="space-y-1">
          {rows.map((s) => (
            <button key={s.id}
                    onClick={() => setSel(s)}
                    className="w-full text-left rounded-lg p-2 text-sm"
                    style={{
                      backgroundColor: sel?.id === s.id
                        ? colors.surfaceSecondary : "transparent",
                      border: `1px solid ${colors.border}`,
                    }}
                    data-testid={`is-booking-${s.id}`}>
              <div className="flex items-center justify-between">
                <div className="font-semibold truncate">
                  {s.contact?.name || s.contact?.email || "(anonymous)"}
                </div>
                <Badge variant="outline">{s.status}</Badge>
              </div>
              <div className="text-xs" style={{ color: colors.muted }}>
                {s.requested_slot?.date} · {s.requested_slot?.start_iso?.slice(11, 16)}
              </div>
            </button>
          ))}
        </div>
      </div>
      <div className="rounded-2xl p-4"
            style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}>
        {!sel && (
          <div className="text-sm text-center py-8"
                style={{ color: colors.muted }}>
            Pick a booking to review / act.
          </div>
        )}
        {sel && (
          <div className="text-sm space-y-2">
            <div className="flex items-center justify-between">
              <h3 className="font-semibold">Booking · {sel.status}</h3>
            </div>
            <div>
              <div className="font-semibold">{sel.contact?.name}</div>
              <div style={{ color: colors.muted }}>{sel.contact?.email}</div>
              <div style={{ color: colors.muted }}>{sel.contact?.phone}</div>
              {sel.contact?.notes && (
                <div className="italic mt-1">"{sel.contact.notes}"</div>
              )}
            </div>
            <div className="rounded p-2"
                  style={{ backgroundColor: colors.surfaceSecondary }}>
              <div className="flex items-center gap-2">
                <CalIcon className="w-4 h-4" />
                <b>{sel.requested_slot?.date}</b>
                <Clock className="w-4 h-4 ml-2" />
                <b>{sel.requested_slot?.start_iso?.slice(11, 16)}</b>
                –
                <b>{sel.requested_slot?.end_iso?.slice(11, 16)}</b>
              </div>
            </div>
            {sel.status === "pending" && (
              <div className="flex gap-2 pt-2">
                <Button onClick={() => confirm(sel.id)}
                          data-testid="is-confirm">
                  <Check className="w-3 h-3 mr-1" /> Confirm
                </Button>
                <Button variant="outline"
                          onClick={() => decline(sel.id)}
                          data-testid="is-decline">
                  <X className="w-3 h-3 mr-1" /> Decline
                </Button>
              </div>
            )}
            {sel.status === "confirmed" && (
              <>
                <div className="text-xs" style={{ color: colors.muted }}>
                  Job: <code>{sel.computed_job_id}</code>
                </div>
                <Button variant="outline"
                          onClick={() => cancel(sel.id)}
                          data-testid="is-cancel">
                  <X className="w-3 h-3 mr-1" /> Cancel booking + job
                </Button>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default function InstaScheduleAdminPage() {
  const nav = useNavigate();
  const [configs, setConfigs] = useState([]);
  const [cfg, setCfg] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const load = useCallback(async () => {
    const r = await api.get("/instaschedule/configs")
      .catch(() => ({ configs: [] }));
    setConfigs(r.configs || []);
    if (r.configs?.length && !cfg) setCfg(r.configs[0]);
  }, [cfg]);
  useEffect(() => { load(); }, [load]);

  const newConfig = () => setCfg({
    slug: `book-${Math.floor(Math.random() * 100000).toString(36)}`,
    headline: "Book your service.",
    brand_color: "#0284C7",
    service_types: [
      { name: "Weekly Pool Service", duration_minutes: 60,
        allow_public_book: true },
    ],
    availability_rules: {
      timezone: "UTC",
      weekday_windows: Object.fromEntries(DOW.map((d) => [d, [{ start: "09:00", end: "17:00" }]])),
      blackout_dates: [], max_bookings_per_day: 20,
      min_notice_hours: 4, max_lead_days: 30,
    },
    route_integration: { enabled: false, assign_strategy: "admin_manual" },
    collect_fields: { name: true, email: true, phone: true, notes: true },
    thank_you_html: "Thanks!", active: false,
  });

  const save = async () => {
    try {
      if (cfg.id) {
        const p = { ...cfg }; delete p.slug; delete p.id;
        delete p.tenant_id; delete p.created_at; delete p.updated_at;
        delete p.active;
        const r = await api.patch(`/instaschedule/configs/${cfg.id}`, p);
        setCfg(r);
        toast.success("Saved");
      } else {
        const r = await api.post("/instaschedule/configs", cfg);
        setCfg(r);
        toast.success("Created");
      }
      load();
    } catch (e) { toast.error(e?.message || "Save failed"); }
  };

  const activate = async () => {
    if (!cfg?.id) return;
    try {
      await api.post(`/instaschedule/configs/${cfg.id}/activate`);
      toast.success("Activated"); load();
    } catch (e) { toast.error(e?.message || "Activate failed"); }
  };

  const publicUrl = cfg?.slug
    ? `${window.location.origin}/book/${cfg.slug}` : "";
  const setSvc = (i, patch) => {
    const svcs = [...(cfg.service_types || [])];
    svcs[i] = patch;
    setCfg({ ...cfg, service_types: svcs });
  };

  return (
    <div className="p-4 md:p-8 max-w-6xl mx-auto space-y-4"
          data-testid="instaschedule-admin">
      <div className="flex items-center gap-3 mb-4">
        <button onClick={() => nav(-1)}
                className="p-2 rounded-lg hover:brightness-95"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}>
          <ArrowLeft size={16} />
        </button>
        <div className="flex-1">
          <h1 className="text-2xl md:text-3xl font-bold"
              style={{ color: colors.onSurface }}>
            InstaSchedule
          </h1>
          <p className="text-xs mt-0.5" style={{ color: colors.muted }}>
            Public 24/7 self-booking. One active config per tenant.
          </p>
        </div>
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        <select className="border rounded p-2 text-sm"
                value={cfg?.id || "new"}
                onChange={(e) => {
                  const v = e.target.value;
                  if (v === "new") newConfig();
                  else setCfg(configs.find((c) => c.id === v));
                }}
                data-testid="is-config-select">
          <option value="new">+ New config</option>
          {configs.map((c) => (
            <option key={c.id} value={c.id}>
              {c.slug} {c.active ? "(active)" : ""}
            </option>
          ))}
        </select>
        {cfg?.id && (
          <>
            <Badge variant="outline">
              {cfg.active ? "Active" : "Draft"}
            </Badge>
            {!cfg.active && (
              <Button variant="outline" size="sm" onClick={activate}
                        data-testid="is-activate">
                Activate
              </Button>
            )}
            {publicUrl && (
              <button onClick={() => {
                        navigator.clipboard.writeText(publicUrl);
                        toast.success("Public URL copied");
                      }}
                      className="text-xs px-2 py-1 rounded border flex items-center gap-1"
                      data-testid="is-copy-url">
                <Copy className="w-3 h-3" /> {publicUrl}
              </button>
            )}
            {cfg.active && (
              <a href={publicUrl} target="_blank" rel="noreferrer"
                  className="text-xs px-2 py-1 rounded border flex items-center gap-1">
                <ExternalLink className="w-3 h-3" /> Open
              </a>
            )}
          </>
        )}
      </div>

      {cfg && (
        <Tabs defaultValue="builder">
          <TabsList>
            <TabsTrigger value="builder" data-testid="is-tab-builder">
              Builder
            </TabsTrigger>
            <TabsTrigger value="bookings"
                          onClick={() => setRefreshKey((n) => n + 1)}
                          data-testid="is-tab-bookings">
              Bookings
            </TabsTrigger>
          </TabsList>
          <TabsContent value="builder" className="mt-4">
            <div className="rounded-2xl p-5 space-y-4"
                  style={{ backgroundColor: colors.surface,
                            border: `1px solid ${colors.border}` }}>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div>
                  <Label>Slug</Label>
                  <Input value={cfg.slug || ""}
                          onChange={(e) => setCfg({ ...cfg, slug: e.target.value })}
                          disabled={!!cfg.id}
                          data-testid="is-slug" />
                </div>
                <div>
                  <Label>Brand color</Label>
                  <Input type="color" value={cfg.brand_color || "#0284C7"}
                          onChange={(e) => setCfg({ ...cfg, brand_color: e.target.value })} />
                </div>
                <div className="md:col-span-2">
                  <Label>Headline</Label>
                  <Input value={cfg.headline || ""}
                          onChange={(e) => setCfg({ ...cfg, headline: e.target.value })}
                          data-testid="is-headline" />
                </div>
              </div>
              <div>
                <div className="flex items-center justify-between">
                  <h3 className="font-semibold text-sm">Service types</h3>
                  <Button size="sm" variant="outline"
                            onClick={() => setCfg({
                              ...cfg,
                              service_types: [...(cfg.service_types || []),
                                { name: "New service", duration_minutes: 60,
                                  allow_public_book: true }],
                            })}>
                    <Plus className="w-3 h-3 mr-1" /> Add
                  </Button>
                </div>
                <div className="space-y-2 mt-2">
                  {(cfg.service_types || []).map((s, i) => (
                    <ServiceRow key={i} svc={s}
                                  onChange={(v) => setSvc(i, v)}
                                  onRemove={() => setCfg({
                                    ...cfg,
                                    service_types: cfg.service_types.filter((_, ix) => ix !== i),
                                  })} />
                  ))}
                </div>
              </div>

              <div>
                <h3 className="font-semibold text-sm mb-2">
                  Availability (weekday windows)
                </h3>
                <WeekdayWindows
                    rules={cfg.availability_rules || {}}
                    onChange={(r) => setCfg({ ...cfg, availability_rules: r })} />
              </div>

              <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                <div>
                  <Label>Min notice (hrs)</Label>
                  <Input type="number"
                          value={cfg.availability_rules?.min_notice_hours || 0}
                          onChange={(e) => setCfg({
                            ...cfg,
                            availability_rules: {
                              ...(cfg.availability_rules || {}),
                              min_notice_hours: Number(e.target.value),
                            },
                          })} />
                </div>
                <div>
                  <Label>Max lead (days)</Label>
                  <Input type="number"
                          value={cfg.availability_rules?.max_lead_days || 30}
                          onChange={(e) => setCfg({
                            ...cfg,
                            availability_rules: {
                              ...(cfg.availability_rules || {}),
                              max_lead_days: Number(e.target.value),
                            },
                          })} />
                </div>
                <div>
                  <Label>Max bookings/day</Label>
                  <Input type="number"
                          value={cfg.availability_rules?.max_bookings_per_day || 20}
                          onChange={(e) => setCfg({
                            ...cfg,
                            availability_rules: {
                              ...(cfg.availability_rules || {}),
                              max_bookings_per_day: Number(e.target.value),
                            },
                          })} />
                </div>
                <div>
                  <Label>Assign strategy</Label>
                  <select className="w-full border rounded p-2 text-sm mt-1"
                          value={cfg.route_integration?.assign_strategy || "admin_manual"}
                          onChange={(e) => setCfg({
                            ...cfg,
                            route_integration: {
                              ...(cfg.route_integration || {}),
                              enabled: e.target.value !== "admin_manual",
                              assign_strategy: e.target.value,
                            },
                          })}>
                    <option value="admin_manual">Admin manual</option>
                    <option value="round_robin">Round robin</option>
                    <option value="least_loaded">Least loaded</option>
                  </select>
                </div>
              </div>

              <div>
                <Label>Thank-you HTML</Label>
                <Textarea rows={2} value={cfg.thank_you_html || ""}
                            onChange={(e) => setCfg({ ...cfg, thank_you_html: e.target.value })} />
              </div>

              <Button onClick={save} data-testid="is-save">
                <Check className="w-4 h-4 mr-1" /> Save
              </Button>
            </div>
          </TabsContent>
          <TabsContent value="bookings" className="mt-4">
            <BookingsPanel refresh={refreshKey} />
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
}
