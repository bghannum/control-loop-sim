import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import type { TickRecord } from "./types";

const K_OFFSET_C = 273.15; // Celsius is display-only, never internal -- same constant app.py/backend use

interface ChartRow {
  tick: number;
  sensed_c: number;
}

export function TemperatureChart({ ticks }: { ticks: TickRecord[] }) {
  const data: ChartRow[] = ticks.map((t) => ({
    tick: t.tick,
    sensed_c: t.t_sensed - K_OFFSET_C,
  }));

  return (
    <ResponsiveContainer width="100%" height={280}>
      <LineChart data={data}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="tick" />
        <YAxis unit="°C" />
        <Tooltip formatter={(value) => `${Number(value).toFixed(1)}°C`} />
        <Line type="monotone" dataKey="sensed_c" stroke="#2563eb" dot={false} isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}
