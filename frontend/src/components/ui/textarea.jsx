import * as React from "react"

import { cn } from "@/lib/utils"

/*
 * Phase N1 · Feb-2026 — Universal input restyle (textarea).
 *
 * Same universal theme as ``<Input>`` — solid-white bg, Phase T1
 * navy text (#000080), slate-200 border, ``rounded-lg`` curve,
 * blue-500 focus ring.  Placeholder is 55%-opacity navy to match
 * the Phase T1 base layer.  Preserves disabled semantics.
 */
const Textarea = React.forwardRef(({ className, ...props }, ref) => {
  return (
    <textarea
      className={cn(
        "flex min-h-[60px] w-full rounded-lg border border-slate-200 bg-white text-[#000080] px-3 py-2 text-base shadow-sm placeholder:text-[#000080]/55 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:border-blue-500 disabled:cursor-not-allowed disabled:opacity-50 md:text-sm",
        className
      )}
      ref={ref}
      {...props} />
  );
})
Textarea.displayName = "Textarea"

export { Textarea }
