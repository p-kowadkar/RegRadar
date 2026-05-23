# FRONTEND.md

React + TypeScript frontend specification. Component breakdown, state management, WebSocket contracts.

---

## 1. Tech Stack

| Layer | Tech | Why |
|---|---|---|
| Framework | React 18+ | Standard |
| Language | TypeScript (strict mode) | Type safety mirrors Pydantic |
| Bundler | Vite | Fast HMR |
| Styling | Tailwind CSS | Utility-first, no CSS files |
| Routing | react-router-dom v6 | Tab-based navigation |
| State | Zustand | Lightweight, no Redux ceremony |
| HTTP | axios | Interceptors for API key + errors |
| WebSocket | native WebSocket + custom manager | Full control |
| Charts | Recharts | Recharts >> Chart.js for React |
| Graph viz | react-force-graph-2d | Knowledge graph view |
| Icons | lucide-react | Modern, consistent |
| Forms | react-hook-form + zod | Type-safe forms |
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
│   ├── main.tsx                    # Entry
│   ├── App.tsx                     # Top-level layout + routing
│   ├── types.ts                    # ALL TypeScript interfaces
│   ├── theme.ts                    # Tailwind theme tokens
│   ├── api/
│   │   ├── client.ts               # axios instance
│   │   ├── endpoints.ts            # Typed endpoint functions
│   │   └── websocket.ts            # WS connection manager
│   ├── store/
│   │   ├── store.ts                # Zustand global state
│   │   ├── slices/
│   │   │   ├── chatSlice.ts
│   │   │   ├── feedSlice.ts
│   │   │   ├── graphSlice.ts
│   │   │   ├── controlsSlice.ts
│   │   │   ├── agentsSlice.ts
│   │   │   └── uiSlice.ts
│   ├── components/
│   │   ├── layout/
│   │   │   ├── AppShell.tsx       # Sidebar + main + right panel
│   │   │   ├── Sidebar.tsx
│   │   │   ├── RightPanel.tsx
│   │   │   └── TopBar.tsx
│   │   ├── dashboard/
│   │   │   ├── Dashboard.tsx
│   │   │   ├── KPICard.tsx
│   │   │   ├── LiveFeed.tsx
│   │   │   └── FeedItem.tsx
│   │   ├── chat/
│   │   │   ├── GroupChat.tsx
│   │   │   ├── AgentMessage.tsx
│   │   │   ├── UserMessage.tsx
│   │   │   ├── ProactiveBubble.tsx
│   │   │   ├── ChatInput.tsx
│   │   │   ├── AgentAvatar.tsx
│   │   │   └── TypingIndicator.tsx
│   │   ├── graph/
│   │   │   ├── KnowledgeGraph.tsx
│   │   │   ├── GraphCanvas.tsx
│   │   │   ├── NodeDetail.tsx
│   │   │   ├── EdgeDetail.tsx
│   │   │   └── SimulationPanel.tsx
│   │   ├── controls/
│   │   │   ├── ControlsBoard.tsx
│   │   │   ├── ControlCard.tsx
│   │   │   ├── ControlHistory.tsx
│   │   │   └── TestNowButton.tsx
│   │   ├── shared/
│   │   │   ├── Badge.tsx
│   │   │   ├── SeverityChip.tsx
│   │   │   ├── StatusPill.tsx
│   │   │   ├── EmptyState.tsx
│   │   │   ├── ErrorBoundary.tsx
│   │   │   └── LoadingSpinner.tsx
│   │   └── debug/
│   │       ├── AgentMonitor.tsx
│   │       └── AuditTrailViewer.tsx
│   ├── hooks/
│   │   ├── useWebSocket.ts
│   │   ├── useApi.ts
│   │   ├── useTaskStream.ts
│   │   └── useStreamingMessage.ts
│   ├── utils/
│   │   ├── dates.ts
│   │   ├── formatters.ts
│   │   └── colors.ts
│   └── styles/
│       └── globals.css
```

---

## 3. types.ts -- The Truth

This file **mirrors Pydantic models exactly**. If they drift, the system breaks.

```typescript
// frontend/src/types.ts

// === Trigger Types ===
export type TriggerType =
  | "user_message" | "new_regulation" | "reg_amended"
  | "deadline_approaching" | "coverage_gap"
  | "data_object_added" | "regulatory_conflict";

// === Severity ===
export type Severity = "CRITICAL" | "HIGH" | "MEDIUM" | "LOW";

// === Control Status ===
export type ControlStatus =
  | "PASSING" | "AT_RISK" | "FAILING"
  | "NOT_APPLICABLE" | "PENDING_RETEST";

// === Agents ===
export type AgentId =
  | "the_watcher" | "the_classifier" | "the_mapper"
  | "the_analyst" | "the_advisor" | "the_auditor";

export type ResponseType = "primary" | "supporting" | "cross_talk";

export interface AgentClaim {
  agent_id: AgentId;
  relevance_score: number;
  response_type: ResponseType;
  depends_on: AgentId[];
  reasoning: string;
}

// === Agent Outputs ===
export interface ThresholdChange {
  metric: string;
  old_value: number | null;
  new_value: number;
  unit: string;
}

export interface ClassifierOutput {
  jurisdiction: string[];
  regulator: string[];
  topic: string[];
  severity: Severity;
  document_type: string;
  deadlines: Record<string, string | null>;
  title: string;
  summary: string;
  threshold_changes: ThresholdChange[];
  confidence: number;
}

export interface AffectedDataObject {
  data_object_id: string;
  impact_type: "direct" | "indirect";
  regulation_section: string;
  obligation: string;
  confidence: number;
  reasoning: string;
}

export interface PortfolioScanResult {
  table: string;
  filter_sql: string;
  affected_positions: number;
  total_notional_usd: number | null;
  total_outstanding_usd: number | null;
  sample_positions: Record<string, any>[];
}

export interface MapperOutput {
  affected_data_objects: AffectedDataObject[];
  portfolio_scan: PortfolioScanResult | null;
  affected_products: string[];
  affected_jurisdictions: string[];
  new_edges_proposed: ProposedEdge[];
  graph_query_used: string;
  uncertainty_notes: string;
}

export interface PositionClassification {
  BREACH: number;
  AT_RISK: number;
  MONITORING: number;
}

export interface PrecedentCase {
  name: string;
  fine_usd: number;
  year: number;
  relevance: string;
}

export interface AnalystOutput {
  position_classification: PositionClassification | null;
  gap_analysis: {
    current_state: string;
    required_state: string;
    gap_severity: "high" | "medium" | "low";
  };
  risk_exposure: {
    estimated_fine_range_usd: [number, number];
    precedent_cases: PrecedentCase[];
    reputational_risk: "high" | "medium" | "low";
    operational_disruption_risk: "high" | "medium" | "low";
  };
  operational_impact: {
    affected_teams: string[];
    affected_systems: string[];
    effort_estimate: "small" | "medium" | "large";
    effort_reasoning: string;
  };
  timeline: {
    days_until_deadline: number | null;
    recommended_start_date: string | null;
    critical_path_items: string[];
  };
  confidence: number;
  confidence_reasoning: string;
}

export interface AdvisorOutput {
  control_updates: ControlUpdate[];
  action_plan: ActionPlanItem[];
  datadog_alert: DatadogAlert | null;
  summary_for_user: string;
}

export interface ControlUpdate {
  control_id: string;
  field: string;
  old_value: any;
  new_value: any;
  new_status_after_retest: ControlStatus | null;
}

export interface ActionPlanItem {
  id: string;
  title: string;
  description: string;
  owner: string;
  deadline: string | null;
  priority: number;
  estimated_effort_hours: number;
  workflow_execution: boolean;
  luminai_sop: string[] | null;
  reason_not_automatable: string | null;
  human_step_description: string | null;
}

export interface AuditorOutput {
  verdict: "approved" | "approved_with_warnings" | "rejected";
  checks: {
    citations_grounded: boolean;
    logical_consistency: boolean;
    no_fabrication: boolean;
    no_scope_drift: boolean;
    completeness: boolean;
  };
  warnings: string[];
  blocking_issues: string[];
  grounded_citations: CitationVerification[];
}

// === KG ===
export type NodeType =
  | "data_object" | "regulation" | "article" | "obligation"
  | "jurisdiction" | "regulator" | "product"
  | "customer_segment" | "portfolio_position";

export type EdgeType =
  | "applies_to" | "requires" | "exempts"
  | "cross_references" | "supersedes" | "amends"
  | "collects" | "processes" | "stores"
  | "classified_as" | "operates_in" | "serves";

export interface KGNode {
  node_id: string;
  node_type: NodeType;
  name: string;
  metadata: Record<string, any>;
  source_url: string;
}

export interface KGEdge {
  edge_id: string;
  source_id: string;
  target_id: string;
  edge_type: EdgeType;
  confidence: number;
  reasoning: string;
}

// === Controls ===
export interface Control {
  control_id: string;
  name: string;
  description: string;
  regulation_ids: string[];
  metric: string;
  threshold_value: number;
  threshold_operator: "gte" | "gt" | "lte" | "lt" | "eq" | "neq";
  threshold_unit: string;
  owner_team: string;
  test_frequency: "realtime" | "hourly" | "daily" | "weekly" | "monthly";
  current_status: ControlStatus;
  last_tested_at: string | null;
}

// === WebSocket ===
export type WSMessageType =
  | "connected" | "task_started" | "agent_claim" | "agent_silent"
  | "agent_thinking" | "agent_response_partial" | "agent_response"
  | "auditor_verdict" | "task_complete" | "task_failed"
  | "proactive_message" | "control_status_changed"
  | "system_notification" | "pong";

export interface WSMessage {
  type: WSMessageType;
  payload: Record<string, any>;
  timestamp: string;
  message_id: string;
  task_id?: string;
  agent_id?: AgentId;
}

// === Feed ===
export interface FeedItem {
  regulation_id: string;
  title: string;
  summary: string;
  severity: Severity;
  regulator: string[];
  jurisdiction: string[];
  topic: string[];
  change_type: "new_regulation" | "reg_amended";
  fetched_at: string;
  affected_data_objects_count: number;
  affected_positions_count: number | null;
  has_active_controls: boolean;
}

// === Tasks ===
export interface Task {
  task_id: string;
  trigger_type: TriggerType;
  started_at: string;
  completed_at: string | null;
  agents_spoken: AgentId[];
  classifier_output: ClassifierOutput | null;
  mapper_output: MapperOutput | null;
  analyst_output: AnalystOutput | null;
  advisor_output: AdvisorOutput | null;
  auditor_output: AuditorOutput | null;
  duration_ms: number | null;
  status: "running" | "complete" | "failed";
}
```

---

## 4. Zustand Store

Single store, sliced by domain:

```typescript
// frontend/src/store/store.ts
import { create } from "zustand";
import { devtools } from "zustand/middleware";
import { chatSlice, ChatSlice } from "./slices/chatSlice";
import { feedSlice, FeedSlice } from "./slices/feedSlice";
import { graphSlice, GraphSlice } from "./slices/graphSlice";
import { controlsSlice, ControlsSlice } from "./slices/controlsSlice";
import { agentsSlice, AgentsSlice } from "./slices/agentsSlice";
import { uiSlice, UiSlice } from "./slices/uiSlice";

export type Store =
  & ChatSlice & FeedSlice & GraphSlice
  & ControlsSlice & AgentsSlice & UiSlice;

export const useStore = create<Store>()(
  devtools(
    (set, get, store) => ({
      ...chatSlice(set, get, store),
      ...feedSlice(set, get, store),
      ...graphSlice(set, get, store),
      ...controlsSlice(set, get, store),
      ...agentsSlice(set, get, store),
      ...uiSlice(set, get, store),
    }),
    { name: "regradar" }
  )
);
```

### Chat Slice Example

```typescript
// frontend/src/store/slices/chatSlice.ts
import { StateCreator } from "zustand";
import { Task, WSMessage, AgentId } from "../../types";
import { Store } from "../store";

export interface ChatSlice {
  tasks: Record<string, Task>;
  activeTaskId: string | null;
  pendingMessages: string[];           // user messages awaiting send
  
  // Actions
  addTask: (task: Task) => void;
  updateTask: (taskId: string, partial: Partial<Task>) => void;
  attachAgentOutput: (taskId: string, agentId: AgentId, output: any) => void;
  setActiveTask: (taskId: string | null) => void;
  applyWSMessage: (msg: WSMessage) => void;
}

export const chatSlice: StateCreator<Store, [], [], ChatSlice> = (set, get) => ({
  tasks: {},
  activeTaskId: null,
  pendingMessages: [],

  addTask: (task) =>
    set((state) => ({
      tasks: { ...state.tasks, [task.task_id]: task },
    })),

  updateTask: (taskId, partial) =>
    set((state) => ({
      tasks: {
        ...state.tasks,
        [taskId]: { ...state.tasks[taskId], ...partial },
      },
    })),

  attachAgentOutput: (taskId, agentId, output) =>
    set((state) => {
      const task = state.tasks[taskId];
      if (!task) return state;
      const updated = { ...task };
      switch (agentId) {
        case "the_classifier": updated.classifier_output = output; break;
        case "the_mapper": updated.mapper_output = output; break;
        case "the_analyst": updated.analyst_output = output; break;
        case "the_advisor": updated.advisor_output = output; break;
        case "the_auditor": updated.auditor_output = output; break;
      }
      updated.agents_spoken = [...updated.agents_spoken, agentId];
      return { tasks: { ...state.tasks, [taskId]: updated } };
    }),

  setActiveTask: (taskId) => set({ activeTaskId: taskId }),

  applyWSMessage: (msg) => {
    const { type, task_id, agent_id, payload } = msg;
    if (!task_id) return;
    
    switch (type) {
      case "task_started":
        get().addTask({
          task_id,
          trigger_type: payload.trigger_type,
          started_at: msg.timestamp,
          completed_at: null,
          agents_spoken: [],
          classifier_output: null,
          mapper_output: null,
          analyst_output: null,
          advisor_output: null,
          auditor_output: null,
          duration_ms: null,
          status: "running",
        });
        get().setActiveTask(task_id);
        break;
      
      case "agent_response":
        if (agent_id) {
          get().attachAgentOutput(task_id, agent_id, payload.output);
        }
        break;
      
      case "task_complete":
        get().updateTask(task_id, {
          status: "complete",
          completed_at: msg.timestamp,
          duration_ms: payload.duration_ms,
        });
        break;
      
      case "task_failed":
        get().updateTask(task_id, { status: "failed" });
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

const WS_URL = import.meta.env.VITE_WS_URL || "ws://localhost:8000/ws/chat";
const API_KEY = import.meta.env.VITE_API_KEY;

class WebSocketManager {
  private ws: WebSocket | null = null;
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  private reconnectDelay = 1000;
  private pingInterval: NodeJS.Timer | null = null;

  connect() {
    if (this.ws?.readyState === WebSocket.OPEN) return;

    this.ws = new WebSocket(WS_URL, ["regradar.v1", API_KEY]);

    this.ws.onopen = () => {
      console.log("[ws] connected");
      this.reconnectAttempts = 0;
      this.startPing();
    };

    this.ws.onmessage = (event) => {
      try {
        const msg: WSMessage = JSON.parse(event.data);
        this.routeMessage(msg);
      } catch (err) {
        console.error("[ws] parse error", err);
      }
    };

    this.ws.onclose = () => {
      console.log("[ws] closed");
      this.stopPing();
      this.scheduleReconnect();
    };

    this.ws.onerror = (err) => {
      console.error("[ws] error", err);
    };
  }

  disconnect() {
    this.stopPing();
    this.ws?.close();
    this.ws = null;
  }

  send(message: Partial<WSMessage>) {
    if (this.ws?.readyState !== WebSocket.OPEN) {
      console.warn("[ws] send while disconnected");
      return;
    }
    this.ws.send(JSON.stringify({
      ...message,
      timestamp: new Date().toISOString(),
      message_id: crypto.randomUUID(),
    }));
  }

  sendUserMessage(text: string) {
    this.send({
      type: "user_message" as any,
      payload: { message: text },
    });
  }

  private routeMessage(msg: WSMessage) {
    const store = useStore.getState();
    
    // Chat-related
    if (msg.task_id) {
      store.applyWSMessage(msg);
    }
    
    // Feed updates
    if (msg.type === "proactive_message") {
      // Show toast
      store.addNotification({
        title: msg.payload.preview,
        severity: msg.payload.severity,
      });
    }
    
    // Control updates
    if (msg.type === "control_status_changed") {
      store.applyControlStatusChange(msg.payload);
    }
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
      this.send({ type: "ping" as any, payload: {} });
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

## 6. Routing

```typescript
// frontend/src/App.tsx
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AppShell } from "./components/layout/AppShell";
import { Dashboard } from "./components/dashboard/Dashboard";
import { GroupChat } from "./components/chat/GroupChat";
import { KnowledgeGraph } from "./components/graph/KnowledgeGraph";
import { ControlsBoard } from "./components/controls/ControlsBoard";
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
          <Route path="chat" element={<GroupChat />} />
          <Route path="graph" element={<KnowledgeGraph />} />
          <Route path="controls" element={<ControlsBoard />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
```

---

## 7. Critical Components

### 7.1 AppShell

Three-column layout: Sidebar | Main | Right Panel.

- Sidebar: navigation (Dashboard, Chat, Graph, Controls), bottom: settings + agent toggles
- Main: `<Outlet />` for routed view
- Right Panel: contextual based on `useStore(s => s.selectedItem)`

### 7.2 Dashboard

Top: 4 KPI cards
- Risk Score (calculated)
- Sources Active (X/Y)
- Coverage % (from `/api/monitor/sources`)
- Last Scan (relative time)

Middle: Live Feed (list of latest FeedItems)
Right (in right panel): selected feed item detail

### 7.3 GroupChat

Slack-style message list, agent messages styled per agent. Bottom: chat input.

Key behaviors:
- Auto-scroll to latest on new message UNLESS user has scrolled up
- Show typing indicator when agent_thinking received
- Show "Auditor reviewing..." badge when auditor running
- Allow expanding agent output (full JSON view in modal)

### 7.4 KnowledgeGraph

Uses `react-force-graph-2d`. Nodes colored by type, edges colored by severity.

Click node → opens NodeDetail in right panel.
Click "Simulate" → opens SimulationPanel for "what if" queries.

### 7.5 ControlsBoard

Grid of ControlCard components. Each card shows:
- Control ID + name
- Status badge (PASSING green / AT_RISK orange / FAILING red)
- Last tested time
- Affected positions count
- "Test Now" button

Click card → opens ControlHistory in right panel (chart of test results over time).

---

## 8. Component Styling Tokens

```typescript
// frontend/src/theme.ts
export const colors = {
  // Brand
  primary: "#2563eb",
  purple: "#7c3aed",
  
  // Severity
  critical: "#dc2626",
  high: "#ea580c",
  medium: "#ca8a04",
  low: "#16a34a",
  
  // Status
  passing: "#16a34a",
  at_risk: "#ea580c",
  failing: "#dc2626",
  
  // Agents (each agent has its own accent color)
  agents: {
    the_watcher: "#16a34a",
    the_classifier: "#2563eb",
    the_mapper: "#7c3aed",
    the_analyst: "#ea580c",
    the_advisor: "#dc2626",
    the_auditor: "#ca8a04",
  },
} as const;
```

Tailwind config maps these.

---

## 9. Agent Message Component (Critical UI)

```typescript
// frontend/src/components/chat/AgentMessage.tsx
import { AgentId } from "../../types";
import { AgentAvatar } from "./AgentAvatar";
import { colors } from "../../theme";

const AGENT_NAMES: Record<AgentId, string> = {
  the_watcher: "The Watcher",
  the_classifier: "The Classifier",
  the_mapper: "The Mapper",
  the_analyst: "The Analyst",
  the_advisor: "The Advisor",
  the_auditor: "The Auditor",
};

interface Props {
  agent_id: AgentId;
  content: React.ReactNode;
  timestamp: string;
  output?: any;
  isStreaming?: boolean;
}

export function AgentMessage({ agent_id, content, timestamp, output, isStreaming }: Props) {
  const accent = colors.agents[agent_id];
  return (
    <div className="flex gap-3 py-2 hover:bg-slate-50 px-4">
      <AgentAvatar agent_id={agent_id} />
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-2">
          <span className="font-semibold" style={{ color: accent }}>
            {AGENT_NAMES[agent_id]}
          </span>
          <span className="text-xs text-slate-400">{timestamp}</span>
          {isStreaming && (
            <span className="text-xs text-slate-400 italic">thinking...</span>
          )}
        </div>
        <div className="mt-1 text-slate-900">
          {content}
        </div>
        {output && (
          <button
            className="mt-2 text-xs text-slate-500 hover:text-slate-700"
            onClick={() => /* open output modal */}
          >
            View structured output →
          </button>
        )}
      </div>
    </div>
  );
}
```

---

## 10. Performance Rules

1. **Memoize expensive renders** -- `useMemo` for filtered feed lists, `React.memo` for cards
2. **Virtualize long lists** -- use `react-virtual` for feed if >100 items
3. **Debounce WebSocket store updates** -- if 10 messages arrive in 100ms, batch them
4. **Don't re-render whole graph on every node update** -- d3-force is expensive
5. **Lazy-load routes** -- `React.lazy(() => import("./components/graph/KnowledgeGraph"))`

---

## 11. Build & Deploy

### Local Dev

```bash
cd frontend
npm install
npm run dev      # Vite on port 5173
```

### Production (Lovable or Vercel)

```bash
npm run build    # outputs to dist/
```

Set env vars at deploy time:
- `VITE_API_URL` = backend URL
- `VITE_WS_URL` = WebSocket URL
- `VITE_API_KEY` = static demo key

---

Read [SEED_DATA.md](SEED_DATA.md) next.
