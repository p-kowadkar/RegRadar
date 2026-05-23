import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  TooltipProps,
  XAxis,
  YAxis,
} from "recharts";
import type { DashboardSummary, Regulation } from "../types";
import { Card, SectionHeader } from "./Card";

interface Props {
  data: DashboardSummary["byPolicy"];
  regulations: Regulation[];
}

interface ChartDatum {
  reg_id: string;
  reg_code: string;
  control: string;
  // Two-line X-axis label: "Reg Z 1026.9(g)" / "Penalty Rate Notice"
  label: string;
  short: string;
  compliant: number;
  at_risk: number;
  out_of_compliance: number;
}

const SHORT_LABELS: Record<string, string> = {
  "Reg Z 1026.9(g)": "Reg Z 9(g)",
  "Reg Z 1026.13": "Reg Z 13",
  "FCRA Section 605": "FCRA 605",
  "FCRA Section 623(a)": "FCRA 623(a)",
};

function shorten(reg_code: string): string {
  return SHORT_LABELS[reg_code] ?? reg_code;
}

export function PolicyBreakdownChart({ data, regulations }: Props) {
  const regById = new Map(regulations.map((r) => [r.regulation_id, r]));

  const enriched: ChartDatum[] = data.map((b) => {
    const reg = regById.get(b.regulation_id);
    const reg_code = reg?.reg_code ?? b.reg_code;
    const control = reg?.control_name ?? "";
    const short = shorten(reg_code);
    return {
      reg_id: b.regulation_id,
      reg_code,
      control,
      label: control ? `${short} · ${control}` : short,
      short,
      compliant: b.compliant,
      at_risk: b.at_risk,
      out_of_compliance: b.out_of_compliance,
    };
  });

  return (
    <Card>
      <SectionHeader title="Compliance by policy" meta="monitored asset count" />
      <div className="px-3 py-3">
        <div className="h-72 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={enriched}
              margin={{ top: 8, right: 8, bottom: 60, left: -16 }}
            >
              <CartesianGrid stroke="#2a323d" strokeDasharray="3 3" vertical={false} />
              <XAxis
                dataKey="short"
                tick={{ fill: "#9da7b3", fontSize: 11 }}
                axisLine={{ stroke: "#2a323d" }}
                tickLine={false}
                interval={0}
                angle={-25}
                textAnchor="end"
                height={60}
              />
              <YAxis
                allowDecimals={false}
                tick={{ fill: "#9da7b3", fontSize: 11 }}
                axisLine={{ stroke: "#2a323d" }}
                tickLine={false}
              />
              <Tooltip
                cursor={{ fill: "rgba(45,212,191,0.08)" }}
                content={<PolicyTooltip />}
              />
              <Legend
                wrapperStyle={{ fontSize: 11, color: "#9da7b3" }}
                iconType="square"
              />
              <Bar dataKey="compliant" stackId="s" fill="#16a34a" name="Compliant" />
              <Bar dataKey="at_risk" stackId="s" fill="#d97706" name="At risk" />
              <Bar
                dataKey="out_of_compliance"
                stackId="s"
                fill="#dc2626"
                name="Out of compliance"
              />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </Card>
  );
}

function PolicyTooltip({ active, payload }: TooltipProps<number, string>) {
  if (!active || !payload || payload.length === 0) return null;
  const datum = payload[0]?.payload as ChartDatum | undefined;
  if (!datum) return null;

  return (
    <div className="rounded-md border border-line bg-surface-alt px-3 py-2 text-xs shadow-panel">
      <div className="flex items-center gap-2 font-mono text-[11px] text-text-muted">
        <span>{datum.reg_id}</span>
        <span>·</span>
        <span>{datum.reg_code}</span>
      </div>
      <div className="mt-0.5 text-sm font-semibold text-text-primary">
        {datum.control}
      </div>
      <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-0.5 text-text-secondary">
        <span>Compliant</span>
        <span className="text-right font-mono tabular-nums text-status-ok">
          {datum.compliant}
        </span>
        <span>At risk</span>
        <span className="text-right font-mono tabular-nums text-status-warn">
          {datum.at_risk}
        </span>
        <span>Out of compliance</span>
        <span className="text-right font-mono tabular-nums text-status-critical">
          {datum.out_of_compliance}
        </span>
      </div>
    </div>
  );
}
