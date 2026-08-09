import { useEffect, useState } from "react";

import { API_BASE_URL } from "./config";
import { ConnectionBadge } from "./ConnectionBadge";
import { TemperatureChart } from "./TemperatureChart";
import { useTickStream } from "./useTickStream";

function App() {
  const { status, ticks, latest } = useTickStream();
  const [running, setRunning] = useState<boolean | null>(null); // null until the initial GET /state resolves

  useEffect(() => {
    fetch(`${API_BASE_URL}/state`)
      .then((res) => res.json())
      .then((state: { running: boolean }) => setRunning(state.running))
      .catch((err) => console.error("failed to fetch initial /state", err));
  }, []);

  const toggleRunning = () => {
    const next = !running;
    fetch(`${API_BASE_URL}/session/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ running: next }),
    })
      .then((res) => res.json())
      .then((body: { running: boolean }) => setRunning(body.running))
      .catch((err) => console.error("failed to POST /session/run", err));
  };

  return (
    <main>
      <header style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
        <h1 style={{ fontSize: "1.25rem", margin: 0 }}>Control Loop -- Phase 9b</h1>
        <ConnectionBadge status={status} />
        <button type="button" onClick={toggleRunning} disabled={running === null}>
          {running ? "Stop" : "Run"}
        </button>
      </header>

      <p>
        {ticks.length} ticks received{latest ? ` -- latest tick #${latest.tick}` : ""}
      </p>

      <TemperatureChart ticks={ticks} />
    </main>
  );
}

export default App;
