"""
Grounded environment for Sterling & Vance Bank.

ADAPTATION FROM THE REFERENCE TOOLKIT:
The original toolkit Environment used a randomized evaluator that
ignored the candidate contents. This implementation keeps the same
EnvironmentFeedback-based evaluation role, but replaces the fake
randomized evaluation with real external evidence from the
Sterling & Vance MCP server.

SOURCE OF TRUTH:
1. Real MCP server responses.
2. MCP banking tools and their underlying database.
3. Optional result from the actual investigation workflow.

The LLM's self-critique is NOT the source of truth.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from planning_lab.models import EnvironmentFeedback


class Environment:
    """
    Grounded evaluator for banking investigation sub-tasks.

    ADAPTED FROM THE TOOLKIT:
    The class keeps the toolkit's Environment abstraction because the
    planning algorithms expect an environment responsible for evaluating
    candidate outputs.

    CHANGED:
    The toolkit's Environment stored a random number generator and a
    success threshold. Those were removed because a random score is not
    meaningful for a real banking investigation.

    Instead, this Environment receives an MCP session so evaluation can
    be performed against the real banking system.
    """

    def __init__(
        self,
        mcp_session: Any,
        validator_tool: str = "validate_investigation",
    ) -> None:
        # ADAPTATION:
        # Replaces the toolkit's random.Random dependency with an MCP
        # session because evaluation must use real external evidence.
        self.mcp_session = mcp_session

        # ADAPTATION:
        # The validator tool is configurable while defaulting to the
        # Sterling & Vance grounded validation tool.
        self.validator_tool = validator_tool

    async def evaluate(
        self,
        candidate: str,
        task: str | None = None,
        execute_task: Callable[[str], Awaitable[Any]] | None = None,
    ) -> EnvironmentFeedback:
        """
        Evaluate a candidate using real external evidence.

        ADAPTED FROM THE TOOLKIT:
        This method preserves the toolkit's core contract:
            candidate/state -> EnvironmentFeedback

        CHANGED:
        The original evaluator ignored the candidate and generated a
        random score. This implementation evaluates the candidate
        against real execution results and/or the MCP validation tool.

        ASYNC ADAPTATION:
        The method is async because MCP tool calls and optional task
        execution are asynchronous operations.
        """

        # ADAPTATION:
        # The toolkit did not need candidate validation because it
        # intentionally ignored the state. A grounded environment must
        # reject an empty candidate before querying external systems.
        if not isinstance(candidate, str) or not candidate.strip():
            return EnvironmentFeedback(
                success=False,
                score=0.0,
                details=["Candidate is empty."],
            )

        candidate = candidate.strip()
        details: list[str] = []
        checks: list[bool] = []

        # ADAPTATION:
        # Optional real execution check.
        #
        # This did not exist in the randomized toolkit environment.
        # It allows the planning system to validate whether the proposed
        # sub-task actually succeeds when executed against the real system.
        if execute_task is not None:
            try:
                execution_result = await execute_task(candidate)

                execution_success = self._execution_succeeded(
                    execution_result
                )

                checks.append(execution_success)

                details.append(
                    "Grounded execution check passed."
                    if execution_success
                    else "Grounded execution check failed."
                )

            except Exception as exc:
                checks.append(False)

                details.append(
                    f"Grounded execution check failed with error: {exc}"
                )

        # ADAPTATION:
        # This replaces the toolkit's randomized score generation.
        #
        # Instead of:
        #     rng.betavariate(...)
        #
        # the candidate is sent to the real Sterling & Vance MCP
        # validation tool, which checks the candidate against the actual
        # banking database.
        try:
            mcp_result = await self._call_validator(
                candidate=candidate,
                task=task or "",
            )

            mcp_success, mcp_details = self._parse_mcp_result(
                mcp_result
            )

            checks.append(mcp_success)
            details.extend(mcp_details)

        except Exception as exc:
            checks.append(False)

            details.append(
                f"Grounded MCP validation failed with error: {exc}"
            )

        # ADAPTED FROM THE TOOLKIT:
        # The Environment still produces an EnvironmentFeedback object
        # when evaluation cannot be performed successfully.
        if not checks:
            return EnvironmentFeedback(
                success=False,
                score=0.0,
                details=[
                    "No grounded validation was performed.",
                    "The LLM cannot be used as the source of truth.",
                ],
            )

        # ADAPTATION:
        # The toolkit's score came from a random Beta distribution.
        #
        # Here the score represents the proportion of real grounded
        # checks that passed.
        score = sum(checks) / len(checks)
        success = all(checks)

        details.append(
            "All grounded validation checks passed."
            if success
            else "At least one grounded validation check failed."
        )

        return EnvironmentFeedback(
            success=success,
            score=round(score, 4),
            details=details,
        )

    async def _call_validator(
        self,
        candidate: str,
        task: str,
    ) -> Any:
        """
        Call the real MCP validation tool.

        NEW / ADDED FOR GROUNDING:
        The reference toolkit had no MCP server and therefore had no
        external validator call. This method is the bridge between the
        planning algorithms and the real Sterling & Vance environment.
        """

        return await self.mcp_session.call_tool(
            self.validator_tool,
            arguments={
                "task": task,
                "candidate": candidate,
            },
        )

    @staticmethod
    def _parse_mcp_result(
        result: Any,
    ) -> tuple[bool, list[str]]:
        """
        Parse the structured result returned by the MCP server.

        NEW / ADDED FOR GROUNDING:
        The reference toolkit returned EnvironmentFeedback directly.
        Our evaluation crosses an MCP boundary, so the MCP response
        must first be converted into the EnvironmentFeedback information
        expected by the planning algorithms.
        """

        details: list[str] = []

        # ADAPTATION:
        # Support the MCP SDK's structuredContent representation.
        structured = getattr(
            result,
            "structuredContent",
            None,
        )

        # ADAPTATION:
        # Also support clients/SDK versions exposing the same field using
        # snake_case.
        if structured is None:
            structured = getattr(
                result,
                "structured_content",
                None,
            )

        if isinstance(structured, dict):
            success = structured.get("success") is True
            raw_details = structured.get("details", [])

            if isinstance(raw_details, list):
                details.extend(str(item) for item in raw_details)
            elif raw_details:
                details.append(str(raw_details))

            details.insert(
                0,
                "Grounded source of truth: real MCP server structured response.",
            )

            return success, details

        # ADAPTATION:
        # Treat an MCP tool error as a failed grounded evaluation instead
        # of allowing an invalid result to be interpreted as success.
        if getattr(result, "isError", False):
            return False, [
                "Grounded source of truth: real MCP server.",
                "The MCP validation tool returned an error.",
            ]

        return False, [
            "Grounded MCP validation failed: "
            "the validator did not return a structured success result."
        ]

    @staticmethod
    def _execution_succeeded(result: Any) -> bool:
        """
        Determine whether an optional real execution explicitly succeeded.

        NEW / ADDED FOR GROUNDING:
        The toolkit had no external task execution layer, so this helper
        is part of the banking-specific grounded adaptation.
        """

        if result is True:
            return True

        if isinstance(result, dict):
            return result.get("success") is True

        return getattr(result, "success", False) is True