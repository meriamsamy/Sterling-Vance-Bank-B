from __future__ import annotations

from typing import Any, Awaitable, Callable

from langchain_core.language_models.chat_models import BaseChatModel

from planning_lab.algorithms.self_refine import (
    deterministic_checks,
    ReflectionResult,
)
# import the grounded Environment class from the local environment.py file because we want to use the real banking Environment instead of the toolkit's randomized Environment.
from .environment import Environment


async def reflect_and_refine(
    goal: str,
    draft: str,
    llm: BaseChatModel,
    environment: Environment,
    execute_task: Callable[[str], Awaitable[Any]] | None = None,
) -> ReflectionResult:

    # ------------------------------------------------------------
    # ADAPTED FROM THE TOOLKIT:
    # Keep the same Self-Refine input/output structure:
    # one draft -> critique -> one revision.
    #
    # CHANGE FROM TOOLKIT:
    # The toolkit only used deterministic_checks() as its external
    # feedback. Our banking adaptation additionally calls the real
    # Sterling & Vance grounded Environment, which validates the
    # candidate against the MCP server and real database.
    # ------------------------------------------------------------

    if not isinstance(draft, str) or not draft.strip():
        raise ValueError("draft must be a non-empty string")

    draft = draft.strip()

    # ------------------------------------------------------------
    # ADAPTED FROM THE TOOLKIT:
    # Reuse the toolkit's deterministic checks instead of
    # rebuilding the same helper in the banking implementation.
    #
    # These checks are NOT the final source of truth. They are
    # lightweight local checks that complement the real environment.
    # ------------------------------------------------------------

    deterministic_issues = deterministic_checks(goal, draft)

    deterministic_report = (
        "\n".join(
            f"- {issue}"
            for issue in deterministic_issues
        )
        or "- Deterministic checks passed."
    )

    # ------------------------------------------------------------
    # BANKING ADAPTATION:
    # Ground the original draft using the real external environment.
    #
    # SOURCE OF TRUTH:
    # Sterling & Vance MCP server -> banking tools/database.
    #
    # The LLM is explicitly NOT treated as the source of truth.
    # ------------------------------------------------------------

    initial_feedback = await environment.evaluate(
        candidate=draft,
        task=goal,
        execute_task=execute_task,
    )

    grounded_report = (
        "\n".join(
            f"- {detail}"
            for detail in initial_feedback.details
        )
        or "- Grounded environment validation passed."
    )

    # ------------------------------------------------------------
    # ADAPTED FROM THE TOOLKIT:
    # Keep an independent LLM critique step.
    #
    # CHANGE FROM TOOLKIT:
    # The critic now receives both:
    #   1. deterministic toolkit checks
    #   2. real grounded MCP/database feedback
    #
    # The critic is NOT the source of truth; it interprets the
    # independently obtained feedback.
    # ------------------------------------------------------------

    critique_response = llm.invoke(
        [
            (
                "system",
                (
                    "You are an independent critic for a banking "
                    "investigation Self-Refine step. "
                    "Judge the draft against the rubric. "
                    "Do not rewrite the draft."
                ),
            ),
            (
                "human",
                f"""Goal:
{goal}

Rubric:
correctness, completeness, internal consistency,
instruction adherence, and no unsupported banking claims.

SOURCE OF TRUTH:
The external Sterling & Vance banking Environment is the
source of truth for factual banking claims.

Grounded MCP/database feedback:
{grounded_report}

Deterministic toolkit checks:
{deterministic_report}

Draft:
{draft}

List concrete issues that should be fixed.
If there are no issues, respond exactly PASS.""",
            ),
        ]
    )

    critique = critique_response.content

    if not isinstance(critique, str) or not critique.strip():
        raise RuntimeError(
            "The chat model returned an empty or unsupported response"
        )

    critique = critique.strip()

    # ------------------------------------------------------------
    # ADAPTED FROM THE TOOLKIT:
    # Self-Refine performs exactly ONE revision.
    #
    # CHANGE FROM TOOLKIT:
    # Revision is based on both the independent critique and the
    # real grounded environment feedback.
    # ------------------------------------------------------------

    if (
        critique.upper() == "PASS"
        and initial_feedback.success
        and not deterministic_issues
    ):
        # No revision is necessary because both the grounded
        # environment and deterministic checks passed.
        revised = draft

    else:
        revision_response = llm.invoke(
            [
                (
                    "system",
                    (
                        "Revise the banking investigation deliverable "
                        "using the grounded external feedback, "
                        "deterministic checks, and independent critique. "
                        "Return only the improved deliverable."
                    ),
                ),
                (
                    "human",
                    f"""Goal:
{goal}

Original draft:
{draft}

Grounded MCP/database feedback:
{grounded_report}

Deterministic toolkit checks:
{deterministic_report}

Independent critique:
{critique}

SOURCE OF TRUTH:
The real Sterling & Vance banking Environment is authoritative
for factual banking information. Do not invent facts to satisfy
the critique.

Return only the improved deliverable.""",
                ),
            ]
        )

        revised = revision_response.content

        if not isinstance(revised, str) or not revised.strip():
            raise RuntimeError(
                "The chat model returned an empty or unsupported response"
            )

        revised = revised.strip()

    # ------------------------------------------------------------
    # BANKING ADAPTATION:
    # Validate the final revised output against the real environment.
    #
    # This is important because the LLM's revision itself is NOT
    # considered proof of correctness.
    #
    # SOURCE OF TRUTH:
    # Real MCP server / real banking database.
    # ------------------------------------------------------------

    final_feedback = await environment.evaluate(
        candidate=revised,
        task=goal,
        execute_task=execute_task,
    )

    # ------------------------------------------------------------
    # ADAPTED OUTPUT:
    # Reuse the toolkit's ReflectionResult structure imported above.
    # We do not redefine the dataclass because it already belongs
    # to the reused toolkit package.
    # ------------------------------------------------------------

    return ReflectionResult(
        draft=draft,
        critique=critique,
        revised=revised,
        grounded_issues=(
            deterministic_issues
            + initial_feedback.details
            + final_feedback.details
        ),
    )