# mcp_server/

Runs against the real `db/bank.db` (built from `db/schema.sql` + `db/seed.sql`).
All 8 protocol concerns live in `server.py`, tagged with `[CONCERN NAME]`
comment blocks so they're easy to find without reading the whole file.

## Setup
```bash
pip install -r ../requirements.txt
cp ../.env.example ../.env   # fill in GROQ_API_KEY
python server.py             # stdio, for local dev
TRANSPORT=http python server.py   # Streamable HTTP, for deployment
```

## Where each concern lives

| Concern | Where | Trigger |
|---|---|---|
| **Capability negotiation** | `build_init_options()`, `client_supports_elicitation()`, `client_supports_sampling()` | Server declares tools/resources/prompts support via `create_initialization_options()`. Server checks the client's *declared* elicitation/sampling capability (from `client_params.capabilities`) before calling either, instead of firing blind and catching an exception. |
| **Notifications** | `login()` | Logging in as employee 1 or 2 (compliance/fraud roles) fires `send_tool_list_changed`, unlocking `batch_sanctions_scan`. Logging in as employee 3 or 4 (teller) doesn't. |
| **Elicitation** | `wire_transfer()` | Any of sanctions / structuring / self-dealing / AI-flagged-high-risk pauses the call via `elicit_form` for an explicit human `approved: bool`. If the client never declared elicitation support, the wire is left `pending_manual_review` instead of silently proceeding or silently failing. |
| **Resources** | `list_resources()` / `read_resource()`, `policy_document.py` | The escalation policy (`policy://sterling-vance/wire-transfer-controls`) is static reference data the model reads once and reasons over — not a function it calls per-request. |
| **Prompts** | `list_prompts()` / `get_prompt()` | `draft_compliance_hold_notice(transfer_id)` — a reusable, parameterized starting point for the recurring "explain why this wire is on hold" task. |
| **Sampling** | `analyze_wire_risk()` | Only called when a wire is already flagged. Routes through `ctx.session.create_message()` — the *client's* model (see `client/client.py`'s `handle_sampling`), never the server's own reasoning. Falls back to a rule-based note if the client didn't declare sampling support. |
| **Transport** | `run_stdio()` / `run_http()` / `main()` | stdio while developing (`TRANSPORT=stdio`, default); Streamable HTTP for deployment (`TRANSPORT=http`) — a multi-branch bank needs more than one employee session hitting the server at once, which stdio's one-process-per-connection model can't do. |
| **Progress tracking** | `batch_scan()` | Sends a progress notification per transaction scanned instead of one blocking reply. Real work here is small (seed data) — this is the code path a nightly scan over thousands of transactions runs through. |
| **Defensive tool design** | `wire_transfer()` + `schemas.py` | Schema (`WIRE_TRANSFER_SCHEMA`) catches bad input shape (`additionalProperties: false`, `exclusiveMinimum`, 2-char country code). The handler independently re-checks balance, wire-authority limit, and that `employee_id` in the args actually matches who's logged in for *this* session — the schema saying it's an integer isn't authorization. |

## Audit trail
Every wire transfer now actually debits the source account (`db_access.debit_account`)
and records who approved/rejected it (`db_access.set_wire_approver`). Every elicited
decision is logged to `compliance_reviews` (`db_access.insert_compliance_review`) —
previously that table existed in the schema/ERD but nothing ever wrote to it.

## Test cases (already in seed.sql, so these are repeatable)
| Login as | Wire | Expected |
|---|---|---|
| 4 (Omar, teller) | source 2 → FR, $3,000 | approved, balance debited |
| 4 (Omar, teller) | source 1 → IR, $7,000 | held — sanctions → elicitation |
| 4 (Omar, teller) | source 3 → US, $14,000 | held — structuring (3 near-$5k deposits on account 3) → elicitation |
| 3 (Emily, teller, linked to customer 2) | source 1 → EG, $6,000 | held — self_dealing → elicitation |
| 1 (John, compliance) then `batch_sanctions_scan` | — | tool only appears after login; progress events fire per transaction |
| Any flagged wire, client started without `sampling_callback`/`elicitation_callback` | — | server detects missing capability, skips the request instead of crashing, wire held for manual review |
