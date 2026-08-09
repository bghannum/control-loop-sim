import {
  anyDetectorFlag,
  faultSeverity,
  historianSeverity,
  SEVERITY_DOT_CLASS,
  sensedTempSeverity,
  tripStrikeSeverity,
  type Severity,
} from "@/lib/severity";
import { cn } from "@/lib/utils";
import type { TickRecord } from "@/types";

const K_OFFSET_C = 273.15;

interface Tile {
  label: string;
  value: string;
  sub: string;
  severity: Severity;
}

// The FastAPI backend (unlike app.py) doesn't wire up a Historian instance
// at all yet -- Phase 4 wired it into Streamlit only. Shown honestly as
// "not wired" rather than faked; see BACKLOG.md for wiring it in properly.
function buildTiles(latest: TickRecord | null): Tile[] {
  if (latest === null) {
    return [
      { label: "True temp", value: "—", sub: "ground truth", severity: "gray" },
      { label: "Sensed temp", value: "—", sub: "reported", severity: "gray" },
      { label: "Actuator", value: "—", sub: "heater output", severity: "gray" },
      { label: "Active faults", value: "none", sub: "ground truth", severity: "gray" },
      { label: "Detector flags", value: "none", sub: "Tier-1 belief", severity: "gray" },
      { label: "Historian", value: "not wired", sub: "logging status", severity: "gray" },
      { label: "Trip strikes", value: "0", sub: "before lockout", severity: "gray" },
    ];
  }

  const activeFlags = Object.entries(latest.detector_flags)
    .filter(([, v]) => v)
    .map(([k]) => k);

  return [
    { label: "True temp", value: `${(latest.t_true - K_OFFSET_C).toFixed(1)}°C`, sub: "ground truth", severity: "gray" },
    {
      label: "Sensed temp",
      value: `${(latest.t_sensed - K_OFFSET_C).toFixed(1)}°C`,
      sub: "reported",
      severity: sensedTempSeverity(latest),
    },
    { label: "Actuator", value: `${latest.actuator_output.toFixed(0)}%`, sub: "heater output", severity: "gray" },
    {
      label: "Active faults",
      value: latest.active_faults.join(", ") || "none",
      sub: "ground truth",
      severity: faultSeverity(latest),
    },
    {
      label: "Detector flags",
      value: activeFlags.join(", ") || "none",
      sub: "Tier-1 belief",
      severity: anyDetectorFlag(latest) ? "red" : "green",
    },
    { label: "Historian", value: "not wired", sub: "logging status", severity: historianSeverity(false) },
    {
      label: "Trip strikes",
      value: `${latest.trip_strikes}/${latest.trip_lockout_threshold}${latest.interlock_locked_out ? " (locked)" : ""}`,
      sub: "before lockout",
      severity: tripStrikeSeverity(latest),
    },
  ];
}

export function TelemetryTiles({ latest }: { latest: TickRecord | null }) {
  const tiles = buildTiles(latest);
  return (
    <div className="grid grid-cols-7 gap-2">
      {tiles.map((tile) => (
        <div key={tile.label} className="rounded-md border border-border bg-card px-2.5 py-2">
          <div className="mb-1 flex items-center gap-1.5 text-[10px] tracking-wide text-muted-foreground uppercase">
            <span className={cn("size-1.5 shrink-0 rounded-full", SEVERITY_DOT_CLASS[tile.severity])} />
            {tile.label}
          </div>
          <div className="truncate font-mono text-[15px] font-semibold text-foreground">{tile.value}</div>
          <div className="mt-0.5 text-[10px] text-muted-foreground">{tile.sub}</div>
        </div>
      ))}
    </div>
  );
}
