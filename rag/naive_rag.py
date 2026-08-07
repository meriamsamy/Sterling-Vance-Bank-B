from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parent.parent))

from rag.self_rag import verify_and_generate

from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings


TOP_K = 3


# ---------------- Embedding Model ----------------

embeddings = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2"
)


# ---------------- Load Vector Database ----------------

vector_db = Chroma(
    persist_directory="rag/chroma_db",
    embedding_function=embeddings
)


# ======================================================
# Naive RAG
# ======================================================

def naive_rag(question):

    # ---------------- Retrieve ----------------

    results = vector_db.similarity_search(
        question,
        k=TOP_K
    )

    print(f"Retrieved {len(results)} documents")


    # ---------------- No Documents ----------------

    if not results:
        return {
            "answer": "I couldn't find that information in the bank policy.",
            "status": "NO_DOCUMENTS",
            "documents_used": 0,
            "iterations": 1,
            "tokens": 0
        }


    # ---------------- Build Context ----------------

    context = "\n\n".join(
        doc.page_content
        for doc in results
    )


    # ---------------- Self-RAG ----------------

    response = verify_and_generate(
        question,
        context
    )


    return {
        "answer": response["answer"],
        "status": response["status"],
        "documents_used": len(results),
        "iterations": 1,
        "tokens": response["tokens"]
    }


# ======================================================
# Interactive Mode
# ======================================================

if __name__ == "__main__":

    while True:

        question = input("\nQuestion: ")

        if question.lower() in ["exit", "quit"]:
            break


        result = naive_rag(question)


        print("\nStatus:")
        print(result["status"])


        print("\nAnswer:")
        print(result["answer"])


        print("\nMetrics:")
        print("Documents:", result["documents_used"])
        print("Iterations:", result["iterations"])
        print("Tokens:", result["tokens"])