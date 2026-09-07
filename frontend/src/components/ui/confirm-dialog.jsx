/**
 * Phase 31 · Step 2c — Reusable imperative confirm dialog.
 *
 * Phase 44 · Fix B (attempt 3) — switched from Radix `AlertDialog`
 * primitives to plain Radix `Dialog` primitives. `AlertDialog` is
 * intentionally hostile to outside-click / escape dismiss because it's
 * meant to "interrupt for a specific action"; various override
 * combinations still saw the `/checks` page swallow backdrop + Confirm
 * taps (e1_tester reports across attempts 1 and 2). `Dialog` fires
 * `onOpenChange(false)` reliably on both backdrop and Escape, which we
 * route through the same `settle(false)` path. Confirm remains a plain
 * button that calls `settle(true)`.
 */
import React, {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState,
} from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { cn } from "@/lib/utils";

const ConfirmContext = createContext(null);

// ─── Global escape hatch ─────────────────────────────────────────────
// Some legacy call-sites are deep in helper functions where adding the
// `useConfirm()` hook would require threading it through several
// props/args. `ConfirmProvider` registers itself here so those
// non-hook code paths can migrate off `window.confirm` in a single
// line via `mustConfirm({...})` / `mustAlert({...})`.
let _globalRequest = null;
export function mustConfirm(opts) {
  if (_globalRequest) return _globalRequest(opts, true);
  // Defensive fallback — should never fire because ConfirmProvider
  // wraps the router. Kept so a test-harness that mounts a single
  // component still gets sensible behavior.
  return Promise.resolve(
    typeof window !== "undefined"
      ? window.confirm(opts?.title || "Are you sure?")
      : false,
  );
}
export function mustAlert(opts) {
  if (_globalRequest) return _globalRequest(opts, false).then(() => undefined);
  if (typeof window !== "undefined") window.alert(opts?.title || opts?.description || "");
  return Promise.resolve();
}

const defaults = {
  title: "Are you sure?",
  description: "",
  confirmText: "Confirm",
  cancelText: "Cancel",
  tone: "default", // "default" | "danger"
  cancelable: true,
  // Feb-2026 · Item 1 follow-up — HEAVY destructive actions require
  // the user to type an exact confirmation string before Confirm is
  // enabled. Pass ``requireTypeConfirm: true`` (default string
  // "DELETE") to opt-in.
  requireTypeConfirm: false,
  typeConfirmString: "DELETE",
  // I1.7.c.2.followup · Feb-2026 — call-site-scoped testids on the
  // confirm/cancel buttons. Layered ON TOP of the stable global
  // ``app-confirm-ok`` / ``app-confirm-cancel`` testids so the
  // existing app-wide confirm-dialog tests still pass unchanged
  // while browser-use automation on a specific flow (e.g.
  // integrations disconnect) can target its own testid.
  confirmTestId: null,
  cancelTestId: null,
};

export function ConfirmProvider({ children }) {
  const [state, setState] = useState(null); // { opts, resolve }
  const activeRef = useRef(null);

  const request = useCallback((opts, cancelable = true) => {
    // Reject any pending prompt so we never leak a hanging Promise.
    if (activeRef.current) {
      activeRef.current.resolve(false);
      activeRef.current = null;
    }
    return new Promise((resolve) => {
      const merged = { ...defaults, ...opts, cancelable };
      const entry = { opts: merged, resolve };
      activeRef.current = entry;
      setState(entry);
    });
  }, []);

  const settle = useCallback((value) => {
    const entry = activeRef.current;
    if (!entry) return;
    activeRef.current = null;
    setState(null);
    entry.resolve(value);
  }, []);

  const value = useMemo(() => ({
    confirm: (opts) => request(opts, true),
    alert: (opts) => request(opts, false),
  }), [request]);

  // Register `request` with the module-level escape hatch so
  // `mustConfirm` / `mustAlert` used in non-hook code paths route
  // through the same Radix dialog. Unregister on unmount so a hot-
  // reload doesn't leave a stale closure hanging.
  useEffect(() => {
    _globalRequest = request;
    return () => {
      if (_globalRequest === request) _globalRequest = null;
    };
  }, [request]);

  const opts = state?.opts;
  const isDanger = opts?.tone === "danger";
  // Feb 2026 · Type-to-confirm friction removed app-wide.
  // The ``requireTypeConfirm`` option is intentionally ignored —
  // callers still pass it for backwards-compat, but the modal now
  // renders without the extra text input and the Confirm button
  // is immediately clickable. The two-click flow (open modal →
  // click Confirm) is preserved for safety.
  const confirmDisabled = false;

  return (
    <ConfirmContext.Provider value={value}>
      {children}
      <DialogPrimitive.Root
        open={!!state}
        onOpenChange={(o) => { if (!o) settle(false); }}
      >
        <DialogPrimitive.Portal>
          <DialogPrimitive.Overlay
            className="fixed inset-0 z-50 bg-black/60 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0"
            data-testid="app-confirm-backdrop"
          />
          <DialogPrimitive.Content
            className={cn(
              "fixed left-[50%] top-[50%] z-50 grid w-full max-w-md translate-x-[-50%] translate-y-[-50%]",
              "gap-4 border bg-background p-6 shadow-lg rounded-lg",
              "data-[state=open]:animate-in data-[state=closed]:animate-out",
              "data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0",
            )}
            data-testid="app-confirm-dialog"
            onKeyDown={(e) => {
              if (e.key === "Enter" && !confirmDisabled) {
                e.preventDefault();
                settle(true);
              }
            }}
          >
            <div className="flex flex-col gap-2">
              <DialogPrimitive.Title
                className="text-lg font-semibold"
                data-testid="app-confirm-title"
              >
                {opts?.title}
              </DialogPrimitive.Title>
              {opts?.description ? (
                <DialogPrimitive.Description
                  className="text-sm text-muted-foreground"
                  data-testid="app-confirm-description"
                >
                  {opts.description}
                </DialogPrimitive.Description>
              ) : (
                // Radix logs a warning if Description is missing; keep
                // an sr-only placeholder to silence it without adding
                // visual noise.
                <DialogPrimitive.Description className="sr-only">
                  {opts?.title}
                </DialogPrimitive.Description>
              )}
              {/* Feb 2026 · Type-to-confirm friction removed — the
                  text input previously gated behind
                  ``requireTypeConfirm`` is no longer rendered. Callers
                  still pass the flag for API backwards-compat, but
                  the two-click "open modal → click Confirm" flow is
                  now the sole safety gate. */}
            </div>
            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              {opts?.cancelable ? (
                <button
                  type="button"
                  data-testid={opts?.cancelTestId || "app-confirm-cancel"}
                  onClick={() => settle(false)}
                  className="inline-flex items-center justify-center rounded-md border border-input bg-background px-4 py-2 text-sm font-medium hover:bg-accent hover:text-accent-foreground"
                >
                  {opts?.cancelText || "Cancel"}
                </button>
              ) : null}
              <button
                type="button"
                data-testid={opts?.confirmTestId || "app-confirm-ok"}
                onClick={() => { if (!confirmDisabled) settle(true); }}
                autoFocus
                disabled={confirmDisabled}
                className={cn(
                  "inline-flex items-center justify-center rounded-md px-4 py-2 text-sm font-semibold text-white disabled:opacity-50 disabled:cursor-not-allowed",
                  isDanger ? "bg-red-600 hover:bg-red-700" : "bg-primary hover:bg-primary/90",
                )}
              >
                {opts?.confirmText || (opts?.cancelable ? "Confirm" : "OK")}
              </button>
            </div>
          </DialogPrimitive.Content>
        </DialogPrimitive.Portal>
      </DialogPrimitive.Root>
    </ConfirmContext.Provider>
  );
}

/**
 * Hook returning a `confirm(opts) => Promise<boolean>` function.
 * Falls back to `window.confirm` only if used outside the provider
 * (defensive — the provider MUST wrap the router, so this branch is
 * really just a compile-time guard).
 */
export function useConfirm() {
  const ctx = useContext(ConfirmContext);
  if (!ctx) {
    return (opts) => Promise.resolve(
      typeof window !== "undefined" ? window.confirm(opts?.title || "Are you sure?") : false,
    );
  }
  return ctx.confirm;
}

/**
 * Hook for cases where the legacy code called `window.alert()` — one
 * button, no cancel. Returns `Promise<void>` that resolves once the
 * user dismisses.
 */
export function useAlert() {
  const ctx = useContext(ConfirmContext);
  if (!ctx) {
    return (opts) => {
      if (typeof window !== "undefined") window.alert(opts?.title || opts?.description || "");
      return Promise.resolve();
    };
  }
  return (opts) => ctx.alert(opts).then(() => undefined);
}
