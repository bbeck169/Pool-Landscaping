/**
 * Slice O1 · Portal "Call Now" CTA.
 *
 * Reads the tenant support phone number from
 * ``/api/tenants/mine/public-config`` and renders a large tap-target
 * button that opens the device's native phone dialer via ``tel:``.
 * If the tenant hasn't configured a support number the button hides
 * entirely — no dead-ended affordance.
 */
import React, { useEffect, useState } from "react";
import { Phone } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

/** Format a raw ``+16028874400`` into ``(602) 887-4400`` for display.
 *  Falls back to the raw value when the parse fails. */
function formatUsPhone(raw) {
  if (!raw) return "";
  const digits = String(raw).replace(/\D+/g, "");
  if (digits.length === 11 && digits.startsWith("1")) {
    return `(${digits.slice(1, 4)}) ${digits.slice(4, 7)}-${digits.slice(7)}`;
  }
  if (digits.length === 10) {
    return `(${digits.slice(0, 3)}) ${digits.slice(3, 6)}-${digits.slice(6)}`;
  }
  return raw;
}

export default function CallNowButton() {
  const [phone, setPhone] = useState(null);

  useEffect(() => {
    let cancelled = false;
    api.get("/tenants/mine/public-config")
      .then((res) => {
        if (!cancelled) setPhone(res?.support_phone_number || null);
      })
      .catch(() => setPhone(null));
    return () => { cancelled = true; };
  }, []);

  if (!phone) return null;
  return (
    <a
      href={`tel:${phone}`}
      className="inline-flex items-center justify-center gap-2 px-5 py-3 rounded-2xl font-bold text-white shadow-md hover:brightness-95 active:brightness-90 select-none"
      style={{
        background: "#16A34A",
        minHeight: 48,
        minWidth: 200,
        textDecoration: "none",
      }}
      data-testid="portal-call-now-btn"
    >
      <Phone size={18} />
      <span className="text-sm sm:text-base">
        Call Now · {formatUsPhone(phone)}
      </span>
    </a>
  );
}
