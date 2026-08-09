import { Button } from "@/components/ui/button";
import { anyDetectorFlag } from "@/lib/severity";
import type { TickRecord, TriageResponse } from "@/types";

// Not in the Phase 9c mockup's content inventory (an apparent oversight --
// Phase 7 shipped this before the Phase 9 brief was written, and the
// brief's inventory doesn't list it despite claiming Phase 8 parity). Kept
// here anyway rather than silently dropping a shipped feature; same
// trigger condition as app.py's combined button (backlog item 7): a
// detector flag or recent non-allow interlock result, whichever came
// first, since a sensor fault and the interlock's reaction to it are
// usually one incident.
const TRIAGE_WINDOW_TICKS = 20; // mirrors config.yaml's triage.history_window_ticks

export function TriagePanel({
  ticks,
  latest,
  result,
  loading,
  onRequest,
}: {
  ticks: TickRecord[];
  latest: TickRecord | null;
  result: TriageResponse | null;
  loading: boolean;
  onRequest: () => void;
}) {
  if (latest === null) return null;

  const recent = ticks.slice(-TRIAGE_WINDOW_TICKS);
  const available = anyDetectorFlag(latest) || recent.some((r) => r.interlock_result !== "allow");

  return (
    <div className="flex items-center gap-3">
      <Button type="button" size="sm" variant="outline" disabled={!available || loading} onClick={onRequest}>
        {loading ? "Asking Claude…" : "Triage with Claude"}
      </Button>
      {!available && (
        <span className="text-[10.5px] text-muted-foreground">
          Enabled once a detector flag is active or the interlock has rejected/clamped/tripped recently.
        </span>
      )}
      {result && result.success && (
        <span className="text-[11.5px] text-foreground/90">
          <b>Triage:</b> likely {result.fault_type} (severity: {result.severity}) — {result.explanation}
        </span>
      )}
      {result && !result.success && (
        <span className="text-[11.5px] text-muted-foreground">Triage failed: {result.error}</span>
      )}
    </div>
  );
}
