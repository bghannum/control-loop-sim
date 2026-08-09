import { globalStatus, SEVERITY_PILL_CLASS } from "@/lib/severity";
import { cn } from "@/lib/utils";
import type { TickRecord } from "@/types";

export function StatusPill({ latest }: { latest: TickRecord | null }) {
  const s = globalStatus(latest);
  return (
    <div className={cn("flex items-center gap-2 rounded-full py-1.5 pr-3 pl-2", SEVERITY_PILL_CLASS[s.severity])}>
      <span
        className={cn(
          "size-2 shrink-0",
          s.shape === "circle" ? "rounded-full" : "rounded-[2px]",
          s.severity === "green" && "bg-severity-green",
          s.severity === "amber" && "bg-severity-amber",
          s.severity === "red" && "bg-severity-red",
          s.severity === "gray" && "bg-severity-gray",
        )}
      />
      <span className="text-xs font-semibold">{s.code}</span>
    </div>
  );
}
