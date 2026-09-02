/**
 * StripeConfigProvider — fetches the publishable key at boot from
 * GET /api/config/public and caches it in React context.
 * NEVER hardcodes pk_live.
 *
 * Phase K23: Added `stripeConfigured` boolean. Fail-closed: if the
 * publishable key is missing or the config fetch errors, Stripe is
 * treated as not configured.
 */
import React, { createContext, useContext, useEffect, useState } from "react";
import { getPublicConfig } from "@/src/api/payments";

type StripeConfig = {
  pk: string;
  mode: string;
  loading: boolean;
  /** true when a valid publishable key is available. */
  stripeConfigured: boolean;
};

const Ctx = createContext<StripeConfig>({
  pk: "",
  mode: "",
  loading: true,
  stripeConfigured: false,
});

export function StripeConfigProvider({ children }: { children: React.ReactNode }) {
  const [pk, setPk] = useState("");
  const [mode, setMode] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getPublicConfig()
      .then((cfg) => {
        setPk(cfg.stripe_publishable_key || "");
        setMode(cfg.stripe_mode || "");
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  // K23 — fail-closed: only configured when a real pk is present.
  const stripeConfigured = pk.length > 0;

  return (
    <Ctx.Provider value={{ pk, mode, loading, stripeConfigured }}>
      {children}
    </Ctx.Provider>
  );
}

export const useStripeConfig = () => useContext(Ctx);
