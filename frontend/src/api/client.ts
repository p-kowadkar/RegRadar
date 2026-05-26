import type {
  AgentRun,
  AgentState,
  BudgetState,
  CoverageRow,
  CrawlResponse,
  DashboardSummary,
  DataAsset,
  PolicyChange,
  Regulation,
  SchemaEvent,
  TriggerResponse,
  TriggerScenario,
  UserKeys,
  Violation,
} from "../types";

const BASE = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

export const API_BASE = BASE;

// ════════════════════════════════════════════════════════════════
// Module-level mutable state -- set by useUserKeys + TurnstileWidget.
// Read on every outbound request so the latest values are always used.
// ════════════════════════════════════════════════════════════════

let _userKeys: UserKeys = {
  llmKey: "",
  llmProvider: "",
  llmModel: "",
  scraperKey: "",
  scraperProvider: "",
};
let _turnstileToken = "";

export function setUserKeys(keys: UserKeys): void {
  _userKeys = keys;
}

export function setTurnstileToken(token: string): void {
  _turnstileToken = token;
}

function buildHeaders(): Record<string, string> {
  const h: Record<string, string> = { "Content-Type": "application/json" };
  if (_userKeys.llmKey && _userKeys.llmProvider) {
    h["X-User-LLM-Key"] = _userKeys.llmKey;
    h["X-User-LLM-Provider"] = _userKeys.llmProvider;
    if (_userKeys.llmModel) {
      h["X-User-LLM-Model"] = _userKeys.llmModel;
    }
  }
  if (_userKeys.scraperKey && _userKeys.scraperProvider) {
    h["X-User-Scraper-Key"] = _userKeys.scraperKey;
    h["X-User-Scraper-Provider"] = _userKeys.scraperProvider;
  }
  if (_turnstileToken) {
    h["cf-turnstile-response"] = _turnstileToken;
  }
  return h;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: buildHeaders(),
    ...init,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
  }
  return (await res.json()) as T;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    body: JSON.stringify(body),
    headers: buildHeaders(),
  });
}

export const api = {
  health: () => request<{ status: string }>("/api/health"),
  summary: () => request<DashboardSummary>("/api/dashboard/summary"),
  listRegulations: () => request<Regulation[]>("/api/regulations"),
  listDataAssets: () => request<DataAsset[]>("/api/data-assets"),
  listViolations: () => request<Violation[]>("/api/violations"),
  getViolation: (id: string) => request<Violation>(`/api/violations/${id}`),
  listPolicyChanges: () => request<PolicyChange[]>("/api/policy-changes"),
  listSchemaEvents: () => request<SchemaEvent[]>("/api/schema-events"),
  listAgentRuns: () => request<AgentRun[]>("/api/agent-runs"),
  listAgentState: () => request<AgentState[]>("/api/agent-state"),
  listCoverage: () => request<CoverageRow[]>("/api/coverage"),

  // ── Trigger endpoints (BYOK + Turnstile aware) ──────────────
  getBudget: () => request<BudgetState>("/api/trigger/budget"),
  triggerScenario: (
    scenario: TriggerScenario,
    account_id?: string,
  ) => post<TriggerResponse>("/api/trigger", { scenario, account_id }),
  triggerCrawl: (regulation_id: string) =>
    post<CrawlResponse>("/api/trigger/crawl", { regulation_id }),
};
