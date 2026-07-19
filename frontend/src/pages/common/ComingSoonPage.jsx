/**
 * Tech Nav 404 Fix · Feb 2026 — placeholder page for features linked
 * from the tech hamburger but not yet available to the technician role.
 *
 * Renders a "Coming soon" panel with a hint about who to contact today
 * (usually the admin) and a link back to the schedule. Prevents the
 * hard 404 users were hitting while a proper tech-side view is scoped.
 */
import React from "react";
import { Link } from "react-router-dom";
import { CalendarDays, Info } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

export default function ComingSoonPage({
  title = "Coming soon",
  message = "This area is being prepared for the technician workspace.",
  contactHint = "Ask an admin for a lookup in the meantime.",
  testId = "tech-coming-soon",
}) {
  return (
    <div className="p-6 max-w-2xl mx-auto" data-testid={testId}>
      <Card className="p-8 flex flex-col items-start gap-4">
        <div className="flex items-center gap-3">
          <Info className="text-blue-600" size={28} />
          <h1 className="text-2xl font-semibold" data-testid={`${testId}-title`}>{title}</h1>
        </div>
        <p className="text-slate-700" data-testid={`${testId}-message`}>{message}</p>
        <p className="text-sm text-slate-500" data-testid={`${testId}-hint`}>{contactHint}</p>
        <Button asChild data-testid={`${testId}-back-btn`} className="mt-2">
          <Link to="/schedule">
            <CalendarDays className="mr-2 h-4 w-4" />
            Back to my schedule
          </Link>
        </Button>
      </Card>
    </div>
  );
}
