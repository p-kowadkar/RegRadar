import { useState } from "react";
import { KeyRound, Play, Server } from "lucide-react";
import { api } from "../api/client";
import type { BudgetState, CrawlResponse, Regulation } from "../types";
import { Card, SectionHeader } from "./Card";

interface Props {
  regulations: Regulation[];
  budget: BudgetState | null;
  hasLLMKey: boolean;
  onOpenSettings: () => void;
}

export function LiveCrawlPanel({
  regulations,
  budget,
  hasLLMKey,
  onOpenSettings,
}: Props) {
  const [selectedReg, setSelectedReg] = useState<string>(
    regulations[0]?.regulation_id ?? "REG-005",
  );
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<CrawlResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleRun = async () => {
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      const r = await api.triggerCrawl(selectedReg);
      setResult(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  };

  const budgetExhausted = budget !== null && budget.used >= budget.budget;
  const disabled = running || (!hasLLMKey && budgetExhausted);

  return (
    <Card>
      <SectionHeader
        title="Run live crawl"
        meta={
          <div className="flex items-center gap-3 text-[11px]">
            {hasLLMKey ? (
              <span className="inline-flex items-center gap-1 text-status-info">
                <KeyRound size={10} />
                BYOK active
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 text-text-muted">
                <Server size={10} />
                Demo pool
              </span>
            )}
            {budget && !hasLLMKey && (
              <span className="font-mono text-text-muted">
                {budget.used}/{budget.budget} today
              </span>
            )}
          </div>
        }
      />
      <div className="space-y-3 p-4">
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-[200px] flex-1">
            <label className="mb-1 block text-xxs font-semibold uppercase tracking-[0.16em] text-text-secondary">
              Regulation
            </label>
            <select
              value={selectedReg}
              onChange={(e) => setSelectedReg(e.target.value)}
              disabled={running}
              className="w-full rounded border border-line bg-surface-alt px-2 py-1.5 text-sm text-text-primary focus:border-line-strong focus:outline-none"
            >
              {regulations.length === 0 ? (
                <option value="REG-005">REG-005 (FCRA Section 605)</option>
              ) : (
                regulations.map((r) => (
                  <option key={r.regulation_id} value={r.regulation_id}>
                    {r.regulation_id} — {r.reg_code} ({r.control_name})
                  </option>
                ))
              )}
            </select>
          </div>
          <button
            onClick={handleRun}
            disabled={disabled}
            className="inline-flex items-center gap-2 rounded border border-brand/40 bg-brand/20 px-3 py-1.5 text-xs font-semibold text-brand transition hover:bg-brand/30 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Play size={12} />
            {running ? "Crawling..." : "Crawl now"}
          </button>
          {!hasLLMKey && (
            <button
              onClick={onOpenSettings}
              className="text-[11px] text-text-muted underline-offset-2 hover:text-brand hover:underline"
            >
              Use your own keys
            </button>
          )}
        </div>

        {budgetExhausted && !hasLLMKey && (
          <div className="rounded border border-status-critical/40 bg-status-critical/10 px-3 py-2 text-xs text-status-critical">
            Daily demo budget exhausted ({budget?.used}/{budget?.budget}).
            Bring your own key to keep crawling, or wait until UTC midnight.
          </div>
        )}

        {error && (
          <div className="rounded border border-status-critical/40 bg-status-critical/10 px-3 py-2 text-xs text-status-critical">
            {error}
          </div>
        )}

        {result && <CrawlResultCard result={result} />}
      </div>
    </Card>
  );
}

function CrawlResultCard({ result }: { result: CrawlResponse }) {
  const v = result.result;
  return (
    <div className="space-y-3 rounded border border-line bg-surface-alt p-3">
      <div className="flex flex-wrap items-center gap-3 text-[11px]">
        <span className="font-mono text-text-muted">
          {result.trigger_id.slice(0, 8)}
        </span>
        <span className="text-text-secondary">{result.regulation_id}</span>
        <span className="text-text-muted">
          {result.elapsed_seconds}s
        </span>
        {result.used_byok && (
          <span className="inline-flex items-center gap-1 rounded border border-status-info/40 bg-status-info/10 px-1.5 py-0.5 text-status-info">
            <KeyRound size={10} />
            BYOK LLM
          </span>
        )}
        {result.used_byok_scraper && (
          <span className="inline-flex items-center gap-1 rounded border border-status-info/40 bg-status-info/10 px-1.5 py-0.5 text-status-info">
            <KeyRound size={10} />
            BYOK scraper
          </span>
        )}
      </div>

      {result.notes.length > 0 && (
        <ul className="space-y-1 text-[11px] text-text-muted">
          {result.notes.map((n, i) => (
            <li key={i}>· {n}</li>
          ))}
        </ul>
      )}

      {v ? (
        <div className="space-y-2 border-t border-line pt-3 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={`rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${
                v.is_material_change
                  ? "border-status-warn/40 text-status-warn"
                  : "border-line text-text-muted"
              }`}
            >
              {v.change_type}
            </span>
            {v.is_material_change && (
              <span className="text-[11px] text-status-warn">material change</span>
            )}
            <span className="font-mono text-[11px] text-text-muted">
              v{v.new_version}
            </span>
          </div>
          <div className="text-text-primary">{v.change_summary}</div>
          {v.relevant_excerpt && (
            <details className="text-[11px] text-text-muted">
              <summary className="cursor-pointer hover:text-text-secondary">
                Source excerpt
              </summary>
              <blockquote className="mt-2 border-l-2 border-line pl-2 italic">
                {v.relevant_excerpt.slice(0, 600)}
                {v.relevant_excerpt.length > 600 && "..."}
              </blockquote>
            </details>
          )}
        </div>
      ) : (
        <div className="border-t border-line pt-2 text-[11px] text-text-muted">
          No verification returned (scrape failed or regulation not found).
        </div>
      )}
    </div>
  );
}
