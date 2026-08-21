# state_graph/customer_risk/utils.py
import functools
import sqlite3
import traceback
from typing import Callable, Any
from mcp import db_access as db

def handle_node_failure(func: Callable[..., dict[str, Any]]):
    @functools.wraps(func)
    def wrapper(state: dict[str, Any], *args, **kwargs) -> dict[str, Any]:
        try:
            return func(state, *args, **kwargs)
        except Exception as exc:
            run_id = state.get("run_id", "unknown_run")
            node_name = func.__name__
            err_msg = str(exc)
            stack_trace = traceback.format_exc()

            ticket_id = None
            if hasattr(db, "create_failure_ticket"):
                ticket_id = db.create_failure_ticket(
                    run_id=run_id,
                    agent_name="customer_risk_agent",
                    node_name=node_name,
                    error_message=err_msg,
                    stack_trace=stack_trace,
                    current_state=state
                )
            elif hasattr(db, "create_ticket"):
                ticket_id = db.create_ticket(
                    run_id=run_id,
                    agent_name="customer_risk_agent",
                    node_name=node_name,
                    error_message=err_msg,
                    stack_trace=stack_trace,
                    current_state=state
                )
            else:
                try:
                    with sqlite3.connect("db/bank.db", timeout=30.0) as conn:
                        cursor = conn.cursor()
                        cursor.execute(
                            """
                            INSERT INTO failure_tickets (agent_name, node_name, error_message, stack_trace, status)
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            ("customer_risk_agent", node_name, err_msg, stack_trace, "OPEN")
                        )
                        conn.commit()
                        ticket_id = cursor.lastrowid
                except Exception as db_err:
                    print(f"Warning: Failed to log failure ticket directly: {db_err}")
                    ticket_id = "FALLBACK_TICKET_001"

            now_str = db._now() if hasattr(db, "_now") else ""

            return {
                "status": "failed",
                "current_node": node_name,
                "failure_ticket_id": ticket_id,
                "risk_reason": f"Execution failed at {node_name}: {err_msg}",
                "updated_at": now_str
            }
    return wrapper