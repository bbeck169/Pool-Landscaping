/**
 * Feb-2026 · Multi-Contact Phase 1 — customer contacts editor
 * + automations-mute toggle.
 *
 * Renders inside CustomerDetail as the "Contacts & preferences"
 * panel. Two responsibilities in one component so the render tree
 * and the admin action set stay clustered:
 *
 *   1. Multi-row editor for ``customer.emails`` (max 4) and
 *      ``customer.mobiles`` (max 4). Each row carries
 *      ``{address|number_e164, label}``. Save posts the full
 *      arrays via ``PATCH /api/customers/{cid}/emails`` +
 *      ``PATCH /api/customers/{cid}/mobiles``.
 *
 *   2. "Mute automations" toggle. Distinct from the existing
 *      ``is_muted`` control (which suppresses auto-scheduling).
 *      Two toggles, two badges — accepted trade-off per Multi-
 *      Contact Phase-1 decision 1B.
 *
 * Test-ids (per brief):
 *   customer-email-row-{i}, customer-email-input-{i},
 *   customer-email-label-{i}, customer-email-notifications-{i},
 *   customer-email-delete-{i}, customer-email-add-btn
 *   (mirrored for mobiles)
 *   customer-mute-automations-toggle, customer-mute-reason-input,
 *   customer-muted-badge, customer-muted-banner
 */
import React, { useMemo, useState } from "react";
import { toast } from "sonner";
import { api } from "@/api";

const MAX_ENTRIES = 4;

function _blankEmail() { return { address: "", label: "primary",
                                    notifications_enabled: true }; }
function _blankMobile() { return { number_e164: "", label: "primary",
                                      notifications_enabled: true }; }

function _hasDupes(rows, key) {
  const seen = new Set();
  for (const r of rows) {
    const k = String(r?.[key] || "").trim().toLowerCase();
    if (!k) continue;
    if (seen.has(k)) return true;
    seen.add(k);
  }
  return false;
}


function ContactEditor({
  title, testidPrefix, rows, setRows, addressField,
  placeholder, kind,
}) {
  const atCap = rows.length >= MAX_ENTRIES;
  const dupes = _hasDupes(rows, addressField);
  return (
    <div data-testid={`${testidPrefix}-editor`}
         className="border rounded p-3 mb-3"
         style={{ borderColor: "#E2E8F0", background: "#F8FAFC" }}>
      <div className="flex items-center justify-between mb-2">
        <div className="text-xs font-bold uppercase tracking-wide"
             style={{ color: "#64748B" }}>{title}</div>
        <div className="text-[10px]" style={{ color: "#64748B" }}>
          {rows.length} of {MAX_ENTRIES}
        </div>
      </div>
      {rows.map((row, i) => (
        <div key={i} className="flex items-center gap-2 mb-2"
             data-testid={`${testidPrefix}-row-${i}`}>
          <input
            type={kind === "email" ? "email" : "tel"}
            className="flex-1 border rounded px-2 py-1 text-sm"
            style={{ borderColor: "#CBD5E1" }}
            placeholder={placeholder}
            value={row[addressField] || ""}
            onChange={(e) => {
              const next = [...rows];
              next[i] = { ...next[i], [addressField]: e.target.value };
              setRows(next);
            }}
            data-testid={`${testidPrefix}-input-${i}`}
          />
          <input
            className="w-28 border rounded px-2 py-1 text-sm"
            style={{ borderColor: "#CBD5E1" }}
            placeholder="Label"
            value={row.label || ""}
            onChange={(e) => {
              const next = [...rows];
              next[i] = { ...next[i], label: e.target.value };
              setRows(next);
            }}
            data-testid={`${testidPrefix}-label-${i}`}
          />
          <label className="flex items-center gap-1 text-xs"
                 style={{ color: "#334155" }}>
            <input
              type="checkbox"
              checked={row.notifications_enabled !== false}
              onChange={(e) => {
                const next = [...rows];
                next[i] = { ...next[i],
                             notifications_enabled: e.target.checked };
                setRows(next);
              }}
              data-testid={`${testidPrefix}-notifications-${i}`}
            />
            notify
          </label>
          <button
            type="button"
            onClick={() => setRows(rows.filter((_, j) => j !== i))}
            className="text-xs px-2 py-1 rounded"
            style={{ background: "#FEE2E2", color: "#991B1B",
                     border: 0, cursor: "pointer" }}
            data-testid={`${testidPrefix}-delete-${i}`}
            aria-label={`Delete row ${i + 1}`}
          >
            ×
          </button>
        </div>
      ))}
      <button
        type="button"
        disabled={atCap}
        onClick={() => setRows([...rows,
          kind === "email" ? _blankEmail() : _blankMobile()])}
        className="text-xs font-semibold px-3 py-1 rounded"
        style={{ background: atCap ? "#E2E8F0" : "#0EA5E9",
                 color: atCap ? "#94A3B8" : "#fff",
                 border: 0,
                 cursor: atCap ? "not-allowed" : "pointer" }}
        data-testid={`${testidPrefix}-add-btn`}
      >
        + Add {kind === "email" ? "email" : "mobile"}
      </button>
      {dupes ? (
        <div className="text-xs mt-2" style={{ color: "#B91C1C" }}
             data-testid={`${testidPrefix}-dupe-error`}>
          Duplicate {kind === "email" ? "address" : "number"} — remove or edit.
        </div>
      ) : null}
    </div>
  );
}


function AutomationsMuteBanner({ customer }) {
  if (!customer?.automations_muted) return null;
  const at = customer.automations_muted_at || "";
  const by = customer.automations_muted_by || "";
  const reason = customer.automations_muted_reason || "";
  return (
    <div
      data-testid="customer-muted-banner"
      className="rounded p-2 mb-3 text-sm"
      style={{ background: "#FEF3C7", color: "#78350F",
                border: "1px solid #FCD34D" }}
      title={`reason=${reason} · muted_at=${at} · muted_by=${by}`}
    >
      <span data-testid="customer-muted-badge"
            className="inline-block px-2 py-0.5 rounded text-xs font-bold uppercase mr-2"
            style={{ background: "#B45309", color: "#fff" }}>
        Automations muted
      </span>
      {reason ? <span>· {reason}</span> : null}
    </div>
  );
}


export default function CustomerMultiContactEditor({
  customer, isAdmin, onRefresh,
}) {
  const [emails, setEmails] = useState(
    () => (Array.isArray(customer?.emails) ? customer.emails.slice(0, MAX_ENTRIES)
                                              : []),
  );
  const [mobiles, setMobiles] = useState(
    () => (Array.isArray(customer?.mobiles) ? customer.mobiles.slice(0, MAX_ENTRIES)
                                                : []),
  );
  const [savingContacts, setSavingContacts] = useState(false);
  const [savingMute, setSavingMute] = useState(false);
  const [muteReason, setMuteReason] = useState("");
  const [showMutePrompt, setShowMutePrompt] = useState(false);

  const cid = customer?.id;
  const dupesExist = _hasDupes(emails, "address") ||
                       _hasDupes(mobiles, "number_e164");

  const saveContacts = async () => {
    if (dupesExist) {
      toast.error("Remove duplicate contacts before saving.");
      return;
    }
    setSavingContacts(true);
    try {
      // Two separate PATCH endpoints — mirrors existing routes.
      await api.patch(`/customers/${cid}/emails`, { emails });
      await api.patch(`/customers/${cid}/mobiles`, { mobiles });
      toast.success("Contacts saved.");
      onRefresh?.();
    } catch (e) {
      toast.error(e?.message || "Save failed.");
    } finally {
      setSavingContacts(false);
    }
  };

  const doToggleMute = async (nextMuted, reason) => {
    setSavingMute(true);
    try {
      const body = { muted: nextMuted };
      if (nextMuted && reason) body.reason = reason;
      await api.patch(`/customers/${cid}/mute-automations`, body);
      toast.success(nextMuted ? "Automations muted." : "Automations unmuted.");
      setShowMutePrompt(false);
      setMuteReason("");
      onRefresh?.();
    } catch (e) {
      toast.error(e?.message || "Update failed.");
    } finally {
      setSavingMute(false);
    }
  };

  const isMutedNow = Boolean(customer?.automations_muted);

  return (
    <div data-testid="customer-multi-contact-panel" className="mb-4">
      <AutomationsMuteBanner customer={customer} />
      <ContactEditor
        title="Emails"
        testidPrefix="customer-email"
        rows={emails} setRows={setEmails}
        addressField="address"
        placeholder="name@example.com"
        kind="email"
      />
      <ContactEditor
        title="Mobiles"
        testidPrefix="customer-mobile"
        rows={mobiles} setRows={setMobiles}
        addressField="number_e164"
        placeholder="+15551234567"
        kind="mobile"
      />
      <div className="flex items-center gap-3 mt-2">
        <button
          type="button"
          disabled={savingContacts || dupesExist}
          onClick={saveContacts}
          className="text-sm font-semibold px-4 py-1.5 rounded"
          style={{ background: "#059669", color: "#fff", border: 0,
                   cursor: (savingContacts || dupesExist) ? "not-allowed" : "pointer",
                   opacity: dupesExist ? 0.6 : 1 }}
          data-testid="customer-contacts-save-btn"
        >
          {savingContacts ? "Saving…" : "Save contacts"}
        </button>
        {isAdmin ? (
          <>
            <label className="flex items-center gap-2 text-sm"
                   style={{ color: "#334155" }}>
              <input
                type="checkbox"
                checked={isMutedNow}
                disabled={savingMute}
                onChange={(e) => {
                  if (e.target.checked) {
                    setShowMutePrompt(true);
                  } else {
                    doToggleMute(false, null);
                  }
                }}
                data-testid="customer-mute-automations-toggle"
              />
              Mute all automated emails &amp; SMS
            </label>
          </>
        ) : null}
      </div>
      {showMutePrompt ? (
        <div className="rounded p-3 mt-2"
             style={{ background: "#FFFBEB",
                       border: "1px solid #FCD34D" }}>
          <div className="text-xs mb-1" style={{ color: "#78350F" }}>
            Optional reason (visible in audit log)
          </div>
          <input
            className="w-full border rounded px-2 py-1 text-sm mb-2"
            style={{ borderColor: "#CBD5E1" }}
            placeholder="e.g. Customer requested via phone 2026-09-11"
            value={muteReason}
            onChange={(e) => setMuteReason(e.target.value)}
            data-testid="customer-mute-reason-input"
          />
          <div className="flex gap-2">
            <button
              type="button"
              disabled={savingMute}
              onClick={() => doToggleMute(true, muteReason || null)}
              className="text-xs font-semibold px-3 py-1 rounded"
              style={{ background: "#B45309", color: "#fff", border: 0,
                       cursor: "pointer" }}
              data-testid="customer-mute-confirm-btn"
            >
              Mute
            </button>
            <button
              type="button"
              onClick={() => { setShowMutePrompt(false); setMuteReason(""); }}
              className="text-xs px-3 py-1 rounded"
              style={{ background: "#E2E8F0", color: "#334155",
                       border: 0, cursor: "pointer" }}
              data-testid="customer-mute-cancel-btn"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
