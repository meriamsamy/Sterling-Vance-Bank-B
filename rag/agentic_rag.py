from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parent.parent))

from rag.self_rag import verify_and_generate

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.retrievers import BM25Retriever
from langchain_groq import ChatGroq

from rag.metadata_filter import extract_metadata_filter
from config import API_KEY


MAX_ITERATIONS = 2
TOP_K = 3


# ======================================================
# Load Vector Database
# ======================================================

embeddings = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2"
)


vector_db = Chroma(
    persist_directory="rag/chroma_db",
    embedding_function=embeddings
)



# ======================================================
# Recover Documents For BM25
# ======================================================

data = vector_db.get()

chunks = [
    Document(
        page_content=text,
        metadata=metadata
    )
    for text, metadata in zip(
        data["documents"],
        data["metadatas"]
    )
]



# ======================================================
# Global BM25
# ======================================================

bm25_retriever = BM25Retriever.from_documents(chunks)
bm25_retriever.k = TOP_K



# ======================================================
# LLM
# ======================================================

llm = ChatGroq(
    api_key=API_KEY,
    model="llama-3.1-8b-instant",
    temperature=0.1
)



# ======================================================
# Agent Step 1:
# Create Retrieval Query
# ======================================================

def plan_retrieval(question):

    prompt = f"""
You are a retrieval planner for a banking compliance policy.

Rewrite the question into keywords that appear in the policy document.

Prefer exact policy terms such as:

- Conflict of Interest
- Fraud Investigator
- Confirmed Fraud
- Account Freeze
- Human Approval
- Decision Matrix

Original question:
{question}

Return only the search query.
"""

    response = llm.invoke(prompt)

    return response.content.strip()



# ======================================================
# Agent Step 2:
# Retrieve Documents
# ======================================================

def retrieve_documents(query):

    section_filter = extract_metadata_filter(query)

    print("Metadata filter:", section_filter)


    # Vector Retrieval

    if section_filter:

        vector_docs = vector_db.similarity_search(
            query,
            k=TOP_K,
            filter={
                "section": section_filter
            }
        )

    else:

        vector_docs = vector_db.similarity_search(
            query,
            k=TOP_K
        )



    # BM25 Retrieval

    if section_filter:

        filtered_chunks = [
            doc
            for doc in chunks
            if doc.metadata.get("section")
            == section_filter
        ]


        if filtered_chunks:

            bm25 = BM25Retriever.from_documents(
                filtered_chunks
            )

            bm25.k = TOP_K

            keyword_docs = bm25.invoke(query)

        else:

            keyword_docs = []


    else:

        keyword_docs = bm25_retriever.invoke(query)



    # Merge

    combined = []

    seen = set()


    for doc in vector_docs + keyword_docs:

        if doc.page_content not in seen:

            combined.append(doc)
            seen.add(doc.page_content)


    return combined



# ======================================================
# Agent Step 3:
# Check Context
# ======================================================

def is_context_enough(question, context):

    prompt = f"""
You check if retrieved policy context is enough.

Question:
{question}

Context:
{context}

Does the context contain the exact policy rules,
roles, and required actions needed to answer the question?

If multiple policy sections are needed,
all required sections must be present.

Answer only YES or NO.
"""


    response = llm.invoke(prompt)

    return "YES" in response.content.upper()



# ======================================================
# Agent Step 4:
# Rewrite Query
# ======================================================

def rewrite_query(question, old_context):

    prompt = f"""
You are improving a search query for a banking policy document.

Question:
{question}

Previous context:
{old_context}

Create a short keyword-based retrieval query.

Rules:

- Use policy terms only.
- Do not write SQL.
- Do not write code.
- Do not explain.

Return only the search keywords.
"""


    response = llm.invoke(prompt)

    return response.content.strip()



# ======================================================
# Agentic RAG
# ======================================================

def agentic_rag(question):

    current_query = plan_retrieval(question)

    print("Initial query:", current_query)


    all_docs = []

    context = ""


    for step in range(MAX_ITERATIONS):

        print(f"\nRetrieval step {step + 1}")


        docs = retrieve_documents(
            current_query
        )


        for doc in docs:

            if doc.page_content not in [
                d.page_content
                for d in all_docs
            ]:

                all_docs.append(doc)



        context = "\n\n".join(
            doc.page_content
            for doc in all_docs
        )


        enough = is_context_enough(
            question,
            context
        )


        print("Context enough:", enough)



        if enough:
            break



        current_query = rewrite_query(
            question,
            context
        )


        print("New query:", current_query)



    # -------- No Documents --------

    if not all_docs:

        return {
            "answer":
            "I couldn't find that information in the bank policy.",

            "status":
            "NO_DOCUMENTS",

            "documents_used":
            0,

            "iterations":
            step + 1,

            "tokens":
            0
        }



    # -------- Self-RAG --------

    response = verify_and_generate(
        question,
        context
    )



    return {
        "answer": response["answer"],
        "status": response["status"],
        "documents_used": len(all_docs),
        "iterations": step + 1,
        "tokens": response["tokens"]
    }



# ======================================================
# Interactive Run
# ======================================================

if __name__ == "__main__":

    while True:

        question = input("\nQuestion: ")


        if question.lower() in ["exit", "quit"]:
            break



        result = agentic_rag(question)


        print("\nStatus:")
        print(result["status"])


        print("\nAnswer:")
        print(result["answer"])


        print("\nMetrics:")
        print("Documents:", result["documents_used"])
        print("Iterations:", result["iterations"])
        print("Tokens:", result["tokens"])