import React from "react";
import { Phone, PhoneOutgoing } from "lucide-react";
import { api } from "@/api";
import { toast } from "sonner";
import { useAuth } from "@/auth";

/**
 * Phase 6B · Feb 2026 — Click-to-call button with tel: fallback.
 *
 * • Admin / manager / super_admin / technician can trigger a RingCentral
 *   RingOut call via POST /api/rc/call.
 * • Technicians (and anyone lacking an RC seat) also get a native
 *   `<a href="tel:…">` fallback rendered directly below the primary
 *   button, so the mobile-web dialer works even when RC ring-out is
 *   rejected (403 / 502 / rate-limit / feature flag off).
 * • Never renders any dollar amount — pricing invisibility is enforced
 *   by keeping the button UI free of `open_invoice_total_usd`. The
 *   SSE toast still shows balance to admin/manager, but that surface
 *   is gated at the subscription level (see useTelephonyLiveEvents).
 *
 * Props:
 *   - phoneNumber (string, required): E.164-preferred destination
 *   - entityKind (string, optional): "customer" | "lead" | "job" |
 *       "property" | "workstream" — attribution written to
 *       /api/rc/log-outbound
 *   - entityId (string, optional): id of the parent record
 *   - label (string, optional): overrides "Call" button copy
 *   - size (string, optional): "sm" | "md" — visual density
 *   - showFallback (bool, optional; default true): render the tel:
 *       fallback for mobile-web / no-RC-seat users
 *   - testIdPrefix (string, optional): base for data-testid attrs
 */
export default function ClickToCallButton({
  phoneNumber,
  entityKind = null,
  entityId = null,
  label = "Call",
  size = "md",
  showFallback = true,
  className = "",
  testIdPrefix = "click-to-call",
}) {
  const { user } = useAuth();
  const [busy, setBusy] = React.useState(false);

  if (!phoneNumber) return null;
  const cleaned = String(phoneNumber).trim();
  const telHref = `tel:${cleaned.replace(/[^0-9+]/g, "")}`;
  const isTech = user?.role === "technician";

  const onCall = async () => {
    if (busy) return;
    setBusy(true);
    try {
      // Fire the outbound intent log first so the admin timeline gets
      // a row even if the RC ring-out ultimately fails.
      if (entityKind && entityId) {
        try {
          await api.post("/rc/log-outbound", {
            to_number: cleaned,
            from_number: user?.phone || "",
            entity_kind: entityKind,
            entity_id: entityId,
          });
        } catch (e) {
          // Intent log failures shouldn't block the actual dial —
          // surface a soft warning and keep going.
          console.warn("rc log-outbound failed:", e?.message || e);
        }
      }
      const res = await api.post("/rc/call", { to_number: cleaned });
      toast.success(`Calling ${cleaned}…`, {
        description: res?.status === "queued" ? "Ring-out queued" : "Placed",
      });
    } catch (e) {
      const msg = e?.message || "Call failed";
      // Techs: silently fall back to the tel: link so their existing
      // native dialer opens. Admin/manager see the toast.
      if (isTech) {
        window.location.href = telHref;
      } else {
        toast.error("Ring-out failed", { description: msg });
      }
    } finally {
      setBusy(false);
    }
  };

  const btnPad = size === "sm" ? "px-2.5 py-1 text-xs" : "px-3 py-1.5 text-sm";

  return (
    <div className={`inline-flex flex-col items-start gap-1 ${className}`}>
      <button
        type="button"
        onClick={onCall}
        disabled={busy}
        className={
          `inline-flex items-center gap-1.5 rounded-lg font-medium ` +
          `bg-emerald-600 hover:bg-emerald-700 text-white transition-colors ` +
          `disabled:opacity-60 disabled:cursor-wait ${btnPad}`
        }
        data-testid={`${testIdPrefix}-button`}
        title={`Call ${cleaned}`}
      >
        <PhoneOutgoing size={size === "sm" ? 12 : 14} />
        {busy ? "Calling…" : label}
      </button>
      {showFallback && (
        <a
          href={telHref}
          className="inline-flex items-center gap-1 text-[11px] text-slate-500 hover:text-slate-800 underline underline-offset-2"
          data-testid={`${testIdPrefix}-tel-fallback`}
        >
          <Phone size={10} /> Dial from this device
        </a>
      )}
    </div>
  );
}
