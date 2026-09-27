/**
 * SAFE-SEND-B · Feb-2026 — inline audit badge for comms log rows.
 *
 * Renders next to a ``comms_send_log`` row in any admin surface
 * so operators can spot at-a-glance which sends were redirected
 * to admin (the ``AGENT`` / ``TEST`` safe-send path) vs. which
 * reached the real customer (``SYSTEM`` passthrough).
 *
 * Detection is order-of-preference:
 *   1. ``row.redirected === true``  → amber "🛡️ Redirected"
 *   2. ``row.redirected === false`` → green  "✅ Live"
 *   3. ``intended != actual``       → amber (defensive — covers
 *                                      callers that write the
 *                                      shape without the bool)
 *   4. Nothing else (``context == null`` → legacy row) → renders
 *      ``null`` so pre-SAFE-SEND-A rows stay uncluttered.
 *
 * Reuses ``@/components/ui/badge`` + ``@/components/ui/tooltip``.
 * No new primitives.
 */
import React from "react";
import { Shield, CheckCircle2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  Tooltip, TooltipContent, TooltipProvider, TooltipTrigger,
} from "@/components/ui/tooltip";


function _isRedirected(row) {
  // Explicit boolean is the primary signal.
  if (row?.redirected === true) return true;
  if (row?.redirected === false) return false;
  // Fallback — some tests write the recipient pair without the
  // boolean (mirrors SAFE-SEND-A.1 spec §"redirected: bool" note).
  const intended = row?.intended_recipient_redacted;
  const actual = row?.recipient_redacted ?? row?.actual_recipient_redacted;
  if (intended != null && actual != null && intended !== actual) {
    return true;
  }
  return null;  // truly indeterminate — likely a legacy row
}


function _tooltipCopy(row, redirected) {
  const intended = row?.intended_recipient_redacted;
  const actual = row?.recipient_redacted ?? row?.actual_recipient_redacted;
  if (redirected && intended && actual) {
    return `Intended: ${intended} — Redirected to: ${actual}`;
  }
  if (redirected && intended) {
    return `Intended recipient: ${intended} (redirected to admin inbox)`;
  }
  if (!redirected && actual) {
    return `Delivered to intended recipient: ${actual}`;
  }
  return null;
}


export default function SafeSendBadge({ row }) {
  // Feb-2026 — pre-SAFE-SEND-A rows have no ``context`` field.
  // Skip entirely so legacy audit rows stay visually uncluttered.
  if (!row || row.context == null) return null;

  const redirected = _isRedirected(row);
  if (redirected === null) return null;

  const tooltip = _tooltipCopy(row, redirected);

  const badge = redirected ? (
    <Badge
      variant="outline"
      className="gap-1 border-amber-400 bg-amber-50 text-amber-900 hover:bg-amber-100"
      data-testid="safe-send-badge-redirected"
    >
      <Shield className="w-3 h-3" aria-hidden />
      <span>Redirected</span>
    </Badge>
  ) : (
    <Badge
      variant="outline"
      className="gap-1 border-green-400 bg-green-50 text-green-800 hover:bg-green-100"
      data-testid="safe-send-badge-live"
    >
      <CheckCircle2 className="w-3 h-3" aria-hidden />
      <span>Live</span>
    </Badge>
  );

  if (!tooltip) return badge;

  return (
    <TooltipProvider delayDuration={100}>
      <Tooltip>
        <TooltipTrigger asChild>
          <span
            className="inline-block cursor-help"
            data-testid="safe-send-badge-tooltip-trigger"
          >
            {badge}
          </span>
        </TooltipTrigger>
        <TooltipContent
          data-testid="safe-send-badge-tooltip-content"
          className="max-w-xs"
        >
          {tooltip}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
