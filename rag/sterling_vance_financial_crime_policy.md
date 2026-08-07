
# Sterling & Vance Bank

## Wire Transfer & Financial Crime Operations Manual

**Version:** 2.0
**Classification:** Internal Use Only

---

# 1. Purpose

This manual defines the internal operational policies used by Sterling & Vance Bank employees when processing wire transfers, reviewing suspicious transactions, and protecting customers from fraud and financial crime.

The policies described in this document apply to all wire transfer operations performed through the bank's internal wire transfer system.

This document is intended for:

* Tellers
* Compliance Officers
* Fraud Investigators
* Internal AI Banking Assistant

---

# 2. Scope

This policy governs:

* Customer account access
* Wire transfer processing
* Fraud detection
* Sanctions screening
* Conflict-of-interest detection
* Human compliance review
* AI-assisted risk assessment
* Account freezing procedures

This policy does not cover loans, credit cards, investments, or other banking services.

---

# 3. Employee Roles

## 3.1 Teller

A Teller may:

* Access customer account information.
* Initiate wire transfers.
* Process standard banking requests.

A Teller may not:

* Approve high-risk transfers.
* Override compliance decisions.
* Freeze customer accounts.
* Release frozen accounts.

---

## 3.2 Compliance Officer

A Compliance Officer may:

* Review transfers flagged by sanctions screening.
* Review AML investigations.
* Approve or reject held transfers.
* Freeze accounts when required.
* Release frozen accounts after investigation.

---

## 3.3 Fraud Investigator

A Fraud Investigator may:

* Review suspected fraud cases.
* Investigate structuring patterns.
* Review conflict-of-interest cases.
* Freeze accounts involved in confirmed fraud.
* Recommend permanent restrictions.

---

# 4. Customer Accounts

Each customer may own one or more bank accounts.

Every account contains:

* Account Number
* Account Owner
* Current Balance
* Account Type
* Creation Date

Account balances must always remain accurate.

The AI assistant must never assume account information without retrieving it from the banking system.

---

# 5. Wire Transfer Process

Every wire transfer requires:

* Source Account
* Destination Account Number
* Destination Country
* Transfer Amount
* Employee initiating the transfer

A transfer enters processing immediately after the employee submits all required information.

The system validates the transfer before any funds are moved.

---

# 6. Transfer Validation

Before approving any transfer, the system verifies:

### Account Validation

* Source account exists.
* Destination account information is provided.

### Employee Validation

The initiating employee must:

* Be logged into the current session.
* Use their own employee identity.

Requests submitted using another employee's identity are rejected immediately.

### Balance Validation

The source account must contain sufficient funds.

Transfers exceeding the available balance are rejected.

---

# 7. Authority Limits

Employee approval authority is limited by role.

| Role               | Maximum Amount |
| ------------------ | -------------- |
| Teller             | $5,000         |
| Compliance Officer | $250,000       |
| Fraud Investigator | $250,000       |

Transfers exceeding an employee's approval authority are rejected.

The employee must not split a transaction into multiple smaller transfers to bypass approval limits.

---

# 8. Wire Transfer Status

Every transfer is assigned one of the following statuses.

## Approved

The transfer passed all validations.

Funds are released immediately.

---

## Pending Manual Review

The transfer requires human review before funds are released.

Funds remain on hold.

---

## Rejected

The transfer failed validation or was rejected during compliance review.

No funds are transferred.

---

# 9. Sanctions Screening

Every international wire transfer is screened against the bank's sanctions list.

If the destination country appears on the sanctions list:

* The transfer must not be released automatically.
* The transfer status becomes **Pending Manual Review**.
* A Compliance Officer must review the transfer.

The AI assistant must never approve a sanctioned transfer without human authorization.

---

# 10. Suspicious Transaction Detection

The system continuously monitors transaction activity for patterns commonly associated with financial crime.

Indicators include:

* Multiple deposits followed by a large outgoing transfer.
* Transaction behavior inconsistent with previous account activity.
* Attempts to avoid internal approval requirements.
* Repeated unusual transfers.

Detection of suspicious behavior does not automatically prove fraud.

Instead, the transaction is paused for further investigation.

---

# 11. Structuring Detection

Structuring is the intentional division of funds into multiple smaller transactions to avoid regulatory attention.

Within Sterling & Vance Bank, a potential structuring pattern exists when:

* Three or more deposits
* Each deposit is close to the reporting threshold
* The deposits are followed by an outgoing wire transfer

When this pattern is detected:

* The transfer is held.
* A Fraud Investigator reviews the activity.

The AI assistant must not override this decision.

---

# 12. Conflict of Interest

Employees must remain independent when handling customer transactions.

A conflict of interest exists when an employee has a personal relationship with a customer connected to the transaction.

Examples include:

* Family relationship.
* Personal ownership.
* Any recorded related customer relationship.

If a conflict is detected:

* The transfer is held.
* A Fraud Investigator reviews the case.

Employees must never approve transactions that create personal benefit.

---

# 13. AI-Assisted Risk Assessment

When a transfer has already been flagged, the AI assistant performs an additional risk assessment.

The AI classifies the transaction history as:

* LOW
* MEDIUM
* HIGH

The AI assessment is advisory only.

It never replaces human judgment.

A HIGH risk assessment increases reviewer awareness but does not automatically reject or approve a transfer.

---

# 14. Human Approval

Certain transfers require explicit human authorization before completion.

Human review is required when:

* A sanctions match is detected.
* Structuring is suspected.
* A conflict of interest exists.
* The AI identifies high risk.

The reviewer may:

* Approve the transfer.
* Reject the transfer.

Without explicit approval, funds remain on hold.

---

# 15. Account Freeze Policy

An account may be temporarily frozen when continued account activity presents a significant financial, regulatory, or fraud risk.

## Reasons for Freezing an Account

An account may be frozen if:

* Confirmed fraudulent activity exists.
* A money laundering investigation requires temporary restriction.
* A sanctions investigation determines that the account is associated with a sanctioned individual or organization.
* A Fraud Investigator confirms self-dealing or insider fraud.
* A regulatory authority requires immediate restriction.

## Effects of a Frozen Account

While an account is frozen:

* No outgoing wire transfers are permitted.
* No withdrawals are allowed.
* Pending wire transfers remain suspended until reviewed.
* Incoming deposits may still be accepted unless prohibited by law or regulatory instruction.

## Authorized Roles

Only the following employees may freeze an account:

* Compliance Officer
* Fraud Investigator

Tellers are not authorized to freeze or unfreeze customer accounts.

## Releasing a Frozen Account

A frozen account may only be released after:

* Completion of the required investigation.
* Approval by an authorized Compliance Officer or Fraud Investigator.
* Documentation of the reason for removing the restriction.

---

# 16. Compliance Review

Every held transfer receives a compliance review.

The reviewer records:

* Decision
* Notes
* Review timestamp
* Reviewer identity

Possible decisions are:

* Approved
* Rejected

Compliance decisions become part of the permanent transfer history.

---

# 17. Decision Matrix

| Situation                  | AI Action | Human Review       | Freeze Account |
| -------------------------- | --------- | ------------------ | -------------- |
| Insufficient balance       | Reject    | No                 | No             |
| Invalid account            | Reject    | No                 | No             |
| Transfer within limits     | Approve   | No                 | No             |
| Amount exceeds authority   | Reject    | No                 | No             |
| Sanctioned destination     | Hold      | Compliance Officer | Optional       |
| Structuring detected       | Hold      | Fraud Investigator | Optional       |
| Conflict of interest       | Hold      | Fraud Investigator | Yes            |
| AI High Risk               | Hold      | Human Review       | No             |
| Confirmed money laundering | Hold      | Compliance Officer | Yes            |
| Confirmed fraud            | Reject    | Fraud Investigator | Yes            |

---

# 18. Guiding Principles

The AI Banking Assistant must:

* Always retrieve banking information from the system.
* Never invent account details.
* Never bypass compliance controls.
* Never approve restricted transactions automatically.
* Always require human approval when required by policy.
* Protect customer funds.
* Follow this policy before completing any wire transfer operation.
