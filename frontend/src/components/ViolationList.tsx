import type { Severity, Violation, ViolationStatus } from "../types";
import { Card, SectionHeader } from "./Card";

interface Props {
  items: Violation[];
  activeId?: string;
  onSelect: (id: string) => void;
}

const STATUS_CLS: Record<ViolationStatus, string> = {
  OPEN: "border-status-critical/40 text-status-critical",
  IN_REMEDIATION: "border-status-warn/40 text-status-warn",
  RESOLVED: "border-status-ok/40 text-status-ok",
  DISMISSED: "border-line text-text-muted",
};

const SEVERITY_CLS: Record<Severity, string> = {
  LOW: "text-text-muted",
  MEDIUM: "text-status-info",
  HIGH: "text-status-warn",
  CRITICAL: "text-status-critical",
};

export function ViolationList({ items, activeId, onSelect }: Props) {
  return (
    <Card className="overflow-hidden">
      <SectionHeader title="Violations" meta={`${items.length} total`} />
      {items.length === 0 ? (
        <div className="px-4 py-6 text-sm text-text-muted">No violations recorded.</div>
      ) : (
        <ul className="divide-y divide-line">
          {items.map((v) => {
            const isActive = v.violation_id === activeId;
            return (
              <li key={v.violation_id}>
                <button
                  onClick={() => onSelect(v.violation_id)}
                  className={`flex w-full flex-col gap-1 px-4 py-3 text-left transition ${
                    isActive ? "bg-surface-alt" : "hover:bg-surface-alt/60"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-[11px] text-text-muted">
                      {v.violation_id}
                    </span>
                    <span
                      className={`rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${STATUS_CLS[v.status]}`}
                    >
                      {v.status.replace("_", " ")}
                    </span>
                  </div>
                  <div className="flex items-center gap-1.5 text-sm font-medium text-text-primary">
                    <span
                      className={`text-[10px] font-semibold uppercase ${SEVERITY_CLS[v.severity]}`}
                    >
                      {v.severity}
                    </span>
                    <span className="text-text-secondary">·</span>
                    <span>{v.reg_code ?? v.regulation_id}</span>
                  </div>
                  <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-text-muted">
                    <span className="rounded border border-line bg-surface-alt px-1.5 py-0.5 uppercase tracking-wider">
                      {v.trigger_type}
                    </span>
                    <span className="font-mono">{v.violation_type}</span>
                  </div>
                  <div className="text-xs text-text-secondary line-clamp-2">
                    {v.breach_detail}
                  </div>
                  <div className="text-[11px] text-text-muted font-mono">
                    {v.account_id} · {new Date(v.detected_at).toLocaleString()}
                  </div>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
