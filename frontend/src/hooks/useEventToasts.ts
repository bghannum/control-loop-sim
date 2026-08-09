import { useEffect, useRef } from "react";
import { toast } from "sonner";

import type { TickRecord } from "@/types";

// Fires a toast on a genuine false->true transition between two
// *consecutive* live ticks -- deliberately does not replay anything from a
// GET /state backlog fetch (a resync jumps the tick number non-
// consecutively, which this treats as "just update the baseline, don't
// toast"). See POST_MVP_BACKLOG.md item 1 for why replaying missed events
// was considered and deferred: toasts are a "notice this now" affordance,
// the decision log is the durable record.
export function useEventToasts(latest: TickRecord | null) {
  const prevRef = useRef<TickRecord | null>(null);

  useEffect(() => {
    const prev = prevRef.current;
    prevRef.current = latest;

    if (latest === null) return;
    if (prev === null || latest.tick !== prev.tick + 1) return; // not consecutive -- skip, just rebaseline

    const hadFault = (name: string) => prev.active_faults.includes(name);
    const hasFault = (name: string) => latest.active_faults.includes(name);
    const hadHardTrip = prev.interlock_reason.toLowerCase().includes("hard trip");
    const hasHardTrip = latest.interlock_reason.toLowerCase().includes("hard trip");

    if (!prev.interlock_locked_out && latest.interlock_locked_out) {
      toast.error(`Interlock locked out after ${latest.trip_strikes} trips`);
    }
    if (!hadHardTrip && hasHardTrip) {
      toast.error("Hard trip fired — actuator forced to 0%");
    }
    if (!prev.override_active && latest.override_active) {
      toast.error("Override triggered by operator");
    }
    if (!prev.ai_fallback_active && latest.ai_fallback_active) {
      toast.error("AI fallback engaged — automatic safe control took over");
    }
    if (!hadFault("stuck") && hasFault("stuck")) {
      toast.warning("Stuck-at fault injected");
    }
    if (!hadFault("spike") && hasFault("spike")) {
      toast.warning("Spike burst triggered");
    }
  }, [latest]);
}
