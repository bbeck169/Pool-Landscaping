/**
 * Feb-2026 · Reusable scroll-trap assertion for vitest.
 *
 * Any page that adopts <SafeScrollContainer /> — or hand-rolls the
 * same guarantees — can pin the convention with:
 *
 *   import { assertNoScrollTrap } from "@/test/helpers/assertNoScrollTrap";
 *   it("outer container is safe to scroll", () => {
 *     render(<MyPage />);
 *     assertNoScrollTrap(screen.getByTestId("my-page"));
 *   });
 */
import { expect } from "vitest";


/**
 * Assert the given DOM element does not trap document scroll.
 *
 * Checks BOTH computed styles (in case a rule leaked in via CSS) AND
 * the class list (so a future author who re-adds ``overflow-hidden``
 * gets a red build even if jsdom's computed style lookup misses it).
 */
export function assertNoScrollTrap(el) {
  if (!el) throw new Error("assertNoScrollTrap: element is null");

  const styles = window.getComputedStyle(el);
  expect(styles.overflow, "outer container must not set overflow: hidden").not.toBe("hidden");
  expect(styles.overflowY, "outer container must not set overflow-y: hidden").not.toBe("hidden");
  expect(styles.overflowY, "outer container must not set overflow-y: scroll").not.toBe("scroll");
  expect(styles.height, "outer container must not fix height to 100vh").not.toBe("100vh");

  const cls = el.className || "";
  // Reject the trap `h-screen` (fixed 100vh height) but NOT `min-h-screen`
  // — the latter is safe because it only sets a *minimum* height, letting
  // the container grow naturally with content.
  expect(cls, "outer container must not include h-screen").not.toMatch(/(?:^|\s)h-screen(?:\s|$)/);
  expect(cls, "outer container must not include max-h-*").not.toMatch(/(?:^|\s)max-h-\S+/);
  expect(cls, "outer container must not include overflow-hidden").not.toMatch(/\boverflow-hidden\b/);
  expect(cls, "outer container must not include overflow-y-scroll").not.toMatch(/\boverflow-y-scroll\b/);
  expect(cls, "outer container must not include overflow-y-hidden").not.toMatch(/\boverflow-y-hidden\b/);
}
