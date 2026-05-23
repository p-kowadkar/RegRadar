import { Bot, Clock, ShieldX, User } from "lucide-react";
import type { RemediationStep, Severity, Violation, ViolationStatus } from "../types";
import { Card, SectionHeader } from "./Card";

interface Props {
  violation: Violation;
}

const STATUS_BADGE: Record<ViolationStatus, string> = {
  OPEN: "border-status-critical/40 text-status-critical",
  IN_REMEDIATION: "border-status-warn/40 text-status-warn",
  RESOLVED: "border-status-ok/40 text-status-ok",
  DISMISSED: "border-line text-text-muted",
};

const SEVERITY_BADGE: Record<Severity, string> = {
  LOW: "border-line text-text-muted",
  MEDIUM: "border-status-info/40 text-status-info",
  HIGH: "border-status-warn/40 text-status-warn",
  CRITICAL: "border-status-critical/40 text-status-critical",
};

export function ViolationTimeline({ violation }: Props) {
  return (
    <Card>
      <SectionHeader
        title="Remediation plan"
        meta={
          <span className="font-mono text-[11px]">
            {violation.violation_id} · {violation.violation_type}
          </span>
        }
      />
      <div className="border-b border-line px-4 py-3">
        <div className="flex flex-wrap items-center gap-2 text-[11px] uppercase tracking-wider text-text-muted">
          <span className="rounded border border-line bg-surface-alt px-1.5 py-0.5 normal-case tracking-normal">
            {violation.trigger_type}
          </span>
          <span className="text-text-muted">·</span>
          <span>Asset</span>
          <code className="font-mono text-[11px] text-text-secondary normal-case">
            {violation.asset_name ?? violation.asset_id}
          </code>
          <span className="text-text-muted">·</span>
          <span>Field</span>
          <code className="font-mono text-[11px] text-text-secondary normal-case">
            {violation.field_name ?? violation.cde_id}
          </code>
          <span className="text-text-muted">·</span>
          <span>Account</span>
          <code className="font-mono text-[11px] text-text-secondary normal-case">
            {violation.account_id}
          </code>
        </div>
        <div className="mt-2 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <ShieldX size={14} className="text-status-critical" />
            <h2 className="text-base font-semibold text-text-primary">
              {violation.reg_code ?? violation.regulation_id}
              <span className="ml-2 text-text-secondary font-normal">
                {violation.control_name ?? ""}
              </span>
            </h2>
          </div>
          <div className="flex items-center gap-1.5">
            <span
              className={`rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${SEVERITY_BADGE[violation.severity]}`}
            >
              {violation.severity}
            </span>
            <span
              className={`rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${STATUS_BADGE[violation.status]}`}
            >
              {violation.status.replace("_", " ")}
            </span>
          </div>
        </div>
        <p className="mt-1 text-sm text-text-secondary">{violation.breach_detail}</p>
        <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-text-muted">
          <span>
            Detected{" "}
            <span className="text-text-secondary">
              {new Date(violation.detected_at).toLocaleString()}
            </span>
          </span>
          {violation.days_in_breach > 0 && (
            <span>
              In breach for{" "}
              <span className="text-text-secondary">{violation.days_in_breach} days</span>
            </span>
          )}
          {violation.resolved_at && (
            <span>
              Resolved{" "}
              <span className="text-text-secondary">
                {new Date(violation.resolved_at).toLocaleString()}
              </span>
            </span>
          )}
        </div>
      </div>

      {violation.steps.length === 0 ? (
        <div className="px-4 py-6 text-sm text-text-muted">
          No remediation steps registered for this violation type.
        </div>
      ) : (
        <ol className="divide-y divide-line">
          {violation.steps.map((s, i) => (
            <StepRow key={s.step_id} step={s} isLast={i === violation.steps.length - 1} />
          ))}
        </ol>
      )}
    </Card>
  );
}

function StepRow({ step, isLast }: { step: RemediationStep; isLast: boolean }) {
  const Icon = step.automated ? Bot : User;
  const tone = step.automated
    ? { text: "text-status-info", ring: "border-status-info/40 bg-status-info/10" }
    : step.requires_approval
      ? { text: "text-status-warn", ring: "border-status-warn/40 bg-status-warn/10" }
      : { text: "text-text-secondary", ring: "border-line bg-surface-alt" };

  return (
    <li className="flex gap-4 px-4 py-4">
      <div className="flex flex-col items-center pt-1">
        <div
          className={`flex h-7 w-7 items-center justify-center rounded-full border ${tone.ring}`}
        >
          <Icon size={13} className={tone.text} />
        </div>
        {!isLast && <div className="mt-1 h-full w-px bg-line" />}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-[11px] text-text-muted">
            {String(step.step_number).padStart(2, "0")}
          </span>
          <span className="text-[10px] font-semibold uppercase tracking-wider text-text-muted">
            {step.automated
              ? "auto"
              : step.requires_approval
                ? "approval"
                : "manual"}
          </span>
          <span className="text-text-muted">·</span>
          <span className="font-mono text-[11px] text-text-secondary">
            {step.action_type}
          </span>
          <span className="text-text-muted">·</span>
          <span className={`inline-flex items-center gap-1 text-xs ${tone.text}`}>
            <Clock size={11} /> {step.estimated_minutes} min
          </span>
        </div>
        <div className="mt-0.5 text-sm font-semibold text-text-primary">
          {step.step_title}
        </div>
        <div className="text-sm text-text-secondary">{step.step_description}</div>
      </div>
    </li>
  );
}
