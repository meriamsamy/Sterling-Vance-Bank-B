# Suspicious Activity Investigation — State Graph

## 1. Problem

Sterling & Vance's compliance/fraud teams need to investigate customers
whose financial activity looks suspicious. An investigation can't always
be completed in one pass: the bank's own database might not contain
enough to reach a reliable conclusion, in which case the agent must
**wait for something external** (a customer statement, a source-of-funds
document, a corroborating report) instead of guessing.

This is not a single-pass LLM task. It's a long-lived workflow whose
state changes in response to events outside the agent's control — which
is exactly what a DAG-based planning agent (see `task_one_loan_agent/`)
cannot do: a DAG runs start-to-finish and is done. This graph can pause
indefinitely, resume from a completely different process, loop back
through the same states more than once, and must not lose collected
evidence if the process dies mid-run.

## 2. Why this can't be the existing planning/RAG agents

- The RAG side answers "what does policy say?" — it doesn't own an
  investigation's lifecycle across multiple sittings.
- The planning agent decomposes a task into a DAG and runs it to
  completion — it has no concept of "pause here until a human or an
  external system responds."

This graph **reuses** both: RAG for the policy-lookup step, and the
existing grounded `validate_investigation()` MCP tool for the final
validation step — but it owns something neither of them do: the
investigation's actual lifecycle.

## 3. Graph states and transitions

```
create_investigation
      |
collect_initial_evidence
      |
analyze_evidence  <---------------------+
      |                                 |
[missing_evidence?]                     |
   /            \                       |
  NO             YES                    |
  |               |                     |
  v               v                     |
reassess_     wait_for_evidence         |
investigation      |                    |
  |          ingest_new_evidence -------+
[hitl_required?]
   /        \
  NO         YES
  |           |
  v           v
close_    waiting_for_admin
investigation    |
  ^         [admin_decision?]
  |          /      |      \
  |     approve  reject  more_evidence
  |         \      /          |
  +----------+----+           v
                        wait_for_evidence
```

| State | What happens |
|---|---|
| `create_investigation` | Opens the investigation (`investigations` row via `db.create_investigation`), initializes state |
| `collect_initial_evidence` | Pulls customer, accounts, transactions, wires, sanctions hits, related employees — everything the bank's **own** database has |
| `analyze_evidence` | RAG-grounded sufficiency check (§5) |
| `wait_for_evidence` | Genuine pause via `interrupt()` — see §4 |
| `ingest_new_evidence` | Merges externally-submitted evidence, loops back to `analyze_evidence` |
| `reassess_investigation` | LATS candidate search + grounded validation (§6) |
| `waiting_for_admin` | Genuine pause via `interrupt()` for HITL (§7) |
| `close_investigation` | Terminal — writes `decision`/`decision_reason` |

Failure handling is **not** a graph node — see §8.

## 4. The waiting state (Issue 4)

`collect_initial_evidence` only pulls from the bank's own database. A
source-of-funds document, a customer's written explanation, a
corroborating report from whoever flagged the account — none of that can
come from that node, by construction. So "evidence insufficient" means
specifically: nothing in the bank's own transaction/wire data
corroborates the reason the investigation was opened.

When that happens, `wait_for_evidence` calls LangGraph's `interrupt()`,
which persists the full state to `state_graph/checkpoints.db`
(`AsyncSqliteSaver`, via `checkpointing_layer.checkpoint_context()`) and
stops execution — no polling loop, no sleep. Resuming happens by calling
`graph.ainvoke(Command(resume=evidence_dict), config)` with the same
`thread_id`, which can happen minutes or days later, from a completely
different process. That's the whole reason the checkpointer is SQLite
and not in-memory.

If the newly-submitted evidence still doesn't clear an open flag, the
loop (`ingest_new_evidence` → `analyze_evidence` → `wait_for_evidence`)
repeats — a genuine cycle, not a straight line.

## 5. Why RAG belongs in `analyze_evidence`

The question this node answers — "given our own DB-detected flags, what
does policy actually require here?" — is a policy-lookup question with
one right answer grounded in a fixed document (`rag/chroma_db`, built
from `sterling_vance_financial_crime_policy.md`). That's exactly what
RAG is for. It reuses `rag/hybrid_rag.py` exactly as-is — hybrid
vector+BM25 retrieval, then Self-RAG verification — no second retriever,
no second policy document.

## 6. Why LATS belongs in `reassess_investigation`

Once evidence is sufficient, there usually isn't one obvious conclusion:
a structuring flag could mean genuine small-business cash handling, or
laundering, or a false positive. That's a *search over competing
interpretations of the same evidence* — a different kind of problem than
a policy lookup, which is why LATS lives here and not in
`analyze_evidence`.

This is a lightweight two-level LATS:
- **Depth 0 (breadth):** generate 3–4 competing candidate conclusions
  (`legitimate_activity` / `potential_fraud` /
  `potential_money_laundering` / `insufficient_evidence`), each with a
  rationale and self-reported confidence.
- **Depth 1 (expand):** take the single most promising candidate and
  give the model one more pass to strengthen or walk back its own
  reasoning.

The full tree is stored in `state["lats_candidates"]` so a grader can
see the search, not just the answer.

**The LLM is not the final source of truth.** Whatever candidate LATS
lands on is passed to `validate_investigation()` — the exact grounded,
DB-backed validator `mcp_server/server.py` already exposes as an MCP tool — and
if validation fails, confidence is reduced accordingly before risk/HITL
routing happens.

## 7. HITL (Issue 5)

Escalation fires when, in `reassess_investigation`:

```
risk_level == "high"
OR confidence < 0.80
OR validate_investigation(...) fails
```

(see `investigation_lats.requires_hitl()` — one function, called from
both the node and the routing edge, so there's exactly one definition of
the threshold).

When it fires, a **real** `human_review_tasks` row is created
(`db.create_human_review_task`, `workflow_type="suspicious_activity"`)
*before* the graph reaches `waiting_for_admin`'s `interrupt()` — without
that row, the pause would still work, but there'd be nothing for an
admin platform to list or click into. The graph only resumes once
`investigation_graph_runner.resolve_hitl_task()` is called with the
admin's actual decision (`approve` / `reject` / `more_evidence`), which
also marks the DB task `completed` first.

## 8. Failure tickets — a different code path than HITL (Issue 6)

HITL is an **expected** pause for a decision the agent isn't allowed to
make alone. A failure ticket is **unplanned** — a tool call errored, a
JSON parse failed, the model returned something unusable.

Nodes in this graph do **not** catch their own exceptions. If a node
caught its own error and returned a normal state update, LangGraph would
treat it as having *completed successfully* and checkpoint past it — so
resuming later would skip the broken node instead of retrying it. That
would silently violate "resume from checkpoint, don't restart."

Instead: exceptions propagate. `investigation_graph_runner._run()` is
the **only** place that catches them — around every `graph.ainvoke(...)`
call. On exception, it reads `graph.aget_state(config)`, which LangGraph
guarantees reflects the *last node that actually completed* (the last
good checkpoint), takes `.next[0]` as the failed node's name, and calls
`create_failure_ticket()` (→ `db.create_workflow_ticket`,
`workflow_type="suspicious_activity"`, status `open`).

Resolving the ticket (`resolve_failure_ticket()`) marks it `resolved`
then calls `graph.ainvoke(None, config)` — LangGraph's own semantics for
"continue from the last checkpoint," which retries the exact node that
raised, not the one after it.

A grader can tell HITL and failure tickets apart by which function
creates them: `db.create_human_review_task()` only ever gets called from
inside `reassess_investigation`; `db.create_workflow_ticket()` only ever
gets called from `investigation_graph_runner._run()`'s except block.

## 9. Checkpointing (Issue 3)

Every node transition goes through `investigation_nodes.update_transition()`,
which does two things: it's the value LangGraph's `AsyncSqliteSaver`
checkpoints after every node (full `InvestigationState` — evidence, RAG
context, LATS candidates, validation result, risk/confidence, HITL/ticket
IDs, everything), *and* it mirrors the small set of fields the admin
platform's list view needs (`status`, `risk_level`, `confidence`,
`decision`) into the plain `investigations` SQL row, so a dashboard can
query without touching LangGraph internals.

**Crash-and-resume demo:** start an investigation that lands in
`wait_for_evidence`, kill the process, restart it, call
`submit_external_evidence()` — the graph resumes from the persisted
checkpoint, does **not** re-run `collect_initial_evidence`, and
incorporates the new evidence directly into `analyze_evidence`.

## 10. Database changes (Issue 7)

New tables (`db/migrations/002_suspicious_activity_investigation.sql`):
`investigations`, `investigation_evidence`. **Not** duplicated:
`workflow_tickets` and `human_review_tasks` already exist in
`db/schema.sql` as shared infrastructure and are reused as-is
(`workflow_type = "suspicious_activity"` distinguishes these rows from
any other graph's).

## 11. MCP tools (Issue 8)

Reused as-is: `get_customer_accounts`, `get_transaction_history`,
`check_sanctions`, `get_account`, `validate_investigation`.

New (added in `mcp_server/db_access.py` / `mcp_server/schemas.py` / `mcp_server/server.py`):
`get_related_employees`, `get_customer_wire_transfers` (full wire rows —
`get_wire_destination_countries` only returns country codes, not enough
for LATS to reason over amounts/status/timing), plus the investigation
lifecycle operations (`create_investigation`, `get_investigation`,
`submit_investigation_evidence`).

The graph calls these through `mcp_server/db_access.py` directly rather than
opening a second MCP client session against itself — it lives in the
same repository/process the MCP server does, so no banking logic is
duplicated, just called without an extra network hop. `validate_investigation`
is imported the same way, directly from `mcp_server/server.py`, so it's the
exact same grounded validator a real MCP client would call.