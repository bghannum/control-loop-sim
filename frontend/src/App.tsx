import { useEffect, useMemo, useState } from "react";

import { AiReasoningPanel } from "@/components/AiReasoningPanel";
import { ControllerCard } from "@/components/ControllerCard";
import { DecisionLog } from "@/components/DecisionLog";
import { FaultInjectionCard } from "@/components/FaultInjectionCard";
import { Panel } from "@/components/Panel";
import { TelemetryTiles } from "@/components/TelemetryTiles";
import { TemperatureChart } from "@/components/TemperatureChart";
import { Toolbar } from "@/components/Toolbar";
import { TriagePanel } from "@/components/TriagePanel";
import { useEventToasts } from "@/hooks/useEventToasts";
import { useSimulationState } from "@/hooks/useSimulationState";
import { cn } from "@/lib/utils";

const RANDOM_SCENARIO = "Random (no fixed seed)";

function useStaleSeconds(lastMessageAt: number | null, isLost: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!isLost) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [isLost]);
  if (lastMessageAt === null) return 0;
  return Math.max(0, Math.round((now - lastMessageAt) / 1000));
}

function App() {
  const sim = useSimulationState();
  useEventToasts(sim.latest);

  const [selectedScenario, setSelectedScenario] = useState(RANDOM_SCENARIO);
  const resetSeed = useMemo(
    () => sim.scenarios.find((s) => s.name === selectedScenario)?.seed ?? null,
    [sim.scenarios, selectedScenario],
  );

  const isLost = sim.status === "lost";
  const staleSeconds = useStaleSeconds(sim.lastMessageAt, isLost);

  return (
    <main className="min-h-screen bg-background px-6 py-6 text-foreground">
      <div className="mx-auto flex max-w-[1680px] flex-col gap-3.5">
        <Toolbar
          status={sim.status}
          latest={sim.latest}
          running={sim.running}
          toggleRunning={sim.toggleRunning}
          resetSession={sim.resetSession}
          resetInterlock={sim.resetInterlock}
          resetSeed={resetSeed}
        />

        <div className="grid grid-cols-[260px_1fr] gap-4">
          <div className="flex flex-col gap-3.5">
            <ControllerCard
              controls={sim.controls}
              setMode={sim.setMode}
              setSetpoint={sim.setSetpoint}
              setManual={sim.setManual}
              setPidGains={sim.setPidGains}
            />
            <FaultInjectionCard
              scenarios={sim.scenarios}
              selectedScenario={selectedScenario}
              onScenarioChange={setSelectedScenario}
              controls={sim.controls}
              setDrift={sim.setDrift}
              setStuck={sim.setStuck}
              triggerSpike={sim.triggerSpike}
            />
          </div>

          <div className="flex flex-col gap-3.5">
            <TelemetryTiles latest={sim.latest} />

            <div className="grid grid-cols-[1.7fr_1fr] gap-3.5">
              <Panel
                title="Chart"
                action={
                  <div className="flex gap-3.5 text-[11px] text-foreground/70">
                    <LegendSwatch color="bg-[oklch(0.68_0.18_40)]" label="True" />
                    <LegendSwatch color="bg-[oklch(0.68_0.14_230)]" label="Sensed" />
                    <LegendSwatch color="bg-[oklch(0.55_0.01_240)]" label="Setpoint" />
                  </div>
                }
                className="relative overflow-hidden"
              >
                <TemperatureChart ticks={sim.ticks} />
                {isLost && <StaleOverlay seconds={staleSeconds} />}
              </Panel>

              <AiReasoningPanel mode={sim.controls.mode} latest={sim.latest} />
            </div>

            <TriagePanel
              ticks={sim.ticks}
              latest={sim.latest}
              result={sim.lastTriage}
              loading={sim.triageLoading}
              onRequest={sim.requestTriage}
            />

            <div className="relative">
              <DecisionLog ticks={sim.ticks} />
              {isLost && <StaleOverlay seconds={staleSeconds} label="Log frozen — no new ticks since disconnect" />}
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}

function LegendSwatch({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className={cn("inline-block h-0.5 w-2.5", color)} />
      {label}
    </span>
  );
}

function StaleOverlay({ seconds, label }: { seconds: number; label?: string }) {
  return (
    <div
      className="absolute inset-0 flex items-center justify-center"
      style={{
        backgroundImage:
          "repeating-linear-gradient(135deg, oklch(0.16 0.012 240 / .82) 0 14px, oklch(0.19 0.014 240 / .82) 14px 28px)",
      }}
    >
      <div className="rounded-md border border-severity-violet bg-severity-violet-bg px-4 py-2.5 text-[12.5px] font-semibold text-severity-violet">
        {label ?? `Stale — last update ${seconds}s ago`}
      </div>
    </div>
  );
}

export default App;
