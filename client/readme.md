# Client (MCP Agent)

## Overview

This client connects a LangChain agent to the Sterling & Vance Bank MCP server.

The client is responsible for:

- Establishing the MCP connection.
- Performing the initialization handshake.
- Discovering available tools.
- Reading server resources.
- Listing available prompt templates.
- Handling runtime notifications.
- Handling elicitation requests.
- Providing the model used for MCP sampling.
- Executing MCP tools through a LangChain agent.

---
# Setup

Install the required packages:

```bash
pip install -r requirements.txt
```

Create a `.env` file and add your Groq API key:

```text
GROQ_API_KEY=your_api_key_here
```
---
# How to Run

## Run the Client (Development - stdio)

```bash
python client/client.py
```

The client automatically starts the MCP server using the stdio transport.

---

## Run with Streamable HTTP

Start the server:

```bash
TRANSPORT=http python mcp/server.py
```

Then start the client:

```bash
TRANSPORT=http python client/client.py
```
---
# Main Components

## System Prompt

Defines the banking assistant's behavior.

The assistant:

- Always uses MCP tools for banking operations.
- Never invents successful operations.
- Waits for human approval when required.
- Reports tool failures instead of generating fake responses.

---

## Elicitation Callback

`handle_elicitation()`

Handles human approval requests coming from the server.

When a high-risk wire transfer requires approval, the client:

1. Displays the approval request.
2. Waits for user input.
3. Returns the approval decision back to the server.

---

## Tool Schemas

Pydantic models define the expected arguments for every MCP tool:

- LoginArgs
- GetAccountArgs
- WireTransferArgs
- BatchScanArgs

These models are used when converting MCP tools into LangChain tools.

---

## MCP Tool Wrapper

`convert_mcp_tool()`

Converts every discovered MCP tool into a LangChain `StructuredTool`.

Responsibilities:

- Calls MCP tools.
- Displays progress updates for long-running operations.
- Reports tool errors clearly.
- Returns tool results to the agent.

---

## Progress Tracking

Long-running tools such as:

- batch_sanctions_scan

use a progress callback that prints intermediate progress while the server is scanning transactions.

---

## Agent

`build_agent()`

Creates the LangChain agent by combining:

- Groq LLM
- MCP tools
- Banking system prompt

---

## Sampling Callback

`handle_sampling()`

Implements the MCP Sampling protocol.

When the server needs additional reasoning for a flagged wire transfer, it sends a `create_message` request to the client.

The client forwards that request to the Groq model and returns the generated response back to the server.

The server never performs its own reasoning.

---

## Notifications

`message_handler()`

Handles notifications pushed by the server.

Current notifications:

- tools/list_changed
- progress

When the available tools change, the client automatically refreshes its tool list instead of polling continuously.

---

## Capability Negotiation

After connecting, the client performs the MCP initialize handshake.

The client checks which capabilities the server supports before using them.

Capabilities checked:

- Resources
- Prompts
- Tool list change notifications

---

## Resources

If the server supports resources, the client:

1. Lists available resources.
2. Reads the Wire Transfer Policy.
3. Adds the policy to the conversation context so the model can use it during reasoning.

---

## Prompts

If the server exposes prompt templates, the client lists them so they can be reused instead of generating prompts manually.

---

## Tool Discovery

After initialization, the client discovers all currently available MCP tools.

When the server later sends a `tools/list_changed` notification, the client refreshes its tools automatically.

---

## Supported Transports

The client supports both MCP transports.

### Development

- stdio

### Deployment

- Streamable HTTP

The transport is selected using the `TRANSPORT` environment variable.

---

# MCP Concerns Covered

This client participates in the following protocol concerns:

- Capability Negotiation
- Notifications
- Elicitation
- Resources
- Prompts
- Sampling
- Progress Tracking
- Transport
