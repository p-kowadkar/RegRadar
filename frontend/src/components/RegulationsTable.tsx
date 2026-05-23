import type { Regulation } from "../types";
import { Card, SectionHeader } from "./Card";

interface Props {
  items: Regulation[];
}

export function RegulationsTable({ items }: Props) {
  return (
    <Card className="overflow-hidden">
      <SectionHeader title="Regulations registry" meta={`${items.length} controls`} />
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-y border-line text-xxs uppercase tracking-[0.16em] text-text-muted">
              <th className="px-4 py-2 text-left font-medium">ID</th>
              <th className="px-4 py-2 text-left font-medium">Reg code</th>
              <th className="px-4 py-2 text-left font-medium">Control</th>
              <th className="px-4 py-2 text-left font-medium">Trigger</th>
              <th className="px-4 py-2 text-left font-medium">Threshold</th>
              <th className="px-4 py-2 text-left font-medium">Last crawled</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {items.map((r) => (
              <tr key={r.regulation_id} className="hover:bg-surface-alt/40">
                <td className="px-4 py-2 font-mono text-xs text-text-secondary">
                  {r.regulation_id}
                </td>
                <td className="px-4 py-2 text-text-primary">{r.reg_code}</td>
                <td className="px-4 py-2 text-text-primary">{r.control_name}</td>
                <td className="px-4 py-2">
                  <span className="rounded border border-line bg-surface-alt px-1.5 py-0.5 text-[10px] uppercase tracking-wider text-text-secondary">
                    {r.trigger_type}
                  </span>
                </td>
                <td className="px-4 py-2 text-text-secondary">
                  {r.threshold_label || (r.threshold_days != null ? `${r.threshold_days} days` : "—")}
                </td>
                <td className="px-4 py-2 font-mono text-xs text-text-muted">
                  {r.last_crawled_at
                    ? new Date(r.last_crawled_at).toLocaleString()
                    : "never"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
