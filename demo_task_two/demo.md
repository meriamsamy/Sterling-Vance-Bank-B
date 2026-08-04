# Demo

**Recording:** https://drive.google.com/drive/folders/1p1KFCLTxXnEb_RgH6k0S1WrFTzqmVIGu

Before recording/re-running: `python3 db/reset_balances.py` — resets all
account balances to their original seed values so every run starts from the
same state and results are repeatable, not lucky.

## Setup
```bash
pip install -r requirements.txt
# set GROQ_API_KEY in .env (see .env.example)
python3 db/reset_balances.py
python3 client/client.py
```

## Test cases (in order, matching the video)

| # | Concern | Steps | Expected result |
|---|---|---|---|
| 1 | Capability negotiation | Connect only | Console prints `tools.listChanged = True`, `resources = True`, `prompts = True` |
| 2 | Resources | Automatic on connect | Wire transfer policy fetched and loaded into the agent's context |
| 3 | Prompts | Automatic on connect | `draft_compliance_hold_notice` listed as available |
| 4 | Notifications (before) | `login as employee 4` (Omar, teller) | Tool list stays `[login, get_account, wire_transfer_initiate]` |
| 5 | Defensive design — clean wire | `send $3000 from account 2 to France, destination FR123` | Approved immediately, no flags |
| 6 | Defensive design — insufficient funds | `send $7000 from account 1 to Iran, destination IR999` | Rejected: insufficient funds ($5,000 balance) |
| 7 | Elicitation — sanctions | `send $500 from account 1 to Iran, destination IR999` | `--- HUMAN APPROVAL REQUIRED ---` prints; type `yes` → wire approved |
| 8 | Elicitation — decline path | Same request again | Type `no` this time → wire cancelled by human reviewer |
| 9 | Elicitation — structuring | (as employee 4) `send $500 from account 3 to a US account, destination US-1234567` | `Flags: structuring` → approval prompt → `yes` → approved |
| 10 | Elicitation — self-dealing | `login as employee 3` (Emily), then any wire | `Flags: self_dealing` regardless of destination → approval prompt |
| 11 | Sampling | Watch the **server terminal** during any of cases 7/9/10 | `[SAMPLING] AI risk analysis (via client's model): ...` prints on stderr before the approval prompt |
| 12 | Notifications (after) | `login as employee 1` (John, compliance) | `[notification] tools/list_changed` prints; `batch_sanctions_scan` becomes available |
| 13 | Progress tracking | `run a sanctions scan` | `[progress] X/10 scanned` ticks up live, not one blocking wait |
| 14 | Handler-level authorization | (as employee 4, teller, $5k limit) `send $50000 from account 2 to France` | Rejected: exceeds teller's wire authority limit |
| 15 | Identity mismatch | `python3 demo/test_identity_mismatch.py` (standalone, bypasses the agent) | `PASS: mismatched employee_id was rejected as expected` |
| 16 | Transport | `python3 mcp/server.py` (stdio) in dev, then `TRANSPORT=http python3 mcp/server.py` for deployment | Both run the same server; HTTP verified separately with a raw `curl` `initialize` call (see `BUGS_FOUND.md`, Bug 10) |

## What the video shows that a transcript alone can't
- The real `--- HUMAN APPROVAL REQUIRED ---` pause actually blocking the
  conversation (cases 7–10), not a paraphrased chat response
- Live `[progress] X/10 scanned` output ticking during the batch scan (case 13)
- The `[SAMPLING]` analysis printing on the server side, separately from the
  client's chat window (case 11)

## Known rough edges, called out honestly
- Case 15 can't be triggered through the chat agent at all (it always fills
  `employee_id` correctly) — the standalone script exists specifically
  because of that gap.
- HTTP transport (case 16) is verified via `curl`, not through the full
  agent — pointing the LangChain client itself at the HTTP endpoint instead
  of stdio is a natural next step, noted in the README's "where it stands
  now."
