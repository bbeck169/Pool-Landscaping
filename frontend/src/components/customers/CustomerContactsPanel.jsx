import React, { useEffect, useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import { Button, TextInput } from "@/components/ui-kit";

/**
 * Phase 48 · Feb-2026 — Customer contact editor, redesigned to match
 * the user's mockup:
 *
 *   Email                  <primary email>
 *   Mobile Phone           <primary mobile>
 *   Home Phone             <landline>
 *
 *   Additional Mobile Phone up to 2
 *     <mobile 1>
 *     <mobile 2>
 *
 *   Additional Emails up to 3
 *     <email 1>
 *     <email 2>
 *     <email 3>
 *
 * Labels bold; input rows non-bold. Uses the existing `mobiles[]` /
 * `emails[]` array schema — index 0 is the primary (auto-flagged
 * ``is_primary=true`` on first insert), indices 1..n-1 render as
 * "additional" rows. ``home_phone`` is a scalar on the customer doc
 * (Phase 48 addition; see backend models.py).
 *
 * Persistence contract preserved: the panel still PATCHes
 *   /customers/{id}/mobiles  {mobiles: [...]}
 *   /customers/{id}/emails   {emails:  [...]}
 * and PATCHes ``home_phone`` via /customers/{id}. Save button appears
 * only when the panel is dirty.
 *
 * MAX_MOBILES = 3 (1 primary + 2 additional).
 * MAX_EMAILS  = 4 (1 primary + 3 additional).
 */
const MAX_MOBILES = 3;
const MAX_EMAILS = 4;
const MAX_ADDITIONAL_MOBILES = MAX_MOBILES - 1;
const MAX_ADDITIONAL_EMAILS = MAX_EMAILS - 1;

function _newMobile(isPrimary) {
  return {
    number_e164: "",
    label: isPrimary ? "Primary" : "Secondary",
    is_primary: !!isPrimary,
    sms_ok: true,
  };
}
function _newEmail(isPrimary) {
  return {
    address: "",
    label: isPrimary ? "Primary" : "Secondary",
    is_primary: !!isPrimary,
    marketing_ok: true,
  };
}

export function CustomerContactsPanel({ customer, onSaved, onError }) {
  const [mobiles, setMobiles] = useState([]);
  const [emails, setEmails] = useState([]);
  const [homePhone, setHomePhone] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    // Seed at least one row so the primary email / mobile inputs
    // always have a slot to write into. Existing docs with populated
    // arrays load as-is.
    const m = (customer?.mobiles && customer.mobiles.length)
      ? customer.mobiles : [_newMobile(true)];
    const e = (customer?.emails && customer.emails.length)
      ? customer.emails : [_newEmail(true)];
    setMobiles(m);
    setEmails(e);
    setHomePhone(customer?.home_phone || "");
  }, [customer?.id, customer?.mobiles, customer?.emails, customer?.home_phone]);

  const _updateMobile = (i, patch) => {
    setMobiles((m) => m.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));
  };
  const _updateEmail = (i, patch) => {
    setEmails((e) => e.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));
  };
  const addAdditionalMobile = () => {
    setMobiles((m) => {
      if (m.length >= MAX_MOBILES) return m;
      return [...m, _newMobile(false)];
    });
  };
  const addAdditionalEmail = () => {
    setEmails((e) => {
      if (e.length >= MAX_EMAILS) return e;
      return [...e, _newEmail(false)];
    });
  };
  const removeMobile = (i) => setMobiles((m) => m.filter((_, idx) => idx !== i));
  const removeEmail = (i) => setEmails((e) => e.filter((_, idx) => idx !== i));

  const save = async () => {
    setBusy(true);
    try {
      const cid = customer.id;
      // Always keep the first entry flagged as primary — the mockup
      // treats "Mobile Phone" / "Email" as the single primary slot.
      const normalize = (rows, keyed) => rows.map((r, idx) => ({
        ...r,
        is_primary: idx === 0,
      })).filter((r) => (r[keyed] || "").trim());
      const cleanMobiles = normalize(mobiles, "number_e164");
      const cleanEmails = normalize(emails, "address");
      await api.patch(`/customers/${cid}/mobiles`, { mobiles: cleanMobiles });
      await api.patch(`/customers/${cid}/emails`, { emails: cleanEmails });
      // home_phone rides on the base customer PATCH.
      const updated = await api.patch(`/customers/${cid}`, { home_phone: homePhone });
      onSaved?.(updated);
    } catch (e) {
      onError?.(e.message);
    } finally {
      setBusy(false);
    }
  };

  const dirty =
    JSON.stringify(mobiles) !== JSON.stringify(customer?.mobiles || (customer ? [_newMobile(true)] : [])) ||
    JSON.stringify(emails) !== JSON.stringify(customer?.emails || (customer ? [_newEmail(true)] : [])) ||
    (customer?.home_phone || "") !== homePhone;

  const primaryMobile = mobiles[0] || _newMobile(true);
  const primaryEmail = emails[0] || _newEmail(true);
  const additionalMobiles = mobiles.slice(1);
  const additionalEmails = emails.slice(1);

  return (
    <div
      className="rounded-xl p-4 space-y-5"
      style={{
        backgroundColor: colors.surfaceSecondary,
        border: `1px solid ${colors.border}`,
      }}
      data-testid="customer-contacts-panel"
    >
      {/* ── Primary contact group ─────────────────────────────────── */}
      <section
        className="grid grid-cols-1 md:grid-cols-[160px_1fr] gap-x-4 gap-y-3 items-center"
        data-testid="cd-primary-contact-group"
      >
        <label
          className="font-bold text-sm"
          style={{ color: colors.onSurface }}
          htmlFor="cd-primary-email"
        >
          Email
        </label>
        <TextInput
          id="cd-primary-email"
          label=""
          type="email"
          value={primaryEmail.address || ""}
          onChange={(e) => _updateEmail(0, { address: e.target.value })}
          placeholder="owner@example.com"
          testid="cd-primary-email"
        />

        <label
          className="font-bold text-sm"
          style={{ color: colors.onSurface }}
          htmlFor="cd-primary-mobile"
        >
          Mobile Phone
        </label>
        <TextInput
          id="cd-primary-mobile"
          label=""
          value={primaryMobile.number_e164 || ""}
          onChange={(e) => _updateMobile(0, { number_e164: e.target.value })}
          placeholder="+14805551234"
          testid="cd-primary-mobile"
        />

        <label
          className="font-bold text-sm"
          style={{ color: colors.onSurface }}
          htmlFor="cd-home-phone"
        >
          Home Phone
        </label>
        <TextInput
          id="cd-home-phone"
          label=""
          value={homePhone}
          onChange={(e) => setHomePhone(e.target.value)}
          placeholder="+14805559876"
          testid="cd-home-phone"
        />
      </section>

      {/* ── Additional mobiles ────────────────────────────────────── */}
      <section data-testid="cd-additional-mobiles-group">
        <div className="flex items-center justify-between mb-2">
          <div className="font-bold text-sm" style={{ color: colors.onSurface }}>
            Additional Mobile Phone up to {MAX_ADDITIONAL_MOBILES}
          </div>
          <Button
            variant="ghost"
            onClick={addAdditionalMobile}
            disabled={additionalMobiles.length >= MAX_ADDITIONAL_MOBILES}
            testid="cd-add-additional-mobile"
          >
            <Plus size={12} /> Add mobile
          </Button>
        </div>
        {additionalMobiles.length === 0 ? (
          <div
            className="text-sm"
            style={{ color: colors.muted }}
            data-testid="cd-additional-mobiles-empty"
          >
            No additional mobile lines yet.
          </div>
        ) : (
          <ul className="space-y-2">
            {additionalMobiles.map((m, idx) => {
              const absIdx = idx + 1;
              return (
                <li
                  key={absIdx}
                  className="flex items-center gap-2"
                  data-testid={`cd-additional-mobile-row-${idx}`}
                >
                  <div className="flex-1">
                    <TextInput
                      label=""
                      value={m.number_e164 || ""}
                      onChange={(e) => _updateMobile(absIdx, { number_e164: e.target.value })}
                      placeholder={`Mobile ${idx + 1}`}
                      testid={`cd-additional-mobile-${idx}`}
                    />
                  </div>
                  <button
                    onClick={() => removeMobile(absIdx)}
                    data-testid={`cd-additional-mobile-remove-${idx}`}
                    title="Remove this mobile"
                    className="p-1"
                  >
                    <Trash2 size={14} color={colors.danger} />
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      {/* ── Additional emails ────────────────────────────────────── */}
      <section data-testid="cd-additional-emails-group">
        <div className="flex items-center justify-between mb-2">
          <div className="font-bold text-sm" style={{ color: colors.onSurface }}>
            Additional Emails up to {MAX_ADDITIONAL_EMAILS}
          </div>
          <Button
            variant="ghost"
            onClick={addAdditionalEmail}
            disabled={additionalEmails.length >= MAX_ADDITIONAL_EMAILS}
            testid="cd-add-additional-email"
          >
            <Plus size={12} /> Add email
          </Button>
        </div>
        {additionalEmails.length === 0 ? (
          <div
            className="text-sm"
            style={{ color: colors.muted }}
            data-testid="cd-additional-emails-empty"
          >
            No additional email addresses yet.
          </div>
        ) : (
          <ul className="space-y-2">
            {additionalEmails.map((em, idx) => {
              const absIdx = idx + 1;
              return (
                <li
                  key={absIdx}
                  className="flex items-center gap-2"
                  data-testid={`cd-additional-email-row-${idx}`}
                >
                  <div className="flex-1">
                    <TextInput
                      label=""
                      type="email"
                      value={em.address || ""}
                      onChange={(e) => _updateEmail(absIdx, { address: e.target.value })}
                      placeholder={`Email ${idx + 1}`}
                      testid={`cd-additional-email-${idx}`}
                    />
                  </div>
                  <button
                    onClick={() => removeEmail(absIdx)}
                    data-testid={`cd-additional-email-remove-${idx}`}
                    title="Remove this email"
                    className="p-1"
                  >
                    <Trash2 size={14} color={colors.danger} />
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      {dirty ? (
        <div className="flex justify-end">
          <Button onClick={save} disabled={busy} testid="cd-contacts-save">
            {busy ? "Saving…" : "Save contacts"}
          </Button>
        </div>
      ) : null}
    </div>
  );
}

export default CustomerContactsPanel;
