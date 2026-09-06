"use client";
import { useState } from "react";

type Proof = { obligation: string; passed: boolean; expected: string; actual: string; delta: string };
type Exc = { id: string; type: string; severity: string; status: string; amount: string };
type FeedEvent = { phase: string; message: string; exception_id?: string };

export default function Home() {
  const [runId, setRunId] = useState("");
  const [status, setStatus] = useState("");
  const [feed, setFeed] = useState<FeedEvent[]>([]);
  const [proofs, setProofs] = useState<Proof[]>([]);
  const [exceptions, setExceptions] = useState<Exc[]>([]);
  const [busy, setBusy] = useState(false);

  async function closeAugust() {
    setBusy(true);
    setFeed([]);
    setProofs([]);
    setExceptions([]);
    const res = await fetch("http://localhost:8000/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ period: "2026-08", rules_enabled: true, seed: 42 }),
    });
    const data = await res.json();
    setRunId(data.run_id);
    setStatus(data.status);
    const es = new EventSource(`http://localhost:8000/runs/${data.run_id}/stream`);
    es.onmessage = (m) => setFeed((f) => [...f, JSON.parse(m.data)]);
    // SSE uses named events; also listen generically via onmessage fallback poll:
    es.addEventListener("package", () => es.close());
    es.addEventListener("await_human", () => es.close());
    setTimeout(() => es.close(), 5000);
    const [pr, ex] = await Promise.all([
      fetch(`http://localhost:8000/runs/${data.run_id}/proofs`).then((r) => r.json()),
      fetch(`http://localhost:8000/runs/${data.run_id}/exceptions`).then((r) => r.json()),
    ]);
    setProofs(pr);
    setExceptions(ex);
    setBusy(false);
  }

  const blocked = proofs.some((p) => !p.passed);

  return (
    <main style={{ padding: "2rem", fontFamily: "system-ui", maxWidth: 900 }}>
      <h1>TieOut — Close Agent</h1>
      <p>Deterministic settlement close agent with proof-carrying engine.</p>
      <button onClick={closeAugust} disabled={busy} style={{ padding: "0.6rem 1.2rem", fontSize: "1rem" }}>
        {busy ? "Closing…" : "Close August"}
      </button>
      {runId && <p>Run <code>{runId}</code> — status: <strong>{status}</strong></p>}
      {blocked && <p style={{ color: "#B0403A", fontWeight: 700 }}>Close BLOCKED: proof failure requires ruling.</p>}

      <h2>Live feed (SSE)</h2>
      <ul>{feed.map((e, i) => <li key={i}><code>{e.phase}</code>: {e.message}</li>)}</ul>

      <h2>Proofs P1–P6</h2>
      <table border={1} cellPadding={6}>
        <thead><tr><th>Obligation</th><th>Pass</th><th>Expected</th><th>Actual</th><th>Delta</th></tr></thead>
        <tbody>{proofs.map((p) => (
          <tr key={p.obligation} style={{ background: p.passed ? "#DCEAE0" : "#F4DEDB" }}>
            <td>{p.obligation}</td><td>{String(p.passed)}</td><td>{p.expected}</td><td>{p.actual}</td><td>{p.delta}</td>
          </tr>
        ))}</tbody>
      </table>

      <h2>Exception queue</h2>
      <table border={1} cellPadding={6}>
        <thead><tr><th>ID</th><th>Type</th><th>Severity</th><th>Status</th><th>Amount</th></tr></thead>
        <tbody>{exceptions.map((e) => (
          <tr key={e.id}><td><a href={`/exceptions/${e.id}`}>{e.id}</a></td><td>{e.type}</td><td>{e.severity}</td><td>{e.status}</td><td>{e.amount}</td></tr>
        ))}</tbody>
      </table>
    </main>
  );
}
