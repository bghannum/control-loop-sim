import type { ConnectionStatus } from "./types";

const LABELS: Record<ConnectionStatus, string> = {
  connecting: "Connecting...",
  open: "Connected",
  reconnecting: "Reconnecting...",
  lost: "Connection lost",
};

const COLORS: Record<ConnectionStatus, string> = {
  connecting: "#9ca3af", // gray
  open: "#16a34a", // green
  reconnecting: "#d97706", // amber
  lost: "#dc2626", // red
};

export function ConnectionBadge({ status }: { status: ConnectionStatus }) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: "0.4rem",
        padding: "0.25rem 0.6rem",
        borderRadius: "999px",
        border: `1px solid ${COLORS[status]}`,
        color: COLORS[status],
        fontSize: "0.85rem",
        fontWeight: 600,
      }}
    >
      <span
        style={{
          width: "0.5rem",
          height: "0.5rem",
          borderRadius: "50%",
          background: COLORS[status],
        }}
      />
      {LABELS[status]}
    </span>
  );
}
