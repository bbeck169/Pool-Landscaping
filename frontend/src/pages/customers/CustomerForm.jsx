import React, { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "@/api";
import { colors } from "@/theme";
import {
  PageHeader,
  TagChip,
  Button,
  TextInput,
  Toast,
} from "@/components/ui-kit";
import { X, Plus, ArrowLeft } from "lucide-react";
import AddressAutocomplete from "@/components/AddressAutocomplete";

const TAG_PRESETS = ["VIP", "Specialty"];

/**
 * Combined New + Edit form. `/customers/new` mounts with no id.
 * `/customers/:id/edit` (Phase 2 extra) prefetches the customer.
 */
export default function CustomerForm() {
  const navigate = useNavigate();
  const { id } = useParams();
  const isEdit = !!id;
  const [toast, setToast] = useState(null);
  const [form, setForm] = useState({
    name: "",
    email: "",
    phone: "",
    address: "",
    billing_address: "",
    gate_code: "",
    notes: "",
    alert_email: "",
    alert_phone: "",
    waitlisted: false,
    tags: [],
    secondary_addresses: [],
    pool_gallons: "",
    is_vip: false,
  });
  const [busy, setBusy] = useState(false);
  const [newTag, setNewTag] = useState("");
  const [newSecondary, setNewSecondary] = useState("");

  useEffect(() => {
    if (!isEdit) return;
    api.get(`/customers/${id}`).then((c) =>
      setForm({
        name: c.name || "",
        email: c.email || "",
        phone: c.phone || "",
        address: c.address || "",
        billing_address: c.billing_address || "",
        gate_code: c.gate_code || "",
        notes: c.notes || "",
        alert_email: c.alert_email || "",
        alert_phone: c.alert_phone || "",
        waitlisted: !!c.waitlisted,
        tags: c.tags || [],
        secondary_addresses: c.secondary_addresses || [],
        pool_gallons: c.pool_gallons == null ? "" : String(c.pool_gallons),
      })
    );
  }, [id, isEdit]);

  const set = (k) => (e) => {
    const v = e?.target?.type === "checkbox" ? e.target.checked : e?.target?.value;
    setForm((f) => ({ ...f, [k]: v }));
  };

  const addTag = (t) => {
    if (!t) return;
    if (form.tags.includes(t)) return;
    setForm((f) => ({ ...f, tags: [...f.tags, t] }));
    setNewTag("");
  };
  const removeTag = (t) => setForm((f) => ({ ...f, tags: f.tags.filter((x) => x !== t) }));

  const addSecondary = () => {
    if (!newSecondary.trim()) return;
    setForm((f) => ({
      ...f,
      secondary_addresses: [...f.secondary_addresses, newSecondary.trim()],
    }));
    setNewSecondary("");
  };
  const removeSecondary = (i) =>
    setForm((f) => ({
      ...f,
      secondary_addresses: f.secondary_addresses.filter((_, idx) => idx !== i),
    }));

  const submit = async (e) => {
    e.preventDefault();
    if (!form.name.trim()) {
      setToast({ tone: "error", message: "Name is required" });
      return;
    }
    // Phase 34d — pool_gallons: blank → null; else must be a plain integer 1..500000.
    let poolGallonsPayload = null;
    if (form.pool_gallons !== "" && form.pool_gallons != null) {
      const n = Number(form.pool_gallons);
      if (!Number.isInteger(n) || n < 1 || n > 500000) {
        setToast({
          tone: "error",
          message: "Pool volume must be a whole number between 1 and 500,000 gallons.",
        });
        return;
      }
      poolGallonsPayload = n;
    }
    setBusy(true);
    try {
      const doc = {
        ...form,
        email: (form.email || "").trim().toLowerCase(),
        pool_gallons: poolGallonsPayload,
        is_vip: !!form.is_vip,
      };
      const saved = isEdit
        ? await api.put(`/customers/${id}`, doc)
        : await api.post("/customers", doc);
      setToast({ tone: "success", message: isEdit ? "Customer updated" : "Customer created" });
      navigate(`/customers/${saved.id || id}`);
    } catch (err) {
      setToast({ tone: "error", message: err.message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-6" data-testid="customer-form-page">
      <button
        onClick={() => navigate(-1)}
        className="flex items-center gap-1 text-sm font-semibold mb-4"
        style={{ color: colors.muted }}
      >
        <ArrowLeft size={14} /> Back
      </button>
      <PageHeader
        title={isEdit ? "Edit Customer" : "New Customer"}
        subtitle="Contact info, alert channels, tags and waitlist state."
      />

      <form onSubmit={submit} className="space-y-4" data-testid="customer-form">
        <div
          className="rounded-2xl p-5 space-y-4"
          style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
        >
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <TextInput label="NAME *" id="name" value={form.name} onChange={set("name")} testid="cf-name" />
            <TextInput label="PRIMARY EMAIL" id="email" type="email" value={form.email} onChange={set("email")} testid="cf-email" />
            <TextInput label="PRIMARY PHONE" id="phone" value={form.phone} onChange={set("phone")} testid="cf-phone" />
            <TextInput label="GATE CODE" id="gate_code" value={form.gate_code} onChange={set("gate_code")} testid="cf-gate" />
            <TextInput label="ALERT EMAIL (after-hours)" id="alert_email" type="email" value={form.alert_email} onChange={set("alert_email")} testid="cf-alert-email" />
            <TextInput label="ALERT PHONE / SMS (after-hours)" id="alert_phone" value={form.alert_phone} onChange={set("alert_phone")} testid="cf-alert-phone" />
          </div>
          <div>
            <div className="text-xs font-semibold mb-1" style={{ color: colors.onSurfaceSecondary }}>PRIMARY ADDRESS</div>
            <AddressAutocomplete
              value={form.address}
              onChange={(v) => setForm((f) => ({ ...f, address: v }))}
              onSelect={(p) => setForm((f) => ({
                ...f, address: p.formatted, lat: p.lat, lng: p.lng,
                city: p.city, state: p.state, zip: p.zip, place_id: p.place_id,
              }))}
              placeholder="Primary service address"
              testid="cf-address"
            />
          </div>
          <TextInput label="BILLING ADDRESS" id="billing_address" value={form.billing_address} onChange={set("billing_address")} testid="cf-billing" />
          <div>
            <label
              className="text-xs font-semibold tracking-wide mb-1 block"
              style={{ color: colors.onSurfaceSecondary }}
              htmlFor="pool_gallons"
            >
              POOL VOLUME (GALLONS)
            </label>
            <input
              id="pool_gallons"
              type="number"
              inputMode="numeric"
              min={1}
              max={500000}
              step={1}
              value={form.pool_gallons}
              onChange={set("pool_gallons")}
              placeholder="e.g. 20000"
              className="w-full px-3.5 py-2.5 rounded-lg outline-none focus:ring-2 text-sm"
              style={{
                backgroundColor: colors.surface,
                color: colors.onSurface,
                border: `1px solid ${colors.border}`,
              }}
              data-testid="customer-pool-gallons-input"
            />
            <div className="text-xs mt-1" style={{ color: colors.muted }}>
              Used for chemical dosing recommendations. Leave blank if unknown.
            </div>
          </div>
        </div>

        {/* Tags */}
        <div
          className="rounded-2xl p-5"
          style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
        >
          <div className="text-xs font-semibold tracking-wide mb-2" style={{ color: colors.onSurfaceSecondary }}>
            TAGS
          </div>
          <div className="flex flex-wrap gap-2 mb-2" data-testid="cf-tags">
            {form.tags.map((t) => (
              <TagChip key={t} tag={t} onRemove={() => removeTag(t)} testid={`cf-tag-${t}`} />
            ))}
            {form.tags.length === 0 ? (
              <span className="text-xs" style={{ color: colors.muted }}>
                No tags. Add VIP, Specialty, or a custom label below.
              </span>
            ) : null}
          </div>
          <div className="flex gap-2 flex-wrap">
            {TAG_PRESETS.map((t) => (
              <Button
                key={t}
                variant="ghost"
                onClick={(e) => { e.preventDefault(); addTag(t); }}
                testid={`cf-preset-${t}`}
              >
                <Plus size={14} /> {t}
              </Button>
            ))}
            <div className="flex-1 flex gap-2 min-w-[220px]">
              <input
                value={newTag}
                onChange={(e) => setNewTag(e.target.value)}
                placeholder="Custom tag"
                className="flex-1 px-3 py-2 text-sm rounded-lg outline-none focus:ring-2"
                style={{
                  backgroundColor: colors.surfaceSecondary,
                  border: `1px solid ${colors.border}`,
                }}
                data-testid="cf-new-tag"
              />
              <Button
                variant="ghost"
                onClick={(e) => { e.preventDefault(); addTag(newTag.trim()); }}
                testid="cf-add-tag"
              >
                Add
              </Button>
            </div>
          </div>
        </div>

        {/* Secondary addresses */}
        <div
          className="rounded-2xl p-5"
          style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
        >
          <div className="text-xs font-semibold tracking-wide mb-2" style={{ color: colors.onSurfaceSecondary }}>
            SECONDARY ADDRESSES
          </div>
          <ul className="mb-2 space-y-1">
            {form.secondary_addresses.map((a, i) => (
              <li key={i} className="flex items-center gap-2 text-sm">
                <span className="flex-1">{a}</span>
                <button
                  onClick={(e) => { e.preventDefault(); removeSecondary(i); }}
                  style={{ color: colors.error }}
                  data-testid={`cf-remove-sec-${i}`}
                >
                  <X size={14} />
                </button>
              </li>
            ))}
          </ul>
          <div className="flex gap-2">
            <input
              value={newSecondary}
              onChange={(e) => setNewSecondary(e.target.value)}
              placeholder="Add another service address"
              className="flex-1 px-3 py-2 text-sm rounded-lg outline-none focus:ring-2"
              style={{
                backgroundColor: colors.surfaceSecondary,
                border: `1px solid ${colors.border}`,
              }}
              data-testid="cf-new-secondary"
            />
            <Button variant="ghost" onClick={(e) => { e.preventDefault(); addSecondary(); }}>
              <Plus size={14} /> Add
            </Button>
          </div>
        </div>

        {/* Notes + waitlist */}
        <div
          className="rounded-2xl p-5 space-y-3"
          style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
        >
          <div>
            <label className="text-xs font-semibold tracking-wide mb-1 block" style={{ color: colors.onSurfaceSecondary }}>
              NOTES
            </label>
            <textarea
              value={form.notes}
              onChange={set("notes")}
              rows={4}
              className="w-full px-3.5 py-2.5 rounded-lg outline-none focus:ring-2 text-sm"
              style={{
                backgroundColor: colors.surface,
                color: colors.onSurface,
                border: `1px solid ${colors.border}`,
              }}
              data-testid="cf-notes"
            />
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={form.waitlisted}
              onChange={set("waitlisted")}
              data-testid="cf-waitlist"
            />
            <span style={{ color: colors.onSurface }}>Add to waitlist (no scheduled visit)</span>
          </label>
          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              checked={!!form.is_vip}
              onChange={set("is_vip")}
              data-testid="customer-vip-toggle"
              className="mt-0.5"
            />
            <span>
              <span style={{ color: colors.onSurface, fontWeight: 600 }}>VIP customer</span>
              <span className="block text-xs" style={{ color: colors.muted }}>
                Highlights on tech routes and dispatch board.
              </span>
            </span>
          </label>
        </div>

        <div className="flex gap-2 justify-end pb-8">
          <Button variant="ghost" onClick={(e) => { e.preventDefault(); navigate(-1); }}>
            Cancel
          </Button>
          <Button type="submit" disabled={busy} testid="cf-submit">
            {busy ? "Saving…" : isEdit ? "Save changes" : "Create customer"}
          </Button>
        </div>
      </form>

      <Toast toast={toast} onClose={() => setToast(null)} />
    </div>
  );
}
