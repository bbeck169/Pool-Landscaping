import * as React from "react"

import { cn } from "@/lib/utils"

/*
 * Phase N1 · Feb-2026 — Universal input restyle.
 *
 * The base <input>/<textarea> class chain is upgraded to the
 * app-wide theme:
 *
 *   background   #FFFFFF           (bg-white)
 *   text color   #000080           (Phase T1 navy — text-[#000080])
 *   border       slate-200         (border-slate-200)
 *   radius       rounded-lg        (curved)
 *   focus        blue-500 ring     (focus-visible:ring-blue-500 +
 *                                    focus-visible:border-blue-500)
 *
 * The ring is applied via a Tailwind ring utility instead of the
 * outline used by the base ``@layer`` block so shadcn's existing
 * ring-tokens shape composes cleanly with any per-consumer size
 * override.  ``placeholder:text-[#000080]/55`` mirrors the base
 * layer's 55%-opacity navy placeholder for shadcn consumers.
 *
 * Semantics preserved:  ``disabled:cursor-not-allowed
 * disabled:opacity-50`` and the file-input tokens stay identical.
 */
const Input = React.forwardRef(({ className, type, ...props }, ref) => {
  return (
    <input
      type={type}
      className={cn(
        "flex h-9 w-full rounded-lg border border-slate-200 bg-white text-[#000080] px-3 py-1 text-base shadow-sm transition-colors file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-foreground placeholder:text-[#000080]/55 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:border-blue-500 disabled:cursor-not-allowed disabled:opacity-50 md:text-sm",
        className
      )}
      ref={ref}
      {...props} />
  );
})
Input.displayName = "Input"

export { Input }
