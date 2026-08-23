"""
REASSESS_INVESTIGATION node.

Covers: Issue "Implement Investigation Graph with LATS + RAG" (the LATS half)
        Issue "Implement HITL Escalation for Investigation"

Why LATS here: once ANALYZE_EVIDENCE has decided the evidence is
sufficient (a concrete flag is grounded in the bank's own data), there
isn't one obvious conclusion — a structuring flag could mean genuine
small-business cash handling, could mean money laundering, or could mean
the flag itself is a false positive. That's a search over competing
interpretations of the same evidence, which is what LATS is for (as
opposed to RAG's job one step earlier: looking up which policy applies).

This is a lightweight two-level LATS, not the full toolkit implementation:
    depth 0 (breadth): generate several competing candidate conclusions
                        from the same evidence, each with a rationale and
                        a self-reported confidence.
    depth 1 (expand):  take the single most-promising candidate and give
                        the model one more pass to either strengthen or
                        walk back its own reasoning before it's treated
                        as final.
The full candidate tree (both depths) is stored in state["lats_candidates"]
so a grader can see the search, not just the answer.

IMPORTANT — the LLM is not the final source of truth. Whatever candidate
LATS lands on is passed to validate_investigation(), the same grounded
DB-backed validator server.py exposes as an MCP tool (see the import note
below), before risk_level/confidence are finalized.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
MCP_DIR = ROOT_DIR / "mcp_server"

# MCP_DIR goes on sys.path FIRST (matches the existing convention already
# used inside mcp/server.py itself, which bare-imports db_access/schemas/
# policy_document — this graph lives in the same repo, so it reuses that
# same convention rather than reinventing packaging).
if str(MCP_DIR) not in sys.path:
    sys.path.insert(0, str(MCP_DIR))

# ROOT_DIR is appended, not inserted, and only needed for `rag.*` imports
# elsewhere in this package. It's deliberately NOT put ahead of normal
# site-packages resolution: mcp/server.py itself does `import mcp.types`,
# meaning the real pip-installed `mcp` SDK package must still resolve
# correctly even after this file runs. As long as this repo's mcp/ folder
# has no __init__.py (it doesn't need one — server.py is run as a script,
# `cd mcp && python server.py`, never imported as `mcp.server_module`),
# Python's import system defers to the real installed package for any
# `import mcp...` statement. If that ever changes, switch this file's
# reuse of validate_investigation to a real MCP client/subprocess call
# instead of a direct import.
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

import mcp_server.db_access as db  # noqa: E402
from mcp_server.server import validate_investigation  # noqa: E402 - reused, not reimplemented

from langchain_mistralai import ChatMistralAI  
from config import MISTRAL_API_KEY

from state_graph.suspicious_activity.investigation_nodes import (  # noqa: E402
    update_transition,
    utc_now,
)
from state_graph.suspicious_activity.investigation_state import InvestigationState  # noqa: E402

WORKFLOW_TYPE = "suspicious_activity"

CANDIDATE_LABELS = (
    "legitimate_activity",
    "potential_fraud",
    "potential_money_laundering",
    "insufficient_evidence",
)

RISK_BY_LABEL = {
    "legitimate_activity": "low",
    "insufficient_evidence": "medium",
    "potential_fraud": "high",
    "potential_money_laundering": "high",
}

llm = ChatMistralAI(
    api_key=MISTRAL_API_KEY,
    model="mistral-small-latest",
    temperature=0.2,
)


def _evidence_summary(state: InvestigationState) -> str:
    evidence = state.get("evidence") or {}
    wires = evidence.get("wires") or []
    accounts = evidence.get("accounts") or []
    related = evidence.get("related_employees") or []

    lines = [
        f"customer_id: {state.get('customer_id')}",
        f"investigation reason: {state.get('reason')}",
        f"flags: {', '.join(state.get('evidence_flags') or []) or 'none'}",
        f"accounts: {[a.get('account_id') for a in accounts]}",
        f"wire transfers ({len(wires)}): "
        + "; ".join(
            f"transfer #{w.get('transfer_id')} ${w.get('amount')} -> "
            f"{w.get('destination_country')} status={w.get('status')}"
            for w in wires[:10]
        ),
        f"related employees: {[e.get('employee_id') for e in related]}",
        f"policy analysis (from ANALYZE_EVIDENCE): {state.get('analysis')}",
    ]
    return "\n".join(lines)


def _parse_json_candidates(raw: str) -> list[dict[str, Any]]:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw.split("\n", 1)[-1] if "\n" in raw else raw
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return []
    if isinstance(data, dict):
        data = data.get("candidates", [])
    out = []
    for item in data if isinstance(data, list) else []:
        label = item.get("label")
        if label not in CANDIDATE_LABELS:
            continue
        out.append({
            "label": label,
            "rationale": str(item.get("rationale", ""))[:600],
            "confidence": max(0.0, min(1.0, float(item.get("confidence", 0.5)))),
        })
    return out


def _generate_candidates(summary: str) -> list[dict[str, Any]]:
    prompt = f"""You are a fraud/AML investigator reviewing evidence for a bank customer.

Evidence:
{summary}

Generate 3-4 competing candidate conclusions for this investigation.
Each candidate must be one of: {', '.join(CANDIDATE_LABELS)}.

Return ONLY a JSON array, no prose, like:
[{{"label": "potential_fraud", "rationale": "...", "confidence": 0.6}}, ...]
"""
    response = llm.invoke(prompt)
    candidates = _parse_json_candidates(response.content)
    if not candidates:
        # Model didn't return usable JSON — fall back to a single
        # conservative candidate rather than crashing the node.
        candidates = [{
            "label": "insufficient_evidence",
            "rationale": "Model did not return a parseable candidate set.",
            "confidence": 0.3,
        }]
    return candidates


def _expand_candidate(summary: str, candidate: dict[str, Any]) -> dict[str, Any]:
    prompt = f"""You previously proposed this conclusion for a bank fraud investigation:

Label: {candidate['label']}
Rationale: {candidate['rationale']}
Confidence: {candidate['confidence']}

Evidence:
{summary}

Critique your own reasoning. Either strengthen it with a more specific
rationale, or revise the label/confidence if the evidence doesn't
actually support it as strongly as first thought.

Return ONLY JSON: {{"label": "...", "rationale": "...", "confidence": 0.0}}
"""
    response = llm.invoke(prompt)
    refined = _parse_json_candidates("[" + response.content.strip().strip("[]") + "]")
    if refined:
        return refined[0]
    return candidate


async def reassess_investigation(state: InvestigationState) -> InvestigationState:
    summary = _evidence_summary(state)

    # ---- LATS depth 0: breadth ----
    candidates = _generate_candidates(summary)
    for c in candidates:
        c["depth"] = 0

    best_initial = max(candidates, key=lambda c: c["confidence"])

    # ---- LATS depth 1: expand the most promising branch ----
    refined = _expand_candidate(summary, best_initial)
    refined["depth"] = 1
    refined["parent_label"] = best_initial["label"]

    all_candidates = candidates + [refined]
    best = refined if refined["confidence"] >= best_initial["confidence"] else best_initial

    candidate_text = (
        f"Investigation conclusion for customer #{state.get('customer_id')}: "
        f"{best['label']}. {best['rationale']} "
        f"Evidence considered: flags={state.get('evidence_flags')}, "
        f"wires={[w.get('transfer_id') for w in (state.get('evidence') or {}).get('wires', [])]}."
    )

    # ---- Grounded validation — the LLM is NOT the source of truth ----
    validation = await validate_investigation(
        task=f"Assess investigation for customer #{state.get('customer_id')}: {state.get('reason')}",
        candidate=candidate_text,
    )
    validated_ok = bool(validation.get("success"))

    risk_level = RISK_BY_LABEL[best["label"]]
    confidence = float(best["confidence"]) * (1.0 if validated_ok else 0.6)

    # ============================================================
    # [HITL DECISION — Issue 5]
    # Fires here, in the same node that computes risk/confidence, so
    # the real database task is created before the graph ever reaches
    # the waiting_for_admin interrupt() in investigation_graph.py.
    # Without creating the row here, the pause would still work
    # (interrupt() persists correctly either way) but there'd be
    # nothing for the admin platform's HITL queue to list or click into.
    # ============================================================
    hitl_required = requires_hitl(risk_level, confidence, validated_ok)
    hitl_task_id = state.get("hitl_task_id")
    hitl_reason = state.get("hitl_reason")

    if hitl_required:
        hitl_reason = (
            f"risk_level={risk_level}, confidence={confidence:.2f}, "
            f"validation_success={validated_ok}. Escalation threshold: "
            f"risk=high OR confidence<0.80 OR grounded validation failed."
        )
        if hitl_task_id is None:  # idempotent — don't duplicate on re-entry
            hitl_task_id = db.create_human_review_task(
                workflow_type=WORKFLOW_TYPE,
                wire_id=None,
                review_id=state.get("investigation_id"),
                status="open",
                reason=hitl_reason,
                recommended_action=candidate_text,
                created_at=utc_now(),
            )

    return update_transition(
        state=state,
        node_name="reassess_investigation",
        status="waiting_for_admin" if hitl_required else "ready_to_close",
        lats_candidates=all_candidates,
        candidate_assessment=candidate_text,
        validation_result=validation,
        analysis=candidate_text,
        risk_level=risk_level,
        confidence=confidence,
        assessed_label=best["label"],
        hitl_required=hitl_required,
        hitl_task_id=hitl_task_id,
        hitl_reason=hitl_reason,
    )


# ============================================================
# [HITL DECISION RULE]
# A single, locatable, testable threshold — both the node above and
# investigation_graph.py's routing edge call this exact function, so
# there's one definition of "requires a human," not two that can drift.
# ============================================================

def requires_hitl(risk_level: str, confidence: float, validated_ok: bool) -> bool:
    return risk_level == "high" or confidence < 0.80 or not validated_ok