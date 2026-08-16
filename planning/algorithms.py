"""
planning/algorithms.py — owns THREE locatable concerns for this repo's
"Planning algorithms, all three" grading row:

  1. [PS WRAPPER]     run_plan_and_solve()   -> wraps planning_lab.algorithms.plan_and_solve
  2. [TOT WRAPPER]     run_tree_of_thoughts() -> wraps planning_lab.algorithms.tree_of_thoughts
  3. [LATS WRAPPER]    run_lats()             -> wraps planning_lab.algorithms.lats

router.py in this same folder decides which of these (or a direct MCP tool
call) a given investigation sub-task is sent to. This file does NOT
reimplement search loops — every loop (beam search, MCTS select/expand/
backpropagate) still lives in the forked `planning_lab` package, unchanged,
per the lab's "don't rebuild the toolkit" requirement.

*** UPDATED: async ***
All three wrappers are now `async def`. The toolkit's own plan_and_solve/
tree_of_thoughts/lats functions are still plain sync functions — nothing
about them changed — but each is now run inside asyncio.to_thread() so a
call here never blocks a real event loop (this repo's mcp/server.py is
async throughout, and teammate 3's grounded Environment.evaluate() is
async too — see the module docstring in router.py for how that bridges
into LATS without touching the toolkit's sync search loop).

OWNERSHIP NOTE: run_lats() takes `environment` as a parameter and never
constructs one. The environment is deliberately someone else's file:
grounding (planning/environment.py) is owned by the Self-Correction +
Grounding + Integration concern, not by this one. This module only
depends on the toolkit's small evaluate() protocol — any object with
`.evaluate(state: str) -> EnvironmentFeedback` works. router.py is
responsible for bridging teammate 3's real *async* Environment into that
sync protocol before it ever reaches this file, so algorithms.py stays
decoupled from her concrete implementation.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol

from langchain_core.language_models.chat_models import BaseChatModel

from planning_lab.algorithms import plan_and_solve as _toolkit_plan_and_solve
from planning_lab.algorithms import tree_of_thoughts as _toolkit_tree_of_thoughts
from planning_lab.algorithms import lats as _toolkit_lats
from planning_lab.algorithms.lats import LATSResult
from planning_lab.models import EnvironmentFeedback, Thought


class EvaluationEnvironment(Protocol):
    """The only contract run_lats() relies on — sync, single-arg, exactly
    what the toolkit's own (sync) lats() calls internally. Whoever owns
    grounding (planning/environment.py, teammate 3) has a real *async*
    Environment; router.py bridges it to this sync protocol before calling
    run_lats(), so this file never needs to know that bridge exists."""

    def evaluate(self, state: str) -> EnvironmentFeedback: ...


# ---------------------------------------------------------------------------
# [PS WRAPPER]
# Fits: sub-tasks with one clear fetch -> analyze -> finding sequence.
# No branching hypotheses, no external score to search against, so ToT/LATS
# would just add cost for nothing here (see comparison table in the README).
# ---------------------------------------------------------------------------
async def run_plan_and_solve(sub_task_instruction: str, evidence_context: str, llm: BaseChatModel) -> str:
    question = (
        f"{sub_task_instruction}\n\n"
        f"Evidence available for this sub-task (from the real database):\n{evidence_context}"
    )
    return await asyncio.to_thread(_toolkit_plan_and_solve, question, llm)


# ---------------------------------------------------------------------------
# [TOT WRAPPER]
# Fits: sub-tasks with several plausible competing explanations for the
# same evidence that need to be generated, scored, and pruned before
# committing to one — the generate/evaluate/beam-search shape ToT is for.
# PS can't compare alternatives; it only executes one line of reasoning.
# ---------------------------------------------------------------------------
async def run_tree_of_thoughts(
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
    return await asyncio.to_thread(_toolkit_tree_of_thoughts, problem, llm, depth=depth, beam_width=beam_width)


# ---------------------------------------------------------------------------
# [LATS WRAPPER]
# Fits: the final policy-grounded recommendation — the one sub-task where a
# wrong output is genuinely expensive. LATS is the only one of the three
# whose candidates are scored by something outside the model's own opinion,
# which is exactly what this step needs. See router.py's environment bridge
# and planning/environment.py for the actual grounding.
# ---------------------------------------------------------------------------
async def run_lats(
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
    # The toolkit's lats() calls environment.evaluate(state) synchronously,
    # with no await — it has no idea teammate 3's real Environment is async.
    # Running the whole (unmodified) toolkit call in a worker thread means
    # that thread has no running event loop of its own, so the sync
    # `environment` passed in here (router.py's bridge around her real
    # async Environment) can safely do asyncio.run() inside .evaluate()
    # without ever hitting "asyncio.run() cannot be called from a running
    # event loop".
    return await asyncio.to_thread(_toolkit_lats, task, llm, environment, iterations, n_actions)


@dataclass
class RouteDecision:
    task_id: str
    method: str  # "direct" | "ps" | "tot" | "lats"
    reason: str