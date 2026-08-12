"""
Tests for the Planning-algorithms concern (PS / ToT / LATS + routing) —
scope: teammate 2 (Planning Algorithms: PS + ToT + LATS + basic routing).

No real Groq calls here on purpose — same philosophy as the forked
toolkit's own tests/test_lab.py: fake/recording LLMs that return
structured, deterministic content so the tests are fast, free, and
reproducible. Real end-to-end runs against Groq live in planning_eval/.

Scope note: grounding (planning/environment.py, GroundedInvestigationEnvironment)
belongs to teammate 3 (Self-Correction + Grounding + Integration). Wherever
these tests need "an environment" for LATS, they use a minimal in-file fake
that only satisfies algorithms.EvaluationEnvironment's protocol
(.evaluate(state) -> EnvironmentFeedback) — proving the interface contract
without depending on, or duplicating, teammate 3's file.
"""
from types import SimpleNamespace

import pytest

from planning.router import route_subtask, dispatch
from planning.algorithms import run_plan_and_solve, run_tree_of_thoughts, run_lats
from planning_lab.models import EnvironmentFeedback
from planning_lab.algorithms.tree_of_thoughts import ThoughtCandidates, ThoughtEvaluation
from planning_lab.algorithms.lats import LATSActionBatch, ValueEstimate


# ---------------------------------------------------------------------------
# [ROUTING]
# ---------------------------------------------------------------------------
def test_router_sends_lookups_direct_and_reasoning_to_the_right_algorithm():
    assert route_subtask("find_accounts").method == "direct"
    assert route_subtask("get_transactions").method == "direct"
    assert route_subtask("check_sanctions").method == "direct"
    assert route_subtask("analyze_wires").method == "ps"
    assert route_subtask("analyze_structuring").method == "ps"
    assert route_subtask("combine_evidence").method == "tot"
    assert route_subtask("risk_assessment").method == "lats"


def test_router_covers_dynamically_injected_counterparty_tasks():
    # Task ids like this only exist at runtime, injected by
    # apply_dynamic_decomposition() in planning/decomposition.py — the
    # router must match them by prefix, not by an exact, pre-known id.
    decision = route_subtask("investigate_counterparty_ACC_UNKNOWN_99")
    assert decision.method == "ps"


def test_router_rejects_unknown_task_ids_instead_of_guessing():
    with pytest.raises(ValueError, match="No route defined"):
        route_subtask("some_new_subtask_nobody_registered")


def test_dispatch_requires_an_environment_for_lats_and_says_why():
    # Integration hasn't wired teammate 3's grounded environment in this
    # test — dispatch() must fail loudly and explain where it comes from,
    # rather than silently falling back to something ungrounded.
    with pytest.raises(ValueError, match="planning/environment.py"):
        dispatch(
            "risk_assessment",
            "Produce the final recommendation",
            "evidence...",
            llm=None,
            environment=None,
        )


# ---------------------------------------------------------------------------
# [PS] analyze_structuring / analyze_wires
# ---------------------------------------------------------------------------
class RecordingLLM:
    """Mirrors planning_lab's own test style: returns a fixed string,
    records what it was asked so the test can assert real context was used."""

    def __init__(self, content: str):
        self.content = content
        self.prompts: list[str] = []

    def invoke(self, messages, **kwargs):
        self.prompts.append(messages[-1][1])
        return SimpleNamespace(content=self.content)


def test_plan_and_solve_runs_on_real_transaction_evidence():
    llm = RecordingLLM("PLAN: inspect near-threshold deposits.\nSOLUTION: 4 deposits of 4,600-4,900 in 10 days match structuring.")
    evidence = "Type: deposit, Amount: 4800, Source: cash, Time: 2026-07-01\nType: deposit, Amount: 4750, Source: cash, Time: 2026-07-03"
    result = run_plan_and_solve("Analyze deposit structuring patterns for account 501", evidence, llm)
    assert "structuring" in result.lower()
    # The real evidence context, not a placeholder, must have reached the model.
    assert "4800" in llm.prompts[0]


def test_dispatch_routes_ps_task_through_plan_and_solve():
    llm = RecordingLLM("PLAN: review wires.\nSOLUTION: single low-value domestic wire, no red flags.")
    result = dispatch(
        "analyze_wires",
        "Analyze wire transfers for account 501",
        "1 wire, $200, domestic",
        llm,
    )
    assert "no red flags" in result.lower()


# ---------------------------------------------------------------------------
# [ToT] combine_evidence — competing explanations
# ---------------------------------------------------------------------------
class ToTLLM:
    """Structured-output fake matching planning_lab's own LATSLLM test
    pattern: with_structured_output(schema) returns a schema-shaped object.
    Unlike a stub that always returns the same score, this one actually
    reads the candidate text being evaluated so the search can tell branches
    apart — otherwise a tie would just preserve generation order and prove
    nothing about the search picking the evidence-backed branch."""

    class Structured:
        def __init__(self, owner, schema):
            self.owner, self.schema = owner, schema

        def invoke(self, messages, **kwargs):
            return self.owner.structured(self.schema, messages[-1][1])

    def with_structured_output(self, schema, *, method):
        assert method == "json_schema"
        return self.Structured(self, schema)

    def structured(self, schema, prompt_text: str):
        if schema is ThoughtCandidates:
            return schema(candidates=["Benign high-volume merchant activity", "Structuring to evade CTR reporting"])
        if schema is ThoughtEvaluation:
            # The problem statement itself mentions "structuring" as one of
            # several candidate explanations to consider, so scanning the
            # whole prompt would score every branch the same. Only the
            # "Candidate path:" line is the actual thing being judged.
            candidate_line = prompt_text.lower().rsplit("candidate path:", 1)[-1]
            if "structuring" in candidate_line:
                return schema(score=0.85, rationale="Repeated near-$5,000 deposits match known structuring pattern.")
            return schema(score=0.35, rationale="No independent evidence supports a benign explanation here.")
        return schema(score=0.5)


def test_tree_of_thoughts_prefers_the_evidence_backed_explanation():
    evidence = "3 deposits of 4,700-4,900 in 6 days; no sanctioned destination; employee unrelated to customer."
    thoughts = run_tree_of_thoughts(
        "Determine the most likely explanation for this customer's activity",
        evidence,
        ToTLLM(),
        depth=1,
        beam_width=2,
    )
    assert thoughts, "ToT should keep at least one surviving branch"
    assert thoughts[0].score >= 0.85
    assert "structuring" in thoughts[0].state.lower()


def test_dispatch_routes_combine_evidence_through_tree_of_thoughts():
    result = dispatch(
        "combine_evidence",
        "Determine the most likely explanation for this customer's activity",
        "3 deposits of 4,700-4,900 in 6 days",
        ToTLLM(),
    )
    assert isinstance(result, list) and result
    assert "structuring" in result[0].state.lower()


# ---------------------------------------------------------------------------
# [LATS] risk_assessment
# Only proves: (a) LATS wiring works, (b) it accepts ANY object satisfying
# EvaluationEnvironment — the exact contract teammate 3's grounded
# environment must implement. It does NOT test grounding correctness;
# that belongs with planning/environment.py's own tests.
# ---------------------------------------------------------------------------
class MinimalFakeEnvironment:
    """The smallest possible object satisfying algorithms.EvaluationEnvironment.
    Stands in for teammate 3's GroundedInvestigationEnvironment until
    integration wires the real one — deliberately dumb (fixed feedback),
    so this test can't be mistaken for a grounding test."""

    def __init__(self, feedback: list[EnvironmentFeedback]):
        self._feedback = iter(feedback)

    def evaluate(self, state: str) -> EnvironmentFeedback:
        return next(self._feedback)


class LATSLLM:
    class Structured:
        def __init__(self, owner, schema):
            self.owner, self.schema = owner, schema

        def invoke(self, messages, **kwargs):
            return self.owner.structured(self.schema)

    def with_structured_output(self, schema, *, method):
        return self.Structured(self, schema)

    def structured(self, schema):
        if schema is LATSActionBatch:
            return schema(actions=[
                {"action": "weak", "state": "Recommendation: insufficient detail."},
                {"action": "strong", "state": "Recommendation: customer 7700's wire is a sanctions hit; escalate."},
            ])
        return schema(score=0.7)

    def invoke(self, messages, **kwargs):
        return SimpleNamespace(content="First branch lacked a definite position; the next branch must commit to one.")


def test_lats_wiring_accepts_any_object_matching_the_environment_protocol():
    environment = MinimalFakeEnvironment([
        EnvironmentFeedback(success=False, score=0.3, details=["stub: insufficient detail"]),
        EnvironmentFeedback(success=True, score=0.95, details=["stub: accepted"]),
    ])
    result = run_lats(
        "Produce the final risk_assessment recommendation",
        "Wire destined for a sanctioned country; no other flags investigated yet.",
        LATSLLM(),
        environment,
        iterations=1,
        n_actions=2,
    )
    assert result.success is True
    assert "sanctions" in result.output.lower()


def test_dispatch_routes_risk_assessment_through_lats_when_environment_is_given():
    environment = MinimalFakeEnvironment([
        EnvironmentFeedback(success=True, score=0.9, details=["stub: accepted"]),
    ])
    result = dispatch(
        "risk_assessment",
        "Produce the final risk_assessment recommendation",
        "evidence...",
        LATSLLM(),
        environment=environment,
    )
    assert result.success is True