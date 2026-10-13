/**
 * MP2 UI — Property detail drawer (Feb-2026 ship).
 *
 * Right-side drawer with 5 tabs:
 *   Info | Contact | Service Notes | Photos | Schedule
 *
 * All admin-only editing. Reads GET /api/properties/:pid and PATCHes
 * the fields the current tab owns. Photos + video URL uploads are
 * left as list-manageable strings — full Emergent Object Storage
 * plumbing is scheduled for the Photos-focused delta (M4/M5).
 */
import React from "react";
import { X } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import { Button, TextInput } from "@/components/ui-kit";
import ResponsiveTabs from "@/components/ui/responsive-tabs";

const TABS = ["Info", "Contact", "Service Notes", "Photos", "Schedule"];

export default function PropertyDrawer({ propertyId, onClose, onChanged, onToast }) {
  const [tab, setTab] = React.useState("Info");
  const [property, setProperty] = React.useState(null);
  const [schedule, setSchedule] = React.useState(null);
  const [loading, setLoading] = React.useState(false);

  const load = React.useCallback(async () => {
    if (!propertyId) return;
    setLoading(true);
    try {
      const p = await api.get(`/properties/${propertyId}`);
      setProperty(p);
    } catch (e) {
      onToast?.({ tone: "error", message: e.message });
    } finally {
      setLoading(false);
    }
  }, [propertyId, onToast]);

  const loadSchedule = React.useCallback(async () => {
    if (!propertyId) return;
    try {
      const r = await api.get(`/properties/${propertyId}/schedule?limit=25`);
      setSchedule(r);
    } catch (e) {
      onToast?.({ tone: "error", message: e.message });
    }
  }, [propertyId, onToast]);

  React.useEffect(() => {
    if (!propertyId) { setProperty(null); setSchedule(null); return; }
    setTab("Info");
    load();
  }, [propertyId, load]);

  React.useEffect(() => {
    if (tab === "Schedule" && propertyId) loadSchedule();
  }, [tab, propertyId, loadSchedule]);

  const patch = async (payload, successMsg) => {
    try {
      const p = await api.patch(`/properties/${propertyId}`, payload);
      setProperty(p);
      onToast?.({ tone: "success", message: successMsg });
      onChanged?.();
    } catch (e) {
      onToast?.({ tone: "error", message: e.message });
    }
  };

  if (!propertyId) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end"
      style={{ backgroundColor: "rgba(0,0,0,0.45)" }}
      onClick={onClose}
      data-testid="property-drawer"
    >
      <aside
        className="w-full max-w-xl h-full overflow-y-auto"
        style={{ backgroundColor: colors.surface, borderLeft: `1px solid ${colors.border}` }}
        onClick={(e) => e.stopPropagation()}
      >
        <header
          className="sticky top-0 z-10 px-5 py-3 flex items-center justify-between"
          style={{
            backgroundColor: colors.surface,
            borderBottom: `1px solid ${colors.border}`,
          }}
        >
          <div>
            <div className="text-base font-bold" style={{ color: colors.onSurface }} data-testid="pd-title">
              {property?.label || (loading ? "Loading…" : "Property")}
            </div>
            <div className="text-xs" style={{ color: colors.onSurfaceSecondary }}>
              {property?.address?.line1 || ""}
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded"
            style={{ color: colors.muted }}
            data-testid="pd-close"
          >
            <X size={18} />
          </button>
        </header>

        {/* Feb-2026 · migrated to <ResponsiveTabs>. Sticky wrapper
            preserves the drawer's scroll-anchor behavior; the
            component itself renders a horizontal strip on ≥md and a
            full-width dropdown below that so the 5 tabs stop
            requiring a horizontal scroll on narrow viewports. */}
        <div
          className="sticky top-[57px] z-10"
          style={{ backgroundColor: colors.surface }}
        >
          <ResponsiveTabs
            tabs={TABS}
            active={tab}
            onChange={setTab}
            testidPrefix="pd-tab"
            ariaLabel="Property sections"
          />
        </div>

        <div className="p-5">
          {loading || !property ? (
            <div className="text-sm" style={{ color: colors.onSurfaceSecondary }}>Loading…</div>
          ) : tab === "Info" ? (
            <InfoTab property={property} onPatch={patch} />
          ) : tab === "Contact" ? (
            <ContactTab property={property} onPatch={patch} />
          ) : tab === "Service Notes" ? (
            <ServiceNotesTab property={property} onPatch={patch} />
          ) : tab === "Photos" ? (
            <PhotosTab property={property} onPatch={patch} />
          ) : tab === "Schedule" ? (
            <ScheduleTab schedule={schedule} />
          ) : null}
        </div>
      </aside>
    </div>
  );
}

function InfoTab({ property, onPatch }) {
  const [form, setForm] = React.useState({
    label: property.label || "",
    line1: property.address?.line1 || "",
    city: property.address?.city || "",
    state: property.address?.state || "",
    postal_code: property.address?.postal_code || "",
    pool_size_gallons: property.pool_size_gallons || "",
    landscape_sq_ft: property.landscape_sq_ft || "",
    pool_type: property.pool_type || "",
    service_types: property.service_types || [],
    service_category: property.service_category || "unset",
  });
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const toggleService = (s) => setForm((f) => ({
    ...f,
    service_types: f.service_types.includes(s)
      ? f.service_types.filter((x) => x !== s)
      : [...f.service_types, s],
  }));

  const save = async () => {
    await onPatch({
      label: form.label,
      address: {
        line1: form.line1, city: form.city, state: form.state, postal_code: form.postal_code,
      },
      pool_size_gallons: form.pool_size_gallons ? Number(form.pool_size_gallons) : null,
      landscape_sq_ft: form.landscape_sq_ft ? Number(form.landscape_sq_ft) : null,
      pool_type: form.pool_type || null,
      service_types: form.service_types,
      // Feb-2026 · P2 #6 property pivot — admin override. ``"unset"``
      // clears the field server-side; the backend stamps
      // provenance (``admin_override`` / ``admin_cleared``).
      service_category:
        form.service_category && form.service_category !== "unset"
          ? form.service_category
          : null,
    }, "Info saved");
  };

  return (
    <div className="space-y-3" data-testid="pd-info-form">
      <TextInput label="LABEL" value={form.label} onChange={set("label")} testid="pd-label" />
      <TextInput label="STREET" value={form.line1} onChange={set("line1")} testid="pd-line1" />
      <div className="grid grid-cols-3 gap-2">
        <TextInput label="CITY" value={form.city} onChange={set("city")} testid="pd-city" />
        <TextInput label="STATE" value={form.state} onChange={set("state")} testid="pd-state" />
        <TextInput label="POSTAL" value={form.postal_code} onChange={set("postal_code")} testid="pd-postal" />
      </div>
      <div className="grid grid-cols-2 gap-2">
        <TextInput label="POOL SIZE (GAL)" type="number" value={form.pool_size_gallons} onChange={set("pool_size_gallons")} testid="pd-pool" />
        <TextInput label="LANDSCAPE (SQ FT)" type="number" value={form.landscape_sq_ft} onChange={set("landscape_sq_ft")} testid="pd-land" />
      </div>
      <TextInput label="POOL TYPE" value={form.pool_type} onChange={set("pool_type")} placeholder="e.g. Fiberglass" testid="pd-pool-type" />
      <div>
        <label className="text-xs font-semibold tracking-wide mb-1 block" style={{ color: colors.onSurfaceSecondary }}>
          SERVICE CATEGORY
        </label>
        <select
          data-testid="pd-service-category"
          value={form.service_category}
          onChange={(e) => setForm((f) => ({
            ...f, service_category: e.target.value,
          }))}
          className="w-full px-2 py-1.5 rounded text-sm"
          style={{
            backgroundColor: colors.surface,
            color: colors.onSurface,
            border: `1px solid ${colors.border}`,
          }}
        >
          <option value="unset">Not set — inherit from customer</option>
          <option value="pool">Pool</option>
          <option value="landscaping">Landscaping</option>
          <option value="both">Both services</option>
        </select>
      </div>
      <div>
        <label className="text-xs font-semibold tracking-wide mb-1 block" style={{ color: colors.onSurfaceSecondary }}>
          SERVICE TYPES
        </label>
        <div className="flex flex-wrap gap-2">
          {["Pool", "Landscape", "Repair"].map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => toggleService(s)}
              className="px-2 py-1 rounded-full text-xs font-semibold"
              style={{
                backgroundColor: form.service_types.includes(s) ? colors.brand : colors.surfaceMuted,
                color: form.service_types.includes(s) ? colors.onBrand : colors.onSurface,
              }}
              data-testid={`pd-svc-${s}`}
            >
              {s}
            </button>
          ))}
        </div>
      </div>
      <Button onClick={save} testid="pd-info-save">Save info</Button>
    </div>
  );
}

function ContactTab({ property, onPatch }) {
  const contact = property.site_contact || {};
  const [mobiles, setMobiles] = React.useState(contact.mobiles || []);
  const [emails, setEmails] = React.useState(contact.emails || []);
  const [name, setName] = React.useState(contact.name || "");

  const addMobile = () => setMobiles((m) => [...m, { number_e164: "", label: "Primary", is_primary: m.length === 0 }].slice(0, 2));
  const addEmail = () => setEmails((e) => [...e, { address: "", label: "Primary", is_primary: e.length === 0 }].slice(0, 3));
  const setMobile = (i, k, v) => setMobiles((m) => m.map((x, idx) => idx === i ? { ...x, [k]: v } : x));
  const setEmail = (i, k, v) => setEmails((e) => e.map((x, idx) => idx === i ? { ...x, [k]: v } : x));
  const rmMobile = (i) => setMobiles((m) => m.filter((_, idx) => idx !== i));
  const rmEmail = (i) => setEmails((e) => e.filter((_, idx) => idx !== i));

  const save = async () => {
    // Ensure exactly one primary in each array (first if none marked).
    const m = mobiles.map((x, i) => ({ ...x, is_primary: mobiles.some((y) => y.is_primary) ? !!x.is_primary : i === 0 }));
    const e = emails.map((x, i) => ({ ...x, is_primary: emails.some((y) => y.is_primary) ? !!x.is_primary : i === 0 }));
    await onPatch({
      site_contact: {
        name: name || null,
        mobiles: m.filter((x) => x.number_e164),
        emails: e.filter((x) => x.address),
        is_primary_contact: true,
      },
    }, "Contact saved");
  };

  return (
    <div className="space-y-3" data-testid="pd-contact-form">
      <TextInput label="ON-SITE NAME" value={name} onChange={(e) => setName(e.target.value)} testid="pd-contact-name" />

      <section>
        <div className="text-xs uppercase font-semibold mb-2 flex items-center justify-between" style={{ color: colors.muted }}>
          Mobiles (max 2)
          <button onClick={addMobile} disabled={mobiles.length >= 2} className="text-brand text-xs" data-testid="pd-add-mobile">+ Add</button>
        </div>
        {mobiles.length === 0 ? <div className="text-xs" style={{ color: colors.onSurfaceSecondary }}>None on file.</div> : null}
        {mobiles.map((m, i) => (
          <div key={i} className="flex items-center gap-2 mb-2">
            <input
              value={m.number_e164 || ""}
              onChange={(e) => setMobile(i, "number_e164", e.target.value)}
              placeholder="+15551234567"
              className="flex-1 px-3 py-2 rounded-lg text-sm"
              style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }}
              data-testid={`pd-mobile-${i}`}
            />
            <label className="text-xs flex items-center gap-1" style={{ color: colors.onSurfaceSecondary }}>
              <input
                type="radio"
                name="primary-mobile"
                checked={!!m.is_primary}
                onChange={() => setMobiles((mm) => mm.map((x, idx) => ({ ...x, is_primary: idx === i })))}
              />
              primary
            </label>
            <button onClick={() => rmMobile(i)} className="text-xs" style={{ color: colors.danger }}>×</button>
          </div>
        ))}
      </section>

      <section>
        <div className="text-xs uppercase font-semibold mb-2 flex items-center justify-between" style={{ color: colors.muted }}>
          Emails (max 3)
          <button onClick={addEmail} disabled={emails.length >= 3} className="text-brand text-xs" data-testid="pd-add-email">+ Add</button>
        </div>
        {emails.length === 0 ? <div className="text-xs" style={{ color: colors.onSurfaceSecondary }}>None on file.</div> : null}
        {emails.map((em, i) => (
          <div key={i} className="flex items-center gap-2 mb-2">
            <input
              value={em.address || ""}
              onChange={(e) => setEmail(i, "address", e.target.value)}
              placeholder="site@example.com"
              className="flex-1 px-3 py-2 rounded-lg text-sm"
              style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }}
              data-testid={`pd-email-${i}`}
            />
            <label className="text-xs flex items-center gap-1" style={{ color: colors.onSurfaceSecondary }}>
              <input
                type="radio"
                name="primary-email"
                checked={!!em.is_primary}
                onChange={() => setEmails((ee) => ee.map((x, idx) => ({ ...x, is_primary: idx === i })))}
              />
              primary
            </label>
            <button onClick={() => rmEmail(i)} className="text-xs" style={{ color: colors.danger }}>×</button>
          </div>
        ))}
      </section>

      <Button onClick={save} testid="pd-contact-save">Save contact</Button>
    </div>
  );
}

function ServiceNotesTab({ property, onPatch }) {
  const notes = property.service_notes || {};
  const [pool, setPool] = React.useState(notes.pool || "");
  const [landscape, setLandscape] = React.useState(notes.landscape || "");
  const save = async () => {
    await onPatch({ service_notes: { pool: pool || null, landscape: landscape || null } }, "Notes saved");
  };
  return (
    <div className="space-y-3" data-testid="pd-notes-form">
      <label className="text-xs uppercase font-semibold" style={{ color: colors.muted }}>Pool note</label>
      <textarea
        rows={4}
        value={pool}
        onChange={(e) => setPool(e.target.value)}
        className="w-full px-3 py-2 rounded-lg text-sm"
        style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }}
        data-testid="pd-note-pool"
      />
      <label className="text-xs uppercase font-semibold" style={{ color: colors.muted }}>Landscape note</label>
      <textarea
        rows={4}
        value={landscape}
        onChange={(e) => setLandscape(e.target.value)}
        className="w-full px-3 py-2 rounded-lg text-sm"
        style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }}
        data-testid="pd-note-landscape"
      />
      <Button onClick={save} testid="pd-notes-save">Save notes</Button>
    </div>
  );
}

function PhotosTab({ property, onPatch }) {
  const [urls, setUrls] = React.useState((property.photo_urls || []).join("\n"));
  const save = async () => {
    const list = urls.split("\n").map((s) => s.trim()).filter(Boolean);
    await onPatch({ photo_urls: list }, "Photos saved");
  };
  return (
    <div className="space-y-3" data-testid="pd-photos-form">
      <div className="text-xs" style={{ color: colors.onSurfaceSecondary }}>
        One image URL per line. Full upload workflow via Emergent Object Storage
        ships in the Photos-focused delta.
      </div>
      <textarea
        rows={6}
        value={urls}
        onChange={(e) => setUrls(e.target.value)}
        className="w-full px-3 py-2 rounded-lg text-sm font-mono"
        style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }}
        data-testid="pd-photo-urls"
      />
      <div className="grid grid-cols-3 gap-2">
        {(property.photo_urls || []).map((u, i) => (
          <img key={i} src={u} alt={`Property photo ${i + 1}`} className="w-full h-24 object-cover rounded-lg" style={{ border: `1px solid ${colors.border}` }} />
        ))}
      </div>
      <Button onClick={save} testid="pd-photos-save">Save photos</Button>
    </div>
  );
}

function ScheduleTab({ schedule }) {
  if (!schedule) return <div className="text-sm" style={{ color: colors.onSurfaceSecondary }}>Loading schedule…</div>;
  const jobs = schedule.jobs || [];
  const upcoming = jobs.filter((j) => j.status && !["completed", "cancelled"].includes(j.status)).slice(0, 5);
  const recent = jobs.slice(0, 20);
  return (
    <div className="space-y-4" data-testid="pd-schedule">
      <section>
        <div className="text-xs uppercase font-semibold mb-2" style={{ color: colors.muted }}>Upcoming (next 5)</div>
        {upcoming.length === 0 ? (
          <div className="text-sm" style={{ color: colors.onSurfaceSecondary }}>Nothing on the books.</div>
        ) : (
          <ul className="space-y-2">
            {upcoming.map((j) => (
              <li key={j.id} className="flex justify-between p-2 rounded-lg" style={{ backgroundColor: colors.surfaceMuted }}>
                <span style={{ color: colors.onSurface }}>{j.title}</span>
                <span className="text-xs" style={{ color: colors.onSurfaceSecondary }}>{j.scheduled_date || "TBD"}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
      <section>
        <div className="text-xs uppercase font-semibold mb-2" style={{ color: colors.muted }}>Recent (last 20)</div>
        {recent.length === 0 ? (
          <div className="text-sm" style={{ color: colors.onSurfaceSecondary }}>No jobs yet.</div>
        ) : (
          <ul className="space-y-1 text-sm">
            {recent.map((j) => (
              <li key={j.id} className="flex justify-between">
                <span style={{ color: colors.onSurface }}>{j.title}</span>
                <span style={{ color: colors.onSurfaceSecondary }}>
                  {j.scheduled_date || "—"} · {j.status || ""}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
