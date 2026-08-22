"""
Static compliance policy - the thing a wire-transfer reviewer would read
once and reason over, not call as a function. Exposed via resources/read
(WIRE_TRANSFER_POLICY_URI in server.py) instead of being wrapped in a tool,
because it doesn't change per-request and the model shouldn't "call" a
policy - it should read it.
"""

WIRE_TRANSFER_POLICY = """# Sterling & Vance Bank - Wire Transfer Escalation Policy (internal, v1.3)

## 1. Sanctions
Any wire whose destination_country appears on the bank's sanctions_list
must be held and routed to a compliance_officer for explicit sign-off
before it is released. Country codes are ISO 3166-1 alpha-2.

## 2. Structuring
Three or more deposits into the source account, each within $500 of the
$5,000 CTR (Currency Transaction Report) threshold, are treated as a
possible structuring pattern. Any outgoing wire from that account must be
held for fraud_investigator review, regardless of destination.

## 3. Self-dealing / conflict of interest
An employee who initiates a wire while linked to a customer record
(related_customer_id is not null) has a standing conflict of interest on
every wire they initiate, not only wires touching their linked customer's
account. These wires are blocked and escalated to a fraud_investigator.

## 4. Authority limits
- teller: up to $5,000 per wire without escalation
- compliance_officer / fraud_investigator: up to $250,000 per wire

## 5. AI-assisted risk review
When a wire trips any of the above flags, the server asks the connected
model (via MCP sampling, not the server's own reasoning) to classify the
transaction history as LOW/MEDIUM/HIGH risk. A HIGH classification is
added as an additional flag and does not bypass human sign-off - it only
informs the reviewer show up in the elicitation prompt.

## 6. Human sign-off
No flagged wire is released without an explicit "approved" response
captured through elicitation. If the connected client does not declare
elicitation support, the wire is held in "pending_manual_review" status
instead of being silently approved or silently dropped.
"""
