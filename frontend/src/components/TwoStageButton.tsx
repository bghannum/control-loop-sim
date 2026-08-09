import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";

const CONFIRM_WINDOW_MS = 3000;

// A brief inline confirm for consequential-but-not-catastrophic actions
// (Reset, Reset Interlock) -- design brief explicitly favored this over a
// modal for a live demo tool that needs to move fast, while still keeping
// a deliberate second click between "meant to click that" and "did it."
export function TwoStageButton({
  label,
  confirmLabel,
  onConfirm,
  size = "sm",
}: {
  label: string;
  confirmLabel: string;
  onConfirm: () => void;
  size?: "sm" | "default";
}) {
  const [armed, setArmed] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (timerRef.current) clearTimeout(timerRef.current);
  }, []);

  const handleClick = () => {
    if (!armed) {
      setArmed(true);
      timerRef.current = setTimeout(() => setArmed(false), CONFIRM_WINDOW_MS);
      return;
    }
    if (timerRef.current) clearTimeout(timerRef.current);
    setArmed(false);
    onConfirm();
  };

  return (
    <Button type="button" size={size} variant={armed ? "destructive" : "secondary"} onClick={handleClick}>
      {armed ? confirmLabel : label}
    </Button>
  );
}
