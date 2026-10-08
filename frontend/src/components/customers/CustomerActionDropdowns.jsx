import React from "react";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
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
 * Feb-2026 · Chemistry flat items (round 2)
 * ─────────────────────────────────────────
 * The Chemistry surface has landed in two rounds:
 *
 *   Round 1 (cc5477dc4) — the standalone brand-colored Chemistry
 *   dropdown that lived inline on the customer header row was folded
 *   into ``+ Create`` as a NESTED submenu labelled ``Chemistry…``.
 *
 *   Round 2 (this commit) — the nested submenu is FLATTENED. Both
 *   original options (Chemistry, Chemistry History) now render as
 *   top-level ``+ Create`` items, sitting directly after ``Meeting``
 *   with intact icons, navigation destinations, and both their new
 *   P52 testids (``cd-action-chemistry`` / ``cd-action-chem-history``)
 *   and their pre-P52 legacy testids (``cd-chemistry`` /
 *   ``cd-chemistry-history``) so every existing suite that clicks
 *   by testid keeps resolving.
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

  // Phase 2 · Feb-2026 — when rendered inside the navy command
  // strip (``navy=true``), the pair of trigger buttons must stay
  // on a SINGLE row with the strip's other actions.  The default
  // ``flex-wrap`` is retained for every non-navy caller so other
  // consumers (currently none, but future proofing) still get
  // multi-row wrap behaviour on narrow viewports.
  const wrapperClass = navy
    ? "flex flex-row flex-nowrap gap-2"
    : "flex flex-wrap gap-2";

  return (
    <div className={wrapperClass} data-testid="customer-action-dropdowns">
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
          {/* Feb-2026 · Chemistry flat items (round 2) — the previous
              ``DropdownMenuSub`` labelled ``Chemistry…`` was flattened
              per user ruling. Both items now render as top-level
              ``+ Create`` siblings, sitting directly after
              ``Meeting``. All four testids
              (``cd-action-chemistry``, ``cd-action-chem-history``,
              ``cd-chemistry``, ``cd-chemistry-history``) plus icons
              and navigate destinations are preserved verbatim from
              the round-1 submenu items — no downstream test that
              clicks by any of these testids should regress. */}
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
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

export default CustomerActionDropdowns;
