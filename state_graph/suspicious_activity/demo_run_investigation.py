"""
CLI for demonstrating crash-and-resume (Issue 3's acceptance criteria).

Run from the project root, with your .env / GROQ_API_KEY set up and
db/bank.db already migrated (both migrations under db/migrations/).

Usage:
    python state_graph/suspicious_activity/demo_run_investigation.py start <customer_id> "<reason>"
    python state_graph/suspicious_activity/demo_run_investigation.py submit-evidence <investigation_id> <evidence_type> "<text>"
    python state_graph/suspicious_activity/demo_run_investigation.py status <investigation_id>
    python state_graph/suspicious_activity/demo_run_investigation.py resolve-hitl <investigation_id> <approve|reject|more_evidence> "<notes>" <assigned_to_employee_id>
    python state_graph/suspicious_activity/demo_run_investigation.py resolve-ticket <investigation_id> <ticket_id>

Each invocation is a SEPARATE, short-lived Python process — the graph
does not sit in a blocking loop while paused. That's the point: a
process can be started, do one step, and exit completely; the pause
lives entirely in state_graph/checkpoints.db until something calls back
in with a Command(resume=...), which can be minutes, hours, or days
later, in an entirely different process.
"""
import asyncio
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from state_graph.suspicious_activity import investigation_graph_runner as runner


async def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    command = sys.argv[1]

    if command == "start":
        customer_id, reason = int(sys.argv[2]), sys.argv[3]
        result = await runner.start_investigation(customer_id, reason)
        print(result)

    elif command == "submit-evidence":
        investigation_id, evidence_type, text = int(sys.argv[2]), sys.argv[3], sys.argv[4]
        result = await runner.submit_external_evidence(
            investigation_id,
            {evidence_type: {"evidence_data": text, "source": "demo_cli"}},
        )
        print(result)

    elif command == "status":
        investigation_id = int(sys.argv[2])
        result = await runner.get_investigation_snapshot(investigation_id)
        print(result)

    elif command == "resolve-hitl":
        investigation_id, decision, notes, assigned_to = (
            int(sys.argv[2]), sys.argv[3], sys.argv[4], int(sys.argv[5])
        )
        result = await runner.resolve_hitl_task(investigation_id, decision, notes, assigned_to)
        print(result)

    elif command == "resolve-ticket":
        investigation_id, ticket_id = int(sys.argv[2]), int(sys.argv[3])
        result = await runner.resolve_failure_ticket(investigation_id, ticket_id)
        print(result)

    else:
        print(f"Unknown command: {command}")
        print(__doc__)


if __name__ == "__main__":
    asyncio.run(main())