import React, { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "@/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  CartesianGrid,
} from "recharts";
import { FlaskConical } from "lucide-react";

/**
 * QuoteIQ Q1-UI · Per-customer chemistry profitability trend.
 * Distinct from the existing dose-calculator ``CustomerChemistry`` page.
 *
 * Route: /customers/:id/chemistry-history
 * Data:  GET /api/pools/{customer_id}/chemical-profitability?months=N
 */
export default function CustomerChemistryHistory() {
  const { id } = useParams();
  const [months, setMonths] = useState(6);
  const [data, setData] = useState(null);

  useEffect(() => {
    api
      .get(`/pools/${id}/chemical-profitability?months=${months}`)
      .then(setData)
      .catch(() => setData({ series: [], totals: { total_cost_cents: 0, visit_count: 0 } }));
  }, [id, months]);

  const centsToDollars = (c) => `$${((c || 0) / 100).toFixed(2)}`;
  const chartData = (data?.series || []).map((s) => ({
    month: s.month,
    cost: (s.total_cost_cents || 0) / 100,
    visits: s.visit_count,
  }));

  return (
    <div className="p-6 space-y-4 max-w-5xl mx-auto" data-testid="customer-chemistry-history">
      <div className="flex items-center gap-3">
        <FlaskConical className="w-6 h-6 text-sky-600" />
        <div>
          <h1 className="text-xl font-semibold tracking-tight">
            Chemistry Profitability
          </h1>
          <p className="text-sm text-muted-foreground">
            Cost of chemicals applied to this pool over the last {months} months.
          </p>
        </div>
        <div className="ml-auto">
          <select
            className="border rounded px-2 py-1 text-sm"
            value={months}
            onChange={(e) => setMonths(parseInt(e.target.value, 10))}
            data-testid="customer-chemistry-months"
          >
            <option value={3}>3 months</option>
            <option value={6}>6 months</option>
            <option value={12}>12 months</option>
            <option value={24}>24 months</option>
          </select>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader className="pb-1">
            <CardTitle className="text-xs text-muted-foreground uppercase">
              Total chemical spend
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-semibold">
              {centsToDollars(data?.totals?.total_cost_cents)}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-1">
            <CardTitle className="text-xs text-muted-foreground uppercase">
              Visits with chemicals
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-semibold">
              {data?.totals?.visit_count ?? 0}
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Monthly trend</CardTitle>
        </CardHeader>
        <CardContent>
          {chartData.length === 0 ? (
            <div className="text-sm text-muted-foreground py-10 text-center">
              No chemistry usage recorded in this window.
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="month" />
                <YAxis />
                <Tooltip />
                <Legend />
                <Line
                  type="monotone"
                  dataKey="cost"
                  name="Cost ($)"
                  stroke="#0ea5e9"
                  strokeWidth={2}
                />
                <Line
                  type="monotone"
                  dataKey="visits"
                  name="Visits"
                  stroke="#22c55e"
                  strokeWidth={2}
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
