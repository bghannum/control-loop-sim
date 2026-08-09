import { useEffect, useState } from "react";

import { Panel } from "@/components/Panel";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { ControllerMode, Controls } from "@/types";

const MODES: { value: ControllerMode; label: string }[] = [
  { value: "manual", label: "Manual" },
  { value: "pid", label: "PID" },
  { value: "ai", label: "AI" },
];

export function ControllerCard({
  controls,
  setMode,
  setSetpoint,
  setManual,
  setPidGains,
}: {
  controls: Controls;
  setMode: (mode: ControllerMode) => void;
  setSetpoint: (setpointC: number) => void;
  setManual: (heaterPct: number, overrideRequested: boolean) => void;
  setPidGains: (kp: number, ki: number, kd: number) => void;
}) {
  return (
    <Panel title="Controller">
      <Tabs value={controls.mode} onValueChange={(v) => setMode(v as ControllerMode)}>
        <TabsList className="mb-3 w-full">
          {MODES.map((m) => (
            <TabsTrigger key={m.value} value={m.value} className="flex-1">
              {m.label}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      <div className="mb-3">
        <div className="mb-1 flex justify-between text-[11.5px] text-muted-foreground">
          <span>Setpoint</span>
          <span className="font-mono text-foreground">{controls.setpoint_c.toFixed(1)}°C</span>
        </div>
        <Slider
          value={[controls.setpoint_c]}
          min={20}
          max={100}
          step={0.5}
          onValueChange={([v]) => setSetpoint(v)}
        />
      </div>

      <div className="min-h-[100px] border-t border-dashed border-border pt-3">
        {controls.mode === "manual" && <ManualInputs controls={controls} setManual={setManual} />}
        {controls.mode === "pid" && <PidInputs controls={controls} setPidGains={setPidGains} />}
        {controls.mode === "ai" && (
          <p className="text-xs leading-relaxed text-muted-foreground">
            Autonomous within the interlock. See reasoning panel →
          </p>
        )}
      </div>
    </Panel>
  );
}

function ManualInputs({
  controls,
  setManual,
}: {
  controls: Controls;
  setManual: (heaterPct: number, overrideRequested: boolean) => void;
}) {
  return (
    <>
      <div className="mb-2.5">
        <div className="mb-1 flex justify-between text-[11.5px] text-muted-foreground">
          <span>Heater output</span>
          <span className="font-mono text-foreground">{controls.manual_heater_pct.toFixed(0)}%</span>
        </div>
        <Slider
          value={[controls.manual_heater_pct]}
          min={0}
          max={100}
          step={1}
          onValueChange={([v]) => setManual(v, controls.manual_override_requested)}
        />
      </div>
      <div className="flex items-center justify-between">
        <Label htmlFor="override-armed" className="text-[11.5px] font-normal text-muted-foreground">
          Override armed
        </Label>
        <Switch
          id="override-armed"
          size="sm"
          checked={controls.manual_override_requested}
          onCheckedChange={(checked) => setManual(controls.manual_heater_pct, checked)}
        />
      </div>
    </>
  );
}

function PidInputs({
  controls,
  setPidGains,
}: {
  controls: Controls;
  setPidGains: (kp: number, ki: number, kd: number) => void;
}) {
  // Local text-input echoes -- committing on blur avoids firing a control
  // call on every keystroke while still tracking prop updates from resync.
  const [kp, setKp] = useState(String(controls.kp));
  const [ki, setKi] = useState(String(controls.ki));
  const [kd, setKd] = useState(String(controls.kd));

  useEffect(() => setKp(String(controls.kp)), [controls.kp]);
  useEffect(() => setKi(String(controls.ki)), [controls.ki]);
  useEffect(() => setKd(String(controls.kd)), [controls.kd]);

  const commit = (next: { kp?: string; ki?: string; kd?: string }) => {
    const nkp = Number(next.kp ?? kp);
    const nki = Number(next.ki ?? ki);
    const nkd = Number(next.kd ?? kd);
    if (Number.isFinite(nkp) && Number.isFinite(nki) && Number.isFinite(nkd)) {
      setPidGains(nkp, nki, nkd);
    }
  };

  return (
    <div className="grid grid-cols-3 gap-2">
      {(
        [
          ["Kp", kp, setKp, (v: string) => commit({ kp: v })],
          ["Ki", ki, setKi, (v: string) => commit({ ki: v })],
          ["Kd", kd, setKd, (v: string) => commit({ kd: v })],
        ] as const
      ).map(([label, value, setValue, onCommit]) => (
        <div key={label}>
          <div className="mb-0.5 text-[10px] text-muted-foreground">{label}</div>
          <input
            className="w-full rounded-sm border border-border bg-background px-1.5 py-1 font-mono text-[13px] text-foreground outline-none focus:border-ring"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onBlur={(e) => onCommit(e.target.value)}
          />
        </div>
      ))}
    </div>
  );
}
