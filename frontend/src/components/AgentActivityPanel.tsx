import { Activity, AlertCircle, Bot, CheckCircle2, Pause } from "lucide-react";
import type { AgentRun, AgentState } from "../types";
import { Card, SectionHeader } from "./Card";

interface Props {
  state: AgentState[];
  runs: AgentRun[];
}

const STATUS_CLS: Record<string, string> = {
  running: "border-status-ok/40 text-status-ok",
  paused: "border-status-warn/40 text-status-warn",
  error: "border-status-critical/40 text-status-critical",
  unknown: "border-line text-text-muted",
};

const STATUS_ICON: Record<string, typeof Activity> = {
  running: Activity,
  paused: Pause,
  error: AlertCircle,
  unknown: Bot,
};

export function AgentActivityPanel({ state, runs }: Props) {
  const noData = state.length === 0 && runs.length === 0;
  return (
    <Card>
      <SectionHeader
        title="Agent activity"
        meta={
          noData
            ? "Awaiting cloud schema for agent_state / agent_outputs"
            : `${state.length} agents · ${runs.length} runs`
        }
      />
      {noData ? (
        <div className="px-4 py-6 text-sm text-text-muted">
          The Impact Analysis Agent writes to{" "}
          <code className="font-mono text-xs text-text-secondary">agent_state</code> and{" "}
          <code className="font-mono text-xs text-text-secondary">agent_outputs</code>.
          Once those tables exist in ClickHouse Cloud, this panel populates automatically.
        </div>
      ) : (
        <div className="grid grid-cols-1 divide-y divide-line lg:grid-cols-2 lg:divide-y-0 lg:divide-x">
          <div className="p-4">
            <div className="mb-2 text-xxs font-semibold uppercase tracking-[0.16em] text-text-secondary">
              Live state
            </div>
            {state.length === 0 ? (
              <div className="text-sm text-text-muted">No state recorded.</div>
            ) : (
              <ul className="space-y-2">
                {state.map((s) => {
                  const Icon = STATUS_ICON[s.status] ?? Bot;
                  return (
                    <li
                      key={s.agent_id}
                      className="rounded border border-line bg-surface-alt px-3 py-2"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-2 font-mono text-xs text-text-primary">
                          <Icon size={12} className="text-brand" />
                          {s.agent_id}
                        </div>
                        <span
                          className={`rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${
                            STATUS_CLS[s.status] ?? STATUS_CLS.unknown
                          }`}
                        >
                          {s.status}
                        </span>
                      </div>
                      <div className="mt-1 grid grid-cols-2 gap-x-3 gap-y-0.5 text-[11px] text-text-muted">
                        <span>cycles</span>
                        <span className="text-right text-text-secondary tabular-nums">
                          {s.cycle_count.toLocaleString()}
                        </span>
                        <span>last cursor</span>
                        <span className="text-right font-mono text-text-secondary truncate">
                          {s.last_cursor || "—"}
                        </span>
                        <span>processed</span>
                        <span className="text-right text-text-secondary">
                          {s.last_processed_at
                            ? new Date(s.last_processed_at).toLocaleTimeString()
                            : "—"}
                        </span>
                      </div>
                      {s.last_error && (
                        <div className="mt-1 truncate text-[11px] text-status-critical">
                          {s.last_error}
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          <div className="p-4">
            <div className="mb-2 text-xxs font-semibold uppercase tracking-[0.16em] text-text-secondary">
              Recent runs
            </div>
            {runs.length === 0 ? (
              <div className="text-sm text-text-muted">No runs yet.</div>
            ) : (
              <ul className="space-y-2">
                {runs.slice(0, 6).map((r) => (
                  <li
                    key={r.trigger_id + r.agent_id + r.started_at}
                    className="rounded border border-line bg-surface-alt px-3 py-2"
                  >
                    <div className="flex items-center justify-between gap-2 text-xs">
                      <span className="font-mono text-text-primary">{r.agent_id}</span>
                      <span className="font-mono text-text-muted">
                        {r.duration_ms.toLocaleString()} ms
                      </span>
                    </div>
                    <div className="mt-0.5 flex items-center gap-2 text-[11px] text-text-muted">
                      <span className="font-mono">
                        {new Date(r.started_at).toLocaleTimeString()}
                      </span>
                      {r.response_type && (
                        <span className="rounded border border-line bg-surface px-1.5 py-0.5 normal-case tracking-normal">
                          {r.response_type}
                        </span>
                      )}
                      {r.auditor_verdict && (
                        <span
                          className={`inline-flex items-center gap-1 ${
                            r.auditor_verdict === "approved"
                              ? "text-status-ok"
                              : r.auditor_verdict === "rejected"
                                ? "text-status-critical"
                                : "text-status-warn"
                          }`}
                        >
                          <CheckCircle2 size={11} /> {r.auditor_verdict}
                        </span>
                      )}
                    </div>
                    {r.error && (
                      <div className="mt-1 truncate text-[11px] text-status-critical">
                        {r.error}
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </Card>
  );
}
