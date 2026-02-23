import { useState } from "react";
import "./App.css";

type HealthResp = { status: string };

const API_BASE = import.meta.env.VITE_API_BASE_URL as string;

export default function App() {
  const [loading, setLoading] = useState(false);
  const [resp, setResp] = useState<HealthResp | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function checkHealth() {
    setLoading(true);
    setErr(null);
    setResp(null);

    try {
      const r = await fetch(`${API_BASE}/health`, {
        method: "GET",
        credentials: "include", // important for cookie auth later
      });
      if (!r.ok) {
        throw new Error(`HTTP ${r.status}`);
      }
      const data = (await r.json()) as HealthResp;
      setResp(data);
    } catch (e: any) {
      setErr(e?.message ?? "Unknown error");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ maxWidth: 720, margin: "40px auto", padding: 16 }}>
      <h1>PM Agent OS (V0)</h1>
      <p>Frontend: React + Vite | Backend: FastAPI | DB: Postgres (Docker)</p>

      <button onClick={checkHealth} disabled={loading}>
        {loading ? "Checking..." : "Check API /health"}
      </button>

      {resp && (
        <pre style={{ marginTop: 16 }}>{JSON.stringify(resp, null, 2)}</pre>
      )}
      {err && <p style={{ marginTop: 16, color: "crimson" }}>{err}</p>}
    </div>
  );
}