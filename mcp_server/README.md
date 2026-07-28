# mcp_server/ — Sterling & Vance Wire Transfer Assistant

This folder implements the MCP server side of the project. It currently
covers three protocol concerns end-to-end (Notifications, Progress tracking,
Defensive tool design), plus enough scaffolding (capability setup, tool
dispatch) to run standalone for testing.

## Files
- `state.py` — in-memory stand-in for Person A's SQLite database (employees, accounts, sanctions list). Swap this for real DB calls once `db/` is ready.
- `schemas.py` — strict JSON Schema for every tool: typed fields, `required`, `additionalProperties: false`, real descriptions.
- `server.py` — the server itself. Every concern is tagged with a comment block so it's easy to find:
  - `[CONCERN 2 - NOTIFICATIONS]`
  - `[CONCERN 7 - PROGRESS TRACKING]`
  - `[CONCERN 8 - DEFENSIVE TOOL DESIGN]`

## How to run
```bash
pip install -r requirements.txt
python server.py
```
This runs over stdio for local development (per the assignment's required
dev→prod transport path; the Streamable HTTP version is Person C's later
commit once the agent side is ready).

## Concern 2 — Notifications
**Trigger:** an employee logs in via `role_login`. If their role is
`compliance_officer` or `fraud_investigator` (and this is a genuine change
from the previous session role), the server calls
`ctx.session.send_tool_list_changed()`.

**Why it's genuine, not decorative:** a teller session must never see
`batch_sanctions_scan` — that tool requires compliance authority. Rather than
either (a) showing it to everyone and gating in the handler, or (b) making
the client poll `tools/list` repeatedly, the tool literally does not exist
for that session until the role change is real.

## Concern 7 — Progress tracking
**Trigger:** `batch_sanctions_scan`, which simulates scanning up to 20,000
transactions. Instead of one blocking call, it sends incremental
`send_progress_notification` updates in chunks (10% increments) so a client
can show "4,000 of 10,000 scanned" instead of appearing frozen.

**Test input:** `{"employee_id": "E-2002", "batch_size": 2000}` (compliance
officer, small batch — completes in a few seconds while still emitting
~10 progress events).

## Concern 8 — Defensive tool design
**Tool:** `wire_transfer_initiate` — the one genuinely risky write tool.

Three independent layers:
1. **Schema** (`schemas.py`): `required` fields, `additionalProperties: false`,
   amount bounded `0 < amount <= 1,000,000`, currency restricted to an enum,
   country code length-constrained.
2. **Server-side validation** (`handle_wire_transfer`): account existence,
   sufficient balance, amount within the *employee's actual* wire authority
   limit — none of which a JSON Schema can express.
3. **Handler-level authorization**: the `employee_id` argument is checked
   against the actual authenticated session (`SESSION_STATE`), not trusted
   at face value — an argument claiming to be a compliance officer does not
   make it so.

**Test inputs (fixed set, repeatable demo):**
| Scenario | Employee | Destination | Expected result |
|---|---|---|---|
| Normal wire | E-1001 (teller) | ACC-100001 (US, clean) | Completes |
| Sanctioned destination | E-1001 (teller) | ACC-100002 (KP) | Held for review |
| Self-dealing | E-1001 (teller) | ACC-100003 (linked to E-1001) | Held for review |
| Over authority | E-1001 (teller, $5k limit) | any, amount=$50,000 | Rejected |
| Mismatched identity | args say E-2002 but E-1001 is logged in | any | Rejected |

## What's intentionally out of scope here
Capability negotiation (declared but not client-checked), elicitation,
resources, prompts, sampling, and the full stdio→HTTP transport migration
are owned by other issues/teammates per the team's split. This file should
not be graded as if it claims those.
