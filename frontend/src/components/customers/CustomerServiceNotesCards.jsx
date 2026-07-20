import React, { useEffect, useState } from "react";
import { Droplets, Trees, ChevronDown, ChevronUp, Save } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import { Button } from "@/components/ui-kit";

/**
 * Two collapsible service-note cards — Pool + Landscape.
 * Feb-2026 service-notes ship.
 *
 * Admin edits inline via PATCH /customers/{cid}/service-notes.
 * Partial payload means the untouched side is preserved server-side.
 * Techs render read-only via ScheduleServiceNotePreview elsewhere.
 */
export function CustomerServiceNotesCards({ customer, onSaved, onError }) {
  const [pool, setPool] = useState(customer?.service_notes?.pool || "");
  const [landscape, setLandscape] = useState(customer?.service_notes?.landscape || "");
  const [poolOpen, setPoolOpen] = useState(true);
  const [landscapeOpen, setLandscapeOpen] = useState(true);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setPool(customer?.service_notes?.pool || "");
    setLandscape(customer?.service_notes?.landscape || "");
  }, [customer?.id, customer?.service_notes]);

  const savePool = async () => {
    setBusy(true);
    try {
      const r = await api.patch(`/customers/${customer.id}/service-notes`, {
        pool: pool || null,
      });
      onSaved?.({ ...customer, service_notes: r.service_notes });
    } catch (e) {
      onError?.(e.message);
    } finally {
      setBusy(false);
    }
  };
  const saveLandscape = async () => {
    setBusy(true);
    try {
      const r = await api.patch(`/customers/${customer.id}/service-notes`, {
        landscape: landscape || null,
      });
      onSaved?.({ ...customer, service_notes: r.service_notes });
    } catch (e) {
      onError?.(e.message);
    } finally {
      setBusy(false);
    }
  };

  const poolDirty = (customer?.service_notes?.pool || "") !== pool;
  const landscapeDirty = (customer?.service_notes?.landscape || "") !== landscape;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4" data-testid="customer-service-notes">
      <ServiceNoteCard
        title="Pool Service Notes"
        accent="#0EA5E9"
        Icon={Droplets}
        open={poolOpen}
        toggle={() => setPoolOpen((o) => !o)}
        value={pool}
        setValue={setPool}
        onSave={savePool}
        dirty={poolDirty}
        busy={busy}
        placeholder="e.g. Chemistry notes, equipment quirks, service preferences…"
        testidPrefix="cd-svcnote-pool"
      />
      <ServiceNoteCard
        title="Landscape Service Notes"
        accent="#22C55E"
        Icon={Trees}
        open={landscapeOpen}
        toggle={() => setLandscapeOpen((o) => !o)}
        value={landscape}
        setValue={setLandscape}
        onSave={saveLandscape}
        dirty={landscapeDirty}
        busy={busy}
        placeholder="e.g. Fence gate on side, watering restrictions, HOA rules…"
        testidPrefix="cd-svcnote-landscape"
      />
    </div>
  );
}

function ServiceNoteCard({
  title, accent, Icon, open, toggle, value, setValue,
  onSave, dirty, busy, placeholder, testidPrefix,
}) {
  return (
    <div
      className="rounded-xl overflow-hidden"
      style={{
        backgroundColor: colors.surface,
        border: `1px solid ${colors.border}`,
        borderLeft: `4px solid ${accent}`,
      }}
      data-testid={testidPrefix}
    >
      <button
        onClick={toggle}
        className="w-full flex items-center justify-between px-4 py-3"
        style={{ backgroundColor: colors.surfaceSecondary }}
        data-testid={`${testidPrefix}-toggle`}
      >
        <div className="flex items-center gap-2">
          <Icon size={16} color={accent} />
          <span className="text-sm font-semibold" style={{ color: colors.onSurface }}>
            {title}
          </span>
          {dirty ? (
            <span
              className="px-1.5 py-0.5 rounded-full text-[10px] font-bold uppercase"
              style={{ backgroundColor: "#FEF3C7", color: "#92400E" }}
            >
              Unsaved
            </span>
          ) : null}
        </div>
        {open ? (
          <ChevronUp size={14} color={colors.muted} />
        ) : (
          <ChevronDown size={14} color={colors.muted} />
        )}
      </button>
      {open ? (
        <div className="p-4 space-y-3">
          <textarea
            className="w-full min-h-[140px] px-3 py-2 rounded-lg text-sm"
            style={{
              backgroundColor: colors.surface,
              color: colors.onSurface,
              border: `1px solid ${colors.border}`,
            }}
            placeholder={placeholder}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            maxLength={5000}
            data-testid={`${testidPrefix}-textarea`}
          />
          <div className="flex items-center justify-between">
            <div className="text-xs" style={{ color: colors.muted }}>
              {value.length} / 5000
            </div>
            <Button
              onClick={onSave}
              disabled={!dirty || busy}
              testid={`${testidPrefix}-save`}
            >
              <Save size={12} /> {busy ? "Saving…" : "Save"}
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export default CustomerServiceNotesCards;
