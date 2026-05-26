import { KeyRound, Radar, RotateCw, Settings } from "lucide-react";

interface Props {
  pollMs: number;
  apiUrl: string;
  onRefresh: () => void;
  onOpenSettings: () => void;
  byokActive: boolean;
}

export function Header({
  pollMs,
  apiUrl,
  onRefresh,
  onOpenSettings,
  byokActive,
}: Props) {
  return (
    <header className="border-b border-line bg-surface/80 backdrop-blur">
      <div className="flex items-center justify-between px-6 py-3">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded border border-line bg-surface-alt text-brand">
            <Radar size={16} />
          </div>
          <div>
            <div className="text-xxs font-semibold uppercase tracking-[0.2em] text-text-muted">
              RegRadar
            </div>
            <h1 className="text-sm font-semibold text-text-primary">Compliance operations</h1>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <StatusDot label={`API ${stripProtocol(apiUrl)}`} />
          <span className="text-xs text-text-muted">
            polling <span className="text-text-secondary">{pollMs / 1000}s</span>
          </span>
          <button
            onClick={onRefresh}
            className="inline-flex items-center gap-1.5 rounded border border-line bg-surface-alt px-2.5 py-1.5 text-xs text-text-secondary hover:border-line-strong hover:text-text-primary"
          >
            <RotateCw size={12} />
            Refresh
          </button>
          <button
            onClick={onOpenSettings}
            className={`inline-flex items-center gap-1.5 rounded border px-2.5 py-1.5 text-xs ${
              byokActive
                ? "border-status-info/40 bg-status-info/10 text-status-info"
                : "border-line bg-surface-alt text-text-secondary hover:border-line-strong hover:text-text-primary"
            }`}
            title={byokActive ? "BYOK active" : "Bring your own keys"}
          >
            {byokActive ? <KeyRound size={12} /> : <Settings size={12} />}
            {byokActive ? "BYOK" : "Settings"}
          </button>
        </div>
      </div>
    </header>
  );
}

function StatusDot({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-text-muted">
      <span className="relative inline-flex h-2 w-2">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-status-ok opacity-50" />
        <span className="relative inline-flex h-2 w-2 rounded-full bg-status-ok" />
      </span>
      <code className="font-mono text-[11px] text-text-secondary">{label}</code>
    </span>
  );
}

function stripProtocol(url: string): string {
  return url.replace(/^https?:\/\//, "");
}
