# Sterling & Vance Bank B 

## 1. Company Overview

Sterling & Vance Bank B is a commercial bank that provides customer account management and wire transfer services. The bank is developing an AI assistant to help employees access customer accounts and initiate wire transfers more efficiently while maintaining security and compliance controls.

# 2. Problem Description

At Sterling & Vance Bank, employees handle customer wire transfers every day. To make their work faster, the bank is introducing an AI assistant that can help employees access customer accounts, review transactions, and initiate wire transfers.

However, giving an AI system the ability to perform financial actions introduces a serious risk. A transfer requested by an employee could involve fraud, money laundering, or a sanctions violation, and an AI acting without proper controls could complete a harmful transaction before anyone reviews it.

To prevent this, the system must include checkpoints where the AI stops and requests human intervention in high-risk situations.

The system handles three main risk scenarios:

1. A wire transfer is sent to a country on a sanctions or watch list, requiring approval from a compliance officer before completion.
2. A customer receives multiple incoming transactions from different sources followed by an outgoing wire transfer, which may indicate suspicious activity and requires human review.
3. A bank employee attempts to transfer money to an account connected to themselves or a related party, causing the transfer to be blocked and escalated to a fraud investigator.

The goal is to build an AI assistant that can support employees while ensuring that sensitive financial operations remain secure, controlled, and compliant.

# 3. System Architecture

---

# 4. Database & ERD

---

# 5. MCP Implementation

---

# 6. Tools Comparison

---

# 7.Demo

---
