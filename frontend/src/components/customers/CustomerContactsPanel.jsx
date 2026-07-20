import React, { useEffect, useState } from "react";
import { Plus, Trash2, Star } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import { Button, TextInput } from "@/components/ui-kit";

/**
 * Multi-contact editor rendered inside the Customer detail Overview tab.
 * Feb-2026 Customer Detail Additions ship.
 *
 * Supports up to 2 mobiles + 3 emails per customer, each row carrying a
 * label, is_primary radio, and consent flag (sms_ok / marketing_ok).
 * Saves are debounced to a single PATCH per collection whenever the
 * user clicks "Save contacts" so the wire chatter stays low.
 */
export function CustomerContactsPanel({ customer, onSaved, onError }) {
  const [mobiles, setMobiles] = useState([]);
  const [emails, setEmails] = useState([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setMobiles(customer?.mobiles || []);
    setEmails(customer?.emails || []);
  }, [customer?.id, customer?.mobiles, customer?.emails]);

  const MAX_MOBILES = 2;
  const MAX_EMAILS = 3;

  const addMobile = () => {
    if (mobiles.length >= MAX_MOBILES) return;
    setMobiles((m) => [
      ...m,
      {
        number_e164: "",
        label: m.length === 0 ? "Primary" : "Secondary",
        is_primary: m.length === 0,
        sms_ok: true,
      },
    ]);
  };
  const updateMobile = (i, patch) => {
    setMobiles((m) => {
      const next = m.map((r, idx) => (idx === i ? { ...r, ...patch } : r));
      // Radio semantics for is_primary — only one true.
      if (patch.is_primary) {
        return next.map((r, idx) => ({ ...r, is_primary: idx === i }));
      }
      return next;
    });
  };
  const removeMobile = (i) => setMobiles((m) => m.filter((_, idx) => idx !== i));

  const addEmail = () => {
    if (emails.length >= MAX_EMAILS) return;
    setEmails((e) => [
      ...e,
      {
        address: "",
        label: e.length === 0 ? "Primary" : "Secondary",
        is_primary: e.length === 0,
        marketing_ok: true,
      },
    ]);
  };
  const updateEmail = (i, patch) => {
    setEmails((e) => {
      const next = e.map((r, idx) => (idx === i ? { ...r, ...patch } : r));
      if (patch.is_primary) {
        return next.map((r, idx) => ({ ...r, is_primary: idx === i }));
      }
      return next;
    });
  };
  const removeEmail = (i) => setEmails((e) => e.filter((_, idx) => idx !== i));

  const save = async () => {
    setBusy(true);
    try {
      const cid = customer.id;
      const cleanMobiles = mobiles.filter((m) => (m.number_e164 || "").trim());
      const cleanEmails = emails.filter((e) => (e.address || "").trim());
      await api.patch(`/customers/${cid}/mobiles`, { mobiles: cleanMobiles });
      const updated = await api.patch(`/customers/${cid}/emails`, {
        emails: cleanEmails,
      });
      onSaved?.(updated);
    } catch (e) {
      onError?.(e.message);
    } finally {
      setBusy(false);
    }
  };

  const dirty =
    JSON.stringify(mobiles) !== JSON.stringify(customer?.mobiles || []) ||
    JSON.stringify(emails) !== JSON.stringify(customer?.emails || []);

  return (
    <div
      className="rounded-xl p-4 space-y-4"
      style={{
        backgroundColor: colors.surfaceSecondary,
        border: `1px solid ${colors.border}`,
      }}
      data-testid="customer-contacts-panel"
    >
      {/* Mobiles */}
      <section>
        <div className="flex items-center justify-between mb-2">
          <div className="text-xs uppercase font-semibold" style={{ color: colors.muted }}>
            Mobile phones ({mobiles.length}/{MAX_MOBILES})
          </div>
          <Button
            variant="ghost"
            onClick={addMobile}
            disabled={mobiles.length >= MAX_MOBILES}
            testid="cd-add-mobile"
          >
            <Plus size={12} /> Add mobile
          </Button>
        </div>
        {mobiles.length === 0 ? (
          <div className="text-sm" style={{ color: colors.muted }}>
            No mobiles on file.
          </div>
        ) : (
          <ul className="space-y-2">
            {mobiles.map((m, i) => (
              <li
                key={i}
                className="grid grid-cols-1 md:grid-cols-6 gap-2 items-center p-2 rounded-lg"
                style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
                data-testid={`cd-mobile-row-${i}`}
              >
                <div className="md:col-span-2">
                  <TextInput
                    label=""
                    value={m.number_e164 || ""}
                    onChange={(e) => updateMobile(i, { number_e164: e.target.value })}
                    placeholder="+14805551234"
                    testid={`cd-mobile-number-${i}`}
                  />
                </div>
                <div className="md:col-span-2">
                  <TextInput
                    label=""
                    value={m.label || ""}
                    onChange={(e) => updateMobile(i, { label: e.target.value })}
                    placeholder="Label (Primary / Secondary / …)"
                    testid={`cd-mobile-label-${i}`}
                  />
                </div>
                <label className="inline-flex items-center gap-1 text-xs" style={{ color: colors.onSurface }}>
                  <input
                    type="radio"
                    checked={!!m.is_primary}
                    onChange={() => updateMobile(i, { is_primary: true })}
                    data-testid={`cd-mobile-primary-${i}`}
                  />
                  <Star size={12} color={m.is_primary ? "#F59E0B" : colors.muted} /> Primary
                </label>
                <label className="inline-flex items-center gap-1 text-xs" style={{ color: colors.onSurface }}>
                  <input
                    type="checkbox"
                    checked={m.sms_ok !== false}
                    onChange={(e) => updateMobile(i, { sms_ok: e.target.checked })}
                    data-testid={`cd-mobile-smsok-${i}`}
                  />
                  SMS ok
                </label>
                <button
                  onClick={() => removeMobile(i)}
                  data-testid={`cd-mobile-remove-${i}`}
                  title="Remove this mobile"
                  className="justify-self-end"
                >
                  <Trash2 size={14} color={colors.danger} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Emails */}
      <section>
        <div className="flex items-center justify-between mb-2">
          <div className="text-xs uppercase font-semibold" style={{ color: colors.muted }}>
            Email addresses ({emails.length}/{MAX_EMAILS})
          </div>
          <Button
            variant="ghost"
            onClick={addEmail}
            disabled={emails.length >= MAX_EMAILS}
            testid="cd-add-email"
          >
            <Plus size={12} /> Add email
          </Button>
        </div>
        {emails.length === 0 ? (
          <div className="text-sm" style={{ color: colors.muted }}>
            No emails on file.
          </div>
        ) : (
          <ul className="space-y-2">
            {emails.map((em, i) => (
              <li
                key={i}
                className="grid grid-cols-1 md:grid-cols-6 gap-2 items-center p-2 rounded-lg"
                style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
                data-testid={`cd-email-row-${i}`}
              >
                <div className="md:col-span-2">
                  <TextInput
                    label=""
                    value={em.address || ""}
                    onChange={(e) => updateEmail(i, { address: e.target.value })}
                    placeholder="owner@example.com"
                    testid={`cd-email-address-${i}`}
                  />
                </div>
                <div className="md:col-span-2">
                  <TextInput
                    label=""
                    value={em.label || ""}
                    onChange={(e) => updateEmail(i, { label: e.target.value })}
                    placeholder="Label (Primary / Billing / Owner / …)"
                    testid={`cd-email-label-${i}`}
                  />
                </div>
                <label className="inline-flex items-center gap-1 text-xs" style={{ color: colors.onSurface }}>
                  <input
                    type="radio"
                    checked={!!em.is_primary}
                    onChange={() => updateEmail(i, { is_primary: true })}
                    data-testid={`cd-email-primary-${i}`}
                  />
                  <Star size={12} color={em.is_primary ? "#F59E0B" : colors.muted} /> Primary
                </label>
                <label className="inline-flex items-center gap-1 text-xs" style={{ color: colors.onSurface }}>
                  <input
                    type="checkbox"
                    checked={em.marketing_ok !== false}
                    onChange={(e) => updateEmail(i, { marketing_ok: e.target.checked })}
                    data-testid={`cd-email-mktok-${i}`}
                  />
                  Marketing ok
                </label>
                <button
                  onClick={() => removeEmail(i)}
                  data-testid={`cd-email-remove-${i}`}
                  title="Remove this email"
                  className="justify-self-end"
                >
                  <Trash2 size={14} color={colors.danger} />
                </button>
              </li>
            ))}
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
