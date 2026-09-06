"use client";
import Link from "next/link";
import { useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type ExcDetail = {
  id: string;
  run_id: string;
  type: string;
  severity: string;
  status: string;
  amount: string;
  currency: string;
  confidence: string;
  evidence: unknown;
  hypotheses: unknown;
  proposed_remedy: unknown;
  detected_by: string;
};

export default function ExceptionDetail({ params }: { params: Promise<{ id: string }> }) {
  const [id, setId] = useState("");
  const [exc, setExc] = useState<ExcDetail | null>(null);
  const [rationale, setRationale] = useState("");
  const [result, setResult] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [resolving, setResolving] = useState(false);

  useEffect(() => {
    params
      .then((p) => {
        setId(p.id);
        return fetch(`${API}/exceptions/${p.id}`);
      })
      .then((r) => {
        if (!r.ok) throw new Error(`Exception not found (${r.status})`);
        return r.json();
      })
      .then(setExc)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load exception"))
      .finally(() => setLoading(false));
  }, [params]);

  async function resolve() {
    if (!rationale.trim()) {
      setResult("A rationale is required — an unexplained approval teaches the compiler nothing.");
      return;
    }
    setResolving(true);
    setResult("");
    try {
      const res = await fetch(`${API}/exceptions/${id}/resolve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision: "approved", rationale }),
      });
      const body = await res.text();
      setResult(res.ok ? `Resolved ✓ — ${body}` : `Failed (${res.status}): ${body}`);
      if (res.ok && exc) setExc({ ...exc, status: "human_resolved" });
    } catch (e) {
      setResult(e instanceof Error ? e.message : "Resolve failed");
    } finally {
      setResolving(false);
    }
  }

  return (
    <main className="container">
      <div className="detail-head">
        <Link className="back" href="/">
          ← Back to close dashboard
        </Link>
        {loading && <div className="skeleton" style={{ marginTop: 16 }}>Loading exception…</div>}
        {error && <div className="error-box">⚠ {error}</div>}
        {exc && (
          <>
            <h1>{exc.id}</h1>
            <div className="detail-meta">
              <span className="pill medium">{exc.type}</span>
              <span className={`pill ${exc.severity}`}>{exc.severity}</span>
              <span className={`pill ${exc.status}`}>{exc.status}</span>
              <span className="run-meta">
                <code>
                  {exc.amount} {exc.currency}
                </code>{" "}
                · confidence <code>{exc.confidence}</code> · via <code>{exc.detected_by}</code>
              </span>
            </div>
          </>
        )}
      </div>

      {exc && (
        <>
          <div className="card">
            <h2>Evidence</h2>
            <pre>{JSON.stringify(exc.evidence, null, 2) ?? "—"}</pre>
          </div>
          <div className="card">
            <h2>Hypotheses</h2>
            <pre>{JSON.stringify(exc.hypotheses, null, 2) ?? "—"}</pre>
          </div>
          <div className="card">
            <h2>Proposed remedy</h2>
            <pre>{JSON.stringify(exc.proposed_remedy, null, 2) ?? "—"}</pre>
          </div>
          <div className="card ruling">
            <h2>Human ruling</h2>
            <textarea
              value={rationale}
              onChange={(e) => setRationale(e.target.value)}
              placeholder="One-line rationale (required) — this becomes the training signal for the Judgment Compiler."
            />
            <div className="row">
              <button className="btn" onClick={resolve} disabled={resolving}>
                {resolving ? "Resolving…" : "Approve with rationale"}
              </button>
            </div>
            {result && <div className="result">{result}</div>}
          </div>
        </>
      )}
    </main>
  );
}
