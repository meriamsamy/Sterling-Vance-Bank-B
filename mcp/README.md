# mcp_server/

Covers protocol concerns 2 (notifications), 7 (progress tracking), and 8
(defensive tool design). Runs against the real `db/bank.db` built from
`schema.sql` + `seed.sql`.

## Setup
```bash
pip install mcp
python server.py
```

## Where each concern lives
- **Notifications** — `login()`. Logging in as employee 1 or 2 (compliance/fraud roles) fires `send_tool_list_changed`, unlocking `batch_sanctions_scan`. Logging in as employee 3 or 4 (teller) doesn't.
- **Progress tracking** — `batch_scan()`. Sends a progress update per transaction scanned instead of one blocking reply.
- **Defensive design** — `wire_transfer()`. Schema catches bad input shape; the function itself re-checks balance, wire limit, and that `employee_id` actually matches who's logged in; risk flags come straight from the real data (sanctions list, deposit pattern, employee-customer link).

## Test cases (already in seed.sql, so these are repeatable)
| Login as | Wire | Expected |
|---|---|---|
| 4 (Omar, teller) | source 2 → FR, $3,000 | approved |
| 4 (Omar, teller) | source 1 → IR, $7,000 | held — sanctions |
| 4 (Omar, teller) | source 3 → US, $14,000 | held — structuring (3 near-$5k deposits on account 3) |
| 3 (Emily, teller, linked to customer 2) | source 1 → EG, $6,000 | held — self_dealing |
| 1 (John, compliance) then `batch_sanctions_scan` | — | tool only appears after login; progress events fire per transaction |

## Not in this file
Elicitation, capability negotiation, resources, prompts, sampling, and the HTTP transport switch — different issues, different owners.
