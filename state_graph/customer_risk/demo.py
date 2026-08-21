from langgraph.types import Command
from state_graph.customer_risk.graph import build_customer_risk_graph

def main():
    print("DEMO STARTED")

    graph = build_customer_risk_graph()

    print("GRAPH BUILT")

    initial_state = {
        "run_id": "risk-demo-001",
        "customer_id": 1,
        "last_processed_transaction_id": None,
        "status": "starting",
        "checkpoint_version": 0,
    }

    config = {"configurable": {"thread_id": "risk-demo-thread-1"}}

    print("INVOKING GRAPH...")

    result = graph.invoke(initial_state, config=config)

    snapshot = graph.get_state(config)

    if snapshot.next:
        print(f"\n[HITL INTERRUPT] Graph paused at node: {snapshot.next}")
        
        interrupt_value = snapshot.tasks[0].interrupts[0].value
        print("Review Request Data:", interrupt_value)

        decision_input = input("\nAdmin Decision (approve/reject): ").strip().lower()
        reason_input = input("Admin Reason (optional): ").strip()

        payload = {
            "decision": decision_input,
            "reason": reason_input or "Manual review completed."
        }

        print("\nRESUMING GRAPH WITH ADMIN DECISION...")
        
        final_result = graph.invoke(Command(resume=payload), config=config)

        print("\n=== FINAL CUSTOMER RISK RESULT ===")
        print(final_result)
    else:
        print("\n=== EXECUTION COMPLETED (NO INTERRUPT) ===")
        print(result)


if __name__ == "__main__":
    main()