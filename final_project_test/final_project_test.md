# Sanctions change Graph test output

```
(venv) PS D:\sterling and vance bank B> python -m final_project_test.sanctions_graph_test
D:\sterling and vance bank B\final_project_test\sanctions_graph_test.py:27: SyntaxWarning: "\s" is an invalid escape sequence. Such sequences will not work in the future. Did you mean "\\s"? A raw string is also an option.
  python -u ".\final_project_test\sanctions_graph_test.py"
D:\sterling and vance bank B\venv\Lib\site-packages\langchain_core\utils\pydantic.py:41: UserWarning: Core Pydantic V1 functionality isn't compatible with Python 3.14 or greater.
  from pydantic.v1 import BaseModel as BaseModelV1
Warning: You are sending unauthenticated requests to the HF Hub. Please set a HF_TOKEN to enable higher rate limits and faster downloads.
Loading weights: 100%|███████████████████████████████████████████████████| 103/103 [00:00<00:00, 1530.26it/s]===========================================STERLING & VANCESANCTIONS GRAPH E2E INTEGRATION TESTProject root: D:\sterling and vance bank B
Bank DB: D:\sterling and vance bank B\db\bank.db
Test prefix: sanctions-test-6e7893e1[PASS] Database backup created: C:\Users\meria\AppData\Local\Temp\bank-test-backup-n744znnf.db===========================================TEST 1 — INITIAL GRAPH EXECUTION + CHECKPOINTUsing real wire: 11
[PASS] Graph returned a result.--- Initial checkpoint ---
current_node: detect_sanctions_change
last_node: collect_evidence
status: waiting
pending_event: None
sanctions_changed: False
sanctions_impact: no_impact
hitl_required: False
hitl_task_id: None
failure_ticket_id: None
failure_resolved: False
failed_node: None
error_type: None
decision: None
next: ('waiting_for_event',)
[PASS] Wire ID persisted in graph state.
[PASS] Destination country persisted.
[PASS] Wire status persisted.
[PASS] Wire amount persisted.
[PASS] Source account ID persisted.
[PASS] Current graph node persisted.
[PASS] Transition timestamp persisted.
[PASS] Evidence field exists.
[PASS] Initial sanctions version persisted.
[PASS] Graph produced a resumable checkpoint.===========================================TEST 2 — EXTERNAL EVENT WAIT--- External-event checkpoint ---
current_node: detect_sanctions_change
last_node: collect_evidence
status: waiting
pending_event: None
sanctions_changed: False
sanctions_impact: no_impact
hitl_required: False
hitl_task_id: None
failure_ticket_id: None
failure_resolved: False
failed_node: None
error_type: None
decision: None
next: ('waiting_for_event',)
[PASS] Workflow status is waiting.
[PASS] External-event checkpoint is resumable.===========================================TEST 3 — REAL SANCTIONS CHANGE DURING OPEN REVIEW[PASS] Destination country exists.
[PASS] Workflow has a starting sanctions version.
Country: IR
Starting sanctions version: 1
[PASS] Existing sanctioned country was temporarily cleared.
[PASS] Real sanctions status change was created.External sanctions event:
{'changed': True, 'event_id': 2, 'version': 3, 'previous_status': 'CLEAR', 'new_status': 'SANCTIONED'}
[PASS] Sanctions event received a persistent event ID.
[PASS] Sanctions version increased.
[PASS] Sanctions status actually changed.
[PASS] Country became sanctioned.[HYBRID RAG TOOL] CALLED
Question: What is the required action when the sanctions status of a destination country changes while an open wire transfer review is still in progress?
Metadata Filter: 9Retrieved 1 documents===========================================CONSTRAINED REACT NODEMCP TOOLS:loginget_accountwire_transfer_initiateCONSTRAINED REACT STEP 1/6MISTRAL RESPONSE:
{
    "action": "tool_call",
    "tool": "get_account",
    "input": {
        "account_id": 3
    },
    "reasoning": "The investigation requires re-evaluation of wire #11#11 due to sanctions status change for destination country 'IR'. The source account (ID: 3) details are already partially known, but we need the most up-to-date account information to ensure compliance and verify no additional risks (e.g., account status, ownership changes) have emerged since the initial evidence was collected."
}VALIDATED ACTION:
ACTION: tool_call
TOOL: get_account
INPUT: {'account_id': 3}
REASONING: The investigation requires re-evaluation of wire #11#11 due to sanctions status change for destination country 'IR'.INVALID TOOL ARGUMENTS:
Unable to validate the MCP tool argument schema.
[PASS] Graph resumed after sanctions event.--- After sanctions update ---
current_node: re_evaluate
last_node: prepare_re_evaluation
status: waiting_for_admin
pending_event: sanctions_update
sanctions_changed: True
sanctions_impact: affected
hitl_required: True
hitl_task_id: 1
failure_ticket_id: None
failure_resolved: False
failed_node: None
error_type: None
decision: None
next: ('waiting_for_admin',)
[PASS] Graph loaded the new sanctions version.
[PASS] Graph sees the country as sanctioned.
[PASS] Graph detected sanctions change.
[PASS] Graph marked the review as affected.===========================================TEST 4 — RE-EVALUATION--- Re-evaluation checkpoint ---
current_node: re_evaluate
last_node: prepare_re_evaluation
status: waiting_for_admin
pending_event: sanctions_update
sanctions_changed: True
sanctions_impact: affected
hitl_required: True
hitl_task_id: 1
failure_ticket_id: None
failure_resolved: False
failure_resolved: False
failed_node: None
error_type: None
decision: None
next: ('waiting_for_admin',)
[PASS] Retrieved policy field exists.
[PASS] RAG policy output is populated.
[PASS] Investigation history exists.
[PASS] Investigation step count exists.
[PASS] Investigation status exists.
[PASS] Workflow reached a valid post-sanctions state.
[PASS] Re-evaluation produced a workflow outcome.===========================================TEST 5 — HUMAN-IN-THE-LOOPUsing real compliance officer: 1--- HITL checkpoint ---
current_node: re_evaluate
last_node: prepare_re_evaluation
status: waiting_for_admin
pending_event: sanctions_update
sanctions_changed: True
sanctions_impact: affected
hitl_required: True
hitl_task_id: 1
failure_ticket_id: None
failure_resolved: False
failed_node: None
error_type: None
decision: None
next: ('waiting_for_admin',)
[PASS] Graph escalated the sanctions-affected case to HITL.
[PASS] Graph is waiting for administrator action.
[PASS] HITL task ID exists in graph state.
[PASS] HITL checkpoint is resumable.
[PASS] HITL task exists in database.
[PASS] HITL task is open.
[PASS] HITL task belongs to the correct wire.
[PASS] Graph resumed after admin decision.--- After admin resume ---
current_node: complete_review
last_node: waiting_for_admin
status: completed
pending_event: sanctions_update
sanctions_changed: True
sanctions_impact: affected
hitl_required: True
hitl_task_id: 1
failure_ticket_id: None
failure_resolved: False
failed_node: None
error_type: None
decision: rejected
next: ()
[PASS] Admin decision entered graph state.
[PASS] HITL task still exists after completion.
[PASS] HITL task is completed.
[PASS] Admin decision persisted on HITL task.
[PASS] Real admin ID persisted on HITL task.===========================================TEST 6 — REAL FAILURE + TICKET + RESUME[PASS] Independent failure workflow started.--- Before injected failure ---
current_node: detect_sanctions_change
last_node: collect_evidence
status: waiting
pending_event: None
sanctions_changed: False
sanctions_impact: no_impact
hitl_required: False
hitl_task_id: None
failure_ticket_id: None
failure_resolved: False
failed_node: None
error_type: None
decision: None
next: ('waiting_for_event',)
[PASS] Failure workflow is waiting for an external event.
[PASS] Failure workflow can resume through waiting_for_event.--- After injected failure ---
current_node: collect_evidence
last_node: waiting_for_event
status: failed
pending_event: new_evidence
sanctions_changed: False
sanctions_impact: no_impact
hitl_required: False
hitl_task_id: None
failure_ticket_id: 4
failure_resolved: False
failed_node: collect_evidence
error_type: RuntimeError
decision: None
next: ('reset_after_failure',)
[PASS] Workflow entered the failure-recovery path.
[PASS] Failure ticket ID persisted in graph state.
[PASS] Failed node was recorded correctly.
[PASS] RuntimeError was persisted.
[PASS] Failure message was persisted.
[PASS] Failure ticket exists in database.
[PASS] Failure ticket starts open.
[PASS] Failure ticket belongs to correct wire.
[PASS] Ticket contains failed node.
[PASS] Ticket contains error type.
[PASS] Ticket contains error message.
[PASS] Failure path is separate from HITL.
[PASS] Workflow resumed after ticket resolution.--- After failure-ticket resolution ---
current_node: detect_sanctions_change
last_node: collect_evidence
status: waiting
pending_event: failure
sanctions_changed: False
sanctions_impact: no_impact
hitl_required: False
hitl_task_id: None
failure_ticket_id: 4
failure_resolved: True
failed_node: collect_evidence
error_type: RuntimeError
decision: None
next: ('waiting_for_event',)
[PASS] Failure resolution persisted in graph state.
[PASS] Workflow left the failed state.
[PASS] Workflow resumed to a valid graph node.
[PASS] Resolved ticket still exists.
[PASS] Failure ticket is marked resolved.
[PASS] Ticket resolution timestamp persisted.===========================================TEST 7 — SANCTIONS HISTORY[PASS] Sanctions history returns a list.
[PASS] At least one sanctions change was persisted.
[PASS] Sanctions event belongs to reviewed country.
[PASS] Sanctions event has a newer version.
[PASS] History contains an actual status transition.===========================================TEST 8 — FRESH PYTHON PROCESS CHECKPOINT[PASS] Failure workflow thread exists.Fresh process stdout:
WIRE_ID=11
CURRENT_NODE=detect_sanctions_change
STATUS=waiting
FAILURE_RESOLVED=True
NEXT=('waiting_for_event',)Fresh process stderr:
D:\sterling and vance bank B\venv\Lib\site-packages\langchain_core\utils\pydantic.py:41: UserWarning: Core Pydantic V1 functionality isn't compatible with Python 3.14 or greater.
  from pydantic.v1 import BaseModel as BaseModelV1
Warning: You are sending unauthenticated requests to the HF Hub. Please set a HF_TOKEN to enable higher rate limits and faster downloads.Loading weights:   0%|          | 0/103 [00:00
```
