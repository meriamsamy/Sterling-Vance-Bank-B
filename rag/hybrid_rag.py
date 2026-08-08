from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parent.parent))

from rag.self_rag import verify_and_generate

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.retrievers import BM25Retriever

from rag.metadata_filter import extract_metadata_filter


TOP_K = 3


# ---------------- Embeddings ----------------

embeddings = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2"
)


# ---------------- Vector DB ----------------

vector_db = Chroma(
    persist_directory="rag/chroma_db",
    embedding_function=embeddings
)


# ---------------- Load Documents ----------------

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


# ---------------- BM25 ----------------

bm25_retriever = BM25Retriever.from_documents(chunks)
bm25_retriever.k = TOP_K


# ======================================================
# Hybrid RAG
# ======================================================

def hybrid_rag(question):

    # ---------------- Metadata Filter ----------------
    print("\n[HYBRID RAG TOOL] CALLED")
    print("Question:", question)

    section_filter = extract_metadata_filter(question)

    print("Metadata Filter:", section_filter)


    # ---------------- Hybrid Retrieval ----------------

    if section_filter:

        vector_docs = vector_db.similarity_search(
            question,
            k=TOP_K,
            filter={
                "section": section_filter
            }
        )


        filtered_chunks = [
            doc
            for doc in chunks
            if doc.metadata.get("section") == section_filter
        ]


        if filtered_chunks:

            bm25 = BM25Retriever.from_documents(filtered_chunks)
            bm25.k = TOP_K

            bm25_docs = bm25.invoke(question)

        else:

            bm25_docs = []


    else:

        vector_docs = vector_db.similarity_search(
            question,
            k=TOP_K
        )

        bm25_docs = bm25_retriever.invoke(question)



    # ---------------- Merge Results ----------------

    combined_docs = []

    seen = set()


    for doc in vector_docs + bm25_docs:

        if doc.page_content not in seen:

            combined_docs.append(doc)
            seen.add(doc.page_content)


    print(f"\nRetrieved {len(combined_docs)} documents")



    # ---------------- No Documents ----------------

    if not combined_docs:

        return {
            "answer": "I couldn't find that information in the bank policy.",
            "status": "NO_DOCUMENTS",
            "documents_used": 0,
            "iterations": 1,
            "tokens": 0,
            "context": "",
            "documents": [],
        }



    # ---------------- Build Context ----------------

    context = "\n\n".join(
        doc.page_content
        for doc in combined_docs
    )



    # ---------------- Self-RAG ----------------

    response = verify_and_generate(
        question,
        context
    )



    return {
        "answer": response["answer"],
        "status": response["status"],
        "documents_used": len(combined_docs),
        "iterations": 1,
        "tokens": response["tokens"],
        "context": context,
        "documents": combined_docs,
    }



# ======================================================
# Interactive Run
# ======================================================

if __name__ == "__main__":

    while True:

        question = input("\nQuestion: ")

        if question.lower() in ["exit", "quit"]:
            break


        result = hybrid_rag(question)


        print("\nStatus:")
        print(result["status"])


        print("\nAnswer:")
        print(result["answer"])


        print("\nMetrics:")
        print("Documents:", result["documents_used"])
        print("Iterations:", result["iterations"])
        print("Tokens:", result["tokens"])