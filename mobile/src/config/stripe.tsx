/**
 * StripeConfigProvider — fetches the publishable key at boot from
 * GET /api/config/public and caches it in React context.
 * NEVER hardcodes pk_live.
 */
import React, { createContext, useContext, useEffect, useState } from "react";
import { getPublicConfig } from "@/src/api/payments";

type StripeConfig = {
  pk: string;
  mode: string;
  loading: boolean;
};

const Ctx = createContext<StripeConfig>({ pk: "", mode: "", loading: true });

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

  return (
    <Ctx.Provider value={{ pk, mode, loading }}>
      {children}
    </Ctx.Provider>
  );
}

export const useStripeConfig = () => useContext(Ctx);
