/**
 * Phase K75 · Step B · Feb-2026 — Remove-pin confirm dialog.
 *
 * Lightweight confirm modal shared by every unpin action. Uses the
 * shadcn <AlertDialog> primitive so we get keyboard-trap, esc-close,
 * and screen-reader-appropriate labelling for free.
 */
import React from "react";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel,
  AlertDialogContent, AlertDialogDescription, AlertDialogFooter,
  AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";


export default function RemovePinConfirm({
  open,
  onOpenChange,
  pin,          // { to, label } | null
  onConfirm,    // () => Promise
}) {
  const label = pin?.label || "this pin";
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent data-testid="remove-pin-confirm">
        <AlertDialogHeader>
          <AlertDialogTitle>Remove &ldquo;{label}&rdquo; from Quick Access?</AlertDialogTitle>
          <AlertDialogDescription>
            You can pin it again later from the picker.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel data-testid="remove-pin-cancel">
            Cancel
          </AlertDialogCancel>
          <AlertDialogAction
            onClick={onConfirm}
            className="bg-red-600 hover:bg-red-700 text-white"
            data-testid="remove-pin-confirm-btn"
          >
            Remove pin
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
