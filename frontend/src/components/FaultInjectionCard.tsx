import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Panel } from "@/components/Panel";
import { Switch } from "@/components/ui/switch";
import type { Controls, Scenario } from "@/types";

const RANDOM_LABEL = "Random (no fixed seed)";

export function FaultInjectionCard({
  scenarios,
  selectedScenario,
  onScenarioChange,
  controls,
  setDrift,
  setStuck,
  triggerSpike,
}: {
  scenarios: Scenario[];
  selectedScenario: string;
  onScenarioChange: (name: string) => void;
  controls: Controls;
  setDrift: (enabled: boolean) => void;
  setStuck: (enabled: boolean) => void;
  triggerSpike: () => void;
}) {
  return (
    <Panel title="Fault injection">
      <select
        className="mb-2.5 w-full rounded-sm border border-border bg-background px-2 py-1.5 text-[12.5px] text-foreground outline-none focus:border-ring"
        value={selectedScenario}
        onChange={(e) => onScenarioChange(e.target.value)}
      >
        <option value={RANDOM_LABEL}>{RANDOM_LABEL}</option>
        {scenarios.map((s) => (
          <option key={s.name} value={s.name}>
            {s.name}
          </option>
        ))}
      </select>
      <p className="mb-2.5 text-[10px] text-muted-foreground">Seeds noise, applied on Reset</p>

      <div className="mb-2 flex items-center justify-between">
        <Label htmlFor="drift-toggle" className="text-[11.5px] font-normal text-muted-foreground">
          Drift
        </Label>
        <Switch id="drift-toggle" size="sm" checked={controls.drift_enabled} onCheckedChange={setDrift} />
      </div>
      <div className="mb-3 flex items-center justify-between">
        <Label htmlFor="stuck-toggle" className="text-[11.5px] font-normal text-muted-foreground">
          Stuck-at
        </Label>
        <Switch id="stuck-toggle" size="sm" checked={controls.stuck_enabled} onCheckedChange={setStuck} />
      </div>

      <Button type="button" variant="outline" size="sm" className="w-full" onClick={triggerSpike}>
        Trigger spike
      </Button>
    </Panel>
  );
}
