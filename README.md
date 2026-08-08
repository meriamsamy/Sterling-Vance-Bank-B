# Sterling & Vance Bank B

## Problem Statement

Sterling & Vance Bank B initially had an MCP-based banking assistant that could handle accounts and wire transfers with fraud and compliance checks. However, the system had no long-term memory, so important events from previous sessions were lost. For example, if an account was previously identified as high-risk or required a freeze, the agent could not remember this in a later session and would treat the case as new.

The system also lacked a reliable, grounded source for the bank's compliance policies, making it difficult to consistently answer questions about sanctions, fraud, human approval, and account freezing.

To address these gaps, we extended the system with  **long-term memory, RAG, and context management** , allowing the agent to preserve important banking events, retrieve relevant official policies, and use previous knowledge when handling new requests.

---

## System Architecture

---

## How To Run

1. Install the required dependencies:

```bash
pip install -r requirements.txt
```

2. Add the Groq API key to `.env`:

```env
API_KEY=your_groq_api_key
```

3. Create the Chroma vector database from the policy document:

```bash
python rag/vectors_managment.py
```

4. Initialize the memory tables:

```bash
python db/migrate_memory_tables.py
```

5. Run the client:

```bash
python client/client.py
```

The client automatically starts the MCP server and connects the agent to the available banking tools, memory, and RAG system.

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

**The real need:** not every message aging out of short-term memory is
worth keeping. A routine "Wire #9999 of 500.00 approved" is noise a
week later; a wire that got held or reviewed for sanctions/structuring
is exactly the kind of event a compliance officer will ask about
again. Something has to decide, per message, forget or promote - and
log *why* - rather than either keeping everything (noisy) or dropping
everything (issue #39's original problem).

**Implementation:** `route_overflow(messages)` (`memory/episodic_memory/promote_or_drop_router.py`)
takes exactly what `ShortTermMemory.overflow_candidates()` hands back
and classifies each message against the *actual* strings
`mcp/server.py`'s `wire_transfer()` returns as tool results:

- `"Wire #{id} held (flags: {flags}). ..."` -> **promote**
- `"Wire #{id} of {amount} approved after compliance review."` -> **promote**
- `"Wire #{id} cancelled by human reviewer."` -> **promote**
- `"Wire #{id} of {amount} approved."` (routine, unflagged) -> **forget**
- anything else (non-wire, non-tool messages) -> **forget**

Since those tool-result strings never carry `customer_id`/`employee_id`/
`reviewer_id`, a promoted message triggers a read-only enrichment
lookup (`_lookup_transfer_context`) against `wire_transfers` ->
`accounts` -> `compliance_reviews` in the same `bank.db`, so the
resulting episode is fully populated instead of a bare string.

Every decision, forget or promote, is written to `promote_or_drop_log`
with its reasoning - not just the ones that got promoted. **Hard
boundary:** this router never writes to `semantic_memory`, only to
`promote_or_drop_log` and, via `EpisodicMemory`, to `episodic_memory`.

**Demo:** `python memory/episodic_memory/demo_promote_or_drop.py` runs
one routine wire (forgotten), one non-tool message (forgotten), and
one flagged/reviewed wire (promoted, enriched, logged) end-to-end
against the real `bank.db`.

### Episodic Memory:

**The real need (issue #39):** "the agent cannot remember previous
fraud investigations or important banking events after the session is
closed." Front-line staff shouldn't have to re-explain a customer's
flag history every session, and the agent shouldn't have to re-scan
raw `wire_transfers` rows to answer "has this customer been flagged
before?" - it should recall a curated event, not re-derive it.

**Implementation:** `EpisodicMemory` (`memory/episodic_memory/episodic_memory.py`)
stores one row per promoted event in the `episodic_memory` table
(`event_type`, `transfer_id`, `customer_id`, `employee_id`, `flags`,
`decision`, `reviewer_id`, `summary`, `promoted_at`,
`promotion_reason`, `consolidated`). Only ever written to by the
promote-or-drop router above - this class has no opinion on what's
worth keeping, it just persists and retrieves.

Key methods: `store_episode(...)`, `get_episode(episode_id)`,
`get_episodes_for_customer(customer_id)` (the real recall query),
`get_recent_episodes(limit)`, and the consolidation-facing pair
`get_unconsolidated_episodes()` / `mark_consolidated(episode_ids)`,
which is the only channel through which semantic memory below ever
learns anything happened - episodic memory itself never writes to
`semantic_memory`.

### Semantic Memory:

**The real need (issue #41):** a fact like a customer's risk level
isn't static - it can be reinforced by a repeat flag, or contradicted
by a later investigation that reaches a different conclusion than an
earlier one. Overwriting it in place would silently erase what the
bank used to believe and why. `customers.risk_level` already existed
in the schema but nothing ever updated it - a real staleness problem,
not an invented one.

**Implementation:** `SemanticMemory` (`memory/semantic_memory/semantic_memory.py`)
stores one row per **fact version** in `semantic_memory`
(`entity_type`, `entity_id`, `fact_key`, `fact_value`, `version`,
`valid_from`, `valid_to`, `status`, `source_episode_ids`,
`superseded_by`, `contradiction_note`). Nothing is ever updated in
place:

- `insert_fact_version(...)` always appends a new version, never edits an existing row.
- `supersede_fact(fact_id, superseded_by)` closes out the old active row (`valid_to`, `status='superseded'`, `superseded_by`) instead of deleting or overwriting it - full history stays queryable via `get_fact_history(...)`.
- `expire_stale_facts(max_age_days=180)` marks facts nobody has reconfirmed as `'expired'` (a distinct status from `'superseded'` - one means "replaced by a newer fact," the other means "just went stale").

Only ever written to by the consolidation pass below - never by the
promote-or-drop router, per #40's hard boundary.

### Consolidation:

**The real need:** semantic facts must never be written at message
time - they need a separate pass that can look across *multiple*
episodes for the same entity and decide whether they agree, reinforce
each other, or genuinely conflict.

**Implementation:** `run_consolidation()` (`memory/semantic_memory/consolidation.py`)
is a standalone, periodic pass - triggered manually via
`python memory/semantic_memory/run_consolidation.py`, never called by
the router and never fired at write time. It pulls every
unconsolidated episode (`EpisodicMemory.get_unconsolidated_episodes()`),
groups them by customer, and for each one derives an implied
`risk_level` via `derive_risk_level(flags, decision)`:

- `sanctions` or `self_dealing` present -> `high`, regardless of decision
- `structuring` only, decision cleared (`approved`/`cleared`) -> `medium`
- `structuring` only, any other/unknown decision -> `high` (conservative default)

That derived value is then reconciled against the customer's current
active fact:

1. **No active fact yet** -> insert the first version.
2. **Same value as current** -> treated as a repeat-offender signal: severity is escalated one level (`_escalate`, capped at `high`), old version superseded, new version versioned with a note explaining the escalation.
3. **Different value than current -> a real conflict.** The newer episode wins (resolved on recency of investigation, not insertion order); the old fact is superseded, not overwritten; `contradiction_note` records both episode ids and the reasoning.

**A real contradiction, not a hypothetical one:** `python memory/semantic_memory/demo_consolidation.py`
seeds two genuine wire transfers for the existing seeded customer
Ahmed Ali (`customer_id=1`) *through the actual PR 3 router* (not
hand-crafted rows) - a `structuring` wire cleared by compliance
(-> derives `medium`), then a later `sanctions` wire (-> derives
`high`). Consolidation resolves the disagreement: `medium` is
superseded, `high` becomes the active fact, and the audit trail
(`get_fact_history`) shows both versions with the contradiction
explained rather than lost.

---

# Retrieval

#### Vector Database

The policy document (`sterling_vance_financial_crime_policy.md`) is split into chunks based on Markdown headers (`#` = Section, `##` = Subsection) using `MarkdownHeaderTextSplitter`. Large sections are further divided into smaller chunks (1000 characters with 200-character overlap) to improve retrieval quality. Each chunk stores metadata (`section`, `subsection`, `document_type`, `version`), is embedded using the `sentence-transformers/all-MiniLM-L6-v2` model, and is indexed in **Chroma**, which uses an HNSW index for efficient vector similarity search. The metadata is also used to optionally filter retrieval to a specific policy section before semantic search is performed.

#### Naive RAG

The baseline retrieval pipeline performs a plain semantic search over the Chroma vector database using `similarity_search`, returning the top **3** most relevant chunks with no metadata filtering, keyword retrieval, or query rewriting. The retrieved chunks are combined into a single context and passed to the shared **Self-RAG verification pipeline**, which validates the retrieved context before generating and verifying the final answer.

#### Hybrid RAG

Hybrid RAG extends the baseline retrieval with two additional components. First, `extract_metadata_filter` uses the LLM to determine whether the question belongs to a specific policy section. If a section is identified, the vector search is filtered using Chroma metadata, and a temporary **BM25** retriever is built only from the chunks belonging to that section. Otherwise, the global BM25 retriever is used. The semantic search results and keyword search results are merged, duplicate chunks are removed, and the combined context is passed to the shared Self-RAG verification pipeline. This improves retrieval for questions containing exact policy terminology, section names, or numerical values.

#### Agentic RAG

Agentic RAG introduces an iterative retrieval loop instead of performing a single retrieval pass. It first uses `plan_retrieval` to rewrite the user's question into a policy-oriented search query. Documents are then retrieved using the same retrieval strategy as Hybrid RAG. After retrieval, `is_context_enough` evaluates whether the collected context is sufficient to answer the question. If not, `rewrite_query` generates a refined retrieval query and another retrieval iteration is performed (up to `MAX_ITERATIONS`). Retrieved documents from all iterations are accumulated and deduplicated before being passed to the shared Self-RAG verification pipeline. This strategy is particularly useful for questions that require information from multiple policy sections.

#### Self-RAG

Self-RAG is implemented as a shared verification layer used by **Naive RAG**, **Hybrid RAG**, and **Agentic RAG** to reduce hallucinations and improve answer reliability.

1. **`verify_retrieved_context`** checks whether the retrieved context is relevant and sufficient for answering the user's question. If the retrieved context is judged insufficient, the process stops immediately and returns `REJECTED_AFTER_RETRIEVAL`.
2. **`generate_answer`** generates an answer using only the retrieved policy context and explicitly avoids relying on outside knowledge.
3. **`verify_answer`** evaluates the generated answer against the retrieved context and classifies it as `SUPPORTED`, `UNSUPPORTED`, or `UNANSWERABLE`. Unsupported answers are rejected (`REJECTED_AFTER_GENERATION`), while `UNANSWERABLE` results return a standard response indicating that the requested information could not be found in the policy instead of fabricating an answer.

Each verification and generation step records token usage through `usage_metadata`, allowing the total token consumption for each query to be accumulated and reported in the retrieval evaluation metrics.

## Context Management Comparison

**Test setup:** A 31-message synthetic transcript modeling a real Sterling & Vance support conversation. The test suite evaluates recall performance across 5 different critical needles (verification PINs, account numbers, confirmation codes, transfer amounts, and branch names) buried under ~7 large tool-call outputs (KYC lookups, transaction history, transfer engine logs). Each strategy was evaluated across all test cases (`memory/context_strategies/context_eval.py`) and scored on needle retention accuracy (%), average input token count, and strategy processing latency.

| Strategy                          | Accuracy (%) | Avg. Input Tokens | Avg. Latency |
| :-------------------------------- | :----------- | :---------------- | :----------- |
| **Sliding Window**          | ❌ 0.0%      | 1,410             | 0.01 ms      |
| **Observation Masking**     | ✅ 100.0%    | 248               | 0.01 ms      |
| **Recursive Summarization** | ⚠️ 40.0%   | 1,229             | 8,523.04 ms  |
| **Zone-based Pruning**      | ✅ 100.0%    | 2,006             | 0.01 ms      |

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

| Architecture | Accuracy    | Avg. Tokens / Query | Avg. Latency / Query |
| ------------ | ----------- | ------------------- | -------------------- |
| Naive RAG    | 4/6 (66.66) | 5024                | 29.92                |
| Hybrid RAG   | 4/6 (66.66) | 4072                | 30.31                |
| Agentic RAG  | 4/6 (66.66) | 5785                | 43.724               |

Evaluation was run on a reduced test set (6 questions) due to API rate limits; results should be validated on a larger set before production use

### what we selected and why:

Although all three retrieval architectures achieved the same accuracy (4/6) on our evaluation set, we selected **Hybrid RAG** as the final retrieval architecture.

Hybrid RAG achieved the same retrieval accuracy as Naive RAG while requiring fewer tokens per query (4072 vs. 5024), making it more cost-efficient. It also retrieved fewer documents on average due to metadata filtering and keyword search, resulting in more focused context without sacrificing answer quality. Although its average latency (30.31 s) was slightly higher than Naive RAG (29.92 s), the difference was negligible compared to the reduction in token usage.

Agentic RAG introduced iterative retrieval and query refinement, but on our banking policy dataset it did not improve accuracy. Instead, it consumed the largest number of tokens (5785) and had the highest latency (43.72 s). Since the additional reasoning steps did not provide measurable gains on our evaluation set, its extra computational cost was not justified.

Therefore, **Hybrid RAG** provides the best balance between retrieval quality, efficiency, and computational cost, making it the most suitable architecture for deployment in our banking compliance assistant.

---

## Demo
Memory (issues #39–#41): `python memory/episodic_memory/demo_promote_or_drop.py`
shows both outcomes of promote-or-drop firing and logging correctly;
`python memory/semantic_memory/demo_consolidation.py` shows a real
contradiction (two flags on the same customer implying different risk
levels) being resolved by consolidation, versioned rather than
overwritten.