# Sterling & Vance Bank Loan Approval Agents

## Company

Sterling & Vance Bank B is a Commercial bank that processes customer loan applications. Loan officers evaluate applications using customer information.

## Problem

The bank needs to decide whether a customer's loan application should be approved, rejected, or reviewed. Some applications are easy to decide, while others need checking more customer information before making the final decision.

## Why an Agent?

A simple rule-based script works well for simple cases, but every possible situation must be written as fixed rules. As the decision process becomes more complex, the script becomes harder to update and maintain.

An AI agent can reason step by step before making a decision. It can choose which information it needs, decide which tool to use, and use the results of previous steps to continue its reasoning until it reaches a final answer.    

### Presentation and demo link        
The design was by Silvana Marzouk and written by all of us          
https://docs.google.com/presentation/d/1alKPV4nFntZwaykGyq3jZPkx6vYcy0Gl/edit?usp=drive_link&ouid=105576425572035483121&rtpof=true&sd=true

## Requirements

Before running the project, install the required Python packages:

```bash
pip install langchain
pip install langchain-groq
pip install python-dotenv
pip install pydantic
```


## Comparison

| agent               | calls per request | token usage     | latency  | what broke on tricky inputs                                                                                              |
| ------------------- | ----------------- | --------------- | -------- | ------------------------------------------------------------------------------------------------------------------------ |
| Reactive            | 0                 | 0               | 0.044 ms | Could not adapt to unseen or complex cases outside its hard-coded rules                                                  |
| Unconstrained ReAct | 9                 | 3382            | 0.38     | try non existent id:<br />The agent detected that the id didn't exist but made unnecessary tool calls before rejecting |
| Routing             | 1                 | less than ReAct | 0.4374   | No routing failures observed                                                                                             |
| Constrained ReAct   | 3                 | 2125            | 0.68     | no failure, stopped after                                                                                               |
