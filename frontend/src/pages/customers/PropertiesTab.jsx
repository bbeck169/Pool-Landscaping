/**
 * MP2 UI — Properties tab on the Customer detail page (Feb-2026 ship).
 *
 * Renders a grid of property cards for a single customer with:
 *   - "+ Add Property" button (disabled + tooltip when at the 8-cap)
 *   - Per-card actions: Edit / Duplicate / Delete (soft, guarded)
 *   - Drag-to-reorder (native HTML5 dnd — persisted via
 *     POST /api/properties/reorder)
 *   - Click the card → opens the PropertyDrawer with 5 tabs
 *     (Info | Contact | Service Notes | Photos | Schedule)
 *
 * All admin-only. RBAC is enforced at the router level; this tab is
 * only rendered from within CustomerDetail whose caller is admin.
 */
import React from "react";
import { Plus, Copy, Trash2, GripVertical, Home, Users, Calendar } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import { Button, Chip, EmptyState, Modal, TextInput } from "@/components/ui-kit";
import PropertyDrawer from "./PropertyDrawer";

const MAX_PROPERTIES = 8;

function formatAddress(addr) {
  if (!addr) return "";
  const parts = [addr.line1, addr.city, addr.state, addr.postal_code].filter(Boolean);
  return parts.join(", ");
}

export default function PropertiesTab({ customer, onToast, onRefreshCustomer }) {
  const [rows, setRows] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [addOpen, setAddOpen] = React.useState(false);
  const [drawerId, setDrawerId] = React.useState(null);
  const [pendingDeleteId, setPendingDeleteId] = React.useState(null);

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.get(`/customers/${customer.id}/properties`);
      setRows(r || []);
    } catch (e) {
      onToast?.({ tone: "error", message: e.message });
    } finally {
      setLoading(false);
    }
  }, [customer.id, onToast]);

  React.useEffect(() => { load(); }, [load]);

  const active = rows.filter((r) => r.active !== false);
  const atCap = active.length >= MAX_PROPERTIES;

  const persistOrder = async (ordered) => {
    try {
      await api.post("/properties/reorder", {
        customer_id: customer.id,
        ordered_property_ids: ordered.map((r) => r.id),
      });
      onRefreshCustomer?.();
    } catch (e) {
      onToast?.({ tone: "error", message: `Reorder failed: ${e.message}` });
      // Roll back — reload from server.
      await load();
    }
  };

  const [dragId, setDragId] = React.useState(null);
  const onCardDragStart = (id) => (e) => {
    setDragId(id);
    e.dataTransfer.effectAllowed = "move";
  };
  const onCardDragOver = (targetId) => (e) => {
    e.preventDefault();
    if (!dragId || dragId === targetId) return;
    const next = [...active];
    const from = next.findIndex((r) => r.id === dragId);
    const to = next.findIndex((r) => r.id === targetId);
    if (from < 0 || to < 0) return;
    const [moved] = next.splice(from, 1);
    next.splice(to, 0, moved);
    // Merge inactive rows back for state consistency.
    const inactive = rows.filter((r) => r.active === false);
    setRows([...next, ...inactive]);
  };
  const onCardDragEnd = async () => {
    if (dragId) {
      setDragId(null);
      await persistOrder(active);
    }
  };

  const duplicate = async (pid) => {
    try {
      await api.post(`/properties/${pid}/duplicate`);
      onToast?.({ tone: "success", message: "Property duplicated" });
      await load();
    } catch (e) {
      onToast?.({ tone: "error", message: e.message });
    }
  };

  const doDelete = async (pid) => {
    try {
      await api.del(`/properties/${pid}`);
      onToast?.({ tone: "success", message: "Property removed" });
      setPendingDeleteId(null);
      await load();
    } catch (e) {
      // Backend returns 400 with "open job(s)" message when jobs are pending.
      onToast?.({ tone: "error", message: e.message });
      setPendingDeleteId(null);
    }
  };

  if (loading) {
    return (
      <div className="text-sm" style={{ color: colors.onSurfaceSecondary }} data-testid="props-loading">
        Loading properties…
      </div>
    );
  }

  return (
    <div className="space-y-4" data-testid="properties-tab">
      <header className="flex items-center justify-between">
        <div>
          <div className="text-lg font-bold" style={{ color: colors.onSurface }}>
            Properties
          </div>
          <div className="text-xs" style={{ color: colors.onSurfaceSecondary }} data-testid="props-count">
            {active.length} of {MAX_PROPERTIES} active
          </div>
        </div>
        <div title={atCap ? `Max ${MAX_PROPERTIES} active properties per customer` : undefined}>
          <Button
            onClick={() => setAddOpen(true)}
            disabled={atCap}
            testid="props-add-button"
          >
            <Plus size={14} /> Add Property
          </Button>
        </div>
      </header>

      {active.length === 0 ? (
        <EmptyState
          title="No properties yet"
          hint="Add a property to bill and route jobs to a specific address."
          action={<Button onClick={() => setAddOpen(true)} testid="props-add-empty-cta">Add first property</Button>}
        />
      ) : (
        <ul
          className="grid grid-cols-1 md:grid-cols-2 gap-3"
          data-testid="props-grid"
        >
          {active.map((p) => (
            <PropertyCard
              key={p.id}
              property={p}
              onOpen={() => setDrawerId(p.id)}
              onDuplicate={() => duplicate(p.id)}
              onDeleteAsk={() => setPendingDeleteId(p.id)}
              draggable
              onDragStart={onCardDragStart(p.id)}
              onDragOver={onCardDragOver(p.id)}
              onDragEnd={onCardDragEnd}
            />
          ))}
        </ul>
      )}

      <PropertyEditModal
        open={addOpen}
        onClose={() => setAddOpen(false)}
        customer={customer}
        onSaved={async () => {
          setAddOpen(false);
          onToast?.({ tone: "success", message: "Property added" });
          await load();
        }}
        onError={(m) => onToast?.({ tone: "error", message: m })}
      />

      <PropertyDrawer
        propertyId={drawerId}
        onClose={() => setDrawerId(null)}
        onChanged={load}
        onToast={onToast}
      />

      <Modal
        open={!!pendingDeleteId}
        onClose={() => setPendingDeleteId(null)}
        title="Remove property?"
        footer={
          <>
            <Button variant="ghost" onClick={() => setPendingDeleteId(null)}>Cancel</Button>
            <Button
              variant="danger"
              onClick={() => doDelete(pendingDeleteId)}
              testid="props-delete-confirm"
            >
              Remove
            </Button>
          </>
        }
      >
        <p className="text-sm" style={{ color: colors.onSurface }}>
          The property is soft-deleted and hidden from routing. If any jobs are
          still open on this property, the delete is refused with an
          error you'll see in the toast.
        </p>
      </Modal>
    </div>
  );
}

function PropertyCard({ property, onOpen, onDuplicate, onDeleteAsk, draggable, onDragStart, onDragOver, onDragEnd }) {
  const contact = property.site_contact || {};
  const primaryPhone = (contact.mobiles || []).find((m) => m.is_primary)?.number_e164;
  const primaryEmail = (contact.emails || []).find((e) => e.is_primary)?.address;
  const svcTypes = property.service_types || [];
  const notes = property.service_notes || {};
  const photoCount = (property.photo_urls || []).length;

  return (
    <li
      className="rounded-2xl p-4 flex flex-col gap-2 transition hover:brightness-95 cursor-pointer"
      style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      draggable={draggable}
      onDragStart={onDragStart}
      onDragOver={onDragOver}
      onDragEnd={onDragEnd}
      onClick={onOpen}
      data-testid={`property-card-${property.id}`}
    >
      <div className="flex items-start gap-2">
        <GripVertical size={16} style={{ color: colors.muted, marginTop: 2, cursor: "grab" }} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <div className="text-sm font-semibold" style={{ color: colors.onSurface }} data-testid="pc-label">
              {property.label || "Property"}
            </div>
            {property.sort_order === 0 ? (
              <Chip label="Primary" tone="brand" testid={`pc-primary-${property.id}`} />
            ) : null}
            {property.backfilled_from_customer ? (
              <Chip label="Auto-seeded" tone="neutral" />
            ) : null}
          </div>
          <div className="text-xs mt-0.5" style={{ color: colors.onSurfaceSecondary }} data-testid="pc-address">
            {formatAddress(property.address)}
          </div>
        </div>
        <div className="flex gap-1" onClick={(e) => e.stopPropagation()}>
          <button
            onClick={onDuplicate}
            className="p-1 rounded hover:brightness-90"
            style={{ color: colors.muted }}
            title="Duplicate"
            data-testid={`pc-dup-${property.id}`}
          >
            <Copy size={14} />
          </button>
          <button
            onClick={onDeleteAsk}
            className="p-1 rounded hover:brightness-90"
            style={{ color: colors.danger }}
            title="Delete"
            data-testid={`pc-del-${property.id}`}
          >
            <Trash2 size={14} />
          </button>
        </div>
      </div>

      <div className="flex flex-wrap gap-1 mt-1">
        {svcTypes.map((s) => (
          <Chip key={s} label={s} tone="brandTertiary" />
        ))}
        {property.pool_size_gallons ? (
          <Chip label={`${property.pool_size_gallons.toLocaleString()} gal`} tone="neutral" />
        ) : null}
        {property.landscape_sq_ft ? (
          <Chip label={`${property.landscape_sq_ft.toLocaleString()} sq ft`} tone="neutral" />
        ) : null}
      </div>

      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs mt-1" style={{ color: colors.onSurfaceSecondary }}>
        <div className="flex items-center gap-1"><Users size={12} /> {contact.name || primaryEmail || "—"}</div>
        <div className="flex items-center gap-1"><Home size={12} /> {property.assigned_technician_id ? "Tech assigned" : "Unassigned"}</div>
        <div>Pool note: {notes.pool ? "✓" : "—"}</div>
        <div>Landscape note: {notes.landscape ? "✓" : "—"}</div>
        <div className="flex items-center gap-1"><Calendar size={12} /> {photoCount} photo{photoCount === 1 ? "" : "s"}</div>
        {primaryPhone ? <div>{primaryPhone}</div> : null}
      </div>
    </li>
  );
}

function PropertyEditModal({ open, onClose, customer, existing, onSaved, onError }) {
  const [form, setForm] = React.useState({
    label: "", line1: "", city: "", state: "", postal_code: "",
    pool_size_gallons: "", landscape_sq_ft: "", pool_type: "",
    service_types: [], site_name: "", site_phone: "", site_email: "",
  });
  React.useEffect(() => {
    if (!open) return;
    if (existing) {
      const contact = existing.site_contact || {};
      setForm({
        label: existing.label || "",
        line1: existing.address?.line1 || "",
        city: existing.address?.city || "",
        state: existing.address?.state || "",
        postal_code: existing.address?.postal_code || "",
        pool_size_gallons: existing.pool_size_gallons || "",
        landscape_sq_ft: existing.landscape_sq_ft || "",
        pool_type: existing.pool_type || "",
        service_types: existing.service_types || [],
        site_name: contact.name || "",
        site_phone: (contact.mobiles || []).find((m) => m.is_primary)?.number_e164 || "",
        site_email: (contact.emails || []).find((e) => e.is_primary)?.address || "",
      });
    } else {
      setForm({
        label: "", line1: "", city: customer?.city || "", state: customer?.state || "",
        postal_code: customer?.postal_code || "", pool_size_gallons: "",
        landscape_sq_ft: "", pool_type: "", service_types: [],
        site_name: "", site_phone: "", site_email: "",
      });
    }
  }, [open, existing, customer]);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const toggleService = (s) => setForm((f) => ({
    ...f,
    service_types: f.service_types.includes(s)
      ? f.service_types.filter((x) => x !== s)
      : [...f.service_types, s],
  }));

  const submit = async () => {
    try {
      const payload = {
        label: form.label,
        address: {
          line1: form.line1,
          city: form.city,
          state: form.state,
          postal_code: form.postal_code,
        },
        pool_size_gallons: form.pool_size_gallons ? Number(form.pool_size_gallons) : null,
        landscape_sq_ft: form.landscape_sq_ft ? Number(form.landscape_sq_ft) : null,
        pool_type: form.pool_type || null,
        service_types: form.service_types,
        site_contact: {
          name: form.site_name || null,
          emails: form.site_email ? [{ address: form.site_email, is_primary: true, label: "Primary" }] : [],
          mobiles: form.site_phone ? [{ number_e164: form.site_phone, is_primary: true, label: "Primary" }] : [],
          is_primary_contact: true,
        },
      };
      if (existing) {
        await api.patch(`/properties/${existing.id}`, payload);
      } else {
        await api.post(`/customers/${customer.id}/properties`, payload);
      }
      onSaved();
    } catch (e) {
      onError(e.message);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={existing ? `Edit ${existing.label || "property"}` : "Add property"}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button onClick={submit} disabled={!form.label || !form.line1} testid="props-edit-submit">
            {existing ? "Save" : "Add property"}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <TextInput label="LABEL *" value={form.label} onChange={set("label")} placeholder="Main house, Rental, Vacation home…" testid="pf-label" />
        <TextInput label="STREET *" value={form.line1} onChange={set("line1")} testid="pf-line1" />
        <div className="grid grid-cols-3 gap-2">
          <TextInput label="CITY" value={form.city} onChange={set("city")} testid="pf-city" />
          <TextInput label="STATE" value={form.state} onChange={set("state")} testid="pf-state" />
          <TextInput label="POSTAL" value={form.postal_code} onChange={set("postal_code")} testid="pf-postal" />
        </div>
        <div className="grid grid-cols-2 gap-2">
          <TextInput label="POOL SIZE (GAL)" type="number" value={form.pool_size_gallons} onChange={set("pool_size_gallons")} testid="pf-pool-size" />
          <TextInput label="LANDSCAPE (SQ FT)" type="number" value={form.landscape_sq_ft} onChange={set("landscape_sq_ft")} testid="pf-landscape" />
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
                data-testid={`pf-svc-${s}`}
              >
                {s}
              </button>
            ))}
          </div>
        </div>
        <div className="pt-2" style={{ borderTop: `1px solid ${colors.border}` }}>
          <div className="text-xs uppercase font-semibold mb-2" style={{ color: colors.muted }}>
            On-site contact (optional)
          </div>
          <TextInput label="NAME" value={form.site_name} onChange={set("site_name")} testid="pf-site-name" />
          <div className="grid grid-cols-2 gap-2 mt-2">
            <TextInput label="PHONE" value={form.site_phone} onChange={set("site_phone")} placeholder="+15551234567" testid="pf-site-phone" />
            <TextInput label="EMAIL" value={form.site_email} onChange={set("site_email")} testid="pf-site-email" />
          </div>
        </div>
      </div>
    </Modal>
  );
}
