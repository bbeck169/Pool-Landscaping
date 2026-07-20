/**
 * ScrollToTop — instant scroll reset on route change.
 *
 * Mounted inside <BrowserRouter> in App.js. The dependency array
 * intentionally uses ``pathname`` only (not search / hash) so:
 *   - Filter changes on Deals / Directory Submissions (?status=…)
 *     do NOT force a scroll jump.
 *   - Same-page anchor navigation (#section) is untouched.
 *   - Actual route transitions (e.g. /marketing/directories →
 *     /marketing/campaigns) start the new page at the top.
 *
 * Also resets any inner scroll container that opts in with the
 * ``data-scroll-root`` attribute, falling back to ``<main>``. This
 * catches AppLayout patterns where the outer body is fixed and a
 * child region is the real scroll host.
 */
import { useEffect } from "react";
import { useLocation } from "react-router-dom";

export default function ScrollToTop() {
  const { pathname } = useLocation();
  useEffect(() => {
    // Window fallback — instant so route change doesn't feel animated.
    try {
      window.scrollTo({ top: 0, left: 0, behavior: "instant" });
    } catch {
      // Older browsers reject the { behavior: "instant" } object form.
      window.scrollTo(0, 0);
    }
    const main =
      document.querySelector("[data-scroll-root]") ||
      document.querySelector("main");
    if (main && typeof main.scrollTo === "function") {
      try {
        main.scrollTo({ top: 0, behavior: "instant" });
      } catch {
        main.scrollTop = 0;
      }
    }
  }, [pathname]);
  return null;
}
