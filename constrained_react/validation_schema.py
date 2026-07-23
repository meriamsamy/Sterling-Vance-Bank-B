from pydantic import BaseModel, Field
from typing import Literal, Optional


class AgentStep(BaseModel):
    """
    Schema that defines the structure of every agent step.

    Every step must contain:
    - action: what the agent wants to do
    - tool: tool name if needed
    - input: tool input
    - reasoning: explanation of why this step is chosen
    """

    action: Literal[
        "tool_call",
        "final_answer",
        "escalate"
    ]

    tool: Optional[str] = None

    input: Optional[dict] = None

    reasoning: str = Field(
        description="Explanation for selecting this step"
    )


MAX_STEPS = 6