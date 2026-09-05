import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import { cva } from "class-variance-authority";

import { cn } from "@/lib/utils"

// Phase K52 Slice C · Feb-2026 — the ``default`` variant now paints
// the K52 signature gradient (emerald-500 → sky-300) instead of the
// pre-K52 flat ``bg-primary``.  Hexes sit inline in the Tailwind
// arbitrary values because CVA cannot consume JS tokens at build
// time; ``theme.js`` remains the single source of truth and the
// vitest suite (`k52-theming.test.js`) asserts the two hexes here
// match ``colors.gradient.from`` / ``colors.gradient.to``.
//
// ``destructive`` is intentionally NOT gradient-ified — per K52
// spec, destructive / danger actions keep the red flat surface so
// the affordance stays semantically distinct from a primary CTA.
// ``ghost`` / ``outline`` / ``link`` / ``secondary`` remain flat —
// they are tertiary affordances that would fight the primary
// gradient's visual weight if they shared it.
const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#22C55E] focus-visible:ring-offset-1 disabled:pointer-events-none disabled:opacity-55 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        // K52 primary — signature emerald→sky gradient with a
        // subtle text-shadow so white body copy still passes the
        // manual eye check on the ``#7DD3FC`` (sky-300) end.
        default:
          "text-white shadow bg-[linear-gradient(90deg,_#22C55E_0%,_#7DD3FC_100%)] hover:bg-[linear-gradient(90deg,_#34D673_0%,_#93DDFD_100%)] active:brightness-95 [text-shadow:0_1px_2px_rgba(0,0,0,0.25)]",
        destructive:
          "bg-destructive text-destructive-foreground shadow-sm hover:bg-destructive/90",
        outline:
          "border border-input shadow-sm hover:bg-accent hover:text-accent-foreground",
        secondary:
          "bg-secondary text-secondary-foreground shadow-sm hover:bg-secondary/80",
        ghost: "hover:bg-accent hover:text-accent-foreground",
        link: "text-primary underline-offset-4 hover:underline",
      },
      size: {
        default: "h-9 px-4 py-2",
        sm: "h-8 rounded-md px-3 text-xs",
        lg: "h-10 rounded-md px-8",
        icon: "h-9 w-9",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

const Button = React.forwardRef(({ className, variant, size, asChild = false, ...props }, ref) => {
  const Comp = asChild ? Slot : "button"
  return (
    <Comp
      className={cn(buttonVariants({ variant, size, className }))}
      ref={ref}
      {...props} />
  );
})
Button.displayName = "Button"

export { Button, buttonVariants }
