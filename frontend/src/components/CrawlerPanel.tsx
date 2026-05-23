import { ExternalLink, FileEdit, GitBranch, ScanLine } from "lucide-react";
import type { PolicyChange, SchemaEvent } from "../types";
import { Card, SectionHeader } from "./Card";

interface Props {
  policyChanges: PolicyChange[];
  schemaEvents: SchemaEvent[];
  regulationCount: number;
}

export function CrawlerPanel({
  policyChanges,
  schemaEvents,
  regulationCount,
}: Props) {
  const recentChanges = policyChanges.slice(0, 6);
  const recentEvents = schemaEvents.slice(0, 4);
  return (
    <Card>
      <SectionHeader
        title="Trigger feed"
        meta={`${regulationCount} regulations · ${policyChanges.length} changes · ${schemaEvents.length} schema events`}
      />
      <div className="grid grid-cols-1 divide-y divide-line lg:grid-cols-2 lg:divide-y-0 lg:divide-x">
        <div className="p-4">
          <div className="mb-2 flex items-center gap-2 text-xxs font-semibold uppercase tracking-[0.16em] text-text-secondary">
            <GitBranch size={12} />
            Policy changes (Crawler)
          </div>
          {recentChanges.length === 0 ? (
            <div className="text-sm text-text-muted">No changes detected.</div>
          ) : (
            <ul className="space-y-2">
              {recentChanges.map((c) => (
                <li
                  key={c.change_id}
                  className="rounded border border-line bg-surface-alt px-3 py-2"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                    <span className="font-mono text-text-muted">
                      {c.change_id.slice(0, 8)}
                    </span>
                    <span className="font-mono text-text-secondary">
                      {c.reg_code ?? c.regulation_id}
                    </span>
                    <span
                      className={`rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${
                        c.material
                          ? "border-status-warn/40 text-status-warn"
                          : "border-line text-text-muted"
                      }`}
                    >
                      {c.change_type}
                    </span>
                  </div>
                  <div className="mt-1 text-sm text-text-primary">
                    {c.change_summary}
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-text-muted font-mono">
                    <span>{new Date(c.detected_at).toLocaleString()}</span>
                    {c.source_url && (
                      <a
                        href={c.source_url}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1 text-text-secondary hover:text-brand"
                      >
                        <ExternalLink size={10} />
                        source
                      </a>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="p-4">
          <div className="mb-2 flex items-center gap-2 text-xxs font-semibold uppercase tracking-[0.16em] text-text-secondary">
            <FileEdit size={12} />
            Schema events
          </div>
          {recentEvents.length === 0 ? (
            <div className="text-sm text-text-muted">No schema events yet.</div>
          ) : (
            <ul className="space-y-2">
              {recentEvents.map((e) => (
                <li
                  key={e.event_id}
                  className="rounded border border-line bg-surface-alt px-3 py-2"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                    <span className="font-mono text-text-muted">
                      {e.event_id.slice(0, 8)}
                    </span>
                    <span
                      className={`rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${
                        e.triggered_impact_analysis
                          ? "border-status-info/40 text-status-info"
                          : "border-line text-text-muted"
                      }`}
                    >
                      {e.event_type}
                    </span>
                  </div>
                  <div className="mt-1 text-sm text-text-primary">
                    <code className="font-mono text-xs">{e.field_name}</code>
                    <span className="mx-1 text-text-muted">on</span>
                    <code className="font-mono text-xs text-text-secondary">
                      {e.asset_name ?? e.asset_id}
                    </code>
                  </div>
                  <div className="mt-1 flex items-center gap-2 text-[11px] text-text-muted font-mono">
                    <ScanLine size={10} />
                    {e.rows_affected.toLocaleString()} rows ·{" "}
                    {new Date(e.detected_at).toLocaleString()}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </Card>
  );
}
