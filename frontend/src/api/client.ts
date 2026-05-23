import type {
  AgentRun,
  AgentState,
  CoverageRow,
  DashboardSummary,
  DataAsset,
  PolicyChange,
  Regulation,
  SchemaEvent,
  Violation,
} from "../types";

const BASE = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

export const API_BASE = BASE;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
  }
  return (await res.json()) as T;
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
};
