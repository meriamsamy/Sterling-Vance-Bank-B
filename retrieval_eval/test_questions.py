TEST_QUESTIONS = [

# =========================
# General
# =========================

{
    "id": 1,
    "category": "General",
    "question": "What is a Conflict of Interest?",
    "expected": ["conflict of interest"]
},

{
    "id": 2,
    "category": "General",
    "question": "Who is responsible for investigating confirmed fraud?",
    "expected": ["fraud investigator"]
},


# =========================
# Identifier
# =========================

{
    "id": 3,
    "category": "Identifier",
    "question": "According to Section 7, what is the maximum transfer amount a Teller may approve?",
    "expected": ["5000", "5,000"]
},

{
    "id": 4,
    "category": "Identifier",
    "question": "According to Section 17, what happens when the AI assesses High Risk?",
    "expected": ["hold", "human review"]
},


# =========================
# Multi-hop
# =========================

{
    "id": 5,
    "category": "Multi-hop",
    "question": "A transfer is sent to a sanctioned country. Describe the complete approval workflow, including required checks and approvals.",
    "expected": [
        "sanction",
        "human approval"
    ]
},

{
    "id": 6,
    "category": "Multi-hop",
    "question": "An employee has a Conflict of Interest while initiating a high-risk wire transfer. Which roles become responsible and what actions are required?",
    "expected": [
        "conflict of interest",
        "fraud investigator",
        "human approval"
    ]
}

]