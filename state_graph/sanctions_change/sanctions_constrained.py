import json
from typing import Any, Literal, Annotated

from langchain_mistralai import ChatMistralAI
import sys
from pathlib import Path

SITE_PACKAGES = Path(sys.prefix) / "Lib" / "site-packages"

if str(SITE_PACKAGES) in sys.path:
    sys.path.remove(str(SITE_PACKAGES))

sys.path.insert(0, str(SITE_PACKAGES))

from langchain_mcp_adapters.client import MultiServerMCPClient

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    TypeAdapter,
)

from config import MISTRAL_API_KEY


# ============================================================
# Configuration
# ============================================================

MAX_STEPS = 6
MISTRAL_MODEL = "mistral-large-latest"


# ============================================================
# MCP Client
# The Constrained ReAct agent uses the REAL MCP server.
# It does not duplicate banking logic locally.
# The MCP server is responsible for exposing the actual banking tools.
# ============================================================

client = MultiServerMCPClient(
    {
        "sterling_vance": {
            "command": "python",
            "args": ["mcp_server/server.py"],
            "transport": "stdio",
        }
    }
)


# ============================================================
# Mistral
# ============================================================

llm = ChatMistralAI(
    model=MISTRAL_MODEL,
    mistral_api_key=MISTRAL_API_KEY,
    temperature=0,
)


# ============================================================
# Constrained ReAct Schemas
# The LLM can produce ONLY one of three actions:
#   tool_call
#   final_answer
#   escalate
# Each action has its own strict schema.
# ============================================================


class ToolCallStep(BaseModel):

    model_config = ConfigDict(extra="forbid")

    action: Literal["tool_call"]

    tool: str = Field(min_length=1)

    input: dict[str, Any]

    reasoning: str = Field(min_length=1)


class FinalAnswerStep(BaseModel):

    model_config = ConfigDict(extra="forbid")

    action: Literal["final_answer"]

    tool: None

    input: dict[str, Any]

    reasoning: str = Field(min_length=1)


class EscalateStep(BaseModel):

    model_config = ConfigDict(extra="forbid")

    action: Literal["escalate"]

    tool: None

    input: dict[str, Any]

    reasoning: str = Field(min_length=1)


AgentStep = Annotated[
    ToolCallStep | FinalAnswerStep | EscalateStep,
    Field(discriminator="action"),
]

AgentStepAdapter = TypeAdapter(AgentStep)


# ============================================================
# System Prompt
# ============================================================

SYSTEM_PROMPT = f"""
You are a constrained ReAct compliance investigation agent
for Sterling & Vance Bank.

Your job is to investigate a banking investigation using
the tools exposed by the MCP server.

You MUST reason step-by-step, but you MUST NOT expose
long chain-of-thought reasoning.

Return ONLY one valid JSON object.

DO NOT wrap the JSON in Markdown.
DO NOT use ```json.
DO NOT return any text before or after the JSON.

The JSON MUST contain exactly these fields:

{{
    "action": "...",
    "tool": "...",
    "input": {{}},
    "reasoning": "short explanation"
}}

------------------------------------------------------------
ALLOWED ACTIONS
------------------------------------------------------------

1. tool_call

Use this when information must be retrieved from the
MCP server.

Requirements:

- action MUST be "tool_call"
- tool MUST contain an actual MCP tool name
- input MUST contain the arguments required by that tool
- reasoning MUST briefly explain why the tool is needed

------------------------------------------------------------

2. final_answer

Use this when enough evidence has been collected.

Requirements:

- action MUST be "final_answer"
- tool MUST be null
- input MUST be {{}}
- reasoning MUST contain the investigation conclusion

------------------------------------------------------------

3. escalate

Use this when the investigation cannot safely reach
a conclusion with the available evidence.

Requirements:

- action MUST be "escalate"
- tool MUST be null
- input MUST be {{}}
- reasoning MUST explain why escalation is necessary

------------------------------------------------------------
AVAILABLE MCP TOOLS
------------------------------------------------------------

The actual tools are provided dynamically by the MCP server.

You may ONLY call tools that appear in the actual MCP
tool list supplied to you.

DO NOT invent tool names.

------------------------------------------------------------
INVESTIGATION RULES
------------------------------------------------------------

1. Start from the investigation information provided
   in the current state.

2. Use MCP tools to collect real evidence.

3. Never invent:

   - customers
   - accounts
   - transactions
   - wire transfers
   - balances
   - sanctions status

4. Tool results are evidence.

5. Do not repeat the exact same tool call with the same
   input when the previous result already provides useful
   evidence.

6. Prefer the minimum number of tool calls required.

7. If evidence is insufficient or conflicting, escalate.

8. When enough evidence exists, return final_answer.

9. Never make a conclusion based on information that was
   not present in the investigation state or MCP results.

8. NEVER call wire_transfer_initiate during investigation.

wire_transfer_initiate is a write/execution tool.
It is NOT a read-only investigation tool.

Do not use it to retrieve wire information.
Do not use it with wire_id.
Do not invent arguments such as simulate=true.

Wire information must come from the current graph state
or from read-only MCP tools.

------------------------------------------------------------
CONSTRAINT
------------------------------------------------------------

Maximum number of reasoning/tool steps:

{MAX_STEPS}

Never exceed this limit.

Never return text outside the JSON object.
"""


# ============================================================
# Helpers
# ============================================================


def get_tool_names(tools):
    """Return names of tools exposed by the real MCP server."""
    return [tool.name for tool in tools]


def serialize_tool_result(result):
    """
    Convert MCP output into text that can safely be stored
    inside the graph state/history.
    """

    if isinstance(result, str):
        return result

    if isinstance(result, list):

        parts = []

        for item in result:

            if hasattr(item, "text"):
                parts.append(item.text)

            else:
                parts.append(str(item))

        return "\n".join(parts)

    return str(result)


def clean_json_response(raw_response: str) -> str:
    """
    Remove Markdown code fences if the model returns them.
    Strict Pydantic validation still happens afterwards.
    """

    text = raw_response.strip()

    if text.startswith("```"):

        lines = text.splitlines()

        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]

        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]

        text = "\n".join(lines).strip()

    return text


# ============================================================
# Safe Escalation
# ============================================================


def safe_escalation(
    reason: str,
    history: list,
    steps: int,
):
    """
    Convert unsafe situations into an explicit escalation
    instead of allowing exceptions to propagate.
    """

    return {
        "investigation_status": "escalated",
        "investigation_answer": (
            "Investigation escalated because the agent "
            "could not safely continue."
        ),
        "investigation_reason": reason,
        "investigation_steps": steps,
        "investigation_history": history,
    }


# ============================================================
# Tool Argument Validation
# ============================================================


def validate_tool_arguments(tool, tool_input):
    if not isinstance(tool_input, dict):
        return (
            False,
            "Tool input must be a JSON object.",
        )

    args_schema = getattr(tool, "args_schema", None)

    if args_schema is None:
        return (
            False,
            f"MCP tool '{tool.name}' does not expose an argument schema.",
        )

    try:
        # -----------------------------------------------------
        # Case 1: Pydantic model
        # -----------------------------------------------------
        if hasattr(args_schema, "model_validate"):
            args_schema.model_validate(tool_input)
            return True, ""

        # -----------------------------------------------------
        # Case 2: Pydantic TypeAdapter
        # -----------------------------------------------------
        if hasattr(args_schema, "validate_python"):
            args_schema.validate_python(tool_input)
            return True, ""

        # -----------------------------------------------------
        # Case 3: JSON Schema dictionary
        # -----------------------------------------------------
        if isinstance(args_schema, dict):
            from jsonschema import Draft202012Validator

            validator = Draft202012Validator(args_schema)

            errors = sorted(
                validator.iter_errors(tool_input),
                key=lambda error: list(error.path),
            )

            if errors:
                messages = []

                for error in errors:
                    path = ".".join(
                        str(part)
                        for part in error.path
                    )

                    if path:
                        messages.append(
                            f"{path}: {error.message}"
                        )
                    else:
                        messages.append(
                            error.message
                        )

                return (
                    False,
                    (
                        f"Invalid arguments for MCP tool "
                        f"'{tool.name}': "
                        + "; ".join(messages)
                    ),
                )

            return True, ""

        return (
            False,
            (
                f"Unsupported argument schema type for "
                f"MCP tool '{tool.name}': "
                f"{type(args_schema).__name__}"
            ),
        )

    except ValidationError as e:
        return (
            False,
            (
                f"Invalid arguments for MCP tool "
                f"'{tool.name}': {e}"
            ),
        )

    except Exception as e:
        return (
            False,
            (
                f"Tool argument validation failed: "
                f"{type(e).__name__}: {e}"
            ),
        )

# ============================================================
# Constrained ReAct NODE
# ============================================================
# This function is designed to be called directly by a State Graph node.
# It receives the graph state and returns only the fields
# that should be updated in the graph state.
# It does NOT create its own workflow.
# It does NOT create its own long-term memory.
# It does NOT contain asyncio.run().
# ============================================================


async def constrained_react_node(state: dict):

    print("\n" + "=" * 70)
    print("CONSTRAINED REACT NODE")
    print("=" * 70)

    # ========================================================
    # 1. Get investigation information from Graph State
    # ========================================================

    question = state.get("question", "")

    if not question:

        return {
            "investigation_status": "escalated",
            "investigation_answer": (
                "Investigation cannot start because "
                "no investigation question was provided."
            ),
            "investigation_reason": "Missing question in graph state.",
            "investigation_steps": 0,
            "investigation_history": [],
        }

    # ========================================================
    # 2. Existing graph history
    # ========================================================
    # If the graph already contains investigation history,reuse it.
    # This is short-term workflow state.
    # We do NOT introduce another memory system.
    # ========================================================

    history = list(
        state.get(
            "investigation_history",
            [],
        )
    )

    # ========================================================
    # 3. Load REAL MCP tools
    # ========================================================

    try:
        tools = await client.get_tools()

    except Exception as e:

        print("\nMCP TOOL DISCOVERY FAILED:")
        print(e)

        return safe_escalation(
            reason=(
                f"MCP tool discovery failed: "
                f"{type(e).__name__}: {e}"
            ),
            history=history,
            steps=0,
        )

    tool_map = {tool.name: tool for tool in tools}
    tool_names = get_tool_names(tools)

    print("\nMCP TOOLS:")

    for name in tool_names:
        print(f"  - {name}")

    # ========================================================
    # 4. Constrained ReAct loop
    # ========================================================

    for step_number in range(MAX_STEPS):

        current_step = step_number + 1

        print("\n" + "-" * 70)
        print(
            f"CONSTRAINED REACT STEP "
            f"{current_step}/{MAX_STEPS}"
        )
        print("-" * 70)

        # ----------------------------------------------------
        # History for LLM
        # ----------------------------------------------------

        history_text = json.dumps(
            history,
            indent=2,
            default=str,
        )

        # ----------------------------------------------------
        # Current State Context
        # ----------------------------------------------------

        state_context = {
            key: value
            for key, value in state.items()
            if key not in {
                "investigation_history",
            }
        }

        state_text = json.dumps(
            state_context,
            indent=2,
            default=str,
        )

        # ----------------------------------------------------
        # User message
        # ----------------------------------------------------

        user_message = f"""
Current investigation state:

{state_text}

Investigation request:

{question}

Previous investigation steps and MCP results:

{history_text}

Available MCP tools:

{json.dumps(tool_names, indent=2)}

Choose the next action.

Return ONLY one valid JSON object.
Do not use Markdown code fences.
"""

        # ====================================================
        # 5. Ask Mistral LLM
        # ====================================================

        try:
            response = await llm.ainvoke(
                [
                    ("system", SYSTEM_PROMPT),
                    ("user", user_message),
                ]
            )

            raw_response = response.content

        except Exception as e:

            print("\nLLM EXECUTION FAILED:")
            print(e)

            history.append(
                {
                    "step": current_step,
                    "type": "llm_error",
                    "error": (
                        f"Mistral execution failed: "
                        f"{type(e).__name__}: {e}"
                    ),
                }
            )

            return safe_escalation(
                reason=(
                    "The reasoning model failed to produce "
                    "a valid response."
                ),
                history=history,
                steps=current_step,
            )

        print("\nMISTRAL RESPONSE:")
        print(raw_response)

        # ====================================================
        # 6. Clean + STRICTLY validate action
        # ====================================================

        cleaned_response = clean_json_response(raw_response)
        try:
            step = AgentStepAdapter.validate_json(
                cleaned_response
            )

        except ValidationError as e:
            print("\nINVALID AGENT RESPONSE:")
            print(e)

            history.append(
                {
                    "step": current_step,
                    "type": "validation_error",
                    "error": (
                        "Invalid constrained action schema."
                    ),
                    "details": str(e),
                    "raw_response": raw_response,
                }
            )

            return safe_escalation(
                reason=(
                    "Mistral returned malformed JSON or "
                    "violated the constrained action schema."
                ),
                history=history,
                steps=current_step,
            )

        except Exception as e:

            print("\nAGENT RESPONSE PARSING FAILED:")
            print(e)

            history.append(
                {
                    "step": current_step,
                    "type": "validation_error",
                    "error": (
                        f"{type(e).__name__}: {e}"
                    ),
                }
            )

            return safe_escalation(
                reason=(
                    "The agent response could not be "
                    "safely validated."
                ),
                history=history,
                steps=current_step,
            )

        # ====================================================
        # 7. Validated action
        # ====================================================

        print("\nVALIDATED ACTION:")
        print("ACTION:", step.action)
        print("TOOL:", step.tool)
        print("INPUT:", step.input)
        print("REASONING:", step.reasoning)

        # ====================================================
        # 8. FINAL ANSWER
        # ====================================================

        if isinstance(step, FinalAnswerStep):

            print("\n" + "=" * 70)
            print("CONSTRAINED REACT COMPLETED")
            print("=" * 70)

            print(step.reasoning)

            history.append(
                {
                    "step": current_step,
                    "type": "final_answer",
                    "reasoning": step.reasoning,
                }
            )

            return {
                "investigation_status": "completed",
                "investigation_answer": step.reasoning,
                "investigation_steps": current_step,
                "investigation_history": history,
            }

        # ====================================================
        # 9. ESCALATION
        # ====================================================

        if isinstance(step, EscalateStep):

            print("\n" + "=" * 70)
            print("CONSTRAINED REACT ESCALATED")
            print("=" * 70)

            print(step.reasoning)

            history.append(
                {
                    "step": current_step,
                    "type": "escalation",
                    "reasoning": step.reasoning,
                }
            )

            return {
                "investigation_status": "escalated",
                "investigation_answer": step.reasoning,
                "investigation_steps": current_step,
                "investigation_history": history,
            }

        # ====================================================
        # 10. TOOL CALL
        # ====================================================

        if isinstance(step, ToolCallStep):

            # ------------------------------------------------
            # Tool allow-list
            # ------------------------------------------------

            if step.tool not in tool_map:

                error_message = (
                    f"Tool '{step.tool}' does not exist "
                    "in the MCP server tool list."
                )

                print("\nINVALID TOOL:")
                print(error_message)

                history.append(
                    {
                        "step": current_step,
                        "type": "validation_error",
                        "tool": step.tool,
                        "input": step.input,
                        "error": error_message,
                    }
                )

                return safe_escalation(
                    reason=(
                        "The agent attempted to call a "
                        "tool that is not exposed by "
                        "the MCP server."
                    ),
                    history=history,
                    steps=current_step,
                )

            # ------------------------------------------------
            # Get REAL MCP tool
            # ------------------------------------------------

            tool = tool_map[step.tool]

            # ------------------------------------------------
            # Validate arguments BEFORE execution
            # ------------------------------------------------

            valid_args, validation_error = (
                validate_tool_arguments(
                    tool,
                    step.input,
                )
            )

            if not valid_args:

                print("\nINVALID TOOL ARGUMENTS:")
                print(validation_error)

                history.append(
                    {
                        "step": current_step,
                        "type": "validation_error",
                        "tool": step.tool,
                        "input": step.input,
                        "error": validation_error,
                    }
                )

                return safe_escalation(
                    reason=(
                        "The agent produced arguments "
                        "that do not match the selected "
                        "MCP tool schema."
                    ),
                    history=history,
                    steps=current_step,
                )

            # ------------------------------------------------
            # Execute REAL MCP tool
            # ------------------------------------------------

            print("\nCALLING MCP TOOL...")
            print("Tool:", step.tool)
            print("Input:", step.input)

            try:

                result = await tool.ainvoke(
                    step.input
                )

                result_text = serialize_tool_result(
                    result
                )

            except Exception as e:

                result_text = (
                    f"MCP tool execution failed: "
                    f"{type(e).__name__}: {e}"
                )

                print("\nMCP TOOL ERROR:")
                print(result_text)

                history.append(
                    {
                        "step": current_step,
                        "type": "tool_error",
                        "tool": step.tool,
                        "input": step.input,
                        "error": result_text,
                    }
                )

                return safe_escalation(
                    reason=(
                        "The selected MCP tool failed "
                        "during execution. No unsupported "
                        "conclusion will be produced."
                    ),
                    history=history,
                    steps=current_step,
                )

            # ------------------------------------------------
            # Save MCP observation
            # ------------------------------------------------

            print("\nMCP RESULT:")
            print(result_text)

            history.append(
                {
                    "step": current_step,
                    "type": "tool_call",
                    "tool": step.tool,
                    "input": step.input,
                    "reasoning": step.reasoning,
                    "result": result_text,
                }
            )

    # ========================================================
    # 11. MAX STEPS
    # ========================================================

    escalation_message = (
        "Investigation escalated because the maximum "
        "number of reasoning steps was reached without "
        "a safe final decision."
    )

    print("\n" + "=" * 70)
    print("MAXIMUM STEPS REACHED")
    print("=" * 70)

    print(escalation_message)

    history.append(
        {
            "step": MAX_STEPS,
            "type": "max_steps",
            "error": escalation_message,
        }
    )

    return {
        "investigation_status": "escalated",
        "investigation_answer": escalation_message,
        "investigation_steps": MAX_STEPS,
        "investigation_history": history,
    }