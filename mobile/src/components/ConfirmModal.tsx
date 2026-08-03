import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Modal,
  View,
  Text,
  StyleSheet,
  Pressable,
  ActivityIndicator,
} from "react-native";

import { colors, spacing, radius, font, fontSize } from "@/src/theme";

/**
 * Phase 30.4 · Feb-2026 — shared destructive-confirmation modal.
 *
 * Motivating cause: native ``Alert.alert(...)`` silently no-ops on
 * some Android/Expo Go builds (root cause of the Phase 30.3 P0
 * portal sign-out regression). Any user-choice confirmation that
 * relied on Alert would look completely dead on those devices. This
 * component renders a first-class RN ``<Modal>`` we can guarantee
 * shows up.
 *
 * THREE consumption styles:
 *
 *   1. Global imperative (RECOMMENDED for 1-off destructive sites):
 *
 *        import { showConfirm } from "@/src/components/ConfirmModal";
 *        // ...
 *        showConfirm({
 *          title: "Delete photo?",
 *          message: "This cannot be undone.",
 *          confirmLabel: "Delete",
 *          confirmStyle: "destructive",
 *          onConfirm: async () => { await api.del(...); await reload(); },
 *        });
 *
 *      Requires a single ``<ConfirmModalHost />`` mounted once in the
 *      root layout (``mobile/app/_layout.tsx``).
 *
 *   2. Declarative (``<ConfirmModal visible ... />``) — good for
 *      stable, single-target confirmations owned by one screen.
 *
 *   3. Hook (``useConfirm()``) — good for list rows where the
 *      confirmation target changes per-row.
 */

export type ConfirmStyle = "destructive" | "primary";

export type ConfirmOptions = {
  title: string;
  message?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  confirmStyle?: ConfirmStyle;
  onConfirm: () => void | Promise<void>;
  onCancel?: () => void;
};

export type ConfirmModalProps = {
  visible: boolean;
  title: string;
  message?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  confirmStyle?: ConfirmStyle;
  onCancel: () => void;
  onConfirm: () => void | Promise<void>;
  testID?: string;
};

export function ConfirmModal({
  visible,
  title,
  message,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  confirmStyle = "primary",
  onCancel,
  onConfirm,
  testID,
}: ConfirmModalProps) {
  const [pending, setPending] = useState(false);

  const handleConfirm = useCallback(async () => {
    if (pending) return;
    setPending(true);
    try {
      await onConfirm();
    } finally {
      setPending(false);
    }
  }, [pending, onConfirm]);

  return (
    <Modal
      visible={visible}
      transparent
      animationType="fade"
      onRequestClose={() => {
        if (!pending) onCancel();
      }}
      testID={testID || "confirm-modal-root"}
    >
      <Pressable
        style={s.backdrop}
        onPress={() => {
          if (!pending) onCancel();
        }}
        testID="confirm-modal-backdrop"
      >
        <Pressable
          style={s.card}
          onPress={() => {}}
          accessibilityRole="alert"
          accessible
        >
          <Text style={s.title} testID="confirm-modal-title">
            {title}
          </Text>
          {message ? (
            <Text style={s.message} testID="confirm-modal-message">
              {message}
            </Text>
          ) : null}

          <View style={s.buttonRow}>
            <Pressable
              testID="confirm-modal-cancel"
              onPress={onCancel}
              disabled={pending}
              style={({ pressed }) => [
                s.btnBase,
                s.btnCancel,
                pressed && { opacity: 0.75 },
                pending && { opacity: 0.5 },
              ]}
              accessibilityRole="button"
              accessibilityLabel={cancelLabel}
            >
              <Text style={s.btnCancelText}>{cancelLabel}</Text>
            </Pressable>

            <Pressable
              testID="confirm-modal-confirm"
              onPress={handleConfirm}
              disabled={pending}
              style={({ pressed }) => [
                s.btnBase,
                confirmStyle === "destructive"
                  ? s.btnDestructive
                  : s.btnPrimary,
                pressed && { opacity: 0.85 },
                pending && { opacity: 0.7 },
              ]}
              accessibilityRole="button"
              accessibilityLabel={confirmLabel}
            >
              {pending ? (
                <ActivityIndicator size="small" color="#fff" />
              ) : (
                <Text style={s.btnConfirmText}>{confirmLabel}</Text>
              )}
            </Pressable>
          </View>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

// ── useConfirm() hook ────────────────────────────────────

export function useConfirm() {
  const [state, setState] = useState<{
    open: boolean;
    opts: ConfirmOptions | null;
  }>({ open: false, opts: null });

  const ref = useRef<ConfirmOptions | null>(null);

  const confirm = useCallback((opts: ConfirmOptions) => {
    ref.current = opts;
    setState({ open: true, opts });
  }, []);

  const close = useCallback(() => {
    setState((prev) => ({ open: false, opts: prev.opts }));
    if (ref.current?.onCancel) ref.current.onCancel();
  }, []);

  const handleConfirm = useCallback(async () => {
    const current = ref.current;
    if (!current) return;
    try {
      await current.onConfirm();
    } finally {
      setState({ open: false, opts: null });
      ref.current = null;
    }
  }, []);

  const ConfirmHost = useMemo(
    () => (
      <ConfirmModal
        visible={state.open}
        title={state.opts?.title || ""}
        message={state.opts?.message}
        confirmLabel={state.opts?.confirmLabel}
        cancelLabel={state.opts?.cancelLabel}
        confirmStyle={state.opts?.confirmStyle || "primary"}
        onCancel={close}
        onConfirm={handleConfirm}
      />
    ),
    [state.open, state.opts, close, handleConfirm],
  );

  return { confirm, ConfirmHost };
}

// ── Global imperative API (showConfirm + ConfirmModalHost) ───

// Module-level pub/sub. A single ConfirmModalHost subscribes and
// renders the modal in response to showConfirm() calls from
// anywhere in the app.
type Subscriber = (opts: ConfirmOptions | null) => void;
let _subscriber: Subscriber | null = null;

// Queue calls that happen before the host has mounted (e.g., during
// first-render hydration). They get replayed on subscribe.
let _pending: ConfirmOptions[] = [];

export function showConfirm(opts: ConfirmOptions) {
  if (_subscriber) {
    _subscriber(opts);
  } else {
    _pending.push(opts);
    // Warn once in DEV if we're queuing — usually means the host
    // isn't mounted yet, which is a wiring bug.
    if (__DEV__) {
      console.warn(
        "[ConfirmModal] showConfirm() called before <ConfirmModalHost /> mounted — queuing.",
      );
    }
  }
}

/**
 * Mount ONCE at the app root (``mobile/app/_layout.tsx``). Subscribes
 * to the module-level pub/sub so any ``showConfirm()`` call from
 * anywhere in the app opens the modal.
 */
export function ConfirmModalHost() {
  const [opts, setOpts] = useState<ConfirmOptions | null>(null);

  useEffect(() => {
    _subscriber = (next) => setOpts(next);
    // Flush any calls that landed before mount.
    if (_pending.length > 0) {
      const first = _pending.shift()!;
      _pending = [];
      setOpts(first);
    }
    return () => {
      _subscriber = null;
    };
  }, []);

  const close = useCallback(() => {
    if (opts?.onCancel) opts.onCancel();
    setOpts(null);
  }, [opts]);

  const handleConfirm = useCallback(async () => {
    if (!opts) return;
    try {
      await opts.onConfirm();
    } finally {
      setOpts(null);
    }
  }, [opts]);

  return (
    <ConfirmModal
      visible={!!opts}
      title={opts?.title || ""}
      message={opts?.message}
      confirmLabel={opts?.confirmLabel}
      cancelLabel={opts?.cancelLabel}
      confirmStyle={opts?.confirmStyle || "primary"}
      onCancel={close}
      onConfirm={handleConfirm}
    />
  );
}

// ── styles ────────────────────────────────────────────────

const s = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: "rgba(15, 23, 42, 0.55)",
    alignItems: "center",
    justifyContent: "center",
    padding: spacing.lg,
  },
  card: {
    width: "100%",
    maxWidth: 400,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.lg,
    gap: spacing.md,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.25,
    shadowRadius: 24,
    elevation: 8,
  },
  title: {
    fontFamily: font.bold,
    fontSize: fontSize.xl,
    color: colors.onSurface,
  },
  message: {
    fontFamily: font.regular,
    fontSize: fontSize.base,
    color: colors.onSurfaceSecondary,
    lineHeight: 20,
  },
  buttonRow: {
    flexDirection: "row",
    justifyContent: "flex-end",
    gap: spacing.sm,
    marginTop: spacing.sm,
  },
  btnBase: {
    minWidth: 96,
    paddingVertical: 12,
    paddingHorizontal: spacing.lg,
    borderRadius: radius.md,
    alignItems: "center",
    justifyContent: "center",
  },
  btnCancel: { backgroundColor: colors.surfaceTertiary },
  btnCancelText: {
    fontFamily: font.semibold,
    fontSize: fontSize.base,
    color: colors.onSurface,
  },
  btnPrimary: { backgroundColor: colors.brand },
  btnDestructive: { backgroundColor: colors.error },
  btnConfirmText: {
    fontFamily: font.bold,
    fontSize: fontSize.base,
    color: "#fff",
  },
});

export default ConfirmModal;
