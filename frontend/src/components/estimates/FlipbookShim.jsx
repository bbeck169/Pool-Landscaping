/**
 * Feb-2026 · Flipbook estimate viewer — thin ``forwardRef`` shim
 * around ``react-pageflip``'s ``HTMLFlipBook``.
 *
 * Two jobs:
 *   1. Insulate the rest of the app from the underlying library so
 *      a future swap (upstream React-19 fixes, or a migration to
 *      ``react-pageflip-enhanced``) is a single-file change.
 *   2. Give consumers a ``forwardRef``-friendly ref surface so the
 *      React 19 typechecker doesn't complain when they call
 *      ``flipbookRef.current.pageFlip().flipNext()``.
 *
 * The wrapper is intentionally pass-through — every prop is
 * forwarded verbatim. Only ``ref`` is proxied.
 *
 * Import path (established convention):
 *
 *     import Flipbook from "@/components/estimates/FlipbookShim";
 *     const ref = useRef(null);
 *     <Flipbook ref={ref} width={640} height={880}>{pages}</Flipbook>;
 *     ref.current.pageFlip().flipNext();
 */
import React, { forwardRef } from "react";
import HTMLFlipBook from "react-pageflip";


const Flipbook = forwardRef(function Flipbook({ children, ...props }, ref) {
  return (
    <HTMLFlipBook ref={ref} {...props}>
      {children}
    </HTMLFlipBook>
  );
});


export default Flipbook;
