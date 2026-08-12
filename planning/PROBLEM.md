## **📌 Problem Framing — Wire Transfer Investigation & Risk Assessment**

### 1. Problem

We are building a **Planning Agent** for a banking compliance/fraud-investigation scenario.

A Compliance Officer / Fraud Investigator gives the agent a high-level request such as:

> **"Investigate customer X's financial activity and determine whether there is suspicious activity, provide the supporting evidence, and give a policy-grounded recommendation."**

The agent is **not responsible for initiating wire transfers, freezing accounts, or waiting for human approval**.

Its responsibility is to **plan and execute the investigation** using the available MCP tools and banking database.

---

### 2. Why this is a Planning Problem

The request is not a single deterministic tool call.

It requires multiple investigation steps, for example:

```text
Customer X
    ↓
Find customer accounts
    ↓
Collect transaction history
    ↓
Analyze wire transfers
    ↓
Check sanctions
    ↓
Analyze suspicious/structuring patterns
    ↓
Investigate relevant relationships/counterparties
    ↓
Combine evidence
    ↓
Risk assessment
    ↓
Policy-grounded recommendation
```

The exact investigation path may depend on **what is discovered during earlier steps**.

Therefore, the agent needs:

* **Task Decomposition**
* **Planning**
* **Dynamic adaptation**
* **Reasoning over multiple possible paths**
* **Routing between planning algorithms**

---

### 3. DAG / Task Decomposition

The investigation should be represented as a **DAG with real branching**, not just a linear sequence.

Example:

```text
                 Customer X
                     │
                     ▼
               Find Accounts
                     │
            ┌────────┼─────────┐
            ▼        ▼         ▼
       Transactions Wires   Sanctions
            │        │
            ▼        ▼
       Structuring  Wire
            │       Analysis
            │        │
            └────┬───┘
                 ▼
          Combine Evidence
                 │
                 ▼
          Risk Assessment
                 │
                 ▼
            Recommendation
```

Independent investigation branches can run separately and their results are later combined.

---

### 4. Dynamic Decomposition

The initial plan should **not always be fixed**.

If an early investigation result reveals something unexpected, the agent should be able to add a new sub-task.

Example:

```text
Find Accounts
      ↓
Analyze Wires
      ↓
Unexpected linked counterparty discovered
      ↓
NEW TASK:
Investigate Counterparty Relationship
      ↓
Update Evidence
      ↓
Re-assess Risk
```

This gives us a real **dynamic decomposition** scenario.

We should also demonstrate at least one case where **decomposition-first and dynamic decomposition produce different investigation paths**.

---

### 5. Planning Algorithms

Different sub-tasks should be routed to the algorithm that fits their reasoning structure.

#### Plan-and-Solve (PS)

For tasks where there is a relatively clear multi-step reasoning process.

Example:

```text
Transaction history
→ identify relevant patterns
→ analyze them
→ produce findings
```

#### Tree-of-Thoughts (ToT)

For tasks with multiple plausible reasoning paths or hypotheses.

Example:

```text
Possible explanations:
    ├── Structuring
    ├── Unusual wire activity
    ├── Sanctions-related risk
    └── Suspicious relationship

→ explore/evaluate alternatives
→ keep promising paths
→ reach the strongest explanation
```

#### LATS

For tasks where multiple candidate actions/recommendations can be explored and **evaluated using real external feedback**.

The feedback must be grounded in the actual banking environment/database/policy validation rather than only the LLM's opinion.

---

### 6. Router

The Router receives a decomposed sub-task and decides whether it should be:

```text
Direct deterministic tool call
        OR
PS
        OR
ToT
        OR
LATS
```

Not every task needs a planning algorithm.

For example:

```text
get_customer_accounts()
→ Direct tool call

analyze_structuring_patterns
→ PS / ToT

evaluate competing risk explanations
→ ToT

choose and validate final recommendation
→ LATS
```

---

### 7. MCP / Database Requirements

The investigation must work with the **existing MCP server and existing banking database**.

The current tools may not be sufficient for the investigation, so we first need to inspect the existing database/schema and MCP server.

If required, we can add **read-only investigation tools**, such as:

```text
get_customer
get_customer_accounts
get_transaction_history
get_customer_wires
check_sanctions
get_customer_relationships
```

But we should only add tools that correspond to **real data and capabilities available in the existing database**.

We should NOT invent tools/data just to make the problem look more complex.

---

### 8. Grounded LATS

LATS needs a real evaluation environment.

Instead of:

```text
LLM → "This plan looks good"
```

we want:

```text
Candidate plan/recommendation
          ↓
Actual banking data / policy validation
          ↓
Environment Feedback
          ↓
Score / Success / Failure / Reason
```

This allows us to demonstrate that **grounded evaluation can catch failures that an ungrounded LLM critique might miss**.

---

### 9. Final Goal

The final Planning Agent should be able to take:

> **"Investigate customer X's financial activity."**

and transform it into:

```text
High-level request
       ↓
Task Decomposition
       ↓
Investigation DAG
       ↓
Router
       ↓
Direct Tools / PS / ToT / LATS
       ↓
Evidence
       ↓
Risk Assessment
       ↓
Policy-grounded Recommendation
```

The key idea is:

> **The agent is planning and adapting an investigation, not simply answering a question or executing one tool call.**
