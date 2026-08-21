from __future__ import annotations

import sqlite3
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.memory import MemorySaver

from .state import CustomerRiskState
from .nodes import (
    load_customer_state,
    collect_recent_activity,
    decompose_risk_review,
    retrieve_risk_policy,
    assess_risk_consistency,
    wait_for_activity,
    risk_review_human_approval,
    apply_admin_decision,
)


def route_after_activity(state: CustomerRiskState) -> str:
    if state.get("recent_activity"):
        return "decompose_risk_review"
    return "wait_for_activity"


def route_after_assessment(state: CustomerRiskState) -> str:
    if state.get("status") == "failed":
        return END

    if state.get("risk_changed", False) or state.get("assessment_confidence", 1.0) < 0.7:
        return "risk_review_human_approval"

    return "wait_for_activity"


def route_after_approval(state: CustomerRiskState) -> str:
    if state.get("admin_decision"):
        return "apply_admin_decision"
    return "wait_for_activity"


def build_customer_risk_graph(checkpointer=None):
    builder = StateGraph(CustomerRiskState)

    # Adding Nodes
    builder.add_node("load_customer_state", load_customer_state)
    builder.add_node("collect_recent_activity", collect_recent_activity)
    builder.add_node("decompose_risk_review", decompose_risk_review)
    builder.add_node("retrieve_risk_policy", retrieve_risk_policy)
    builder.add_node("assess_risk_consistency", assess_risk_consistency)
    builder.add_node("wait_for_activity", wait_for_activity)
    builder.add_node("risk_review_human_approval", risk_review_human_approval)
    builder.add_node("apply_admin_decision", apply_admin_decision)

    # Edges & Routing
    builder.add_edge(START, "load_customer_state")
    builder.add_edge("load_customer_state", "collect_recent_activity")

    builder.add_conditional_edges(
        "collect_recent_activity",
        route_after_activity,
        {
            "decompose_risk_review": "decompose_risk_review",
            "wait_for_activity": "wait_for_activity",
        },
    )

    builder.add_edge("decompose_risk_review", "retrieve_risk_policy")
    builder.add_edge("retrieve_risk_policy", "assess_risk_consistency")

    builder.add_conditional_edges(
        "assess_risk_consistency",
        route_after_assessment,
        {
            "risk_review_human_approval": "risk_review_human_approval",
            "wait_for_activity": "wait_for_activity",
            END: END,
        },
    )

    builder.add_conditional_edges(
        "risk_review_human_approval",
        route_after_approval,
        {
            "apply_admin_decision": "apply_admin_decision",
            "wait_for_activity": "wait_for_activity",
        },
    )

    builder.add_edge("apply_admin_decision", "wait_for_activity")
    builder.add_edge("wait_for_activity", END)

    # ✅ التعديل هنا: استخدام sqlite3.connect بدلاً من from_conn_string
    if checkpointer is None:
        conn = sqlite3.connect("checkpoints.db", check_same_thread=False)
        checkpointer = SqliteSaver(conn)

    return builder.compile(checkpointer=checkpointer)