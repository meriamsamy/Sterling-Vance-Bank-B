from __future__ import annotations

from typing import Any, Awaitable, Callable

from langchain_core.language_models.chat_models import BaseChatModel

# ADAPTED IMPORT:
# ReflexionTrial and ReflexionResult are reused from the shared toolkit planning_lab
# package instead of redefining the toolkit data models locally.
# EnvironmentFeedback is also reused from the shared package.
from planning_lab.models import EnvironmentFeedback
from planning_lab.algorithms.reflexion import ReflexionTrial, ReflexionResult

# ADAPTED:
# The toolkit's Environment is replaced by our grounded banking Environment.
# It validates candidates against the real MCP server / database instead of
# the toolkit's randomized evaluator.
#import my local Environment class instead of the toolkit's Environment because we want to use the grounded banking Environment.
from .environment import Environment

# ADAPTED:
# The original Reflexion algorithm is synchronous because the toolkit
# environment was synchronous. Our grounded Environment performs MCP
# communication asynchronously, so the Reflexion loop must also be async.
async def reflexion(
    task: str,
    llm: BaseChatModel,
    environment: Environment,
    max_trials: int = 3,
    memory_size: int = 3,

    # ADAPTED:
    # Optional execution hook for running the actual investigation workflow.
    # This allows the grounded Environment to validate real execution results
    # in addition to calling the MCP validation tool.
    execute_task: Callable[[str], Awaitable[Any]] | None = None,
) -> ReflexionResult:

    # UNCHANGED FROM TOOLKIT:
    # Keep the original parameter validation from the Reflexion algorithm.
    if max_trials < 1 or memory_size < 1:
        raise ValueError(
            "max_trials and memory_size must be positive"
        )

    # UNCHANGED FROM TOOLKIT:
    # Reflexion maintains an episodic memory of reflections from failed trials.
    memory: list[str] = []
    trials: list[ReflexionTrial] = []

    # UNCHANGED FROM TOOLKIT:
    # Keep track of the best attempt in case all trials fail.
    best_attempt = ""
    best_score = -1.0

    # UNCHANGED FROM TOOLKIT:
    # Reflexion retries the entire task across multiple trials.
    for number in range(1, max_trials + 1):

        # UNCHANGED FROM TOOLKIT:
        # Recall only the most recent reflections according to memory_size.
        recalled = (
            "\n".join(
                f"- {item}"
                for item in memory[-memory_size:]
            )
            or "- No prior trials."
        )

        # UNCHANGED FROM TOOLKIT:
        # The LLM generates a complete attempt using the previous
        # episodic reflections as context.
        response = llm.invoke(
            [
                (
                    "system",
                    "You are the acting agent in a Reflexion "
                    "loop for a banking investigation system. "
                    "Attempt the entire task again.",
                ),
                (
                    "human",
                    f"""Task:
{task}

Episodic memory from previous failed trials:
{recalled}

Produce the complete deliverable.
Apply remembered lessons without discussing them.""",
                ),
            ]
        )

        # UNCHANGED FROM TOOLKIT:
        # Extract and validate the LLM-generated attempt.
        attempt = response.content

        if not isinstance(attempt, str) or not attempt.strip():
            raise RuntimeError(
                "The chat model returned an empty or unsupported response"
            )

        attempt = attempt.strip()

        # MAJOR ADAPTATION:
        # The toolkit called its randomized Environment here.
        # We instead call the grounded banking Environment, which checks
        # the candidate against real external evidence.
        #
        # Source of truth:
        #   1. Real MCP server validation.
        #   2. Real banking database/state.
        #   3. Optional actual investigation execution.
        #
        # The LLM does NOT decide whether the attempt succeeded.
        feedback: EnvironmentFeedback = await environment.evaluate(
            candidate=attempt,
            task=task,
            execute_task=execute_task,
        )

        # UNCHANGED FROM TOOLKIT:
        # Store the attempt and its EnvironmentFeedback as one trial.
        trial = ReflexionTrial(
            number=number,
            attempt=attempt,
            feedback=feedback,
        )

        # UNCHANGED FROM TOOLKIT:
        # Keep the highest-scoring attempt as a fallback.
        if feedback.score > best_score:
            best_attempt = attempt
            best_score = feedback.score

        # ADAPTED BEHAVIOR:
        # The success decision now comes from the grounded Environment.
        # This replaces relying on the toolkit's randomized evaluator.
        if feedback.success:
            trials.append(trial)

            return ReflexionResult(
                success=True,
                output=attempt,
                trials=trials,
                memory=memory[-memory_size:],
            )

        # UNCHANGED FROM TOOLKIT:
        # Convert Environment feedback into text that can be used
        # by the reflection step.
        feedback_details = (
            "\n".join(
                f"- {item}"
                for item in feedback.details
            )
            or "- No additional details were provided."
        )

        # UNCHANGED IN ALGORITHM:
        # After a failed attempt, Reflexion asks the LLM to produce
        # a concise verbal reflection rather than rewriting the answer.
        response = llm.invoke(
            [
                (
                    "system",
                    "Generate a concise first-person Reflexion "
                    "memory, not a revised answer.",
                ),
                (
                    "human",
                    f"""Task:
{task}

Failed attempt:
{attempt}

External environment feedback:
{feedback_details}

Source of truth:
The external banking Environment is the source of truth.
Do not assume the failed attempt was correct just because
the language model produced it.

State what I did wrong and the specific strategy I should
use in the next trial.

Start with "I".""",
                ),
            ]
        )

        # UNCHANGED FROM TOOLKIT:
        # Extract and validate the generated reflection.
        reflection = response.content

        if not isinstance(reflection, str) or not reflection.strip():
            raise RuntimeError(
                "The chat model returned an empty or unsupported response"
            )

        reflection = reflection.strip()

        # UNCHANGED FROM TOOLKIT:
        # Attach the reflection to the current failed trial.
        trial.reflection = reflection
        trials.append(trial)

        # UNCHANGED FROM TOOLKIT:
        # Carry the verbal reflection into the next trial.
        # The memory is capped when it is recalled and returned.
        memory.append(reflection)

    # UNCHANGED FROM TOOLKIT:
    # If every trial fails, return the best attempt found.
    return ReflexionResult(
        success=False,
        output=best_attempt,
        trials=trials,
        memory=memory[-memory_size:],
    )