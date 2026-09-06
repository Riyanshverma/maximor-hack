"use client";
import Link from "next/link";
import { useRef, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Proof = {
  obligation: string;
  passed: boolean;
  expected: string;
  actual: string;
  delta: string;
  detail?: Record<string, unknown>;
};
type Exc = {
  id: string;
  type: string;
  severity: string;
  status: string;
  amount: string;
  currency: string;
  confidence: string;
  detected_by: string;
};
type FeedEvent = { phase: string; message: string; exception_id?: string };

const PROOF_NAMES: Record<string, string> = {
  P1: "Debit / credit balance",
  P2: "Payout components sum",
  P3: "Clearing account rollforward",
  P4: "Bank tie-out",
  P5: "Revenue completeness",
  P6: "No-orphans mapping",
};

const ALL_PHASES = [
  "ingest",
  "normalize",
  "match",
  "classify",
  "compose",
  "prove",
  "detect",
  "investigate",
  "route",
  "await_human",
  "reprove",
  "package",
];

export default function Home() {
  const [period, setPeriod] = useState("2026-08");
  const [runId, setRunId] = useState("");
  const [status, setStatus] = useState("");
  const [feed, setFeed] = useState<FeedEvent[]>([]);
  const [proofs, setProofs] = useState<Proof[]>([]);
  const [exceptions, setExceptions] = useState<Exc[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const esRef = useRef<EventSource | null>(null);

  const seenPhases = new Set(feed.map((e) => e.phase));
  const failedProofs = proofs.filter((p) => !p.passed);

  async function runClose() {
    setBusy(true);
    setError("");
    setFeed([]);
    setProofs([]);
    setExceptions([]);
    setRunId("");
    setStatus("");
    esRef.current?.close();
    try {
      const res = await fetch(`${API}/runs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ period, rules_enabled: true, seed: 42 }),
      });
      if (!res.ok) throw new Error(`POST /runs failed: ${res.status}`);
      const data = await res.json();
      setRunId(data.run_id);
      setStatus(data.status);

      const es = new EventSource(`${API}/runs/${data.run_id}/stream`);
      esRef.current = es;
      es.onmessage = (m) => {
        try {
          setFeed((f) => [...f, JSON.parse(m.data)]);
        } catch {
          /* ignore malformed chunk */
        }
      };
      es.onerror = () => es.close();
      setTimeout(() => es.close(), 8000);

      const [pr, ex] = await Promise.all([
        fetch(`${API}/runs/${data.run_id}/proofs`).then((r) => {
          if (!r.ok) throw new Error(`proofs: ${r.status}`);
          return r.json();
        }),
        fetch(`${API}/runs/${data.run_id}/exceptions`).then((r) => {
          if (!r.ok) throw new Error(`exceptions: ${r.status}`);
          return r.json();
        }),
      ]);
      setProofs(pr);
      setExceptions(ex);
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Run failed — is the backend up at " + API + "?"
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="container">
      <section className="hero">
        <h1>Close the period. Prove every cent.</h1>
        <p>
          TieOut decomposes merchant-of-record payouts into journal entries and
          refuses to close until six deterministic proof obligations pass.
          A language model never computes a final dollar amount — the engine does.
        </p>
        <div className="controls">
          <label>
            Period
            <select value={period} onChange={(e) => setPeriod(e.target.value)} disabled={busy}>
              <option value="2026-08">2026-08 — August</option>
              <option value="2026-09">2026-09 — September</option>
            </select>
          </label>
          <div style={{ alignSelf: "flex-end", display: "flex", gap: 10 }}>
            <button className="btn" onClick={runClose} disabled={busy}>
              {busy ? "Closing…" : `Close ${period}`}
            </button>
          </div>
          {runId && (
            <span className="run-meta">
              Run <code>{runId}</code> · status <code>{status}</code>
            </span>
          )}
        </div>
        {error && <div className="error-box">⚠ {error}</div>}
        {status === "blocked" && (
          <div className="banner blocked">
            Close BLOCKED — {failedProofs.map((p) => p.obligation).join(", ")} failing.
            Proof failure is a block, not a warning.
            <small>Review the evidence below and rule on an exception to proceed.</small>
          </div>
        )}
        {status === "closed" && (
          <div className="banner closed">
            Period closed — all six proofs pass, clearing account is $0.00.
            <small>Audit package is ready.</small>
          </div>
        )}
      </section>

      <section className="section">
        <div className="section-head">
          <h2>Live run feed</h2>
          <span className="count">server-sent events · phases</span>
        </div>
        {feed.length > 0 && (
          <div className="phases">
            {ALL_PHASES.map((p) => (
              <span
                key={p}
                className={`phase-chip${seenPhases.has(p) ? " done" : ""}${
                  feed.length > 0 && feed[feed.length - 1].phase === p ? " current" : ""
                }`}
              >
                {p}
              </span>
            ))}
          </div>
        )}
        {busy && feed.length === 0 && <div className="skeleton">Running close pipeline…</div>}
        {!busy && feed.length === 0 && (
          <div className="empty">No run yet — pick a period and press Close to stream the pipeline.</div>
        )}
        {feed.length > 0 && (
          <div className="feed">
            {feed.map((e, i) => (
              <div key={i} className={`feed-item ${e.phase}`}>
                <span className="ph">{e.phase}</span>
                <span className="msg">
                  {e.message}
                  {e.exception_id && (
                    <>
                      {" — "}
                      <Link href={`/exceptions/${e.exception_id}`}>{e.exception_id}</Link>
                    </>
                  )}
                </span>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="section">
        <div className="section-head">
          <h2>Proof obligations</h2>
          <span className="count">
            {proofs.length > 0
              ? `${proofs.filter((p) => p.passed).length}/${proofs.length} passing`
              : "P1–P6"}
          </span>
        </div>
        {proofs.length === 0 && !busy && (
          <div className="empty">Proof results appear here after a run.</div>
        )}
        <div className="proof-grid">
          {proofs.map((p) => (
            <div key={p.obligation} className={`proof-card ${p.passed ? "pass" : "fail"}`}>
              <div className="proof-top">
                <span className="proof-id">{p.obligation}</span>
                <span className="proof-name">{PROOF_NAMES[p.obligation] ?? ""}</span>
                <span className={`badge ${p.passed ? "pass" : "fail"}`}>
                  {p.passed ? "PASS" : "FAIL"}
                </span>
              </div>
              <div className="proof-nums">
                <div>expected<strong>{p.expected}</strong></div>
                <div>actual<strong>{p.actual}</strong></div>
                <div>delta<strong>{p.delta}</strong></div>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="section">
        <div className="section-head">
          <h2>Exception queue</h2>
          <span className="count">
            {exceptions.length > 0 ? `${exceptions.length} open` : "detected by 7 handlers"}
          </span>
        </div>
        {exceptions.length === 0 && !busy && (
          <div className="empty">No exceptions — a blocked close will list them here for triage.</div>
        )}
        {exceptions.length > 0 && (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Type</th>
                  <th>Severity</th>
                  <th>Status</th>
                  <th>Amount</th>
                  <th>Detected by</th>
                </tr>
              </thead>
              <tbody>
                {exceptions.map((e) => (
                  <tr key={e.id}>
                    <td className="mono">
                      <Link href={`/exceptions/${e.id}`}>{e.id}</Link>
                    </td>
                    <td>{e.type}</td>
                    <td>
                      <span className={`pill ${e.severity}`}>{e.severity}</span>
                    </td>
                    <td>
                      <span className={`pill ${e.status}`}>{e.status}</span>
                    </td>
                    <td className="mono">
                      {e.amount} {e.currency}
                    </td>
                    <td className="mono">{e.detected_by}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <footer className="footer">
        TieOut · deterministic spine (ingest → prove → route) · LLMs classify &amp; explain, the engine
        computes · money serialized as string, never float.
      </footer>
    </main>
  );
}
