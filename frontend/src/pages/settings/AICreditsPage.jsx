import React, { useEffect, useState } from "react";
import { api } from "@/api";
import { useAuth } from "@/auth";
import { toast } from "sonner";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { CreditCard, Sparkles, TrendingUp, AlertCircle } from "lucide-react";

/**
 * QuoteIQ Q1-UI · AI Credits admin page.
 *
 * Balance header + plan selector (super only) + top-up modal (super only)
 * + paginated transactions table with feature filter. Bearer JWT via api.
 */
export default function AICreditsPage() {
  const { user } = useAuth();
  const isSuper = user?.role === "super_admin";
  const [balance, setBalance] = useState(null);
  const [txns, setTxns] = useState([]);
  const [cursor, setCursor] = useState(null);
  const [nextCursor, setNextCursor] = useState(null);
  const [feature, setFeature] = useState("");
  const [topupOpen, setTopupOpen] = useState(false);
  const [topupAmt, setTopupAmt] = useState("");
  const [topupNote, setTopupNote] = useState("");
  const [planPicker, setPlanPicker] = useState("");
  const [loading, setLoading] = useState(false);

  const loadBalance = async () => {
    try {
      const d = await api.get("/ai-credits/balance");
      setBalance(d);
      setPlanPicker(d.plan);
    } catch (e) {
      toast.error("Could not load AI credits balance");
    }
  };

  const loadTxns = async (afterCursor = null) => {
    setLoading(true);
    try {
      const qs = new URLSearchParams();
      qs.set("limit", "20");
      if (feature) qs.set("feature", feature);
      if (afterCursor) qs.set("cursor", afterCursor);
      const d = await api.get(`/ai-credits/transactions?${qs.toString()}`);
      setTxns(afterCursor ? [...txns, ...d.transactions] : d.transactions);
      setNextCursor(d.next_cursor);
      setCursor(afterCursor);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadBalance();
  }, []);

  useEffect(() => {
    loadTxns();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [feature]);

  const submitTopup = async () => {
    const amt = parseInt(topupAmt, 10);
    if (!amt || amt < 1) {
      toast.error("Amount must be a positive integer");
      return;
    }
    try {
      await api.post("/ai-credits/topup", {
        amount: amt,
        note: topupNote || "manual_topup",
      });
      toast.success(`Added ${amt.toLocaleString()} credits`);
      setTopupOpen(false);
      setTopupAmt("");
      setTopupNote("");
      await loadBalance();
      await loadTxns();
    } catch (e) {
      toast.error(e?.message || "Top-up failed");
    }
  };

  const submitPlanChange = async () => {
    if (!planPicker || planPicker === balance?.plan) return;
    try {
      await api.patch("/ai-credits/plan", { plan: planPicker });
      toast.success(`Plan set to ${planPicker}`);
      await loadBalance();
      await loadTxns();
    } catch (e) {
      toast.error(e?.message || "Plan change failed");
    }
  };

  if (!balance)
    return (
      <div className="p-6 text-sm text-muted-foreground">
        Loading AI credits…
      </div>
    );

  const pctLeft = balance.monthly_grant
    ? Math.max(0, (balance.balance / balance.monthly_grant) * 100)
    : 0;
  const bannerTone =
    balance.balance <= 0
      ? "bg-red-50 text-red-800 border-red-200"
      : balance.warning
        ? "bg-yellow-50 text-yellow-800 border-yellow-200"
        : "hidden";

  return (
    <div
      className="p-6 space-y-6 max-w-6xl mx-auto"
      data-testid="ai-credits-page"
    >
      <div className="flex items-center gap-3">
        <Sparkles className="w-6 h-6 text-sky-600" />
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">AI Credits</h1>
          <p className="text-sm text-muted-foreground">
            Fuel for AI-powered estimates, autopilot copy, before/after
            renders, and virtual call agents.
          </p>
        </div>
      </div>

      <div
        className={`border rounded-md px-4 py-3 text-sm flex items-center gap-2 ${bannerTone}`}
        data-testid="ai-credits-warning"
      >
        <AlertCircle className="w-4 h-4" />
        {balance.balance <= 0
          ? "Balance is at or below zero. AI features will keep running but you should top up or upgrade the plan."
          : "You're below 20% of your monthly grant. Consider a top-up before the next reset."}
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <Card data-testid="ai-credits-balance-card">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-muted-foreground">
              Current Balance
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-4xl font-semibold tracking-tight">
              {balance.balance.toLocaleString()}
            </div>
            <div className="mt-2 h-2 rounded bg-gray-200 overflow-hidden">
              <div
                className={`h-full ${
                  balance.warning ? "bg-yellow-500" : "bg-sky-500"
                }`}
                style={{ width: `${Math.min(100, pctLeft)}%` }}
              />
            </div>
            <div className="text-xs mt-1 text-muted-foreground">
              of {balance.monthly_grant.toLocaleString()} monthly grant
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-muted-foreground">
              Plan
            </CardTitle>
          </CardHeader>
          <CardContent>
            <Badge className="text-base py-1 px-3 capitalize" variant="outline">
              {balance.plan}
            </Badge>
            <div className="text-xs mt-2 text-muted-foreground">
              Last reset:{" "}
              {balance.last_reset_at
                ? new Date(balance.last_reset_at).toLocaleString()
                : "—"}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-muted-foreground">
              Actions
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {isSuper && (
              <>
                <div className="flex gap-2 items-center">
                  <Select value={planPicker} onValueChange={setPlanPicker}>
                    <SelectTrigger
                      className="flex-1"
                      data-testid="ai-credits-plan-select"
                    >
                      <SelectValue placeholder="Plan" />
                    </SelectTrigger>
                    <SelectContent>
                      {Object.entries(balance.available_plans || {}).map(
                        ([k, v]) => (
                          <SelectItem key={k} value={k}>
                            {k} — {v.toLocaleString()}/mo
                          </SelectItem>
                        ),
                      )}
                    </SelectContent>
                  </Select>
                  <Button
                    size="sm"
                    onClick={submitPlanChange}
                    disabled={planPicker === balance.plan}
                    data-testid="ai-credits-plan-save"
                  >
                    Save
                  </Button>
                </div>
                <Button
                  className="w-full"
                  onClick={() => setTopupOpen(true)}
                  data-testid="ai-credits-topup-open"
                >
                  <CreditCard className="w-4 h-4 mr-2" />
                  Top up
                </Button>
              </>
            )}
            {!isSuper && (
              <p className="text-xs text-muted-foreground">
                Plan changes and top-ups require super-admin access.
              </p>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="flex flex-row items-center gap-3">
          <TrendingUp className="w-4 h-4 text-muted-foreground" />
          <CardTitle className="text-base">Transactions</CardTitle>
          <div className="ml-auto w-52">
            <Select value={feature || "__all"} onValueChange={(v) => setFeature(v === "__all" ? "" : v)}>
              <SelectTrigger data-testid="ai-credits-feature-filter">
                <SelectValue placeholder="All features" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__all">All features</SelectItem>
                <SelectItem value="estimator">estimator</SelectItem>
                <SelectItem value="autopilot">autopilot</SelectItem>
                <SelectItem value="before_after">before/after</SelectItem>
                <SelectItem value="virtual_call">virtual call</SelectItem>
                <SelectItem value="other">other</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-muted-foreground text-xs uppercase tracking-wide">
                  <th className="py-2 pr-4">When</th>
                  <th className="py-2 pr-4">Feature</th>
                  <th className="py-2 pr-4">Reason</th>
                  <th className="py-2 pr-4 text-right">Delta</th>
                  <th className="py-2 pr-4 text-right">Balance After</th>
                </tr>
              </thead>
              <tbody>
                {txns.length === 0 && !loading && (
                  <tr>
                    <td
                      colSpan={5}
                      className="py-6 text-center text-muted-foreground"
                    >
                      No transactions yet.
                    </td>
                  </tr>
                )}
                {txns.map((t) => (
                  <tr key={t.id} className="border-b last:border-b-0">
                    <td className="py-2 pr-4 whitespace-nowrap">
                      {new Date(t.created_at).toLocaleString()}
                    </td>
                    <td className="py-2 pr-4">
                      <Badge variant="outline">{t.feature}</Badge>
                    </td>
                    <td className="py-2 pr-4">{t.reason}</td>
                    <td
                      className={`py-2 pr-4 text-right font-medium ${
                        t.delta < 0 ? "text-red-600" : "text-emerald-600"
                      }`}
                    >
                      {t.delta > 0 ? "+" : ""}
                      {t.delta.toLocaleString()}
                    </td>
                    <td className="py-2 pr-4 text-right">
                      {t.balance_after.toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {nextCursor && (
            <div className="mt-4 text-center">
              <Button
                variant="outline"
                onClick={() => loadTxns(nextCursor)}
                disabled={loading}
                data-testid="ai-credits-load-more"
              >
                Load more
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog open={topupOpen} onOpenChange={setTopupOpen}>
        <DialogContent data-testid="ai-credits-topup-modal">
          <DialogHeader>
            <DialogTitle>Top up credits</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <Label>Amount (credits)</Label>
              <Input
                type="number"
                min="1"
                value={topupAmt}
                onChange={(e) => setTopupAmt(e.target.value)}
                placeholder="e.g. 1000"
                data-testid="ai-credits-topup-amount"
              />
            </div>
            <div>
              <Label>Note (optional)</Label>
              <Input
                value={topupNote}
                onChange={(e) => setTopupNote(e.target.value)}
                placeholder="e.g. quarterly boost"
                data-testid="ai-credits-topup-note"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setTopupOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={submitTopup}
              data-testid="ai-credits-topup-submit"
            >
              Add credits
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
