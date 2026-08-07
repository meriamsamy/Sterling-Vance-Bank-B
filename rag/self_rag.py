from langchain_groq import ChatGroq
from config import API_KEY

# ---------------- LLM ----------------

llm = ChatGroq(
    api_key=API_KEY,
    model="qwen/qwen3.6-27b",
    temperature=0.1
)

# ======================================================
# Post Retrieval Verification
# ======================================================

def verify_retrieved_context(question, context):

    prompt = f"""
You are a retrieval verifier for a banking compliance assistant.

Check whether the retrieved context is relevant
and contains enough information to answer the question.

Question:
{question}

Retrieved Context:
{context}

Return exactly one word:

SUPPORTED

UNSUPPORTED
"""

    response = llm.invoke(prompt)

    return (
        response.content.strip().upper(),
        response.usage_metadata["total_tokens"]
    )


# ======================================================
# Generation
# ======================================================

def generate_answer(question, context):

    prompt = f"""
You are a Sterling & Vance Bank compliance assistant.

Answer only using the provided policy context.

Do not invent policies.
Do not use outside knowledge.

If the answer cannot be found in the context, say exactly:

I couldn't find that information in the bank policy.

Context:
{context}

Question:
{question}

Answer:
"""

    response = llm.invoke(prompt)

    return (
        response.content,
        response.usage_metadata["total_tokens"]
    )

# ======================================================
# Post Generation Verification
# ======================================================

def verify_answer(question, context, answer):

    prompt = f"""
You are a strict answer verifier.

Check if the generated answer is supported
by the provided policy context.

Question:
{question}

Context:
{context}

Generated Answer:
{answer}

Return exactly one word:

SUPPORTED

UNANSWERABLE

UNSUPPORTED
"""

    response = llm.invoke(prompt)

    return (
        response.content.strip().upper(),
        response.usage_metadata["total_tokens"]
    )

# ======================================================
# Self-RAG Wrapper
# ======================================================

def verify_and_generate(question, context):

    # -------- Retrieval Verification --------

    retrieval_status, retrieval_tokens = verify_retrieved_context(
        question,
        context
    )

    total_tokens = retrieval_tokens

    if retrieval_status == "UNSUPPORTED":

        return {
            "answer":
            "Retrieval verification failed. Retrieved documents are not relevant.",
            "status":
            "REJECTED_AFTER_RETRIEVAL",
            "tokens":
            total_tokens
        }

    # -------- Generation --------

    answer, generation_tokens = generate_answer(
        question,
        context
    )

    total_tokens += generation_tokens

    # -------- Generation Verification --------

    answer_status, verification_tokens = verify_answer(
        question,
        context,
        answer
    )

    total_tokens += verification_tokens

    if answer_status == "UNSUPPORTED":

        return {
            "answer":
            "Answer verification failed. Generated answer is not supported.",
            "status":
            "REJECTED_AFTER_GENERATION",
            "tokens":
            total_tokens
        }

    if answer_status == "UNANSWERABLE":

        return {
            "answer":
            "I couldn't find that information in the bank policy.",
            "status":
            "UNANSWERABLE",
            "tokens":
            total_tokens
        }

    return {
        "answer": answer,
        "status": "VERIFIED",
        "tokens": total_tokens
    }