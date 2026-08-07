from pathlib import Path
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma

# --- Load Markdown File ---
BASE_DIR = Path(__file__).resolve().parent
file_path = BASE_DIR / "sterling_vance_financial_crime_policy.md"

with open(file_path, "r", encoding="utf-8") as f:
    markdown_text = f.read()

# --- Split by Markdown Headers ---
headers_to_split_on = [
    ("#", "Section"),
    ("##", "Subsection"),
]

markdown_splitter = MarkdownHeaderTextSplitter(
    headers_to_split_on=headers_to_split_on
)

docs = markdown_splitter.split_text(markdown_text)

# --- Split Large Sections ---
text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000,
    chunk_overlap=200,
)

chunks = text_splitter.split_documents(docs)
for chunk in chunks:

    section = chunk.metadata.get("Section", "Unknown")

    if section != "Unknown":
        section = section.split(".")[0].strip()

    chunk.metadata = {
        "source": "sterling_vance_financial_crime_policy.md",
        "document_type": "compliance_policy",
        "version": "2.0",
        "section": section,
        "subsection": chunk.metadata.get("Subsection", "Unknown")
    }
print("Chunks saved!")
print(f"Number of chunks: {len(chunks)}")

# --- Embedding Model ---
embeddings = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2"
)

# --- Create Chroma Vector Database --- 
vector_db = Chroma.from_documents(
    documents=chunks,
    embedding=embeddings,
    persist_directory="rag/chroma_db",
    collection_metadata={"hnsw:space": "cosine"}
)

print("Vector Database Created Successfully!")

# --- Preview Chunks ---
for i, chunk in enumerate(chunks, start=1):
    print(f"\nChunk {i}")
    print("Metadata:", chunk.metadata)
    print(chunk.page_content)
    print("=" * 80)