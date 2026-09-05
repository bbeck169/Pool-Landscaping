import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import { cva } from "class-variance-authority";

import { cn } from "@/lib/utils"

// Phase K52 Slice C · Feb-2026 — the ``default`` variant paints the
// K52 signature gradient (emerald-500 → sky-300).
//
// Phase K54 · Feb-2026 — the ``destructive`` variant paints the
// solid red-600 surface with a red-500 focus ring (see
// ``colors.destructive`` in ``theme.js``). The tokens sit inline
// in Tailwind arbitrary values because CVA cannot consume JS
// tokens at build time; ``theme.js`` remains the single source of
// truth and ``test/k54-destructive-buttons.test.js`` asserts these
// hexes match ``colors.destructive.bg`` / ``bgHover`` / ``ring``.
//
// ``destructive`` is intentionally NOT gradient-ified — destructive
// / danger actions keep the red flat surface so the affordance
// stays semantically distinct from a primary CTA. ``ghost`` /
// ``outline`` / ``link`` / ``secondary`` remain flat — they are
// tertiary affordances that would fight the primary gradient's
// visual weight if they shared it.
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
        // K54 destructive — solid #DC2626 / white / #B91C1C hover /
        // #EF4444 focus ring. ``disabled:opacity-55`` is inherited
        // from the base cva above so no override needed here.
        destructive:
          "bg-[#DC2626] text-white shadow-sm hover:bg-[#B91C1C] active:brightness-95 focus-visible:ring-[#EF4444]",
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
