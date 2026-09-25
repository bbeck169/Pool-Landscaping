import React from "react";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSub,
  DropdownMenuSubTrigger,
  DropdownMenuSubContent,
  DropdownMenuPortal,
} from "@/components/ui/dropdown-menu";
import {
  Mail, MessageSquare, ChevronDown, Plus, Calendar, DollarSign,
  FileText, ClipboardCheck, ListChecks, Users, Link2, Beaker,
} from "lucide-react";
import { Button } from "@/components/ui-kit";
import { useNavigate } from "react-router-dom";
import { colors } from "@/theme";

/**
 * Top-right Send ▼ + + Create ▼ dropdowns on the Customer detail page.
 * Feb-2026 Customer Detail Additions ship.
 *
 * All items pre-fill the target flow with the current customer via a
 * ``?customer_id=`` query param — every existing create route already
 * respects this convention, so no receiving-side changes are required.
 *
 * Feb-2026 · Customer Header Navy Strip
 * ─────────────────────────────────────
 * When the parent renders us inside the unified navy command strip
 * (see ``CustomerDetail.jsx``), it passes ``navy={true}`` — both
 * trigger buttons then adopt the strip's white-on-navy styling so
 * they blend with the rest of the strip's controls. Menu content
 * (the popover) keeps its default (light) styling — spec calls for
 * only the trigger to live on navy.
 *
 * Feb-2026 · Chemistry submenu consolidation
 * ─────────────────────────────────────────
 * The standalone "Chemistry" brand-colored dropdown that lived
 * inline on the customer header row is folded into ``+ Create``
 * as a nested submenu labelled "Chemistry…". Both original
 * options (Chemistry, Chemistry History) are preserved with their
 * legacy testids so every existing suite keeps resolving.
 */
export function CustomerActionDropdowns({
  customer, onSend, onQuickTask, onSendServiceRecordsLink,
  navy = false,
}) {
  const navigate = useNavigate();
  const cid = customer?.id;
  const primaryEmail =
    (customer?.emails || []).find((e) => e.is_primary)?.address ||
    customer?.email ||
    "";
  const primaryMobile =
    (customer?.mobiles || []).find((m) => m.is_primary)?.number_e164 ||
    customer?.phone ||
    "";

  // Feb-2026 · Navy strip variant — invert the ``Button`` variant
  // colors so a white-on-navy trigger reads correctly against
  // ``colors.nav.bg``. Applied via inline ``style`` overrides so
  // we don't have to fork the Button primitive.
  const navyTriggerStyle = navy ? {
    background: "transparent",
    color: colors.nav.fg,
    border: `1px solid rgba(255,255,255,0.20)`,
  } : undefined;
  const navyTriggerClass = navy
    ? "hover:!bg-white/10 focus:!ring-2 focus:!ring-white/40"
    : "";

  return (
    <div className="flex flex-wrap gap-2" data-testid="customer-action-dropdowns">
      {/* Send ▼ */}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            testid="customer-send-menu-trigger"
            style={navyTriggerStyle}
            className={navyTriggerClass}
          >
            Send <ChevronDown size={14} />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem
            disabled={!primaryEmail}
            onSelect={() => onSend?.({ channel: "email", to: primaryEmail })}
            data-testid="customer-send-email"
          >
            <Mail size={14} className="mr-2" /> Email
          </DropdownMenuItem>
          <DropdownMenuItem
            disabled={!primaryMobile}
            onSelect={() => onSend?.({ channel: "sms", to: primaryMobile })}
            data-testid="customer-send-sms"
          >
            <MessageSquare size={14} className="mr-2" /> Text (SMS)
          </DropdownMenuItem>
          {/* Task 6 · Feb 2026 — Send service records link. Opens a
              dedicated modal that dispatches a signed portal
              auto-login URL to the customer via Email or SMS. */}
          <DropdownMenuItem
            onSelect={() => onSendServiceRecordsLink?.()}
            data-testid="customer-send-service-records-link"
          >
            <Link2 size={14} className="mr-2" /> Service records link
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      {/* + Create ▼ */}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            testid="customer-create-menu-trigger"
            style={navyTriggerStyle}
            className={navyTriggerClass}
          >
            <Plus size={14} /> Create <ChevronDown size={14} />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem
            onSelect={() => navigate(`/jobs/new?customer_id=${cid}`)}
            data-testid="customer-create-visit"
          >
            <Calendar size={14} className="mr-2" /> Visit
          </DropdownMenuItem>
          <DropdownMenuItem
            onSelect={() => navigate(`/payments/new?customer_id=${cid}`)}
            data-testid="customer-create-payment"
          >
            <DollarSign size={14} className="mr-2" /> Payment
          </DropdownMenuItem>
          <DropdownMenuItem
            onSelect={() => navigate(`/quotes/new?customer_id=${cid}`)}
            data-testid="customer-create-estimate"
          >
            <FileText size={14} className="mr-2" />
            <span className="flex flex-col leading-tight">
              <span>Estimate &rarr; Quote</span>
              <span className="text-[10px] text-slate-500">Creates a quote you can send, sign, and collect on.</span>
            </span>
          </DropdownMenuItem>
          <DropdownMenuItem
            onSelect={() => navigate(`/invoices/new?customer_id=${cid}`)}
            data-testid="customer-create-invoice"
          >
            <ClipboardCheck size={14} className="mr-2" /> Invoice
          </DropdownMenuItem>
          <DropdownMenuItem
            onSelect={() => onQuickTask?.()}
            data-testid="customer-create-todo"
          >
            <ListChecks size={14} className="mr-2" /> To-Do
          </DropdownMenuItem>
          <DropdownMenuItem
            onSelect={() =>
              navigate(`/jobs/new?customer_id=${cid}&visit_type=meeting`)
            }
            data-testid="customer-create-meeting"
          >
            <Users size={14} className="mr-2" /> Meeting
          </DropdownMenuItem>
          {/* Feb-2026 · Chemistry submenu — folds the previous
              standalone "Chemistry" brand-colored dropdown on the
              customer header row into ``+ Create``. Both original
              options and their pre-P52 legacy testids are preserved
              so every existing suite that clicks by testid keeps
              resolving. */}
          <DropdownMenuSub>
            <DropdownMenuSubTrigger
              data-testid="customer-create-chemistry-submenu"
              className="flex items-center gap-2"
            >
              <Beaker size={14} className="mr-2" /> Chemistry…
            </DropdownMenuSubTrigger>
            <DropdownMenuPortal>
              <DropdownMenuSubContent>
                <DropdownMenuItem
                  onSelect={() => navigate(`/customers/${cid}/chemistry`)}
                  data-testid="cd-action-chemistry"
                  data-legacy-testid="cd-chemistry"
                >
                  <Beaker size={14} className="mr-2" /> Chemistry
                </DropdownMenuItem>
                <DropdownMenuItem
                  onSelect={() =>
                    navigate(`/customers/${cid}/chemistry-history`)
                  }
                  data-testid="cd-action-chem-history"
                  data-legacy-testid="cd-chemistry-history"
                >
                  <Beaker size={14} className="mr-2" /> Chemistry History
                </DropdownMenuItem>
              </DropdownMenuSubContent>
            </DropdownMenuPortal>
          </DropdownMenuSub>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

export default CustomerActionDropdowns;
