""" 
Grounded environment for Sterling & Vance Bank. 
 
ADAPTATION FROM THE REFERENCE TOOLKIT: 
The original toolkit Environment used a randomized evaluator that 
ignored the candidate contents. This implementation keeps the same 
EnvironmentFeedback-based evaluation role, but replaces the fake 
randomized evaluation with real external evidence from the 
Sterling & Vance MCP server. 
 
SOURCE OF TRUTH: 
1. Real MCP validation responses. 
2. The Sterling & Vance MCP banking tools and their underlying database. 
3. Optional execution results from the real investigation workflow, 
   used as an additional grounded check, not as the final authority. 
 
The LLM's self-critique is NOT the source of truth. 
""" 
 
from __future__ import annotations 
 
from typing import Any, Awaitable, Callable 
 
from planning_lab.models import EnvironmentFeedback 
 
 
class Environment: 
    """ 
    Grounded evaluator for banking investigation sub-tasks. 
    """ 
 
    def __init__( 
        self, 
        mcp_session: Any, 
        validator_tool: str = "validate_investigation", 
    ) -> None: 
 
        self.mcp_session = mcp_session 
        self.validator_tool = validator_tool 
 
    async def evaluate( 
        self, 
        candidate: str, 
        task: str | None = None, 
        execute_task: Callable[[str], Awaitable[Any]] | None = None, 
    ) -> EnvironmentFeedback: 
 
        # --------------------------------------------------------- 
        # Candidate validation 
        # --------------------------------------------------------- 
 
        if not isinstance(candidate, str) or not candidate.strip(): 
 
            return EnvironmentFeedback( 
                success=False, 
                score=0.0, 
                details=["Candidate is empty."], 
            ) 
 
        candidate = candidate.strip() 
        details: list[str] = [] 
 
        # --------------------------------------------------------- 
        # Optional execution check 
        # --------------------------------------------------------- 
 
        if execute_task is not None: 
 
            try: 
 
                execution_result = await execute_task(candidate) 
 
                execution_success = self._execution_succeeded( 
                    execution_result 
                ) 
 
                details.append( 
                    "Grounded execution check passed." 
                    if execution_success 
                    else "Grounded execution check failed." 
                ) 
 
                if not execution_success: 
 
                    return EnvironmentFeedback( 
                        success=False, 
                        score=0.0, 
                        details=details, 
                    ) 
 
            except Exception as exc: 
 
                return EnvironmentFeedback( 
                    success=False, 
                    score=0.0, 
                    details=[ 
                        *details, 
                        f"Grounded execution check failed with error: {exc}", 
                    ], 
                ) 
 
        else: 
            pass 
 
        # --------------------------------------------------------- 
        # MCP validation 
        # --------------------------------------------------------- 
 
        try: 
 
            mcp_result = await self._call_validator( 
                candidate=candidate, 
                task=task or "", 
            ) 
 
            mcp_success, mcp_details = self._parse_mcp_result( 
                mcp_result 
            ) 
 
            details.extend(mcp_details) 
 
        except Exception as exc: 
 
            return EnvironmentFeedback( 
                success=False, 
                score=0.0, 
                details=[ 
                    *details, 
                    f"Grounded MCP validation failed with error: {exc}", 
                ], 
            ) 
 
        # --------------------------------------------------------- 
        # Final feedback 
        # --------------------------------------------------------- 
 
        return EnvironmentFeedback( 
            success=mcp_success, 
            score=1.0 if mcp_success else 0.0, 
            details=[ 
                *details, 
                ( 
                    "Grounded source of truth: real MCP validation " 
                    "backed by the banking database." 
                ), 
                ( 
                    "All grounded validation checks passed." 
                    if mcp_success 
                    else "Grounded MCP validation failed." 
                ), 
            ], 
        ) 
 
    async def _call_validator( 
        self, 
        candidate: str, 
        task: str, 
    ) -> Any: 
 
        try: 
 
            result = await self.mcp_session.call_tool( 
                self.validator_tool, 
                arguments={ 
                    "task": task, 
                    "candidate": candidate, 
                }, 
            ) 
 
            return result 
 
        except Exception as exc: 
 
            raise 
 
    @staticmethod 
    def _parse_mcp_result( 
        result: Any, 
    ) -> tuple[bool, list[str]]: 
 
        details: list[str] = [] 
 
        structured = getattr( 
            result, 
            "structuredContent", 
            None, 
        ) 
 
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
 
        if result is True: 
            return True 
 
        if isinstance(result, dict): 
            return result.get("success") is True 
 
        return getattr(result, "success", False) is True
