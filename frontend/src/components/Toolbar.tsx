import { ConnectionBadge } from "@/components/ConnectionBadge";
import { StatusPill } from "@/components/StatusPill";
import { Button } from "@/components/ui/button";
import { TwoStageButton } from "@/components/TwoStageButton";
import type { ConnectionStatus, TickRecord } from "@/types";

export function Toolbar({
  status,
  latest,
  running,
  toggleRunning,
  resetSession,
  resetInterlock,
  resetSeed,
}: {
  status: ConnectionStatus;
  latest: TickRecord | null;
  running: boolean;
  toggleRunning: () => void;
  resetSession: (seed?: number | null) => void;
  resetInterlock: () => void;
  resetSeed: number | null;
}) {
  return (
    <div className="flex items-center gap-3 rounded-lg border border-border bg-card px-4 py-2.5">
      <span className="text-sm font-bold tracking-tight text-foreground">Thermal Loop</span>
      <ConnectionBadge status={status} />
      <StatusPill latest={latest} />
      <div className="ml-auto flex gap-2">
        <Button type="button" size="sm" onClick={toggleRunning}>
          {running ? "Pause" : "Run"}
        </Button>
        <TwoStageButton label="Reset" confirmLabel="Confirm reset?" onConfirm={() => resetSession(resetSeed)} />
        <TwoStageButton label="Reset Interlock" confirmLabel="Confirm reset interlock?" onConfirm={resetInterlock} />
      </div>
    </div>
  );
}
