# Sterling & Vance Bank B

## Problem Statement

---

## System Architecture

---

## How To Run

---

## Memory 

### Short-term Memory:

**The real need:** a compliance officer's session at Sterling & Vance
is multi-turn by nature - they log in, look up an account, ask a
policy question, then initiate a wire transfer, all in one sitting.
The banking agent needs the immediate conversation history (who's
logged in, which account was just discussed) to answer follow-up
requests correctly, without re-asking for context the officer already
gave.

**Implementation:** `ShortTermMemory` (`memory/short_term_memory/short_term_memory.py`)
is a rolling buffer (`deque(maxlen=20)`) holding the most recent
messages of the session.

The non-obvious part: `agent.ainvoke()` returns real LangChain message
objects (`HumanMessage` / `AIMessage` / `ToolMessage`), not plain
dicts. If short-term memory stored those objects as-is, every context
strategy (`sliding`/`masking`/`summary`/`zone`, all of which do
`msg.get("role")`) would crash on the very next turn. `ShortTermMemory._normalize()`
converts anything handed to it - LangChain objects or plain dicts -
into one consistent `{"role", "content", ...}` shape, and critically
also preserves `tool_call_id` and `tool_calls` when present. Dropping
those breaks tool-call turns with `KeyError: 'tool_call_id'` the next
time a stored `ToolMessage` is fed back into the agent - this was
caught and fixed by running a real login -> get_account ->
wire_transfer_initiate session end-to-end.

### Scratchpad:

**The real need:** the agent's current task ("processing a wire
transfer for employee 1") is a different kind of state than the chat
transcript - it shouldn't disappear or get garbled if `memory` gets
pruned or summarized mid-task. A compliance officer mid-transfer
shouldn't have the agent lose track of what it's doing because the
sliding window rolled the wrong message off, or recursive
summarization compacted it away.

**Implementation:** `Scratchpad` (`memory/short_term_memory/scratchpad.py`)
tracks `goal`, `plan`, `current_step`, and `notes` for the current
request, entirely separate from `ShortTermMemory`. Each turn:

1. `scratchpad.set_goal(user)` / `set_current_step(...)` records what
   the agent is actively working on.
2. The scratchpad's current state is injected into the agent's context
   as a one-off `SystemMessage` for that turn only, so the LLM
   genuinely uses it (goal/step/notes so far) rather than just
   tracking it for show.
3. That injected message is explicitly filtered out before calling
   `memory.replace_messages()`, so it never becomes a permanent part
   of the transcript.

**Why it survives pruning:** the scratchpad lives entirely outside
`memory`. None of the four context strategies (which only ever operate
on `memory.get_messages()`) can touch it - whatever a strategy prunes
or summarizes, the scratchpad's record of the current goal and
tool-call notes is untouched.

### Context Management:

Sterling & Vance conversations get bloated fast - not by long
dialogue, but by large tool-call results (KYC lookups, transaction
history dumps, transfer engine logs). A long session risks burying an
early but important detail (e.g. a verification PIN, an account note)
under this tool-call noise by the time it's needed again. All four
strategies below (`memory/context_strategies/`) were implemented and
benchmarked against this exact failure mode - see the comparison table
and justification further down this README.

### Promote-or-Drop:

### Episodic Memory:

### Semantic Memory:

### Consolidation:

---

## Retrieval

### Vector Database:

### Naive RAG:

### Hybrid RAG:

### Agentic RAG:

### Self-RAG:

---

## Context Management Comparison

**Test setup:** A 31-message synthetic transcript modeling a real Sterling & Vance support conversation. The test suite evaluates recall performance across 5 different critical needles (verification PINs, account numbers, confirmation codes, transfer amounts, and branch names) buried under ~7 large tool-call outputs (KYC lookups, transaction history, transfer engine logs). Each strategy was evaluated across all test cases (`memory/context_strategies/context_eval.py`) and scored on needle retention accuracy (%), average input token count, and strategy processing latency.

| Strategy | Accuracy (%) | Avg. Input Tokens | Avg. Latency |
| :--- | :--- | :--- | :--- |
| **Sliding Window** | ❌ 0.0% | 1,410 | 0.01 ms |
| **Observation Masking** | ✅ 100.0% | 248 | 0.01 ms |
| **Recursive Summarization** | ⚠️ 40.0% | 1,229 | 8,523.04 ms |
| **Zone-based Pruning** | ✅ 100.0% | 2,006 | 0.01 ms |

### what we selected and why:

We ship **observation masking** as the default context strategy (`ACTIVE_CONTEXT_STRATEGY = "masking"` in `client/client.py`).

- **Sliding window failed completely (0.0% Accuracy):** A fixed rolling window consistently dropped critical details shared in early turns once the conversation progressed past message 10, while still consuming 1,410 tokens.
- **Recursive summarization is unreliable and excessively slow (40.0% Accuracy, ~8.5s Latency):** It lost 60% of critical needle facts because the summarization LLM frequently compacts away exact codes and identifiers as non-essential prose. Furthermore, making extra Groq calls to summarize added massive latency overhead (~8.5 seconds per turn), making it unacceptable for real-time compliance workflows.
- **Zone-based pruning retained information (100.0% Accuracy) but lacked effective compression:** While fast (0.01 ms) and accurate, it retained 2,006 input tokens—8x more tokens than masking. It fails to target our actual source of context bloat, which is large tool payloads rather than user dialogue.
- **Observation masking is the clear winner (100.0% Accuracy, 248 Tokens, 0.01 ms Latency):** It achieved perfect recall accuracy, compressed context down to the absolute smallest footprint (248 tokens vs. Zone's 2,006), and executed with zero added API latency. By directly masking raw tool outputs while preserving user and assistant dialogue intact, it guarantees that critical user inputs are never lost.

**Caveat:** this table reflects one fixed transcript run, not an average
over multiple variations. Before final submission we plan to re-run
this against 2-3 more transcripts (varying where the needle fact sits
and how large the tool outputs are) to confirm masking's win holds up
and isn't an artifact of this one test case's layout.
## Retrieval Architecture Comparison

| Architecture      | Accuracy | Avg. Tokens / Query | Avg. Latency / Query |
| ----------------- | -------- | -------------------- | ---------------------- |
| Naive RAG         |          |                       |                         |
| Hybrid RAG        |          |                       |                         |
| Agentic RAG       |          |                       |                         |
| Graph RAG (Bonus) |          |                       |                         |

### what we selected and why:

---

## Demo