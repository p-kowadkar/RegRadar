import type { CoverageRow } from "../types";
import { Card, SectionHeader } from "./Card";

interface Props {
  rows: CoverageRow[];
}

export function CoverageMatrix({ rows }: Props) {
  return (
    <Card className="overflow-hidden">
      <SectionHeader
        title="Asset × regulation coverage"
        meta={`${rows.length} mappings`}
      />
      {rows.length === 0 ? (
        <div className="px-4 py-6 text-sm text-text-muted">
          No coverage mappings recorded.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-y border-line text-xxs uppercase tracking-[0.16em] text-text-muted">
                <th className="px-4 py-2 text-left font-medium">Asset</th>
                <th className="px-4 py-2 text-left font-medium">Regulation</th>
                <th className="px-4 py-2 text-left font-medium">Owner</th>
                <th className="px-4 py-2 text-right font-medium">CDEs</th>
                <th className="px-4 py-2 text-right font-medium">Open</th>
                <th className="px-4 py-2 text-left font-medium">Scope</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {rows.map((r) => (
                <tr
                  key={`${r.asset_id}::${r.regulation_id}`}
                  className="hover:bg-surface-alt/40"
                >
                  <td className="px-4 py-2">
                    <div className="text-text-primary">{r.asset_name}</div>
                    <div className="font-mono text-[11px] text-text-muted">
                      {r.asset_id}
                    </div>
                  </td>
                  <td className="px-4 py-2">
                    <div className="text-text-primary">{r.reg_code}</div>
                    <div className="font-mono text-[11px] text-text-muted">
                      {r.regulation_id}
                    </div>
                  </td>
                  <td className="px-4 py-2 text-text-secondary">
                    {r.compliance_owner || "—"}
                  </td>
                  <td className="px-4 py-2 text-right font-mono text-xs text-text-secondary tabular-nums">
                    {r.cde_count}
                  </td>
                  <td
                    className={`px-4 py-2 text-right font-mono text-xs tabular-nums ${
                      r.open_violations > 0
                        ? "text-status-critical"
                        : "text-text-muted"
                    }`}
                  >
                    {r.open_violations}
                  </td>
                  <td className="px-4 py-2">
                    {r.in_scope ? (
                      <span className="rounded border border-status-ok/40 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-status-ok">
                        in scope
                      </span>
                    ) : (
                      <span className="rounded border border-line px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-text-muted">
                        out
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
