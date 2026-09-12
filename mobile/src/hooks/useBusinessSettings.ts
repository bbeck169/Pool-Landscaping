/**
 * useBusinessSettings — fetches tenant business settings for the
 * admin surface (brand colours, logo, company info).
 *
 * Returns { branding, loading, error, reload } where `branding`
 * is the `effective` block with sensible defaults so consumers
 * can render without null-guards.
 */
import { useCallback, useEffect, useState } from "react";
import {
  getBusinessSettings,
  type BusinessSettingsEffective,
} from "@/src/api/businessSettings";

const DEFAULT_PRIMARY = "#0B4A6F";
const DEFAULT_SECONDARY = "#F97316";

function withDefaults(
  b: Partial<BusinessSettingsEffective> | null | undefined,
): BusinessSettingsEffective {
  return {
    ...b,
    brand_primary_hex: b?.brand_primary_hex || DEFAULT_PRIMARY,
    brand_secondary_hex: b?.brand_secondary_hex || DEFAULT_SECONDARY,
  };
}

export function useBusinessSettings(skip = false) {
  const [state, setState] = useState<{
    branding: BusinessSettingsEffective;
    loading: boolean;
    error: any;
  }>({
    branding: withDefaults(null),
    loading: !skip,
    error: null,
  });

  const reload = useCallback(async () => {
    if (skip) {
      setState({ branding: withDefaults(null), loading: false, error: null });
      return;
    }
    setState((s) => ({ ...s, loading: true }));
    try {
      const r = await getBusinessSettings();
      setState({
        branding: withDefaults(r?.effective || null),
        loading: false,
        error: null,
      });
    } catch (e) {
      setState({
        branding: withDefaults(null),
        loading: false,
        error: e,
      });
    }
  }, [skip]);

  useEffect(() => {
    reload();
  }, [reload]);

  return { ...state, reload };
}

export { DEFAULT_PRIMARY, DEFAULT_SECONDARY };
