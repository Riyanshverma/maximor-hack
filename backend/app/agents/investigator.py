"""Investigator agent: deterministic hypothesis/evidence orchestration.

LLM call-out point is isolated in `llm_hypothesize` (default: deterministic
fallback). Amounts always come from handler tools, never the model.
"""
from typing import Any


def llm_hypothesize(exc_type: str, evidence: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Optional LLM hook. Returns None -> caller uses handler hypotheses.

    Reads OPENAI_API_KEY; on any failure returns None (deterministic path).
    """
    import os

    if not os.getenv("OPENAI_API_KEY"):
        return None
    try:
        import json
        import urllib.request

        prompt = (
            f"Exception type {exc_type}. Evidence: {json.dumps(evidence)[:2000]}. "
            "Return JSON list of hypotheses with keys title, status, reason."
        )
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=json.dumps(
                {"model": "gpt-5-nano", "messages": [{"role": "user", "content": prompt}], "temperature": 0}
            ).encode(),
            headers={
                "Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode())
        text = body["choices"][0]["message"]["content"]
        parsed = json.loads(text[text.index("[") : text.rindex("]") + 1])
        return parsed if isinstance(parsed, list) else None
    except Exception:
        return None


def investigate(handler: Any, draft: Any, ctx: Any) -> dict[str, Any]:
    """Run gather -> hypothesize (-> optional LLM structure) -> propose."""
    evidence = handler.gather(draft, ctx)
    hypotheses = handler.hypothesize(draft, evidence)
    llm_hyps = llm_hypothesize(getattr(handler, "type", "?"), evidence)
    if llm_hyps:
        hypotheses = llm_hyps
    hypothesis = hypotheses[0] if hypotheses else {}
    remedy = handler.propose(draft, hypothesis)
    return {"evidence": evidence, "hypotheses": hypotheses, "remedy": remedy}
