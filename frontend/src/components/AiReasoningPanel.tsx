import { Panel } from "@/components/Panel";
import type { ControllerMode, TickRecord } from "@/types";

// Same DOM slot in every mode -- empty placeholder text in Manual/PID,
// contents swapped in for AI -- so switching modes never reflows neighbors.
export function AiReasoningPanel({ mode, latest }: { mode: ControllerMode; latest: TickRecord | null }) {
  const filled = mode === "ai" && latest !== null;

  return (
    <Panel title="AI reasoning" className="flex min-h-[280px] flex-col border-dashed">
      {!filled && (
        <div className="flex flex-1 items-center justify-center text-center text-[11.5px] leading-relaxed text-muted-foreground/70">
          Reserved for AI mode.
          <br />
          Empty in Manual/PID — same slot, no reflow.
        </div>
      )}
      {filled && latest && <AiReasoningContent latest={latest} />}
    </Panel>
  );
}

function AiReasoningContent({ latest }: { latest: TickRecord }) {
  const proposed = latest.proposed_action;
  const metadata = proposed.metadata as Record<string, unknown>;
  const elapsed = typeof metadata.seconds_since_last_success === "number" ? metadata.seconds_since_last_success : 0;
  const waiting = Boolean(metadata.waiting);
  const lastError = typeof metadata.last_error === "string" ? metadata.last_error : null;

  return (
    <>
      {latest.ai_fallback_active && (
        <div className="mb-2.5 rounded-md bg-severity-red-bg px-2.5 py-1.5 text-[11.5px] font-semibold text-severity-red">
          AI unresponsive for {elapsed.toFixed(0)}s — automatic safe fallback active.
        </div>
      )}
      {!latest.ai_fallback_active && waiting && (
        <div className="mb-2.5 text-[11.5px] text-muted-foreground">Waiting on AI response…</div>
      )}

      <div className="mb-2.5 flex justify-between">
        <div>
          <div className="mb-0.5 text-[10.5px] text-muted-foreground">Confidence</div>
          <div className="font-mono text-[15px] font-semibold text-foreground">{proposed.confidence ?? "—"}</div>
        </div>
        <div>
          <div className="mb-0.5 text-[10.5px] text-muted-foreground">Concern</div>
          <div
            className={`font-mono text-[12.5px] font-semibold ${proposed.flagged_sensor_concern ? "text-severity-amber" : "text-foreground"}`}
          >
            {proposed.flagged_sensor_concern ? "Flagged" : "None"}
          </div>
        </div>
      </div>

      {proposed.rationale && (
        <div className="mb-2.5 border-l-2 border-border pl-2.5 text-xs leading-relaxed text-foreground/90 italic">
          "{proposed.rationale}"
        </div>
      )}

      {lastError && <div className="mt-auto text-[11px] text-muted-foreground">Last AI error: {lastError}</div>}
    </>
  );
}
