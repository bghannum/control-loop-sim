import { CONNECTION_DOT_CLASS, CONNECTION_LABEL, CONNECTION_PILL_CLASS, CONNECTION_PULSE } from "@/lib/severity";
import { cn } from "@/lib/utils";
import type { ConnectionStatus } from "@/types";

export function ConnectionBadge({ status }: { status: ConnectionStatus }) {
  return (
    <div className={cn("flex items-center gap-1.5 rounded-full py-1 pr-2.5 pl-2 text-xs font-medium", CONNECTION_PILL_CLASS[status])}>
      <span
        className={cn("size-1.5 rounded-full", CONNECTION_DOT_CLASS[status], CONNECTION_PULSE[status] && "animate-pulse")}
      />
      {CONNECTION_LABEL[status]}
    </div>
  );
}
