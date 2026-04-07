import json
import logging
import os
from collections import Counter

import anthropic

log = logging.getLogger("trace-rca-service")
_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client

ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")

# ── Prompt Template ──────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an expert Site Reliability Engineer performing Root Cause Analysis on a microservice system.
You will receive:
1. Structural RCA ranking (from causal + Jaccard scoring on trace DAGs)
2. Service dependency graph (parent → child relationships)
3. Log evidence per service (ERROR/WARN logs from the failure window)

Your task: Analyze the evidence and determine the true root cause service.

CONSTRAINTS:
- The root cause MUST be one of the services in the structural ranking
- Classify each service as INTRINSIC (origin fault) or PROPAGATED (cascading failure)
- Only ONE service can be INTRINSIC — the rest are PROPAGATED
- Provide concrete evidence from logs for your classification
- Output valid JSON only"""

USER_PROMPT_TEMPLATE = """## Structural RCA Ranking (Stage 1)
{ranking_text}

## Service Dependencies (from trace DAGs)
{dependency_text}

## Log Evidence per Service
{log_text}

## Task
Analyze the above and return JSON:
{{
  "analysis": [
    {{"service": "<name>", "classification": "INTRINSIC|PROPAGATED", "evidence": "<brief reasoning from logs+structure>"}}
  ],
  "root_cause": {{"service": "<name>", "confidence": <0.0-1.0>}},
  "propagation_chain": ["A → B → C"]
}}"""


def _build_ranking_text(ranking: list[tuple[str, float]]) -> str:
    lines = []
    for i, (svc, score) in enumerate(ranking[:5], 1):
        lines.append(f"{i}. {svc} (score: {score:.4f})")
    return "\n".join(lines)


def _build_dependency_text(traces: list[dict]) -> str:
    """Extract unique parent→child service edges from trace DAGs."""
    edges: set[tuple[str, str]] = set()
    for trace in traces:
        if trace.get("label") != 1:
            continue
        nodes = trace["nodes"]
        for node in nodes.values():
            parent_svc = node.get("parent_service")
            if parent_svc and parent_svc != node["service"]:
                edges.add((parent_svc, node["service"]))

    if not edges:
        return "No dependency edges found."
    return "\n".join(f"- {p} → {c}" for p, c in sorted(edges))


def _build_log_text(logs: dict[str, list[dict]]) -> str:
    """Format log evidence per service for the prompt."""
    sections = []
    for svc, entries in logs.items():
        if not entries:
            sections.append(f"### {svc}\nNo ERROR/WARN logs found.")
            continue
        log_lines = []
        for entry in entries[:10]:  # Cap at 10 per service to control token usage
            level = entry.get("level", "?").upper()
            msg = entry.get("message", "")[:200]  # Truncate long messages
            log_lines.append(f"  [{level}] {msg}")
        sections.append(f"### {svc}\n" + "\n".join(log_lines))
    return "\n\n".join(sections)


def analyze(
    ranking: list[tuple[str, float]],
    traces: list[dict],
    logs: dict[str, list[dict]],
) -> dict:
    """Single LLM call to analyze root cause with log evidence.

    Returns parsed JSON dict or error fallback.
    """
    client = _get_client()

    user_prompt = USER_PROMPT_TEMPLATE.format(
        ranking_text=_build_ranking_text(ranking),
        dependency_text=_build_dependency_text(traces),
        log_text=_build_log_text(logs),
    )

    try:
        response = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )

        # Extract text content from response (skip thinking blocks from proxy)
        text = next(b.text for b in response.content if b.type == "text")
        # Parse JSON from response (handle markdown code blocks)
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]

        return json.loads(text.strip())

    except json.JSONDecodeError as e:
        log.error(f"LLM returned invalid JSON: {e}")
        return _fallback_result(ranking)
    except anthropic.APIError as e:
        log.error(f"Anthropic API error: {e}")
        return _fallback_result(ranking)
    except Exception as e:
        log.error(f"LLM analysis failed: {e}", exc_info=True)
        return _fallback_result(ranking)


def analyze_with_consistency(
    ranking: list[tuple[str, float]],
    traces: list[dict],
    logs: dict[str, list[dict]],
    n_samples: int = 3,
) -> dict:
    """Self-consistency wrapper: sample n times, majority vote on root cause.

    Returns:
        {
            "root_cause": {"service": str, "confidence": float},
            "agreement_ratio": float,
            "analysis": [...],  # from the winning sample
            "propagation_chain": [...],
            "confidence_level": "AUTO|WARNING|ESCALATE",
            "all_samples": [...]  # raw results for debugging
        }
    """
    n_samples = max(1, n_samples)
    results = []
    for i in range(n_samples):
        log.info(f"LLM sample {i+1}/{n_samples}")
        result = analyze(ranking, traces, logs)
        results.append(result)

    # Majority voting on root_cause service
    root_causes = [
        r.get("root_cause", {}).get("service", "unknown")
        for r in results
    ]
    winner, winner_count = Counter(root_causes).most_common(1)[0]
    agreement_ratio = winner_count / n_samples

    # Pick the best sample (the one matching the winner with highest confidence)
    best_sample = next(
        (r for r in results if r.get("root_cause", {}).get("service") == winner),
        results[0],
    )

    # Confidence calibration
    structural_margin = _compute_structural_margin(ranking)
    llm_confidence = best_sample.get("root_cause", {}).get("confidence", 0.5)
    final_confidence = structural_margin * llm_confidence * agreement_ratio

    # Action thresholds
    if final_confidence >= 0.7:
        confidence_level = "AUTO"
    elif final_confidence >= 0.4:
        confidence_level = "WARNING"
    else:
        confidence_level = "ESCALATE"

    return {
        "root_cause": {"service": winner, "confidence": round(final_confidence, 4)},
        "agreement_ratio": round(agreement_ratio, 2),
        "analysis": best_sample.get("analysis", []),
        "propagation_chain": best_sample.get("propagation_chain", []),
        "confidence_level": confidence_level,
        "all_samples": results,
    }


def _compute_structural_margin(ranking: list[tuple[str, float]]) -> float:
    """Margin between top-1 and top-2 structural scores.

    High margin = structural algo is confident → boost LLM weight.
    Low margin = ambiguous → LLM has more influence.
    Returns value in [0.5, 1.0].
    """
    if len(ranking) < 2:
        return 1.0
    top1_score = ranking[0][1]
    top2_score = ranking[1][1]
    if top1_score == 0:
        return 0.5
    margin = (top1_score - top2_score) / top1_score
    return max(0.5, min(1.0, 0.5 + margin * 0.5))


def _fallback_result(ranking: list[tuple[str, float]]) -> dict:
    """Fallback when LLM fails: return Stage 1 top result."""
    if not ranking:
        return {"root_cause": {"service": "unknown", "confidence": 0.0}, "analysis": [], "propagation_chain": []}
    top_svc, top_score = ranking[0]
    return {
        "analysis": [{"service": top_svc, "classification": "INTRINSIC", "evidence": "LLM unavailable; structural ranking only"}],
        "root_cause": {"service": top_svc, "confidence": round(top_score, 4)},
        "propagation_chain": [],
    }
