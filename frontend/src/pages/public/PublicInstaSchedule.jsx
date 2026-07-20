/**
 * QuoteIQ Q5 · Public InstaSchedule page — `/book/:slug`.
 *
 * Unauthenticated. Same shell as PublicInstaQuote (no AppLayout, no
 * auth). 4 steps: service → date → slot → contact → review.
 */
import React, { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { CheckCircle2, Loader2, ChevronLeft } from "lucide-react";

const BASE = process.env.REACT_APP_BACKEND_URL;

function fmtSlotTime(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleTimeString([], {
    hour: "numeric", minute: "2-digit",
  });
}

function fmtSlotDate(ymd) {
  if (!ymd) return "";
  return new Date(ymd + "T12:00:00Z").toLocaleDateString([], {
    weekday: "short", month: "short", day: "numeric",
  });
}

function DatePicker({ cfg, service, value, onChange }) {
  const rules = cfg.availability_rules || {};
  const maxLead = Number(rules.max_lead_days || 30);
  const blackout = new Set(rules.blackout_dates || []);
  const weekdays = rules.weekday_windows || {};
  const dowKey = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"];
  const today = new Date();
  const days = [];
  for (let i = 0; i <= maxLead; i++) {
    const d = new Date(today);
    d.setDate(d.getDate() + i);
    const ymd = d.toISOString().slice(0, 10);
    const dow = dowKey[d.getUTCDay()];
    // Actually rely on local getDay to match the tenant-perceived weekday.
    const dowLocal = dowKey[d.getDay()];
    const hasWindow = (weekdays[dowLocal] || []).length > 0;
    days.push({
      ymd, label: d.getDate(), dow: dowLocal,
      disabled: !hasWindow || blackout.has(ymd),
    });
  }
  return (
    <div style={{ display: "grid",
                    gridTemplateColumns: "repeat(7, 1fr)", gap: 6 }}>
      {days.map((d) => (
        <button key={d.ymd}
                onClick={() => !d.disabled && onChange(d.ymd)}
                disabled={d.disabled}
                style={{
                  padding: 8, borderRadius: 8,
                  border: `1px solid ${value === d.ymd ? cfg.brand_color : "#e4e4e7"}`,
                  background: value === d.ymd
                    ? cfg.brand_color : d.disabled ? "#f4f4f5" : "#fff",
                  color: value === d.ymd ? "#fff"
                    : d.disabled ? "#a1a1aa" : "#18181b",
                  cursor: d.disabled ? "not-allowed" : "pointer",
                  fontSize: 12,
                }}
                data-testid={`is-date-${d.ymd}`}>
          <div style={{ fontSize: 9, textTransform: "uppercase",
                          opacity: 0.7 }}>
            {d.dow}
          </div>
          <div style={{ fontWeight: 700 }}>{d.label}</div>
        </button>
      ))}
    </div>
  );
}

function SlotGrid({ cfg, slots, loading, value, onChange }) {
  if (loading) return <Loader2 className="animate-spin" size={20} />;
  if (!slots.length) {
    return (
      <div style={{ color: "#71717a", padding: 12,
                      textAlign: "center", fontSize: 14 }}>
        No slots available for that date.
      </div>
    );
  }
  return (
    <div style={{ display: "grid",
                    gridTemplateColumns: "repeat(auto-fill, minmax(110px, 1fr))",
                    gap: 6 }}>
      {slots.map((s) => (
        <button key={s.start_iso}
                onClick={() => onChange(s)}
                style={{
                  padding: 8, borderRadius: 8,
                  border: `1px solid ${value?.start_iso === s.start_iso
                    ? cfg.brand_color : "#e4e4e7"}`,
                  background: value?.start_iso === s.start_iso
                    ? cfg.brand_color : "#fff",
                  color: value?.start_iso === s.start_iso ? "#fff" : "#18181b",
                  cursor: "pointer", fontSize: 13, fontWeight: 500,
                }}
                data-testid={`is-slot-${s.start_iso}`}>
          {fmtSlotTime(s.start_iso)}
        </button>
      ))}
    </div>
  );
}

export default function PublicInstaSchedulePage() {
  const { slug } = useParams();
  const [cfg, setCfg] = useState(null);
  const [error, setError] = useState("");
  const [step, setStep] = useState(1);
  const [service, setService] = useState(null);
  const [dateYmd, setDateYmd] = useState("");
  const [slot, setSlot] = useState(null);
  const [slots, setSlots] = useState([]);
  const [slotsLoading, setSlotsLoading] = useState(false);
  const [contact, setContact] = useState({});
  const [hp, setHp] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(null);

  useEffect(() => {
    fetch(`${BASE}/api/public/instaschedule/${slug}`)
      .then(async (r) => {
        if (r.ok) return r.json();
        throw new Error("Not found");
      })
      .then(setCfg)
      .catch((e) => setError(e.message || "Not found"));
  }, [slug]);

  useEffect(() => {
    if (!service || !dateYmd) return;
    setSlotsLoading(true);
    fetch(`${BASE}/api/public/instaschedule/${slug}/slots?service_type_id=${service.id}&date=${dateYmd}`)
      .then((r) => r.json())
      .then((d) => setSlots(d.slots || []))
      .catch(() => setSlots([]))
      .finally(() => setSlotsLoading(false));
  }, [service, dateYmd, slug]);

  const CF = cfg?.collect_fields || {};
  const brand = cfg?.brand_color || "#0284C7";

  const submit = async () => {
    setBusy(true); setError("");
    try {
      const r = await fetch(`${BASE}/api/public/instaschedule/${slug}/book`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          service_type_id: service.id,
          requested_slot: { start_iso: slot.start_iso,
                              end_iso: slot.end_iso },
          contact,
          notes: contact.notes || "",
          _hp: hp,
        }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
      if (data.success_redirect_url) {
        window.location.href = data.success_redirect_url;
        return;
      }
      setDone(data);
    } catch (e) {
      setError(e.message || "Booking failed");
    } finally { setBusy(false); }
  };

  if (error && !cfg) {
    return (
      <div style={centerBox}>
        <div style={{ fontSize: 20, fontWeight: 700 }}>Not found</div>
        <div style={{ color: "#71717a", marginTop: 6 }}>{error}</div>
      </div>
    );
  }
  if (!cfg) return <div style={centerBox}><Loader2 className="animate-spin" /></div>;

  if (done) {
    return (
      <div style={centerBox} data-testid="is-done">
        <div style={{ maxWidth: 480, background: "#fff", borderRadius: 16,
                        padding: 32, borderTop: `4px solid ${brand}`,
                        boxShadow: "0 8px 24px rgba(0,0,0,0.06)" }}>
          <CheckCircle2 color="#10b981" size={48} />
          <h1 style={{ fontSize: 22, fontWeight: 700, margin: "12px 0 6px" }}>
            Booking received
          </h1>
          <div style={{ color: "#52525b", marginBottom: 10 }}>
            Reference: <b>{done.id}</b><br />
            Slot: <b>{fmtSlotDate(done.requested_slot.date)}, {fmtSlotTime(done.requested_slot.start_iso)}</b>
          </div>
          <div dangerouslySetInnerHTML={{ __html: cfg.thank_you_html || "" }} />
        </div>
      </div>
    );
  }

  return (
    <div style={{ minHeight: "100vh", background: "#f4f4f5" }}
          data-testid="is-public-page">
      <div style={pageInner(brand)}>
        <h1 style={{ fontSize: 26, fontWeight: 800, margin: 0 }}>
          {cfg.headline}
        </h1>
        {cfg.subheadline && (
          <div style={{ color: "#71717a", marginTop: 4 }}>
            {cfg.subheadline}
          </div>
        )}

        <div style={{ marginTop: 20 }}>
          {step > 1 && (
            <button onClick={() => setStep(step - 1)} style={backBtn}>
              <ChevronLeft size={14} /> Back
            </button>
          )}
        </div>

        {step === 1 && (
          <section style={{ marginTop: 12 }}>
            <h2 style={h2}>1 · Pick a service</h2>
            <div style={{ display: "flex", flexDirection: "column",
                            gap: 8, marginTop: 8 }}>
              {cfg.service_types.map((s) => (
                <button key={s.id}
                        onClick={() => { setService(s); setStep(2); }}
                        style={svcBtn}
                        data-testid={`is-svc-${s.id}`}>
                  <div style={{ fontWeight: 700 }}>{s.name}</div>
                  <div style={{ color: "#71717a", fontSize: 13 }}>
                    {s.description || `${s.duration_minutes} min`}
                  </div>
                </button>
              ))}
            </div>
          </section>
        )}

        {step === 2 && (
          <section style={{ marginTop: 12 }}>
            <h2 style={h2}>2 · Pick a date</h2>
            <div style={{ marginTop: 8 }}>
              <DatePicker cfg={cfg} service={service}
                            value={dateYmd}
                            onChange={(v) => { setDateYmd(v); setStep(3); }} />
            </div>
          </section>
        )}

        {step === 3 && (
          <section style={{ marginTop: 12 }}>
            <h2 style={h2}>3 · Pick a slot · {fmtSlotDate(dateYmd)}</h2>
            <div style={{ marginTop: 8 }}>
              <SlotGrid cfg={cfg} slots={slots} loading={slotsLoading}
                          value={slot}
                          onChange={(s) => { setSlot(s); setStep(4); }} />
            </div>
          </section>
        )}

        {step === 4 && (
          <section style={{ marginTop: 12 }}>
            <h2 style={h2}>4 · Your info</h2>
            <div style={{ background: "#f4f4f5", padding: 12,
                            borderRadius: 8, marginTop: 8, marginBottom: 12,
                            fontSize: 14 }}>
              <b>{service.name}</b> · {fmtSlotDate(dateYmd)} · {fmtSlotTime(slot.start_iso)}
            </div>
            <div style={{ display: "grid",
                            gridTemplateColumns: "1fr 1fr", gap: 10 }}>
              {CF.name !== false && (
                <input placeholder="Name" style={inp}
                        value={contact.name || ""}
                        onChange={(e) => setContact({ ...contact, name: e.target.value })}
                        data-testid="is-name" />
              )}
              {CF.email !== false && (
                <input placeholder="Email" type="email" style={inp}
                        value={contact.email || ""}
                        onChange={(e) => setContact({ ...contact, email: e.target.value })}
                        data-testid="is-email" />
              )}
              {CF.phone !== false && (
                <input placeholder="Phone" type="tel" style={inp}
                        value={contact.phone || ""}
                        onChange={(e) => setContact({ ...contact, phone: e.target.value })}
                        data-testid="is-phone" />
              )}
              {(CF.address || service.requires_address) && (
                <input placeholder="Address" style={{ ...inp, gridColumn: "span 2" }}
                        value={contact.address || ""}
                        onChange={(e) => setContact({ ...contact, address: e.target.value })}
                        data-testid="is-address" />
              )}
              {CF.notes && (
                <textarea placeholder="Notes (optional)"
                            style={{ ...inp, gridColumn: "span 2" }}
                            rows={2}
                            value={contact.notes || ""}
                            onChange={(e) => setContact({ ...contact, notes: e.target.value })}
                            data-testid="is-notes" />
              )}
            </div>
            {/* Honeypot */}
            <input value={hp} onChange={(e) => setHp(e.target.value)}
                    autoComplete="off" tabIndex={-1}
                    style={{ position: "absolute", left: -9999, opacity: 0 }}
                    aria-hidden="true" name="_hp" />
            {error && (
              <div style={{ color: "#b91c1c", marginTop: 12 }}>{error}</div>
            )}
            <button onClick={submit} disabled={busy}
                    style={{
                      marginTop: 16, background: brand, color: "#fff",
                      border: "none", padding: "12px 18px", borderRadius: 10,
                      fontWeight: 700, cursor: busy ? "wait" : "pointer",
                      width: "100%",
                    }}
                    data-testid="is-submit">
              {busy ? "Submitting…" : "Confirm booking"}
            </button>
          </section>
        )}
      </div>
    </div>
  );
}

const centerBox = {
  minHeight: "100vh", display: "flex", alignItems: "center",
  justifyContent: "center", flexDirection: "column",
  padding: 24, background: "#f4f4f5",
};
const pageInner = (brand) => ({
  maxWidth: 760, margin: "0 auto", padding: 24,
  background: "#fff", minHeight: "100vh",
  borderTop: `6px solid ${brand}`,
});
const h2 = { fontSize: 15, fontWeight: 700, margin: 0 };
const backBtn = {
  background: "transparent", border: "none", color: "#3f3f46",
  fontSize: 13, cursor: "pointer", display: "flex", alignItems: "center",
  gap: 4,
};
const svcBtn = {
  padding: 14, textAlign: "left", border: "1px solid #e4e4e7",
  borderRadius: 12, background: "#fff", cursor: "pointer",
};
const inp = {
  padding: 10, borderRadius: 8, border: "1px solid #d4d4d8",
  fontSize: 14,
};
