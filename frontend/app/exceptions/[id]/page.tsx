"use client";
import { useEffect, useState } from "react";

export default function ExceptionDetail({ params }: { params: { id: string } }) {
  const [exc, setExc] = useState<any>(null);
  const [rationale, setRationale] = useState("");
  const [result, setResult] = useState("");

  useEffect(() => {
    fetch(`http://localhost:8000/exceptions/${params.id}`)
      .then((r) => r.json())
      .then(setExc);
  }, [params.id]);

  async function resolve() {
    const res = await fetch(`http://localhost:8000/exceptions/${params.id}/resolve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision: "approved", rationale }),
    });
    setResult(`${res.status}: ${await res.text()}`);
  }

  if (!exc) return <main style={{ padding: "2rem" }}>Loading…</main>;
  return (
    <main style={{ padding: "2rem", fontFamily: "system-ui", maxWidth: 900 }}>
      <h1>Exception {exc.id}</h1>
      <p>Type: <strong>{exc.type}</strong> · Status: <strong>{exc.status}</strong> · Amount: {exc.amount} {exc.currency}</p>
      <h2>Evidence</h2>
      <pre>{JSON.stringify(exc.evidence, null, 2)}</pre>
      <h2>Hypotheses</h2>
      <pre>{JSON.stringify(exc.hypotheses, null, 2)}</pre>
      <h2>Proposed remedy</h2>
      <pre>{JSON.stringify(exc.proposed_remedy, null, 2)}</pre>
      <h2>Human ruling</h2>
      <input value={rationale} onChange={(e) => setRationale(e.target.value)} placeholder="One-line rationale (required)" style={{ width: "100%", padding: "0.5rem" }} />
      <button onClick={resolve} style={{ marginTop: "0.5rem", padding: "0.5rem 1rem" }}>Approve with rationale</button>
      {result && <p>{result}</p>}
    </main>
  );
}
