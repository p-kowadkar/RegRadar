# FRONTEND.md

React + TypeScript frontend specification. Built for the 4-agent architecture, the 3 trigger paths, and the live WebSocket stream from `/ws/stream`.

---

## 1. Tech Stack

| Layer | Tech | Why |
|---|---|---|
| Framework | React 18+ | Standard |
| Language | TypeScript (strict mode) | Mirrors Pydantic types from backend |
| Bundler | Vite | Fast HMR |
| Styling | Tailwind CSS | Utility-first |
| Routing | react-router-dom v6 | Tab-based |
| State | Zustand | Lightweight, no Redux ceremony |
| Server state | TanStack Query | Cache + invalidation for REST |
| HTTP | axios | Interceptors |
| WebSocket | native WebSocket + custom manager | Full control over reconnection |
| Charts | Recharts | Native React |
| Icons | lucide-react | Modern, consistent |
| Date | date-fns | Lightweight |

---

## 2. Project Structure

```
frontend/
├── package.json
├── tsconfig.json
├── vite.config.ts
├── tailwind.config.js
├── index.html
├── src/
│   ├── main.tsx                          # Entry
│   ├── App.tsx                           # Top-level layout + routing
│   ├── types.ts                          # ALL TypeScript interfaces (mirrors Pydantic)
│   ├── theme.ts                          # Tailwind theme tokens + agent colors
│   ├── api/
│   │   ├── client.ts                     # axios instance
│   │   ├── endpoints.ts                  # Typed endpoint functions
│   │   └── websocket.ts                  # WS connection manager
│   ├── store/
│   │   ├── store.ts                      # Zustand global state
│   │   └── slices/
│   │       ├── agentsSlice.ts            # the 4 agents' current state
│   │       ├── controlsSlice.ts          # 6 controls + their statuses
│   │       ├── triggersSlice.ts          # trigger history + active stream
│   │       ├── briefsSlice.ts            # published cited.md briefs
│   │       └── uiSlice.ts                # UI state (selected items, modals)
│   ├── components/
│   │   ├── layout/
│   │   │   ├── AppShell.tsx              # Sidebar + main + right panel
│   │   │   ├── Sidebar.tsx
│   │   │   ├── RightPanel.tsx
│   │   │   └── TopBar.tsx
│   │   ├── dashboard/
│   │   │   ├── Dashboard.tsx             # the main demo view
│   │   │   ├── KPICard.tsx               # 4 cards: controls passing/failing, breaches, briefs published, USDC earned
│   │   │   ├── AgentStatusGrid.tsx       # 4 agent cards (live status)
│   │   │   ├── AgentCard.tsx
│   │   │   ├── ControlsBoard.tsx         # 6 control cards
│   │   │   └── ControlCard.tsx
│   │   ├── triggers/
│   │   │   ├── TriggerStream.tsx         # live WS-driven feed
│   │   │   ├── TriggerCard.tsx
│   │   │   ├── TriggerDetail.tsx         # full chain view
│   │   │   ├── ImpactReportView.tsx
│   │   │   └── AuditorVerdictView.tsx
│   │   ├── regulations/
│   │   │   ├── RegulationsList.tsx       # the 2 regulations: TILA, FCRA
│   │   │   └── RegulationDetail.tsx      # extracted conditions + linked controls
│   │   ├── briefs/
│   │   │   ├── PublishedBriefsList.tsx
│   │   │   └── PublishedBriefDetail.tsx  # links to cited.md
│   │   ├── demo/
│   │   │   ├── DemoControlPanel.tsx      # buttons to fire scenarios (presenter-only)
│   │   │   └── ScenarioCard.tsx
│   │   └── shared/
│   │       ├── Badge.tsx
│   │       ├── SeverityChip.tsx
│   │       ├── StatusPill.tsx
│   │       ├── EmptyState.tsx
│   │       ├── ErrorBoundary.tsx
│   │       └── LoadingSpinner.tsx
│   ├── hooks/
│   │   ├── useWebSocket.ts
│   │   ├── useTriggerStream.ts
│   │   └── useControls.ts
│   ├── utils/
│   │   ├── dates.ts
│   │   ├── formatters.ts                 # currency, %, etc.
│   │   └── colors.ts
│   └── styles/
│       └── globals.css
```

---

## 3. `types.ts` -- The Truth

These TypeScript types mirror the Pydantic models in `backend/data/models.py`. If they drift, the system breaks.

```typescript
// frontend/src/types.ts

// ════════════════════════════════════════════════
// Agents (4 of them now, not 6)
// ════════════════════════════════════════════════
export type AgentId = "policy_crawler" | "impact_analysis" | "auditor" | "monitoring";

export const AGENT_DISPLAY_NAMES: Record<AgentId, string> = {
  policy_crawler: "Policy Crawler",
  impact_analysis: "Impact Analysis",
  auditor: "Auditor",
  monitoring: "Monitoring",
};

export const AGENT_ACTIVATION_MODES: Record<AgentId, string> = {
  policy_crawler: "scheduled (hourly)",
  impact_analysis: "event-driven",
  auditor: "post-Impact Analysis",
  monitoring: "scheduled (daily)",
};

export const AGENT_MODELS: Record<AgentId, string | null> = {
  policy_crawler: "gemini-3.5-flash",
  impact_analysis: "gemini-3.5-flash",
  auditor: "gemini-3.1-pro + Check Grounding",
  monitoring: null, // zero LLM
};

// ════════════════════════════════════════════════
// Trigger types (3 paths)
// ════════════════════════════════════════════════
export type TriggerType = "policy_change" | "schema_event" | "behavior_event";

// ════════════════════════════════════════════════
// Controls (6 of them now)
// ════════════════════════════════════════════════
export type ControlId =
  | "CTRL-TILA-PENALTY-RATE-NOTICE"
  | "CTRL-TILA-PROMO-RATE-NOTICE"
  | "CTRL-TILA-DISPUTE-RESOLUTION"
  | "CTRL-FCRA-STALE-DATA"
  | "CTRL-FCRA-BUREAU-ACCURACY"
  | "CTRL-FCRA-DISPUTE-FLAG";

export type ControlStatus = "PASSING" | "WARNING" | "FAILING" | "UNTESTED";

export type Severity = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

export interface ControlSummary {
  control_id: ControlId;
  name: string;
  related_regulation_section: string;
  status: ControlStatus;
  breach_count: number;
  breach_balance_usd: number;
  last_tested_at: string | null;
  owner_team: string;
  severity: Severity;
}

// ════════════════════════════════════════════════
// Trigger detail (matches backend's TriggerDetail)
// ════════════════════════════════════════════════
export interface TriggerDetail {
  trigger_id: string;
  trigger_type: TriggerType;
  payload: Record<string, any>;
  occurred_at: string;
  impact_report: ImpactReport | null;
  auditor_verdict: AuditorVerdict | null;
  published_brief: PublishedBriefSummary | null;
  dd_alerts: DDAlertSummary[];
  audit_trail: AuditTrailEntry[];
}

export interface ImpactReport {
  trigger_id: string;
  affected_controls: ControlUpdate[];
  total_breach_count: number;
  total_at_risk_count: number;
  total_balance_at_risk_usd: number;
  citations: string[];
  suggested_remediation: string[];
  reasoning: string;
  generated_at: string;
  llm_model_used: string;
  llm_tokens_in: number;
  llm_tokens_out: number;
}

export interface ControlUpdate {
  control_id: ControlId;
  new_status: ControlStatus;
  affected_account_count: number;
  affected_balance_usd: number;
  rationale: string;
  related_regulation_section: string;
}

export interface AuditorVerdict {
  trigger_id: string;
  verdict: "approved" | "approved_with_warnings" | "rejected";
  overall_confidence: number;
  claims_audited: ClaimAudit[];
  warnings: string[];
  rejection_reasons: string[];
  safe_to_publish: boolean;
  safe_to_alert: boolean;
  audited_at: string;
  llm_model_used: string;
}

export interface ClaimAudit {
  claim: string;
  cited_section: string | null;
  confidence: number;
  supporting_text: string | null;
  flagged_reason: string | null;
}

// ════════════════════════════════════════════════
// Published briefs (cited.md)
// ════════════════════════════════════════════════
export interface PublishedBriefSummary {
  brief_id: string;
  title: string;
  slug: string;
  cited_md_url: string;
  related_regulation_id: string;
  affected_account_count: number;
  published_at: string;
  fetch_count: number;
  paid_fetch_count: number;
  total_usdc_earned: number;
}

// ════════════════════════════════════════════════
// WebSocket messages
// ════════════════════════════════════════════════
export type WSMessageType =
  | "connected"
  | "trigger_received"
  | "agent_started"
  | "agent_tool_call"
  | "agent_completed"
  | "control_status_changed"
  | "brief_published"
  | "datadog_alert_sent"
  | "x402_fetch_succeeded"
  | "trigger_complete"
  | "trigger_failed"
  | "pong";

export interface WSMessage {
  type: WSMessageType;
  payload: Record<string, any>;
  timestamp: string;
  message_id: string;
  trigger_id?: string;
  agent_id?: AgentId;
}

// ════════════════════════════════════════════════
// Agent status (from /api/agents/status)
// ════════════════════════════════════════════════
export interface AgentStatus {
  agent_id: AgentId;
  display_name: string;
  activation_mode: "scheduled_hourly" | "event_driven" | "post_impact_analysis" | "scheduled_daily";
  model: string | null;
  last_run_at: string | null;
  last_run_status: "success" | "failed" | "in_progress" | null;
  total_runs_today: number;
  total_llm_tokens_today: number;
  avg_latency_ms: number | null;
}
```

---

## 4. Zustand Store

```typescript
// frontend/src/store/store.ts
import { create } from "zustand";
import { devtools } from "zustand/middleware";
import { agentsSlice, AgentsSlice } from "./slices/agentsSlice";
import { controlsSlice, ControlsSlice } from "./slices/controlsSlice";
import { triggersSlice, TriggersSlice } from "./slices/triggersSlice";
import { briefsSlice, BriefsSlice } from "./slices/briefsSlice";
import { uiSlice, UiSlice } from "./slices/uiSlice";

export type Store = AgentsSlice & ControlsSlice & TriggersSlice & BriefsSlice & UiSlice;

export const useStore = create<Store>()(
  devtools(
    (set, get, store) => ({
      ...agentsSlice(set, get, store),
      ...controlsSlice(set, get, store),
      ...triggersSlice(set, get, store),
      ...briefsSlice(set, get, store),
      ...uiSlice(set, get, store),
    }),
    { name: "regradar" }
  )
);
```

### `triggersSlice.ts` -- the critical one for the demo

```typescript
// frontend/src/store/slices/triggersSlice.ts
import { StateCreator } from "zustand";
import { TriggerDetail, WSMessage, AgentId, ControlId, ControlStatus } from "../../types";
import { Store } from "../store";

export interface TriggersSlice {
  triggers: Record<string, TriggerDetail>;
  activeTriggerId: string | null;

  setActive: (id: string | null) => void;
  applyWSMessage: (msg: WSMessage) => void;
}

export const triggersSlice: StateCreator<Store, [], [], TriggersSlice> = (set, get) => ({
  triggers: {},
  activeTriggerId: null,

  setActive: (id) => set({ activeTriggerId: id }),

  applyWSMessage: (msg) => {
    const { type, trigger_id, agent_id, payload } = msg;
    if (!trigger_id) return;

    switch (type) {
      case "trigger_received":
        set((s) => ({
          triggers: {
            ...s.triggers,
            [trigger_id]: {
              trigger_id,
              trigger_type: payload.trigger_type,
              payload: payload,
              occurred_at: msg.timestamp,
              impact_report: null,
              auditor_verdict: null,
              published_brief: null,
              dd_alerts: [],
              audit_trail: [],
            },
          },
          activeTriggerId: trigger_id,
        }));
        break;

      case "agent_started":
        // Update the agentsSlice in parallel
        get().setAgentRunning(agent_id!, trigger_id);
        break;

      case "agent_completed":
        get().setAgentIdle(agent_id!);
        // For impact_analysis, write the report stub from payload
        if (agent_id === "impact_analysis") {
          set((s) => ({
            triggers: {
              ...s.triggers,
              [trigger_id]: {
                ...s.triggers[trigger_id],
                impact_report: {
                  trigger_id,
                  affected_controls: [],
                  total_breach_count: payload.total_breach_count,
                  total_at_risk_count: payload.total_at_risk_count || 0,
                  total_balance_at_risk_usd: payload.total_balance_at_risk_usd,
                  citations: payload.citations || [],
                  suggested_remediation: [],
                  reasoning: "",
                  generated_at: msg.timestamp,
                  llm_model_used: payload.llm_model_used || "gemini-3.5-flash",
                  llm_tokens_in: payload.llm_tokens_in || 0,
                  llm_tokens_out: payload.llm_tokens_out || 0,
                },
              },
            },
          }));
        }
        if (agent_id === "auditor") {
          set((s) => ({
            triggers: {
              ...s.triggers,
              [trigger_id]: {
                ...s.triggers[trigger_id],
                auditor_verdict: {
                  trigger_id,
                  verdict: payload.verdict,
                  overall_confidence: payload.overall_confidence,
                  claims_audited: payload.claims_audited || [],
                  warnings: payload.warnings || [],
                  rejection_reasons: payload.rejection_reasons || [],
                  safe_to_publish: payload.safe_to_publish,
                  safe_to_alert: payload.safe_to_alert,
                  audited_at: msg.timestamp,
                  llm_model_used: payload.llm_model_used || "gemini-3.1-pro",
                },
              },
            },
          }));
        }
        break;

      case "control_status_changed":
        get().applyControlStatusChange(
          payload.control_id as ControlId,
          payload.new_status as ControlStatus,
          payload.breach_count
        );
        break;

      case "brief_published":
        set((s) => ({
          triggers: {
            ...s.triggers,
            [trigger_id]: {
              ...s.triggers[trigger_id],
              published_brief: {
                brief_id: payload.brief_id,
                title: payload.title || "",
                slug: payload.slug || "",
                cited_md_url: payload.cited_md_url,
                related_regulation_id: payload.related_regulation_id || "",
                affected_account_count: payload.affected_account_count || 0,
                published_at: msg.timestamp,
                fetch_count: 0,
                paid_fetch_count: 0,
                total_usdc_earned: 0,
              },
            },
          },
        }));
        get().addBrief(payload);
        break;

      case "datadog_alert_sent":
        set((s) => ({
          triggers: {
            ...s.triggers,
            [trigger_id]: {
              ...s.triggers[trigger_id],
              dd_alerts: [
                ...s.triggers[trigger_id].dd_alerts,
                {
                  alert_id: payload.alert_id,
                  control_id: payload.control_id,
                  severity: payload.severity,
                  sent_at: msg.timestamp,
                },
              ],
            },
          },
        }));
        break;

      case "trigger_complete":
      case "trigger_failed":
        // Mark in audit trail; clean up active state after a delay
        break;
    }
  },
});
```

---

## 5. WebSocket Connection Manager

```typescript
// frontend/src/api/websocket.ts
import { WSMessage } from "../types";
import { useStore } from "../store/store";

const WS_URL = import.meta.env.VITE_WS_URL || "ws://localhost:8000/ws/stream";
const API_KEY = import.meta.env.VITE_API_KEY || "regradar-demo";

class WebSocketManager {
  private ws: WebSocket | null = null;
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  private reconnectDelay = 1000;
  private pingInterval: ReturnType<typeof setInterval> | null = null;

  connect() {
    if (this.ws?.readyState === WebSocket.OPEN) return;
    // Browsers don't allow custom headers on WS; encode key in subprotocol
    this.ws = new WebSocket(WS_URL, ["regradar.v1", API_KEY]);

    this.ws.onopen = () => {
      console.log("[ws] connected");
      this.reconnectAttempts = 0;
      this.startPing();
    };

    this.ws.onmessage = (event) => {
      try {
        const msg: WSMessage = JSON.parse(event.data);
        useStore.getState().applyWSMessage(msg);
      } catch (err) {
        console.error("[ws] parse error", err);
      }
    };

    this.ws.onclose = () => {
      console.log("[ws] closed");
      this.stopPing();
      this.scheduleReconnect();
    };

    this.ws.onerror = (err) => console.error("[ws] error", err);
  }

  send(message: object) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(message));
    }
  }

  disconnect() {
    this.stopPing();
    this.ws?.close();
    this.ws = null;
  }

  private scheduleReconnect() {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) return;
    const delay = this.reconnectDelay * 2 ** this.reconnectAttempts;
    setTimeout(() => {
      this.reconnectAttempts++;
      this.connect();
    }, delay);
  }

  private startPing() {
    this.pingInterval = setInterval(() => {
      this.send({ type: "ping", payload: {} });
    }, 30000);
  }

  private stopPing() {
    if (this.pingInterval) {
      clearInterval(this.pingInterval);
      this.pingInterval = null;
    }
  }
}

export const wsManager = new WebSocketManager();
```

---

## 6. Routing & App Shell

```typescript
// frontend/src/App.tsx
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AppShell } from "./components/layout/AppShell";
import { Dashboard } from "./components/dashboard/Dashboard";
import { ControlsBoard } from "./components/dashboard/ControlsBoard";
import { TriggerStream } from "./components/triggers/TriggerStream";
import { PublishedBriefsList } from "./components/briefs/PublishedBriefsList";
import { RegulationsList } from "./components/regulations/RegulationsList";
import { DemoControlPanel } from "./components/demo/DemoControlPanel";
import { useEffect } from "react";
import { wsManager } from "./api/websocket";

export default function App() {
  useEffect(() => {
    wsManager.connect();
    return () => wsManager.disconnect();
  }, []);

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<AppShell />}>
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="dashboard" element={<Dashboard />} />
          <Route path="controls" element={<ControlsBoard />} />
          <Route path="triggers" element={<TriggerStream />} />
          <Route path="regulations" element={<RegulationsList />} />
          <Route path="briefs" element={<PublishedBriefsList />} />
          <Route path="demo" element={<DemoControlPanel />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
```

---

## 7. Critical Components for the Demo

### 7.1 Dashboard

Top: 4 KPI cards
- Controls FAILING / PASSING (live)
- Total breaches today
- Briefs published to cited.md
- Total USDC earned via x402 (starts at 0; bumps live during the close)

Middle: `AgentStatusGrid` (4 cards, one per agent, showing live status with pulsing indicator when running)

Bottom: `ControlsBoard` (6 cards in a grid)

Right panel: when a trigger is active, shows the `TriggerDetail` view with the chain stages.

### 7.2 AgentCard

```typescript
// frontend/src/components/dashboard/AgentCard.tsx
import { AgentId, AGENT_DISPLAY_NAMES, AGENT_MODELS } from "../../types";
import { useStore } from "../../store/store";

interface Props {
  agentId: AgentId;
}

export function AgentCard({ agentId }: Props) {
  const status = useStore((s) => s.agents[agentId]);
  const isRunning = status?.is_running ?? false;
  const accent = AGENT_COLORS[agentId];

  return (
    <div
      className={`rounded-lg border-2 p-4 transition-all ${
        isRunning ? "border-current shadow-lg" : "border-slate-200"
      }`}
      style={{ color: accent }}
    >
      <div className="flex items-baseline justify-between">
        <h3 className="font-semibold text-slate-900">{AGENT_DISPLAY_NAMES[agentId]}</h3>
        {isRunning && <span className="text-xs animate-pulse">● running</span>}
      </div>
      <p className="text-xs text-slate-500 mt-1">{AGENT_MODELS[agentId] || "Zero LLM"}</p>
      <div className="mt-3 text-sm text-slate-600">
        Runs today: <span className="font-mono">{status?.total_runs_today ?? 0}</span>
      </div>
      <div className="mt-1 text-sm text-slate-600">
        Tokens today: <span className="font-mono">{(status?.total_llm_tokens_today ?? 0).toLocaleString()}</span>
      </div>
    </div>
  );
}
```

### 7.3 ControlCard

Shows status badge (PASSING green / WARNING amber / FAILING red), breach count, balance exposure, last tested time, owner team. Animates color change when a control flips status during the demo.

### 7.4 TriggerStream

Real-time list of triggers, newest first. Each row shows: trigger_type icon, timestamp, affected controls count, auditor verdict, brief URL (clickable).

### 7.5 DemoControlPanel (presenter-only -- protect with route guard or env flag)

Five large buttons:
- **Fire: Schema Enrichment (FCRA headline)** -- the main demo trigger
- **Fire: Dispute Filed (cross-trigger)** -- the secondary
- **Fire: Policy Change (TILA promo)** -- backup
- **Reset Demo State** -- truncates the demo tables, reseeds (use only if a run gets ugly)
- **Toggle Datadog AI Agent Console** -- opens the Datadog tab in a new window

Each button calls the corresponding `/api/internal/scenarios/{scenario}` endpoint.

---

## 8. Theme Tokens

```typescript
// frontend/src/theme.ts
export const colors = {
  // Brand
  primary: "#2563eb",
  purple: "#7c3aed",

  // Status
  passing: "#16a34a",
  warning: "#ea580c",
  failing: "#dc2626",
  untested: "#64748b",

  // Severity
  critical: "#dc2626",
  high: "#ea580c",
  medium: "#ca8a04",
  low: "#16a34a",

  // Agents (one accent per agent for visual continuity in chain views)
  agents: {
    policy_crawler: "#0ea5e9",    // sky
    impact_analysis: "#7c3aed",   // purple
    auditor: "#ca8a04",            // amber
    monitoring: "#16a34a",         // green
  },
} as const;
```

Tailwind config maps these. Use `text-policy-crawler bg-policy-crawler/10` etc.

---

## 9. Build & Deploy

### Local Dev

```bash
cd frontend
npm install
npm run dev      # Vite on port 5173
```

### Production

```bash
npm run build    # outputs to dist/
```

Env vars at deploy:
- `VITE_API_URL=http://localhost:8000`
- `VITE_WS_URL=ws://localhost:8000/ws/stream`
- `VITE_API_KEY=regradar-demo`

---

## AI Tool Hints

1. **Start with `types.ts`.** Build every other file with these types imported. Drift here breaks everything.

2. **Build `triggersSlice.ts` second.** The whole demo flows through `applyWSMessage`. Get it right.

3. **Component build order:** AppShell → Sidebar → Dashboard → AgentCard + ControlCard → TriggerStream → DemoControlPanel.

4. **Test the WS reconnect logic by killing the backend mid-cascade.** Frontend should reconnect within 1-2 seconds.

5. **DemoControlPanel should be presenter-only.** Hide it behind a query string (`?demo=1`) or env flag (`VITE_SHOW_DEMO_CONTROLS=1`) so a judge clicking around doesn't accidentally fire the headline trigger.

6. **Pre-warm Tailwind classes.** The agent color classes (`text-policy-crawler`, `text-impact-analysis`, etc.) need to be in the Tailwind safelist or they'll get tree-shaken.
