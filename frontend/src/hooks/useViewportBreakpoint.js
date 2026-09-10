/**
 * Feb-2026 · Universal mobile-responsive redesign · SSR-safe
 * viewport breakpoint hook.
 *
 * Returns ``'mobile' | 'desktop'`` based on the Tailwind ``md``
 * breakpoint (768px). Every customer-facing doc surface
 * (EstimateView, InvoiceView, PublicInvoicePay, PortalSign)
 * subscribes to this hook so the desktop table + top-toolbar
 * layout swaps to a stacked mobile card list + sticky bottom
 * action bar at the same threshold.
 *
 * SSR safety: when ``window`` is undefined (Node / build-time
 * pre-render), returns ``'desktop'`` so the initial paint
 * matches the more information-dense layout — mobile clients
 * flip to the card layout on first client-side render.
 */
import { useEffect, useState } from "react";

const MOBILE_QUERY = "(max-width: 767.98px)";


function readInitial() {
  if (typeof window === "undefined") return "desktop";
  try {
    return window.matchMedia(MOBILE_QUERY).matches ? "mobile" : "desktop";
  } catch {
    return "desktop";
  }
}


export function useViewportBreakpoint() {
  const [bp, setBp] = useState(readInitial);

  useEffect(() => {
    if (typeof window === "undefined") return undefined;
    let mql;
    try {
      mql = window.matchMedia(MOBILE_QUERY);
    } catch {
      return undefined;
    }
    const onChange = () => setBp(mql.matches ? "mobile" : "desktop");
    onChange();
    // ``addEventListener`` is the modern API; ``addListener`` is
    // the deprecated fallback (Safari < 14).
    if (typeof mql.addEventListener === "function") {
      mql.addEventListener("change", onChange);
      return () => mql.removeEventListener("change", onChange);
    }
    mql.addListener(onChange);
    return () => mql.removeListener(onChange);
  }, []);

  return bp;
}


export const DOC_MOBILE_BREAKPOINT_QUERY = MOBILE_QUERY;

export default useViewportBreakpoint;
