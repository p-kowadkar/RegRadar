import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { DashboardSummary } from "../types";
import { Card, SectionHeader } from "./Card";

interface Props {
  data: DashboardSummary["byPolicy"];
}

export function PolicyBreakdownChart({ data }: Props) {
  return (
    <Card>
      <SectionHeader title="Compliance by policy" meta="monitored asset count" />
      <div className="px-3 py-3">
        <div className="h-56 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
              <CartesianGrid stroke="#2a323d" strokeDasharray="3 3" vertical={false} />
              <XAxis
                dataKey="policy"
                tick={{ fill: "#9da7b3", fontSize: 11 }}
                axisLine={{ stroke: "#2a323d" }}
                tickLine={false}
              />
              <YAxis
                allowDecimals={false}
                tick={{ fill: "#9da7b3", fontSize: 11 }}
                axisLine={{ stroke: "#2a323d" }}
                tickLine={false}
              />
              <Tooltip
                cursor={{ fill: "rgba(45,212,191,0.08)" }}
                contentStyle={{
                  background: "#161b22",
                  border: "1px solid #2a323d",
                  borderRadius: 6,
                  color: "#e6edf3",
                  fontSize: 12,
                }}
              />
              <Legend wrapperStyle={{ fontSize: 11, color: "#9da7b3" }} iconType="square" />
              <Bar dataKey="compliant" stackId="s" fill="#16a34a" name="Compliant" />
              <Bar dataKey="at_risk" stackId="s" fill="#d97706" name="At risk" />
              <Bar dataKey="out_of_compliance" stackId="s" fill="#dc2626" name="Out of compliance" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </Card>
  );
}
