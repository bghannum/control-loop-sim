import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import type { TickRecord } from "@/types";

const K_OFFSET_C = 273.15; // Celsius is display-only, never internal -- same constant app.py/backend use

// Colors validated by prior testing (Phase 8 + the Phase 9c mockup) --
// kept identical across both frontends deliberately.
const TRUE_COLOR = "oklch(0.68 0.18 40)"; // red/orange
const SENSED_COLOR = "oklch(0.68 0.14 230)"; // blue
const SETPOINT_COLOR = "oklch(0.55 0.01 240)"; // dashed neutral

interface ChartRow {
  tick: number;
  true_c: number;
  sensed_c: number;
  setpoint_c: number;
}

export function TemperatureChart({ ticks }: { ticks: TickRecord[] }) {
  const data: ChartRow[] = ticks.map((t) => ({
    tick: t.tick,
    true_c: t.t_true - K_OFFSET_C,
    sensed_c: t.t_sensed - K_OFFSET_C,
    setpoint_c: t.setpoint - K_OFFSET_C,
  }));

  if (data.length === 0) {
    return (
      <div className="flex h-[280px] items-center justify-center text-sm text-muted-foreground">
        No data yet — press Run to start
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={280}>
      <LineChart data={data}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
        <XAxis dataKey="tick" stroke="var(--muted-foreground)" fontSize={11} />
        <YAxis unit="°C" stroke="var(--muted-foreground)" fontSize={11} width={48} />
        <Tooltip
          contentStyle={{ background: "var(--popover)", border: "1px solid var(--border)", fontSize: 12 }}
          formatter={(value, name) => [`${Number(value).toFixed(1)}°C`, name]}
        />
        <Line type="monotone" dataKey="setpoint_c" name="Setpoint" stroke={SETPOINT_COLOR} strokeDasharray="6 6" dot={false} isAnimationActive={false} />
        <Line type="monotone" dataKey="true_c" name="True" stroke={TRUE_COLOR} strokeWidth={2} dot={false} isAnimationActive={false} />
        <Line type="monotone" dataKey="sensed_c" name="Sensed" stroke={SENSED_COLOR} strokeWidth={2} dot={false} isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}
