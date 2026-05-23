// === Dashboard summary ===

export interface RegulationBucket {
  regulation_id: string;
  reg_code: string;
  compliant: number;
  at_risk: number;
  out_of_compliance: number;
}

export interface DashboardSummary {
  monitored: number;
  accountedFor: number;
  outOfCompliance: number;
  fixesSuggested: number;
  fixesCompleted: number;
  byPolicy: RegulationBucket[];
}

// === Regulations and assets ===

export interface Regulation {
  regulation_id: string;
  regulation_name: string;
  act: string;
  reg_code: string;
  control_name: string;
  trigger_type: string;
  threshold_days: number | null;
  threshold_label: string;
  effective_date: string | null;
  last_crawled_at: string | null;
}

export interface DataAsset {
  asset_id: string;
  asset_name: string;
  asset_type: string;
  system: string;
  table_name: string;
  owner_team: string;
  data_classification: string;
  row_count_est: number;
  refresh_cadence: string;
}

// === Violations ===

export type ViolationStatus = "OPEN" | "IN_REMEDIATION" | "RESOLVED" | "DISMISSED";
export type Severity = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

export interface RemediationStep {
  step_id: string;
  step_number: number;
  step_title: string;
  step_description: string;
  action_type: string;
  automated: boolean;
  requires_approval: boolean;
  estimated_minutes: number;
}

export interface Violation {
  violation_id: string;
  regulation_id: string;
  reg_code: string | null;
  control_name: string | null;
  asset_id: string;
  asset_name: string | null;
  cde_id: string;
  field_name: string | null;
  account_id: string;
  violation_type: string;
  trigger_type: string;
  breach_detail: string;
  days_in_breach: number;
  severity: Severity;
  status: ViolationStatus;
  detected_at: string;
  resolved_at: string | null;
  steps: RemediationStep[];
}

// === Crawler-driven feeds ===

export interface PolicyChange {
  change_id: string;
  regulation_id: string;
  reg_code: string | null;
  detected_at: string;
  change_type: string;
  prior_version: string;
  new_version: string;
  change_summary: string;
  material: boolean;
  source_url: string;
}

export interface SchemaEvent {
  event_id: string;
  asset_id: string;
  asset_name: string | null;
  event_type: string;
  field_name: string;
  detected_at: string;
  rows_affected: number;
  triggered_impact_analysis: boolean;
}

// === Agent activity ===

export interface AgentRun {
  trigger_id: string;
  agent_id: string;
  started_at: string;
  completed_at: string | null;
  duration_ms: number;
  response_type: string | null;
  auditor_verdict: string | null;
  error: string | null;
}

export interface AgentState {
  agent_id: string;
  last_processed_at: string | null;
  last_cursor: string;
  cycle_count: number;
  last_error: string;
  status: string;
  updated_at: string | null;
}

export interface CoverageRow {
  asset_id: string;
  asset_name: string;
  regulation_id: string;
  reg_code: string;
  in_scope: boolean;
  compliance_owner: string;
  cde_count: number;
  open_violations: number;
}
