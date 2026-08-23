from pathlib import Path
import json
import sys

from langchain_core.documents import Document
from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma


# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

DOCUMENTS_DIR = BASE_DIR / "documents"
CHROMA_DIR = BASE_DIR / "chroma_db"

DOCUMENTS_DIR.mkdir(exist_ok=True)


# ============================================================
# EMBEDDINGS
# ============================================================

embeddings = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2"
)


# ============================================================
# VECTOR DATABASE
# ============================================================

vector_db = Chroma(
    persist_directory=str(CHROMA_DIR),
    embedding_function=embeddings,
    collection_metadata={"hnsw:space": "cosine"},
)


# ============================================================
# INGEST MARKDOWN
# ============================================================

def ingest_markdown(
    file_name: str,
    content: str,
):
    if not file_name.lower().endswith(".md"):
        raise ValueError("Only Markdown (.md) files are supported.")

    safe_name = Path(file_name).name

    file_path = DOCUMENTS_DIR / safe_name

    file_path.write_text(
        content,
        encoding="utf-8",
    )

    # ---------------- Markdown headers ----------------

    markdown_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=[
            ("#", "Section"),
            ("##", "Subsection"),
        ]
    )

    docs = markdown_splitter.split_text(content)

    # ---------------- Large sections ----------------

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
    )

    chunks = splitter.split_documents(docs)

    # ---------------- Metadata ----------------

    for chunk in chunks:
        section = chunk.metadata.get(
            "Section",
            "Unknown",
        )

        if section != "Unknown":
            section = section.split(".")[0].strip()

        chunk.metadata = {
            "source": safe_name,
            "document_type": "markdown",
            "version": "1.0",
            "section": section,
            "subsection": chunk.metadata.get(
                "Subsection",
                "Unknown",
            ),
        }

    # ---------------- Remove old version ----------------

    existing = vector_db.get(
        where={"source": safe_name}
    )

    existing_ids = existing.get("ids", [])

    if existing_ids:
        vector_db.delete(
            ids=existing_ids
        )

    # ---------------- Add new version ----------------

    if chunks:
        vector_db.add_documents(chunks)

    return {
        "id": safe_name,
        "name": safe_name,
        "type": "md",
        "status": "indexed",
        "chunks": len(chunks),
        "sizeBytes": len(content.encode("utf-8")),
    }


# ============================================================
# DELETE MARKDOWN
# ============================================================

def delete_markdown(file_name: str):

    safe_name = Path(file_name).name

    # Remove vectors belonging to this document
    existing = vector_db.get(
        where={"source": safe_name}
    )

    existing_ids = existing.get("ids", [])

    if existing_ids:
        vector_db.delete(
            ids=existing_ids
        )

    # Remove physical file
    file_path = DOCUMENTS_DIR / safe_name

    if file_path.exists():
        file_path.unlink()

    return True


# ============================================================
# LIST MARKDOWN DOCUMENTS
# ============================================================

def list_markdown_documents():

    documents = []

    for file_path in DOCUMENTS_DIR.glob("*.md"):

        documents.append({
            "id": file_path.name,
            "name": file_path.name,
            "type": "md",
            "sizeBytes": file_path.stat().st_size,
            "status": "indexed",
            "uploadedAt": file_path.stat().st_mtime,
        })

    return documents


# ============================================================
# CLI BRIDGE
#
# Next.js calls this file and sends JSON through stdin.
#
# Supported commands:
#
# {"action":"list"}
# {"action":"upload","name":"x.md","content":"..."}
# {"action":"delete","name":"x.md"}
# ============================================================

def main():

    try:
        request = json.loads(
            sys.stdin.read()
        )

        action = request.get("action")

        if action == "list":

            result = list_markdown_documents()

        elif action == "upload":

            result = ingest_markdown(
                file_name=request["name"],
                content=request["content"],
            )

        elif action == "delete":

            delete_markdown(
                request["name"]
            )

            result = {
                "success": True
            }

        else:
            raise ValueError(
                f"Unknown action: {action}"
            )

        print(
            json.dumps(
                {
                    "success": True,
                    "data": result,
                },
                ensure_ascii=False,
            )
        )

    except Exception as exc:

        print(
            json.dumps(
                {
                    "success": False,
                    "error": str(exc),
                },
                ensure_ascii=False,
            )
        )

        sys.exit(1)


if __name__ == "__main__":
    main()