import { ComponentType } from "react";
import { LucideProps } from "lucide-react";
import { Card } from "./Card";

interface KpiCardProps {
  label: string;
  value: number | string;
  hint?: string;
  icon: ComponentType<LucideProps>;
  tone?: "neutral" | "ok" | "warn" | "critical" | "info" | "brand";
}

const TONE: Record<NonNullable<KpiCardProps["tone"]>, string> = {
  neutral: "text-text-secondary",
  ok: "text-status-ok",
  warn: "text-status-warn",
  critical: "text-status-critical",
  info: "text-status-info",
  brand: "text-brand",
};

export function KpiCard({ label, value, hint, icon: Icon, tone = "neutral" }: KpiCardProps) {
  return (
    <Card className="px-4 py-3.5">
      <div className="flex items-center justify-between gap-3">
        <div className="text-xxs font-semibold uppercase tracking-[0.16em] text-text-muted">
          {label}
        </div>
        <Icon size={14} className={TONE[tone]} />
      </div>
      <div className="mt-1.5 text-3xl font-semibold tabular-nums text-text-primary">
        {value}
      </div>
      {hint && <div className="mt-1 text-xs text-text-muted">{hint}</div>}
    </Card>
  );
}
