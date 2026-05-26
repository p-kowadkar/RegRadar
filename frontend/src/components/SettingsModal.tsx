import { useEffect, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  ExternalLink,
  Eye,
  EyeOff,
  KeyRound,
  Loader2,
  X,
} from "lucide-react";
import { api } from "../api/client";
import type {
  LLMProvider,
  ScraperProvider,
  UserKeys,
  ValidationResult,
} from "../types";

interface Props {
  open: boolean;
  initial: UserKeys;
  onSave: (keys: UserKeys) => void;
  onClose: () => void;
}

const LLM_PROVIDERS: { value: LLMProvider; label: string; hint: string }[] = [
  { value: "openrouter", label: "OpenRouter", hint: "openrouter.ai — one key, 300+ models, recommended" },
  { value: "gemini", label: "Google Gemini", hint: "ai.google.dev — direct Google API key" },
  { value: "openai", label: "OpenAI", hint: "platform.openai.com — locked to gpt-5.4-mini for cost predictability" },
];

const SCRAPER_PROVIDERS: { value: ScraperProvider; label: string; hint: string }[] = [
  { value: "firecrawl", label: "Firecrawl", hint: "firecrawl.dev — recommended, free monthly tier" },
  { value: "nimble", label: "Nimble", hint: "nimbleway.com — paid, more advanced" },
];

// Suggested OpenRouter slugs shown as datalist autocomplete.
// OpenRouter adds new models frequently; this is a starter set, not exhaustive.
const OPENROUTER_SUGGESTIONS = [
  "google/gemini-2.5-flash",
  "google/gemini-2.5-pro",
  "anthropic/claude-sonnet-4.5",
  "anthropic/claude-opus-4.5",
  "anthropic/claude-haiku-4.5",
  "openai/gpt-5.4-mini",
  "openai/gpt-5.5",
  "x-ai/grok-4",
  "deepseek/deepseek-v3.2",
  "meta-llama/llama-4-maverick",
];

type ValidationStatus =
  | { state: "idle" }
  | { state: "loading" }
  | { state: "done"; result: ValidationResult }
  | { state: "error"; message: string };


export function SettingsModal({ open, initial, onSave, onClose }: Props) {
  const [keys, setKeys] = useState<UserKeys>(initial);
  const [showLLM, setShowLLM] = useState(false);
  const [showScraper, setShowScraper] = useState(false);
  const [llmStatus, setLlmStatus] = useState<ValidationStatus>({ state: "idle" });
  const [scraperStatus, setScraperStatus] = useState<ValidationStatus>({ state: "idle" });

  useEffect(() => {
    if (open) {
      setKeys(initial);
      setLlmStatus({ state: "idle" });
      setScraperStatus({ state: "idle" });
    }
  }, [open, initial]);

  // Reset validation status when the user edits the corresponding key
  useEffect(() => {
    setLlmStatus({ state: "idle" });
  }, [keys.llmKey, keys.llmProvider, keys.llmModel]);
  useEffect(() => {
    setScraperStatus({ state: "idle" });
  }, [keys.scraperKey, keys.scraperProvider]);

  if (!open) return null;

  const handleSave = () => {
    onSave(keys);
    onClose();
  };

  const handleClear = () => {
    const empty: UserKeys = {
      llmKey: "",
      llmProvider: "",
      llmModel: "",
      scraperKey: "",
      scraperProvider: "",
    };
    setKeys(empty);
    onSave(empty);
    onClose();
  };

  const handleValidateLLM = async () => {
    if (!keys.llmKey || !keys.llmProvider) return;
    setLlmStatus({ state: "loading" });
    try {
      const result = await api.validateLLM({
        llmKey: keys.llmKey,
        llmProvider: keys.llmProvider,
        llmModel: keys.llmModel || undefined,
      });
      setLlmStatus({ state: "done", result });
    } catch (e) {
      setLlmStatus({
        state: "error",
        message: e instanceof Error ? e.message : String(e),
      });
    }
  };

  const handleValidateScraper = async () => {
    if (!keys.scraperKey || !keys.scraperProvider) return;
    setScraperStatus({ state: "loading" });
    try {
      const result = await api.validateScraper({
        scraperKey: keys.scraperKey,
        scraperProvider: keys.scraperProvider,
      });
      setScraperStatus({ state: "done", result });
    } catch (e) {
      setScraperStatus({
        state: "error",
        message: e instanceof Error ? e.message : String(e),
      });
    }
  };

  const llmReady = Boolean(keys.llmKey && keys.llmProvider);
  const scraperReady = Boolean(keys.scraperKey && keys.scraperProvider);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg rounded-md border border-line bg-surface shadow-panel"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-line px-4 py-3">
          <div className="flex items-center gap-2">
            <KeyRound size={14} className="text-brand" />
            <h2 className="text-sm font-semibold text-text-primary">
              Bring your own keys
            </h2>
          </div>
          <button
            onClick={onClose}
            className="text-text-muted hover:text-text-primary"
            aria-label="Close"
          >
            <X size={16} />
          </button>
        </div>

        <div className="space-y-4 px-4 py-4">
          <p className="text-xs leading-relaxed text-text-muted">
            Stored only in your browser's localStorage. Sent to the server as{" "}
            <code className="font-mono text-text-secondary">X-User-*</code> headers, never logged.
            Skip this and the demo uses a shared pool with a daily rate limit.
          </p>

          {/* LLM key */}
          <div className="space-y-2">
            <label className="text-xxs font-semibold uppercase tracking-[0.16em] text-text-secondary">
              LLM provider
            </label>
            <select
              value={keys.llmProvider}
              onChange={(e) =>
                setKeys({
                  ...keys,
                  llmProvider: e.target.value as LLMProvider | "",
                  llmModel: "", // reset model on provider change
                })
              }
              className="w-full rounded border border-line bg-surface-alt px-2 py-1.5 text-sm text-text-primary focus:border-line-strong focus:outline-none"
            >
              <option value="">— none —</option>
              {LLM_PROVIDERS.map((p) => (
                <option key={p.value} value={p.value}>
                  {p.label}
                </option>
              ))}
            </select>
            {keys.llmProvider && (
              <p className="text-[11px] text-text-muted">
                {LLM_PROVIDERS.find((p) => p.value === keys.llmProvider)?.hint}
              </p>
            )}
            <div className="relative">
              <input
                type={showLLM ? "text" : "password"}
                value={keys.llmKey}
                onChange={(e) => setKeys({ ...keys, llmKey: e.target.value })}
                placeholder={llmKeyPlaceholder(keys.llmProvider)}
                className="w-full rounded border border-line bg-surface-alt px-2 py-1.5 pr-8 font-mono text-xs text-text-primary placeholder:text-text-muted focus:border-line-strong focus:outline-none"
                autoComplete="off"
                spellCheck={false}
              />
              <button
                type="button"
                onClick={() => setShowLLM((s) => !s)}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-primary"
                aria-label={showLLM ? "Hide key" : "Show key"}
              >
                {showLLM ? <EyeOff size={12} /> : <Eye size={12} />}
              </button>
            </div>

            {/* Provider-specific model selector */}
            {keys.llmProvider === "openrouter" && (
              <div className="space-y-1">
                <div className="flex items-center justify-between">
                  <label className="text-[11px] text-text-secondary">
                    Model ID
                  </label>
                  <a
                    href="https://openrouter.ai/models"
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 text-[11px] text-text-muted hover:text-brand"
                  >
                    browse models
                    <ExternalLink size={10} />
                  </a>
                </div>
                <input
                  type="text"
                  value={keys.llmModel}
                  onChange={(e) => setKeys({ ...keys, llmModel: e.target.value })}
                  placeholder="anthropic/claude-sonnet-4.5"
                  list="openrouter-models"
                  className="w-full rounded border border-line bg-surface-alt px-2 py-1.5 font-mono text-xs text-text-primary placeholder:text-text-muted focus:border-line-strong focus:outline-none"
                  autoComplete="off"
                  spellCheck={false}
                />
                <datalist id="openrouter-models">
                  {OPENROUTER_SUGGESTIONS.map((slug) => (
                    <option key={slug} value={slug} />
                  ))}
                </datalist>
                <p className="text-[11px] text-text-muted">
                  Format: <code className="font-mono">org/model-name</code>. Leave blank to fall back to{" "}
                  <code className="font-mono">google/gemini-2.5-flash</code>.
                </p>
              </div>
            )}

            {keys.llmProvider === "openai" && (
              <div className="rounded border border-line/60 bg-surface-alt/40 px-2 py-1.5 text-[11px] text-text-muted">
                Model: <code className="font-mono text-text-secondary">gpt-5.4-mini</code> (locked — reasoning model, ~$0.40/$1.60 per 1M tokens)
              </div>
            )}

            <ValidateRow
              ready={llmReady}
              status={llmStatus}
              onClick={handleValidateLLM}
              kind="LLM"
            />
          </div>

          {/* Scraper key */}
          <div className="space-y-2">
            <label className="text-xxs font-semibold uppercase tracking-[0.16em] text-text-secondary">
              Scraper provider
            </label>
            <select
              value={keys.scraperProvider}
              onChange={(e) =>
                setKeys({
                  ...keys,
                  scraperProvider: e.target.value as ScraperProvider | "",
                })
              }
              className="w-full rounded border border-line bg-surface-alt px-2 py-1.5 text-sm text-text-primary focus:border-line-strong focus:outline-none"
            >
              <option value="">— none —</option>
              {SCRAPER_PROVIDERS.map((p) => (
                <option key={p.value} value={p.value}>
                  {p.label}
                </option>
              ))}
            </select>
            {keys.scraperProvider && (
              <p className="text-[11px] text-text-muted">
                {SCRAPER_PROVIDERS.find((p) => p.value === keys.scraperProvider)?.hint}
              </p>
            )}
            <div className="relative">
              <input
                type={showScraper ? "text" : "password"}
                value={keys.scraperKey}
                onChange={(e) => setKeys({ ...keys, scraperKey: e.target.value })}
                placeholder="fc-... (paste your key)"
                className="w-full rounded border border-line bg-surface-alt px-2 py-1.5 pr-8 font-mono text-xs text-text-primary placeholder:text-text-muted focus:border-line-strong focus:outline-none"
                autoComplete="off"
                spellCheck={false}
              />
              <button
                type="button"
                onClick={() => setShowScraper((s) => !s)}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-primary"
                aria-label={showScraper ? "Hide key" : "Show key"}
              >
                {showScraper ? <EyeOff size={12} /> : <Eye size={12} />}
              </button>
            </div>

            <ValidateRow
              ready={scraperReady}
              status={scraperStatus}
              onClick={handleValidateScraper}
              kind="scraper"
            />
          </div>
        </div>

        <div className="flex items-center justify-between border-t border-line px-4 py-3">
          <button
            onClick={handleClear}
            className="text-xs text-text-muted hover:text-status-critical"
          >
            Clear all keys
          </button>
          <div className="flex gap-2">
            <button
              onClick={onClose}
              className="rounded border border-line bg-surface-alt px-3 py-1.5 text-xs text-text-secondary hover:border-line-strong hover:text-text-primary"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              className="rounded border border-brand/40 bg-brand/20 px-3 py-1.5 text-xs font-semibold text-brand hover:bg-brand/30"
            >
              Save
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function llmKeyPlaceholder(provider: LLMProvider | ""): string {
  switch (provider) {
    case "openrouter":
      return "sk-or-v1-... (paste your OpenRouter key)";
    case "gemini":
      return "AIza... (paste your Google AI Studio key)";
    case "openai":
      return "sk-... (paste your OpenAI key)";
    default:
      return "paste your key";
  }
}


interface ValidateRowProps {
  ready: boolean;
  status: ValidationStatus;
  onClick: () => void;
  kind: "LLM" | "scraper";
}

function ValidateRow({ ready, status, onClick, kind }: ValidateRowProps) {
  const loading = status.state === "loading";
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between gap-2">
        <button
          type="button"
          onClick={onClick}
          disabled={!ready || loading}
          className="inline-flex items-center gap-1.5 rounded border border-line bg-surface-alt px-2.5 py-1 text-[11px] text-text-secondary transition hover:border-line-strong hover:text-text-primary disabled:cursor-not-allowed disabled:opacity-50"
        >
          {loading ? (
            <>
              <Loader2 size={11} className="animate-spin" />
              Validating…
            </>
          ) : (
            <>Validate {kind} key</>
          )}
        </button>
        <StatusBadge status={status} />
      </div>
      <StatusDetail status={status} />
    </div>
  );
}

function StatusBadge({ status }: { status: ValidationStatus }) {
  if (status.state === "idle" || status.state === "loading") return null;
  if (status.state === "error") {
    return (
      <span className="inline-flex items-center gap-1 rounded border border-status-critical/40 bg-status-critical/10 px-1.5 py-0.5 text-[10px] uppercase tracking-wider text-status-critical">
        <AlertCircle size={10} />
        Request failed
      </span>
    );
  }
  // status.state === "done"
  const r = status.result;
  if (r.ok) {
    return (
      <span className="inline-flex items-center gap-1 rounded border border-status-ok/40 bg-status-ok/10 px-1.5 py-0.5 text-[10px] uppercase tracking-wider text-status-ok">
        <CheckCircle2 size={10} />
        Valid · {r.latency_ms}ms
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded border border-status-critical/40 bg-status-critical/10 px-1.5 py-0.5 text-[10px] uppercase tracking-wider text-status-critical">
      <AlertCircle size={10} />
      {r.error_category ?? "error"}
    </span>
  );
}

function StatusDetail({ status }: { status: ValidationStatus }) {
  if (status.state === "error") {
    return (
      <p className="text-[11px] text-status-critical">{status.message}</p>
    );
  }
  if (status.state !== "done") return null;
  const r = status.result;
  if (r.ok) {
    return (
      <p className="text-[11px] text-text-muted">
        Key works. {r.provider && <span className="font-mono">{r.provider}</span>}
        {r.model && r.model !== "(default)" && (
          <>
            {" · "}
            <span className="font-mono">{r.model}</span>
          </>
        )}
      </p>
    );
  }
  return (
    <div className="space-y-0.5">
      {r.error && (
        <p className="text-[11px] text-status-critical">{r.error}</p>
      )}
      {r.detail && r.detail !== r.error && (
        <details className="text-[11px] text-text-muted">
          <summary className="cursor-pointer hover:text-text-secondary">
            Provider detail
          </summary>
          <pre className="mt-1 whitespace-pre-wrap break-words rounded border border-line bg-surface-alt p-2 font-mono text-[10px]">
            {r.detail}
          </pre>
        </details>
      )}
    </div>
  );
}
