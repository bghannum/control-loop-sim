import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

// Lightweight card matching the mockup's info-dense style (tight padding,
// small uppercase section label) -- shadcn's own Card/CardHeader/CardTitle
// carry more chrome than this content needs.
export function Panel({
  title,
  action,
  className,
  children,
}: {
  title: string;
  action?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={cn("rounded-lg border border-border bg-card p-3.5", className)}>
      <div className="mb-2.5 flex items-center">
        <span className="text-[10.5px] font-bold tracking-wide text-muted-foreground uppercase">{title}</span>
        {action && <div className="ml-auto">{action}</div>}
      </div>
      {children}
    </div>
  );
}
