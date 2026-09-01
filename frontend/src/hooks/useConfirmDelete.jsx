// Feb-2026 · Item 1 follow-up — Reusable hook that renders the
// ConfirmDeleteDialog and exposes an ``ask()`` function returning a
// Promise<boolean>. Lets any page swap a ``window.confirm(...)`` +
// ``await api.del(...)`` block for a two-liner.
//
// Usage:
//   const { dialog, ask } = useConfirmDelete();
//   ...
//   const ok = await ask({
//     title: "Delete customer?",
//     body:  "This will archive the customer record.",
//     requireTypeConfirm: true,
//   });
//   if (!ok) return;
//   await api.del(...);
//
// Renders ``{dialog}`` once inside the component tree.
import React from "react";
import ConfirmDeleteDialog from "@/components/common/ConfirmDeleteDialog";

export default function useConfirmDelete() {
  const [state, setState] = React.useState({ open: false });
  const resolverRef = React.useRef(null);

  const ask = React.useCallback((opts = {}) => {
    // Phase H3 · Feb-2026 — normalise the brief-spec ``typedKeyword``
    // alias onto the underlying ``requireTypeConfirm`` +
    // ``typeConfirmString`` shape the dialog already supports.
    // Zero churn for the 3 pre-existing callers; new callers can pass
    // ``typedKeyword: "REVOKE"`` and skip the two-flag boilerplate.
    const normalised = { ...opts };
    if (typeof opts.typedKeyword === "string" && opts.typedKeyword) {
      normalised.requireTypeConfirm = true;
      normalised.typeConfirmString = opts.typedKeyword;
    }
    return new Promise((resolve) => {
      resolverRef.current = resolve;
      setState({ open: true, ...normalised });
    });
  }, []);

  const finish = React.useCallback((val) => {
    setState((s) => ({ ...s, open: false }));
    const fn = resolverRef.current;
    resolverRef.current = null;
    if (fn) fn(val);
  }, []);

  const dialog = (
    <ConfirmDeleteDialog
      open={!!state.open}
      title={state.title}
      body={state.body}
      confirmLabel={state.confirmLabel}
      destructive={state.destructive !== false}
      requireTypeConfirm={!!state.requireTypeConfirm}
      typeConfirmString={state.typeConfirmString || "DELETE"}
      onCancel={() => finish(false)}
      onConfirm={() => finish(true)}
    />
  );

  return { dialog, ask };
}
