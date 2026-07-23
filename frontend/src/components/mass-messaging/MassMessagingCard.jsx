/**
 * Phase 15 · Feb-2026 — Mass Messaging: Dashboard top-of-page card.
 *
 * Admin / super_admin only. Renders a compact one-liner CTA that
 * opens the compose dialog. Self-guards on role — mount-site does
 * the same check for discoverability but the component returns
 * null if a non-admin ends up rendering it.
 */
import React, { useState } from "react";
import { Megaphone, Mail, MessageSquareText } from "lucide-react";
import { useAuth } from "@/auth";
import { colors } from "@/theme";
import { Button } from "@/components/ui/button";
import MassMessagingComposeDialog from "@/components/mass-messaging/MassMessagingComposeDialog";

export default function MassMessagingCard() {
  const { user } = useAuth();
  const [open, setOpen] = useState(false);

  const role = (user?.role || "").toLowerCase();
  if (role !== "admin" && role !== "super_admin") return null;

  return (
    <>
      <div
        className="rounded-2xl p-4 md:p-5 mb-4 flex items-center gap-4 flex-wrap"
        style={{
          background: colors.surface,
          border: `1px solid ${colors.border}`,
        }}
        data-testid="mass-messaging-card"
      >
        <div
          className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
          style={{
            background: colors.brandTertiary,
            color: colors.brand,
          }}
        >
          <Megaphone size={22} />
        </div>
        <div className="flex-1 min-w-[220px]">
          <div
            className="text-sm font-bold"
            style={{ color: colors.onSurface }}
            data-testid="mass-messaging-card-title"
          >
            Mass Messaging
          </div>
          <div
            className="text-xs mt-0.5 flex items-center gap-3 flex-wrap"
            style={{ color: colors.muted }}
          >
            <span>Send a broadcast to all active customers</span>
            <span className="inline-flex items-center gap-1">
              <Mail size={11} /> Email
            </span>
            <span className="inline-flex items-center gap-1">
              <MessageSquareText size={11} /> SMS
            </span>
          </div>
        </div>
        <Button
          type="button"
          onClick={() => setOpen(true)}
          className="font-semibold"
          data-testid="mass-messaging-compose-btn"
        >
          Compose
        </Button>
      </div>

      <MassMessagingComposeDialog
        open={open}
        onOpenChange={setOpen}
      />
    </>
  );
}
