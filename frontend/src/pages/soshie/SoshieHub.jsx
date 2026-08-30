/**
 * Phase S2 · Feb-2026 — Soshie Hub page.
 *
 * Three sub-tabs (Brand Brain, Autopilot Schedules, Review Queue)
 * plus an 8-platform Connect Grid.  All wired to the S1/S1.5
 * backend endpoints — no new page tree, no new mobile.
 *
 * Route: `/soshie` (Admin only).
 */
import React, { useState } from "react";
import { Sparkles } from "lucide-react";
import { Tabs, TabsList, TabsTrigger, TabsContent }
  from "@/components/ui/tabs";
import { PageHeader } from "@/components/ui-kit";
import BrandBrainTab from "./BrandBrainTab";
import AutopilotSchedulesTab from "./AutopilotSchedulesTab";
import ReviewQueueTab from "./ReviewQueueTab";

export default function SoshieHub() {
  const [tab, setTab] = useState("brand-brain");
  return (
    <div className="p-4 md:p-8 max-w-6xl mx-auto"
         data-testid="soshie-hub">
      <PageHeader
        title="Soshie · Social Publishing"
        subtitle="Brand memory, autopilot schedules, and review queue"
      />
      <Tabs value={tab} onValueChange={setTab} className="mt-4">
        <TabsList data-testid="soshie-tabs" className="mb-6">
          <TabsTrigger value="brand-brain"
                          data-testid="tab-brand-brain">
            <Sparkles size={14} className="mr-1.5" />
            Brand Brain
          </TabsTrigger>
          <TabsTrigger value="autopilot"
                          data-testid="tab-autopilot">
            Autopilot Schedules
          </TabsTrigger>
          <TabsTrigger value="review-queue"
                          data-testid="tab-review-queue">
            Review Queue
          </TabsTrigger>
        </TabsList>
        <TabsContent value="brand-brain"
                        data-testid="pane-brand-brain">
          <BrandBrainTab />
        </TabsContent>
        <TabsContent value="autopilot"
                        data-testid="pane-autopilot">
          <AutopilotSchedulesTab />
        </TabsContent>
        <TabsContent value="review-queue"
                        data-testid="pane-review-queue">
          <ReviewQueueTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
