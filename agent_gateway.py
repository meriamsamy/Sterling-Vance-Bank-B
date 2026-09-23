"""Connection layer between the web UI chat and the already-built live agents.

The UI posts {agent_name, message, thread_id} to POST /invoke in mcp_server.server.
Two of the five agents (customer-risk, sanctions-change) already had a real
implementation there. The others were broken:

  * memory-rag             -> returned a hardcoded stub string
  * planning-decomposition -> returned a hardcoded stub string
  * suspicious-activity    -> not routed at all ("Unknown agent")

This module bridges those three gaps by reusing the project's OWN entry points,
unchanged:

  * memory-rag             -> client/client.py's live pipeline (build_agent,
                              convert_mcp_tool, route_and_log, the STEPS 1-13
                              memory/RAG loop)
  * planning-decomposition -> planning_agent.PlanningAgent(session).run(goal)
                              (+ the same `login` call run_session() does)
  * suspicious-activity    -> state_graph/suspicious_activity/
                              investigation_graph_runner.py's public API
                              (start_investigation / submit_external_evidence /
                              get_investigation_snapshot)

Nothing is mocked, faked or duplicated: no agent, workflow, tool, MCP
registration, database or State Graph is modified by this file.

Design notes
------------
* One streamable-HTTP MCP connection per UI thread_id, held for the process
  lifetime. Each UI thread keeps its own MCP session, its own short-term
  memory / scratchpad / planning session, and its own checkpoint threads -
  so sessions are isolated and the user can switch agents at any time.
* Gateway sessions deliberately omit the MCP elicitation/sampling callbacks.
  When the server asks for approval from a client that has no elicitation
  support, it falls back to its designed HITL behaviour (hold high-risk wires
  as pending_manual_review instead of auto-approving) - HITL stays active and
  is never short-circuited from the chat UI.
* If the transport breaks mid-request the connection is rebuilt for the NEXT
  message instead of silently re-running the finished request (re-running a
  banking operation twice would be worse than asking the user to resend).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8000/mcp")
PLANNING_EMPLOYEE_ID = int(os.getenv("PLANNING_EMPLOYEE_ID", "1"))


class GatewayError(RuntimeError):
    """A live agent could not complete the request; str() is the user-facing cause."""


# ---------------------------------------------------------------------------
# transport helpers
# ---------------------------------------------------------------------------

def _is_transport_error(exc: BaseException) -> bool:
    """True only for stream/connection failures - never for LLM or logic errors."""
    try:
        import anyio
        import httpx
    except Exception:  # pragma: no cover - both are hard deps of mcp
        anyio = httpx = None  # type: ignore

    transport_types: tuple[type[BaseException], ...] = (ConnectionError, OSError)
    if anyio is not None:
        transport_types += (anyio.BrokenResourceError, anyio.ClosedResourceError)
    if httpx is not None:
        transport_types += (httpx.ReadError, httpx.WriteError, httpx.ReadTimeout,
                            httpx.ConnectError, httpx.RemoteProtocolError)

    if isinstance(exc, transport_types):
        return True

    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            "connection reset",
            "connection aborted",
            "server disconnected",
            "peer closed",
            "broken pipe",
            "stream closed",
            "transport",
        )
    )


class _HttpMcpConnection:
    """A streamable-HTTP MCP client connection bound to one UI thread_id."""

    def __init__(self, thread_id: str):
        self.thread_id = thread_id
        self.session: ClientSession | None = None
        self.caps: Any = None
        self.tools_dirty = True  # same semantics as client.py's tools_ref
        self._cm = None
        self._get_session = None

    async def _message_handler(self, message: Any) -> None:
        # Mirrors client.py's message_handler: the only part the gateway
        # needs is the "tool list changed" push notification.
        if isinstance(message, Exception):
            return
        notification = getattr(message, "root", message)
        if getattr(notification, "method", None) == "notifications/tools/list_changed":
            self.tools_dirty = True

    async def _open(self) -> None:
        self._cm = streamablehttp_client(MCP_SERVER_URL)
        read, write, _ = await self._cm.__aenter__()
        self._get_session = ClientSession(
            read,
            write,
            message_handler=self._message_handler,
        )
        self.session = await self._get_session.__aenter__()
        init_result = await self.session.initialize()
        self.caps = init_result.capabilities
        self.tools_dirty = True

    async def aclose(self) -> None:
        for cm in (self._get_session, self._cm):
            if cm is not None:
                try:
                    await cm.__aexit__(None, None, None)
                except Exception:
                    pass
        self._get_session = self._cm = self.session = None

    async def recreate(self) -> None:
        """Rebuild the session in place after a transport failure."""
        await self.aclose()
        await self._open()


# ---------------------------------------------------------------------------
# session registry + per-thread serialization
# ---------------------------------------------------------------------------

_registry: dict[str, _HttpMcpConnection] = {}
_registry_lock = asyncio.Lock()
_thread_locks: dict[str, asyncio.Lock] = {}


def _thread_lock(thread_id: str) -> asyncio.Lock:
    lock = _thread_locks.get(thread_id)
    if lock is None:
        lock = _thread_locks[thread_id] = asyncio.Lock()
    return lock


async def get_connection(thread_id: str) -> _HttpMcpConnection:
    """Return (opening if needed) this thread's MCP connection."""
    async with _registry_lock:
        conn = _registry.get(thread_id)
        if conn is None:
            conn = _registry[thread_id] = _HttpMcpConnection(thread_id)
        if conn.session is None:
            try:
                await conn._open()
            except Exception as exc:
                _registry.pop(thread_id, None)
                await conn.aclose()
                raise GatewayError(
                    f"Cannot reach the MCP server at {MCP_SERVER_URL}: {exc}"
                ) from exc
        return conn


async def release_connection(thread_id: str) -> None:
    async with _registry_lock:
        conn = _registry.pop(thread_id, None)
    if conn is not None:
        await conn.aclose()


async def _call_on_connection(
    thread_id: str, fn: Callable[[_HttpMcpConnection], Any]
) -> Any:
    """Run fn(connection) on this thread's connection.

    Transport failures rebuild the connection (so the NEXT message works)
    but never re-execute fn - retrying a completed banking operation would
    be worse than asking the user to resend once.
    """
    conn = await get_connection(thread_id)
    try:
        return await fn(conn)
    except Exception as exc:
        if not _is_transport_error(exc):
            raise
        try:
            await conn.recreate()
        except Exception as rebuild_exc:
            await release_connection(thread_id)
            raise GatewayError(
                f"Cannot reach the MCP server at {MCP_SERVER_URL}: {rebuild_exc}"
            ) from exc
        raise GatewayError(
            f"The connection to the MCP server was interrupted mid-request "
            f"({exc}). It has been reconnected - please send the message again."
        ) from exc


# ===========================================================================
# Agent 2: Memory & RAG
#
# Reuses client/client.py's real pipeline: same LLM, same system prompt via
# build_agent(), same MCP tool conversion, same STEPS 1-13 (short-term memory
# with Promote-or-Drop routing, scratchpad, context strategy, hybrid RAG,
# long-term memory retrieval + both verification passes, answer fallback).
# The only difference: state is kept per UI thread instead of per process,
# and the interactive input()/print() loop is replaced by this call.
# ===========================================================================

class _MemoryThread:
    """Per-thread state for the Memory & RAG pipeline (mirrors client.py's locals)."""

    def __init__(self) -> None:
        from memory.short_term_memory.short_term_memory import ShortTermMemory
        from memory.short_term_memory.scratchpad import Scratchpad
        from memory.context_strategies.context_manager import ContextManager

        self.stm = ShortTermMemory(max_messages=20)
        self.scratchpad = Scratchpad()
        self.context_manager = ContextManager()
        self.llm = None          # ChatGroq, created lazily
        self.tools = None        # session-bound StructuredTools
        self.agent = None        # session-bound compiled agent
        self.policy_loaded = False

    def invalidate_session_objects(self) -> None:
        """Drop anything bound to a dead MCP session (conversation memory stays)."""
        self.tools = None
        self.agent = None


_memory_threads: dict[str, _MemoryThread] = {}


async def _ensure_policy_reference(conn: _HttpMcpConnection, state: _MemoryThread) -> None:
    """STEP (session start) of client.py: load the bank policy MCP resource into STM."""
    if state.policy_loaded:
        return
    state.policy_loaded = True  # set first so a resource failure isn't retried forever

    caps = conn.caps
    if caps is None or caps.resources is None:
        return
    resources = await conn.session.list_resources()
    if not resources.resources:
        return
    policy = await conn.session.read_resource(resources.resources[0].uri)
    policy_text = policy.contents[0].text
    if policy_text:
        route_fn = lambda candidates: _route(candidates, state.scratchpad)  # noqa: E731
        state.stm.add_message_with_routing(
            "user", f"[Bank Policy Reference]\n\n{policy_text}", route_fn=route_fn
        )
        state.stm.add_message_with_routing(
            "assistant", "Policy reference loaded.", route_fn=route_fn
        )


def _route(candidates, scratchpad):
    from client.client import route_and_log

    return route_and_log(candidates, scratchpad)


async def _ensure_memory_agent(conn: _HttpMcpConnection, state: _MemoryThread) -> None:
    """Build (or refresh) the LangChain agent for this thread's MCP session."""
    from client.client import SCHEMAS, build_agent, convert_mcp_tool
    from langchain_groq import ChatGroq
    from config import API_KEY

    if state.llm is None:
        state.llm = ChatGroq(
            groq_api_key=API_KEY, model="openai/gpt-oss-20b", temperature=0.1
        )

    if state.tools is None or conn.tools_dirty:
        mcp_tools = await conn.session.list_tools()
        # client/client.py's SCHEMAS covers the four tools its agent can call;
        # the server also exposes admin/investigation tools that have no
        # schema there, so only schema-backed tools enter this agent.
        state.tools = [
            convert_mcp_tool(conn.session, tool)
            for tool in mcp_tools.tools
            if tool.name in SCHEMAS
        ]
        state.agent = build_agent(state.llm, state.tools)
        conn.tools_dirty = False


async def _memory_turn(state: _MemoryThread, user: str, conn: _HttpMcpConnection) -> str:
    """One full STEPS 1-13 pass of client/client.py's live loop."""
    from client.client import ACTIVE_CONTEXT_STRATEGY, retrieve_long_term_memory
    from client.client import verify_long_term_memory, verify_memory_answer
    from client.client import hybrid_rag
    from langchain_core.messages import SystemMessage, ToolMessage, convert_to_messages

    # --- session setup (policy resource + agent/tools) ---
    await _ensure_policy_reference(conn, state)
    await _ensure_memory_agent(conn, state)

    route_fn = lambda candidates: _route(candidates, state.scratchpad)  # noqa: E731

    # STEP 1 - USER -> SHORT-TERM MEMORY
    state.stm.add_message_with_routing("user", user, route_fn=route_fn)

    # STEP 2 - SCRATCHPAD
    state.scratchpad.set_goal(user)
    state.scratchpad.set_current_step("Retrieving context")

    # STEP 3 - SHORT-TERM CONTEXT
    raw_context = state.context_manager.process(
        ACTIVE_CONTEXT_STRATEGY, state.stm.get_messages()
    )
    context_messages = []

    for message in raw_context:
        if isinstance(message, dict):
            if message.get("role") in ("tool", "function"):
                message.setdefault("tool_call_id", "fallback_call_id")
                message.setdefault("name", "unknown_tool")
            context_messages.extend(convert_to_messages([message]))
        elif isinstance(message, ToolMessage):
            if not getattr(message, "tool_call_id", None):
                message.tool_call_id = "fallback_call_id"
            if not getattr(message, "name", None):
                message.name = "unknown_tool"
            context_messages.append(message)
        else:
            context_messages.append(message)

    # STEP 4 - HYBRID RAG (always runs; sync embedding work off the event loop)
    state.scratchpad.set_current_step("Running Hybrid RAG retrieval")
    rag_result = await asyncio.to_thread(hybrid_rag, user)
    retrieved_context = rag_result.get("context", "")

    if retrieved_context:
        context_messages.insert(
            0,
            SystemMessage(
                content="[Hybrid RAG Retrieved Knowledge]\n\n"
                + retrieved_context
                + "\n\nUse this retrieved knowledge as supporting evidence. "
                "It must not override actual MCP tool results."
            ),
        )
    else:
        context_messages.insert(
            0,
            SystemMessage(
                content="[Hybrid RAG Result]\nNo relevant bank documents were "
                "retrieved for this request."
            ),
        )

    # STEP 5 - LONG-TERM MEMORY (+ post-retrieval verification)
    state.scratchpad.set_current_step("Retrieving long-term memory")
    long_term_context = await asyncio.to_thread(retrieve_long_term_memory, user)

    memory_verification = None
    if long_term_context:
        memory_verification = await verify_long_term_memory(
            llm=state.llm, query=user, memory_context=long_term_context
        )
        if memory_verification.supported:
            context_messages.insert(
                0,
                SystemMessage(
                    content="[Verified Long-Term Memory]\n\n"
                    + long_term_context
                    + "\n\nThis memory was verified as relevant to the current "
                    "request."
                ),
            )
        else:
            long_term_context = ""  # not verified -> not provided (client.py behaviour)

    # STEP 6 - SCRATCHPAD CONTEXT
    scratchpad_state = state.scratchpad.get_state()
    context_messages.insert(
        0,
        SystemMessage(
            content="[Internal Scratchpad State]\n"
            f"Goal: {scratchpad_state['goal']}\n"
            f"Current Step: {scratchpad_state['current_step']}\n"
            f"Notes: {', '.join(scratchpad_state['notes'])}"
        ),
    )

    # STEP 7 - AGENT
    state.scratchpad.set_current_step("Calling agent")
    final_response = await state.agent.ainvoke({"messages": context_messages})
    generated_answer = final_response["messages"][-1].content
    final_context_messages = context_messages

    # STEP 8 - MEMORY ANSWER VERIFICATION (+ fallback regeneration)
    if long_term_context and memory_verification is not None:
        answer_verification = await verify_memory_answer(
            llm=state.llm,
            query=user,
            memory_context=long_term_context,
            generated_answer=generated_answer,
        )
        if not answer_verification["supported"]:
            fallback_context_messages = [
                message
                for message in context_messages
                if not (
                    isinstance(message, SystemMessage)
                    and message.content.startswith("[Verified Long-Term Memory]")
                )
            ]
            final_response = await state.agent.ainvoke(
                {"messages": fallback_context_messages}
            )
            final_context_messages = fallback_context_messages

    # STEP 9 - NEW MESSAGES GENERATED THIS TURN
    new_messages = final_response["messages"][len(final_context_messages):]
    for message in new_messages:
        tool_name = getattr(message, "name", None)
        if tool_name:
            state.scratchpad.add_note(f"Tool call: {tool_name}")

    # STEP 10 - OUTPUT
    answer = final_response["messages"][-1].content
    if not isinstance(answer, str):
        answer = str(answer)

    # STEP 11 - SAVE CONVERSATION (only this turn's messages)
    for message in new_messages:
        normalized = state.stm._normalize(message)
        state.stm.add_normalized_message_with_routing(normalized, route_fn=route_fn)

    # STEP 12 - RESET SCRATCHPAD
    state.scratchpad.set_current_step("Waiting for next request")

    # STEP 13 - REFRESH MCP TOOLS if the server pushed a change
    if conn.tools_dirty:
        await _ensure_memory_agent(conn, state)

    return answer


async def run_memory_rag_request(message: str, thread_id: str) -> str:
    """Run the real Memory & RAG pipeline for this UI thread."""
    state = _memory_threads.setdefault(thread_id, _MemoryThread())

    async with _thread_lock(thread_id):
        try:
            text = await _call_on_connection(
                thread_id, lambda conn: _memory_turn(state, message, conn)
            )
        except GatewayError:
            state.invalidate_session_objects()
            raise
        except Exception as exc:
            state.invalidate_session_objects()
            raise GatewayError(f"Memory & RAG pipeline failed: {exc}") from exc

    text = (text or "").strip()
    if not text:
        state.invalidate_session_objects()
        raise GatewayError(
            "Memory & RAG returned an empty response (LLM backend unavailable - "
            "check GROQ_API_KEY in .env)."
        )
    return text


# ===========================================================================
# Agent 3: Planning & Decomposition
#
# Reuses planning_agent.PlanningAgent unchanged: the same `login` call
# planning_agent.run_session() performs, then PlanningAgent(session).run(goal).
# ===========================================================================

class _PlanningSession:
    def __init__(self, thread_id: str, employee_id: int):
        self.thread_id = thread_id
        self.employee_id = employee_id
        self.agent = None
        self.logged_in = False

    async def _ensure(self, session: ClientSession) -> None:
        if self.logged_in and self.agent is not None:
            return
        from planning_agent import PlanningAgent

        login_result = await session.call_tool(
            "login", {"employee_id": self.employee_id}
        )
        self.agent = PlanningAgent(session)
        self.logged_in = True
        self.login_text = _first_text(login_result)

    async def run(self, session: ClientSession, goal: str) -> dict[str, Any]:
        await self._ensure(session)
        return await self.agent.run(goal)

    def invalidate(self) -> None:
        """Session-bound objects are stale after the MCP session is rebuilt."""
        self.agent = None
        self.logged_in = False


_planning_sessions: dict[str, _PlanningSession] = {}


def _first_text(result: Any) -> str:
    try:
        return "\n".join(
            block.text for block in result.content if hasattr(block, "text")
        )
    except Exception:
        return ""


def _format_planning_result(result: dict[str, Any]) -> str:
    """Readable rendering of PlanningAgent.run()'s structured result."""
    tasks = result.get("tasks") or {}
    lines = [
        "Planning & Decomposition",
        "",
        f"Goal: {result.get('goal', '')}",
        f"Model: {result.get('model', '')}",
        f"Tasks: {result.get('completed_tasks', 0)}/{result.get('task_count', 0)} completed",
        "",
        "Plan (topological order):",
    ]
    for task_id in result.get("topological_order", []):
        task = tasks.get(task_id, {})
        lines.append(
            f"  {task_id} [{task.get('status', '?')}] - {task.get('description', '')}"
        )

    terminal = result.get("terminal_tasks") or []
    if terminal:
        lines += ["", "Final findings (grounded against MCP):"]
        for task_id in terminal:
            text = str((tasks.get(task_id) or {}).get("result", ""))
            if len(text) > 1500:
                text = text[:1500] + "\n...[truncated]"
            lines.append(f"  {task_id}: {text}")

    return "\n".join(lines)


async def run_planning_request(message: str, thread_id: str) -> str:
    """Run the real Planning & Decomposition agent on this thread's session."""
    session_state = _planning_sessions.get(thread_id)
    if session_state is None:
        session_state = _planning_sessions[thread_id] = _PlanningSession(
            thread_id, PLANNING_EMPLOYEE_ID
        )

    async with _thread_lock(thread_id):
        try:
            result = await _call_on_connection(
                thread_id, lambda conn: session_state.run(conn.session, message)
            )
        except GatewayError:
            # session-state may now be bound to a rebuilt MCP session
            session_state.invalidate()
            raise
        except Exception as exc:
            session_state.invalidate()
            raise GatewayError(f"Planning & Decomposition run failed: {exc}") from exc

    try:
        text = _format_planning_result(result)
    except Exception as exc:
        raise GatewayError(
            f"Planning & Decomposition returned an unreadable result: {exc}"
        ) from exc

    if result.get("failed_tasks"):
        text += (
            f"\n\nNote: {result.get('failed_tasks')} task(s) failed during "
            "execution - results above show what did complete."
        )
    return text


# ===========================================================================
# Agent 5: Suspicious Activity
#
# Reuses investigation_graph_runner's public API directly (it is the seam the
# module docstring defines for platform backends). State is durable in
# state_graph/checkpoints.db, keyed by the investigation thread the runner
# mints; this module only keeps the UI-thread -> investigation_id mapping.
# ===========================================================================

_thread_investigations: dict[str, int] = {}

_CUSTOMER_ID_RE = re.compile(
    r"customer(?:[\s_]*(?:id|no|number))?[\s:=_#]*(\d+)", re.IGNORECASE
)
_INVESTIGATION_ID_RE = re.compile(r"investigation\s*#?(\d+)", re.IGNORECASE)


async def run_suspicious_activity_request(message: str, thread_id: str) -> str:
    """Route a chat message to the existing suspicious-activity investigation graph.

    Per-thread state machine:
      * no investigation on this thread -> need a customer ID, then start one
      * paused waiting_for_evidence     -> the user's message IS the external
                                           evidence (submit_external_evidence)
      * paused hitl_required            -> report only; an admin must resolve it
                                           through resolve_hitl_task (never
                                           auto-approved from the chat)
      * open investigation              -> status snapshot; a DIFFERENT customer
                                           ID in the message starts a new one
    """
    from state_graph.suspicious_activity.investigation_graph_runner import (
        get_investigation_snapshot,
        start_investigation,
        submit_external_evidence,
    )
    from mcp_server import db_access as db

    async with _thread_lock(thread_id):
        investigation_id = _thread_investigations.get(thread_id)

        # An explicit "investigation N" in the message always wins (lets a
        # user resume a known investigation after a server restart).
        explicit = _INVESTIGATION_ID_RE.search(message)
        if explicit and db.get_investigation(int(explicit.group(1))):
            investigation_id = _thread_investigations[thread_id] = int(
                explicit.group(1)
            )

        customer_match = _CUSTOMER_ID_RE.search(message)

        try:
            if investigation_id is None:
                return await _start_new_investigation(
                    message, thread_id, customer_match, start_investigation, db
                )

            snapshot = await get_investigation_snapshot(investigation_id)
            interrupt_payload = snapshot.get("interrupt") or {}
            values = snapshot.get("values") or {}

            if snapshot.get("paused"):
                reason = interrupt_payload.get("reason")
                if reason == "waiting_for_evidence":
                    missing = interrupt_payload.get("missing_evidence") or []
                    evidence_payload = {
                        key: {"evidence_data": message, "source": "chat_user"}
                        for key in missing
                    } or {"external": {"evidence_data": message, "source": "chat_user"}}
                    result = await submit_external_evidence(
                        investigation_id, evidence_payload
                    )
                    return _format_investigation_result(
                        investigation_id, result, await get_investigation_snapshot(
                            investigation_id
                        )
                    )
                if reason == "hitl_required":
                    return (
                        f"Suspicious Activity Investigation #{investigation_id}\n\n"
                        "This investigation is PAUSED and requires a human-in-the-loop "
                        "decision (risk: "
                        f"{interrupt_payload.get('risk_level', 'n/a')}, confidence: "
                        f"{interrupt_payload.get('confidence', 'n/a')}).\n"
                        f"Reason: {interrupt_payload.get('hitl_reason', 'n/a')}\n"
                        f"Review task id: {interrupt_payload.get('hitl_task_id', 'n/a')}\n\n"
                        "I cannot approve or reject it from chat - an administrator "
                        "must resolve the human review task "
                        "(POST /admin/hitl/{{task_id}}/resume, decision: approve | "
                        "reject | more_evidence).\n\n"
                        + _format_snapshot(snapshot)
                    )
                return (
                    f"Suspicious Activity Investigation #{investigation_id} is "
                    f"paused ({interrupt_payload.get('reason', 'unknown')}):\n\n"
                    + json.dumps(interrupt_payload, indent=2, default=str)
                )

            # Not paused: a DIFFERENT customer id starts a fresh investigation,
            # otherwise report this thread's current state.
            if customer_match:
                requested_customer = int(customer_match.group(1))
                if values.get("customer_id") != requested_customer:
                    return await _start_new_investigation(
                        message,
                        thread_id,
                        customer_match,
                        start_investigation,
                        db,
                    )

            return (
                f"Suspicious Activity Investigation #{investigation_id}\n\n"
                + _format_snapshot(snapshot)
            )
        except GatewayError:
            raise
        except Exception as exc:
            raise GatewayError(f"Suspicious Activity workflow failed: {exc}") from exc


async def _start_new_investigation(
    message: str,
    thread_id: str,
    customer_match: re.Match | None,
    start_investigation,
    db,
) -> str:
    if customer_match is None:
        open_rows = db.list_open_investigations()
        hint = ""
        if open_rows:
            known = ", ".join(
                f"#{row['investigation_id']} (customer {row['customer_id']}, "
                f"{row['status']})"
                for row in open_rows
            )
            hint = f" Open investigations you can reference: {known}."
        return (
            "Please provide a customer ID to investigate "
            "(e.g. 'Investigate customer 2 for unusual transfers')." + hint
        )

    customer_id = int(customer_match.group(1))
    if db.get_customer(customer_id) is None:
        return (
            f"Customer {customer_id} does not exist in the bank database - "
            "give an existing customer ID (e.g. 1, 2 or 3)."
        )

    result = await start_investigation(customer_id=customer_id, reason=message)
    investigation_id = result.get("investigation_id")
    if result.get("status") != "failed" and investigation_id is not None:
        _thread_investigations[thread_id] = investigation_id

    snapshot = None
    if investigation_id is not None:
        try:
            snapshot = await get_investigation_snapshot(investigation_id)
        except Exception:
            snapshot = None
    return _format_investigation_result(investigation_id, result, snapshot)


def _format_investigation_result(
    investigation_id: int | None, result: dict[str, Any], snapshot: dict | None
) -> str:
    header = (
        f"Suspicious Activity Investigation #{investigation_id}"
        if investigation_id is not None
        else "Suspicious Activity Investigation"
    )
    status = result.get("status")

    if status == "failed":
        return (
            f"{header}\n\nThe investigation run FAILED.\n"
            f"Error: {result.get('error', 'unknown')}\n"
            f"Failed node: {result.get('failed_node', 'unknown')}\n"
            f"Failure ticket: {result.get('ticket_id', 'n/a')} "
            "(an admin can resolve it via POST /admin/tickets/{id}/resume)."
        )

    if status == "closed":
        return (
            f"{header}\n\nClosed.\n"
            f"Decision: {result.get('decision', 'n/a')}\n"
            f"Reason: {result.get('decision_reason', 'n/a')}"
        )

    # paused or unknown -> show the freshest snapshot we have
    if snapshot is not None:
        interrupt_payload = snapshot.get("interrupt") or {}
        if snapshot.get("paused") and interrupt_payload.get("reason") == "hitl_required":
            return (
                f"{header}\n\nPaused for a human-in-the-loop decision "
                "(an admin must resolve it - it is never auto-approved from "
                "chat).\n\n" + _format_snapshot(snapshot)
            )
        if snapshot.get("paused"):
            return (
                f"{header}\n\nPaused waiting for external evidence. Send the "
                "evidence as your next message and it will be submitted to the "
                "investigation.\n\n" + _format_snapshot(snapshot)
            )
        return f"{header}\n\n" + _format_snapshot(snapshot)

    return f"{header}\n\nRun status: {status or 'unknown'}\n{result}"


def _format_snapshot(snapshot: dict[str, Any]) -> str:
    values = snapshot.get("values") or {}
    lines = [
        f"Status: {values.get('status', 'unknown')}",
        f"Customer: {values.get('customer_id', '?')}",
    ]
    if values.get("risk_level") is not None:
        lines.append(f"Risk level: {values['risk_level']}")
    if values.get("confidence") is not None:
        lines.append(f"Confidence: {values['confidence']}")
    if values.get("evidence_flags"):
        lines.append(f"Flags: {', '.join(values['evidence_flags'])}")
    if values.get("missing_evidence"):
        lines.append(f"Still missing: {', '.join(values['missing_evidence'])}")
    if values.get("analysis"):
        analysis = str(values["analysis"])
        if len(analysis) > 800:
            analysis = analysis[:800] + "...[truncated]"
        lines.append(f"Analysis: {analysis}")
    if values.get("decision"):
        lines.append(f"Decision: {values['decision']}")
    if values.get("decision_reason"):
        lines.append(f"Decision reason: {values['decision_reason']}")
    if values.get("error"):
        lines.append(f"Last error: {values['error']}")
    if values.get("hitl_reason"):
        lines.append(f"Human review reason: {values['hitl_reason']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# shutdown (called from the FastAPI lifespan)
# ---------------------------------------------------------------------------

async def shutdown() -> None:
    """Close every open MCP connection and drop per-thread state."""
    async with _registry_lock:
        conns = list(_registry.values())
        _registry.clear()
    _memory_threads.clear()
    _planning_sessions.clear()
    _thread_investigations.clear()
    _thread_locks.clear()
    for conn in conns:
        await conn.aclose()
