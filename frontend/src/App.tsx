import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  ListChecks,
  ShieldCheck,
} from "lucide-react";

import { api, API_BASE } from "./api/client";
import { Header } from "./components/Header";
import { KpiCard } from "./components/KpiCard";
import { PolicyBreakdownChart } from "./components/PolicyBreakdownChart";
import { ViolationTimeline } from "./components/ViolationTimeline";
import { ViolationList } from "./components/ViolationList";
import { CrawlerPanel } from "./components/CrawlerPanel";
import { RegulationsTable } from "./components/RegulationsTable";
import { AgentActivityPanel } from "./components/AgentActivityPanel";
import { CoverageMatrix } from "./components/CoverageMatrix";
import { SettingsModal } from "./components/SettingsModal";
import { TurnstileWidget } from "./components/TurnstileWidget";
import { LiveCrawlPanel } from "./components/LiveCrawlPanel";
import { useUserKeys } from "./hooks/useUserKeys";
import type {
  AgentRun,
  AgentState,
  BudgetState,
  CoverageRow,
  DashboardSummary,
  PolicyChange,
  Regulation,
  SchemaEvent,
  Violation,
} from "./types";

const POLL_MS = 10000;
const TURNSTILE_SITE_KEY = import.meta.env.VITE_TURNSTILE_SITE_KEY as string | undefined;

export default function App() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [violations, setViolations] = useState<Violation[]>([]);
  const [regulations, setRegulations] = useState<Regulation[]>([]);
  const [policyChanges, setPolicyChanges] = useState<PolicyChange[]>([]);
  const [schemaEvents, setSchemaEvents] = useState<SchemaEvent[]>([]);
  const [agentRuns, setAgentRuns] = useState<AgentRun[]>([]);
  const [agentState, setAgentState] = useState<AgentState[]>([]);
  const [coverage, setCoverage] = useState<CoverageRow[]>([]);
  const [budget, setBudget] = useState<BudgetState | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);

  const { keys, setKeys, hasLLMKey, hasScraperKey } = useUserKeys();

  const refresh = useCallback(async () => {
    try {
      const [s, v, r, pc, se, runs, st, cov, b] = await Promise.all([
        api.summary(),
        api.listViolations(),
        api.listRegulations(),
        api.listPolicyChanges(),
        api.listSchemaEvents(),
        api.listAgentRuns(),
        api.listAgentState(),
        api.listCoverage(),
        api.getBudget().catch(() => null),
      ]);
      setSummary(s);
      setViolations(v);
      setRegulations(r);
      setPolicyChanges(pc);
      setSchemaEvents(se);
      setAgentRuns(runs);
      setAgentState(st);
      setCoverage(cov);
      setBudget(b);
      setError(null);
      setActiveId((curr) => curr ?? v[0]?.violation_id ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = window.setInterval(refresh, POLL_MS);
    return () => window.clearInterval(id);
  }, [refresh]);

  const active = useMemo(
    () => violations.find((v) => v.violation_id === activeId) ?? violations[0] ?? null,
    [violations, activeId],
  );

  return (
    <div className="min-h-screen">
      <TurnstileWidget siteKey={TURNSTILE_SITE_KEY} />
      <SettingsModal
        open={settingsOpen}
        initial={keys}
        onSave={setKeys}
        onClose={() => setSettingsOpen(false)}
      />
      <Header
        pollMs={POLL_MS}
        apiUrl={API_BASE}
        onRefresh={refresh}
        onOpenSettings={() => setSettingsOpen(true)}
        byokActive={hasLLMKey || hasScraperKey}
      />

      <main className="mx-auto max-w-[1500px] px-6 py-5">
        {error && (
          <div className="mb-4 rounded border border-status-critical/40 bg-status-critical/10 px-3 py-2 text-sm text-status-critical">
            {error}
          </div>
        )}

        {/* KPI strip */}
        <section className="mb-5 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          <KpiCard
            label="Assets monitored"
            value={summary?.monitored ?? "—"}
            icon={Activity}
            tone="brand"
            hint="data_assets"
            source="SELECT count() FROM data_assets"
          />
          <KpiCard
            label="Accounted for"
            value={summary?.accountedFor ?? "—"}
            icon={ShieldCheck}
            tone="ok"
            hint="In scope of a regulation"
            source="asset_regulation_map.in_scope = true"
          />
          <KpiCard
            label="Out of compliance"
            value={summary?.outOfCompliance ?? "—"}
            icon={AlertTriangle}
            tone="critical"
            hint="OPEN + IN_REMEDIATION"
            source="compliance_violations.status IN (OPEN, IN_REMEDIATION)"
          />
          <KpiCard
            label="Suggested fixes"
            value={summary?.fixesSuggested ?? "—"}
            icon={ListChecks}
            tone="warn"
            hint="Steps for live violations"
            source="remediation_steps ⨝ violations(OPEN, IN_REMEDIATION)"
          />
          <KpiCard
            label="Fixes completed"
            value={summary?.fixesCompleted ?? "—"}
            icon={CheckCircle2}
            tone="ok"
            hint="RESOLVED violations"
            source="compliance_violations.status = RESOLVED"
          />
        </section>

        {/* Crawler + chart */}
        <section className="mb-5 grid grid-cols-1 gap-3 lg:grid-cols-3">
          <div className="lg:col-span-2">
            <CrawlerPanel
              policyChanges={policyChanges}
              schemaEvents={schemaEvents}
              regulationCount={regulations.length}
            />
          </div>
          <div>
            {summary && summary.byPolicy.length > 0 ? (
              <PolicyBreakdownChart
                data={summary.byPolicy}
                regulations={regulations}
              />
            ) : null}
          </div>
        </section>

        {/* Live crawl (BYOK end-to-end) */}
        <section className="mb-5">
          <LiveCrawlPanel
            regulations={regulations}
            budget={budget}
            hasLLMKey={hasLLMKey}
            onOpenSettings={() => setSettingsOpen(true)}
          />
        </section>

        {/* Violations + timeline */}
        <section className="mb-5 grid grid-cols-1 gap-3 lg:grid-cols-3">
          <div className="lg:col-span-1">
            <ViolationList
              items={violations}
              activeId={active?.violation_id}
              onSelect={setActiveId}
            />
          </div>
          <div className="lg:col-span-2">
            {active ? (
              <ViolationTimeline violation={active} />
            ) : (
              <div className="rounded border border-dashed border-line bg-surface px-6 py-12 text-center text-sm text-text-muted">
                No violations to inspect.
              </div>
            )}
          </div>
        </section>

        {/* Regulations registry */}
        <section className="mb-5">
          <RegulationsTable items={regulations} />
        </section>

        {/* Agent activity (Impact Analysis cursor + recent agent_outputs) */}
        <section className="mb-5">
          <AgentActivityPanel state={agentState} runs={agentRuns} />
        </section>

        {/* Coverage matrix */}
        <section className="mb-5">
          <CoverageMatrix rows={coverage} />
        </section>

        <footer className="mt-8 border-t border-line pt-3 text-xs text-text-muted">
          <div className="flex flex-wrap items-center gap-3 font-mono">
            <span>ClickHouse Cloud · regradar</span>
            <span>·</span>
            <span>Scrape · Nimble → Firecrawl</span>
            <span>·</span>
            <span>LLM · OpenRouter / Gemini (BYOK supported)</span>
          </div>
        </footer>
      </main>
    </div>
  );
}
