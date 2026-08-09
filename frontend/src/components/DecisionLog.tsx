import { useState, type CSSProperties } from "react";

import { Panel } from "@/components/Panel";
import { decisionLogRowSeverity } from "@/lib/severity";
import { cn } from "@/lib/utils";
import type { TickRecord } from "@/types";

const ROWS_DEFAULT = 50;

const ROW_BG_VAR: Record<ReturnType<typeof decisionLogRowSeverity>, string | undefined> = {
  red: "var(--color-severity-red-bg)",
  amber: "var(--color-severity-amber-bg)",
  none: undefined,
};

const SOURCE_COLOR: Record<string, string> = {
  manual: "text-muted-foreground",
  pid: "text-severity-violet",
  ai: "text-severity-amber",
};

function formatFlags(flags: Record<string, boolean>): string {
  const active = Object.entries(flags)
    .filter(([, v]) => v)
    .map(([k]) => k);
  return active.join(", ") || "-";
}

export function DecisionLog({ ticks }: { ticks: TickRecord[] }) {
  const [showFullHistory, setShowFullHistory] = useState(false);

  const rows = showFullHistory ? ticks : ticks.slice(-ROWS_DEFAULT);
  const rowsNewestFirst = [...rows].reverse();

  return (
    <Panel
      title="Decision log — most important element, always in view"
      action={
        <label className="flex items-center gap-1.5 text-[11.5px] text-muted-foreground select-none">
          <input
            type="checkbox"
            checked={showFullHistory}
            onChange={(e) => setShowFullHistory(e.target.checked)}
            className="size-3"
          />
          Show full history
        </label>
      }
      className="flex-1"
    >
      <div className="max-h-[420px] overflow-y-auto rounded-md border border-border">
        <table className="w-full border-collapse text-[11.5px]">
          <thead className="sticky top-0 bg-card">
            <tr className="border-b border-border text-left text-[10px] tracking-wide text-muted-foreground uppercase">
              <th className="px-2 py-1.5 font-bold">Tick</th>
              <th className="px-2 py-1.5 font-bold">Src</th>
              <th className="px-2 py-1.5 font-bold">Out</th>
              <th className="px-2 py-1.5 font-bold">Result</th>
              <th className="px-2 py-1.5 font-bold">Reason</th>
              <th className="px-2 py-1.5 font-bold">Override</th>
              <th className="px-2 py-1.5 font-bold">Locked</th>
              <th className="px-2 py-1.5 font-bold">Detector</th>
            </tr>
          </thead>
          <tbody>
            {rowsNewestFirst.map((record) => {
              const severity = decisionLogRowSeverity(record);
              return (
                <tr
                  key={record.tick}
                  className="decision-log-row border-b border-border/40"
                  style={{ "--row-bg": ROW_BG_VAR[severity] } as CSSProperties}
                >
                  <td className="px-2 py-1.5 font-mono text-muted-foreground">{record.tick}</td>
                  <td className="px-2 py-1.5">
                    <span className={cn("font-mono text-[10px] font-bold", SOURCE_COLOR[record.controller_source])}>
                      {record.controller_source.toUpperCase()}
                    </span>
                  </td>
                  <td className="px-2 py-1.5 font-mono text-foreground">{record.actuator_output.toFixed(1)}%</td>
                  <td className="px-2 py-1.5">
                    <span
                      className={cn(
                        "rounded-sm px-1.5 py-0.5 text-[10px] font-bold uppercase",
                        severity === "red" && "bg-severity-red-bg text-severity-red",
                        severity === "amber" && "bg-severity-amber-bg text-severity-amber",
                        severity === "none" && "text-muted-foreground",
                      )}
                    >
                      {record.interlock_result}
                    </span>
                  </td>
                  <td className="px-2 py-1.5 text-foreground/80">{record.interlock_reason}</td>
                  <td className="px-2 py-1.5 text-muted-foreground">{record.override_active ? "Y" : "N"}</td>
                  <td className="px-2 py-1.5 text-muted-foreground">{record.interlock_locked_out ? "Y" : "N"}</td>
                  <td className="px-2 py-1.5 text-[10.5px] text-muted-foreground">{formatFlags(record.detector_flags)}</td>
                </tr>
              );
            })}
            {rowsNewestFirst.length === 0 && (
              <tr>
                <td colSpan={8} className="px-2 py-6 text-center text-muted-foreground">
                  No ticks yet — press Run to start
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
