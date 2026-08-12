"""
planning/algorithms.py — owns THREE locatable concerns for this repo's
"Planning algorithms, all three" grading row:

  1. [PS WRAPPER]     run_plan_and_solve()   -> wraps planning_lab.algorithms.plan_and_solve
  2. [TOT WRAPPER]     run_tree_of_thoughts() -> wraps planning_lab.algorithms.tree_of_thoughts
  3. [LATS WRAPPER]    run_lats()             -> wraps planning_lab.algorithms.lats

router.py in this same folder decides which of these (or a direct MCP tool
call) a given investigation sub-task is sent to. This file does NOT
reimplement search loops — every loop (beam search, MCTS select/expand/
backpropagate) still lives in the forked `planning_lab` package, per the
lab's "don't rebuild the toolkit" requirement.

OWNERSHIP NOTE: run_lats() takes `environment` as a parameter and never
constructs one. The environment is deliberately someone else's file:
grounding (a real GroundedInvestigationEnvironment backed by db_access.py)
is owned by the Self-Correction + Grounding + Integration concern, not by
this one. This module only depends on the toolkit's small evaluate()
protocol — any object with `.evaluate(state: str) -> EnvironmentFeedback`
works, including the toolkit's own randomized default for local testing
before the grounded one exists.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from langchain_core.language_models.chat_models import BaseChatModel

from planning_lab.algorithms import plan_and_solve as _toolkit_plan_and_solve
from planning_lab.algorithms import tree_of_thoughts as _toolkit_tree_of_thoughts
from planning_lab.algorithms import lats as _toolkit_lats
from planning_lab.algorithms.lats import LATSResult
from planning_lab.models import EnvironmentFeedback, Thought


class EvaluationEnvironment(Protocol):
    """The only contract run_lats() relies on. Whoever owns grounding
    (planning/environment.py, teammate 3) implements this; this file never
    imports that module, so either side can land independently."""

    def evaluate(self, state: str) -> EnvironmentFeedback: ...


# ---------------------------------------------------------------------------
# [PS WRAPPER]
# Fits: analyze_structuring, analyze_wires
# Shape: one customer, one account, a bounded transaction list already
# fetched — a single clear plan-then-execute pass is enough. No branching
# hypotheses, no external score to search against, so ToT/LATS would just
# add cost for nothing here (see comparison table in the README).
# ---------------------------------------------------------------------------
def run_plan_and_solve(sub_task_instruction: str, evidence_context: str, llm: BaseChatModel) -> str:
    question = (
        f"{sub_task_instruction}\n\n"
        f"Evidence available for this sub-task (from the real database):\n{evidence_context}"
    )
    return _toolkit_plan_and_solve(question, llm)


# ---------------------------------------------------------------------------
# [TOT WRAPPER]
# Fits: combine_evidence
# Shape: several plausible competing explanations for the same evidence
# (sanctions-driven, structuring, self-dealing, or genuinely benign) that
# need to be generated, scored, and pruned before committing to one —
# exactly the generate/evaluate/beam-search shape ToT is for. PS can't
# compare alternatives; it only executes one line of reasoning.
# ---------------------------------------------------------------------------
def run_tree_of_thoughts(
    sub_task_instruction: str,
    evidence_context: str,
    llm: BaseChatModel,
    depth: int = 2,
    beam_width: int = 2,
) -> list[Thought]:
    problem = (
        f"{sub_task_instruction}\n\n"
        f"Combined evidence from earlier investigation sub-tasks:\n{evidence_context}\n\n"
        "Consider distinct competing explanations (sanctions exposure, structuring, "
        "self-dealing, or genuinely benign activity) before committing to the strongest one."
    )
    return _toolkit_tree_of_thoughts(problem, llm, depth=depth, beam_width=beam_width)


# ---------------------------------------------------------------------------
# [LATS WRAPPER]
# Fits: risk_assessment (final policy-grounded recommendation)
# Shape: the one sub-task where a wrong output is genuinely expensive — an
# investigator acting on a hallucinated "clear" verdict, or missing a real
# sanctions/structuring hit. LATS is the only one of the three whose
# candidates are scored by something outside the model's own opinion, which
# is exactly what this step needs. See environment.py for the grounding.
# ---------------------------------------------------------------------------
def run_lats(
    sub_task_instruction: str,
    evidence_context: str,
    llm: BaseChatModel,
    environment: EvaluationEnvironment,
    iterations: int = 2,
    n_actions: int = 2,
) -> LATSResult:
    task = (
        f"{sub_task_instruction}\n\n"
        f"Combined evidence from earlier investigation sub-tasks:\n{evidence_context}\n\n"
        "Produce a complete, policy-grounded recommendation stating which risk "
        "factors apply (sanctions / structuring / self-dealing) and why, or that "
        "the customer is clear. Do not hedge — state a definite position."
    )
    return _toolkit_lats(task, llm, environment, iterations=iterations, n_actions=n_actions)


@dataclass
class RouteDecision:
    task_id: str
    method: str  # "direct" | "ps" | "tot" | "lats"
    reason: str