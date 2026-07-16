/**
 * Phase 31 · Step 2c — Reusable imperative confirm dialog.
 *
 * Replaces the raw `window.confirm` / `window.alert` calls scattered
 * across destructive admin/tech flows with a Radix AlertDialog-driven
 * confirmation, so we get consistent styling, focus management, and
 * `Esc` / `Enter` keyboard support without changing any business logic.
 *
 * Usage:
 *   const confirm = useConfirm();
 *   const ok = await confirm({
 *     title: "Delete this payee?",
 *     description: `"${name}" — this cannot be undone.`,
 *     confirmText: "Delete",
 *     tone: "danger",
 *   });
 *   if (!ok) return;
 *
 * Also exposes `useAlert()` for the `window.alert()` cases we're
 * migrating in the same pass (single OK button, no cancel).
 */
import React, {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState,
} from "react";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";

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

  return (
    <ConfirmContext.Provider value={value}>
      {children}
      <AlertDialog
        open={!!state}
        onOpenChange={(o) => { if (!o) settle(false); }}
      >
        <AlertDialogContent
          className="max-w-md"
          data-testid="app-confirm-dialog"
          // Radix AlertDialog INTENTIONALLY suppresses Escape and
          // outside-pointer dismiss by default (versus plain Dialog),
          // because an AlertDialog is meant to interrupt for a
          // specific action. Our product decision (per the Phase 31
          // Step 2c regression report) is that Cancel-equivalent
          // dismiss shortcuts SHOULD work — so we explicitly restore
          // both by resolving the pending promise with `false`.
          onEscapeKeyDown={(e) => {
            e.preventDefault();
            settle(false);
          }}
          onPointerDownOutside={(e) => {
            e.preventDefault();
            settle(false);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              settle(true);
            }
          }}
        >
          <AlertDialogHeader>
            <AlertDialogTitle data-testid="app-confirm-title">
              {opts?.title}
            </AlertDialogTitle>
            {opts?.description ? (
              <AlertDialogDescription data-testid="app-confirm-description">
                {opts.description}
              </AlertDialogDescription>
            ) : null}
          </AlertDialogHeader>
          <AlertDialogFooter>
            {opts?.cancelable ? (
              <AlertDialogCancel
                data-testid="app-confirm-cancel"
                onClick={() => settle(false)}
              >
                {opts?.cancelText || "Cancel"}
              </AlertDialogCancel>
            ) : null}
            <AlertDialogAction
              data-testid="app-confirm-ok"
              className={isDanger ? "bg-red-600 hover:bg-red-700" : ""}
              onClick={() => settle(true)}
              autoFocus
            >
              {opts?.confirmText || (opts?.cancelable ? "Confirm" : "OK")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
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
