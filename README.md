# Sterling & Vance Bank Loan Approval Agents

## Company

Sterling & Vance Bank B is a Commercial bank that processes customer loan applications. Loan officers evaluate applications using customer information.

## Problem

The bank needs to decide whether a customer's loan application should be approved, rejected, or reviewed. Some applications are easy to decide, while others need checking more customer information before making the final decision.

## Why an Agent?

A simple rule-based script works well for simple cases, but every possible situation must be written as fixed rules. As the decision process becomes more complex, the script becomes harder to update and maintain.

An AI agent can reason step by step before making a decision. It can choose which information it needs, decide which tool to use, and use the results of previous steps to continue its reasoning until it reaches a final answer.

## Project Structure

### `reactive/`


### `unconstrained_react/`

**Description:**  ReAct agent without constraints. The model decides its own reasoning process, tool calls, and stopping point.

**Run**

```bash
cd unconstrained_react
python main.py
```

**Model / Provider:**

* Provider: Groq
* Model: llama-3.3-70b-versatile

### `routing/`


### `constrained_react/`

**Description:** ReAct agent with schema validation, a restricted tool allow-list, and a max steps for (for loop)

**Run**

```bash
cd constrained_react
python main.py
```

**Model / Provider:**

* Provider: Groq
* Model: llama-3.3-70b-versatile

## Comparison

| agent               | calls per request | token usage | latency | what broke on tricky inputs                                                                                              |
| ------------------- | ----------------- | ----------- | ------- | ------------------------------------------------------------------------------------------------------------------------ |
| Reactive            |                   |             |         |                                                                                                                          |
| Unconstrained ReAct | 9                 | 3382        | 0.38    | try non existent id:<br />The agent detected that the id didn't exist but made unnecessary tool calls before rejecting |
| Routing             |                   |             |         |                                                                                                                          |
| Constrained ReAct   | 3                 | 2125        | 0.68    | no failure, stopped after                                                                                               |
