"""
ANALYZE_EVIDENCE node.

Covers: Issue "Implement Investigation Graph with LATS + RAG" (the RAG half).

Reuses rag/hybrid_rag.py exactly as-is (vector + BM25 retrieval over the
compliance policy Chroma store, then Self-RAG verification) — this graph
does not stand up a second retriever or a second policy document.

Why RAG belongs here and not in REASSESS_INVESTIGATION:
    The question this node answers — "given what our own flags mean
    according to policy, is DB-only evidence enough to reason about a
    conclusion, or is this investigation going nowhere without something
    external?" — is a policy-lookup question with one right answer
    grounded in a fixed document. That's exactly what RAG is for. LATS
    is reserved for the different, harder question later: given
    sufficient evidence, which of several plausible interpretations of
    that evidence is correct? That's a search-over-conclusions problem,
    not a lookup problem — see investigation_lats.py.

Sufficiency rule, grounded in what evidence actually is available:
    collect_initial_evidence() only pulls from the bank's OWN database.
    Documents, tips, and explanations from outside the bank can't come
    from that node — by construction. So "evidence insufficient" here
    means specifically: nothing in the bank's own transaction/wire data
    corroborates the reason the investigation was opened (evidence_flags
    is empty). If a concrete flag *is* present (sanctions/structuring/
    self_dealing), that is real grounded evidence, sufficient to move on
    to REASSESS_INVESTIGATION — RAG is still used to retrieve which
    policy section applies and what role must review it, which becomes
    part of the analysis and later informs the HITL escalation reason.
"""
from __future__ import annotations

from rag.hybrid_rag import hybrid_rag  # noqa: E402

from state_graph.suspicious_activity.investigation_nodes import update_transition  # noqa: E402
from state_graph.suspicious_activity.investigation_state import InvestigationState  # noqa: E402

# Which policy question to ask per DB-detectable flag. Phrased close to
# the section headings in sterling_vance_financial_crime_policy.md so
# metadata_filter.extract_metadata_filter() has a real shot at pinning
# down the right section instead of falling back to unfiltered search.
POLICY_QUESTION_BY_FLAG = {
    "sanctions": "What must happen when a wire transfer's destination country is on the sanctions list?",
    "structuring": "What review is required when a structuring pattern is detected in an account's deposits?",
    "self_dealing": "What review is required when an employee has a conflict of interest with a customer?",
}

NO_FLAGS_QUESTION = (
    "What should happen when suspicious transaction activity is reported "
    "but the transaction indicators don't clearly match a specific policy "
    "violation like sanctions, structuring, or conflict of interest?"
)


def analyze_evidence(state: InvestigationState) -> InvestigationState:
    flags = state.get("evidence_flags") or []

    if not flags:
        # Nothing in the bank's own data corroborates the reason this
        # investigation was opened. That's a genuine "we have nothing
        # concrete to reason over yet" case — RAG still grounds *why*
        # we're waiting (policy says suspicious reports without a clear
        # DB match still require documented follow-up), but the missing
        # piece itself has to come from outside the bank.
        result = hybrid_rag(NO_FLAGS_QUESTION)
        analysis = (
            "No sanctions, structuring, or self-dealing signal was found "
            "in this customer's own transaction/wire history. Grounded "
            f"policy guidance: {result['answer']}"
        )
        return update_transition(
            state=state,
            node_name="analyze_evidence",
            status="waiting_for_evidence",
            analysis=analysis,
            rag_context=result.get("context", ""),
            missing_evidence=["corroborating_report_or_external_evidence"],
        )

    # At least one concrete, DB-grounded flag exists. Retrieve the
    # applicable policy section per flag so the eventual HITL/closure
    # reasoning is explicitly grounded in policy text, not just the raw
    # flag name.
    analysis_parts: list[str] = []
    context_parts: list[str] = []

    for flag in flags:
        question = POLICY_QUESTION_BY_FLAG.get(flag)
        if question is None:
            continue
        result = hybrid_rag(question)
        analysis_parts.append(f"[{flag}] {result['answer']}")
        if result.get("context"):
            context_parts.append(result["context"])

    analysis = (
        f"Grounded evidence found: {', '.join(flags)}. "
        + " ".join(analysis_parts)
    )

    return update_transition(
        state=state,
        node_name="analyze_evidence",
        status="reassessing",
        analysis=analysis,
        rag_context="\n\n".join(context_parts),
        missing_evidence=[],
    )