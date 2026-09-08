import React from "react";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
} from "@/components/ui/dropdown-menu";
import { Mail, MessageSquare, ChevronDown, Plus, Calendar, DollarSign, FileText, ClipboardCheck, ListChecks, Users, Link2 } from "lucide-react";
import { Button } from "@/components/ui-kit";
import { useNavigate } from "react-router-dom";

/**
 * Top-right Send ▼ + + Create ▼ dropdowns on the Customer detail page.
 * Feb-2026 Customer Detail Additions ship.
 *
 * All items pre-fill the target flow with the current customer via a
 * ``?customer_id=`` query param — every existing create route already
 * respects this convention, so no receiving-side changes are required.
 */
export function CustomerActionDropdowns({ customer, onSend, onQuickTask, onSendServiceRecordsLink }) {
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

  return (
    <div className="flex flex-wrap gap-2" data-testid="customer-action-dropdowns">
      {/* Send ▼ */}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" testid="customer-send-menu-trigger">
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
          <Button testid="customer-create-menu-trigger">
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
            <FileText size={14} className="mr-2" /> Estimate
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
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

export default CustomerActionDropdowns;
